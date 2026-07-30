from __future__ import annotations

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised through the fallback test
    fcntl = None
import hashlib
import json
import math
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .ids import safe_segment
from .models import (
    AdapterContext,
    AdapterWarning,
    CategoryIndex,
    CategorySpec,
    EvidenceSource,
    ReportAdapter,
    ReportManifest,
    ReportStatus,
    ReportVersion,
    Severity,
)
from .search_index import SnapshotSearchIndex


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class _ReportClaim:
    """Process-safe exclusive claim released automatically after a worker dies."""

    def __init__(self, report_root: Path, report_id: str):
        self.path = report_root / ".locks" / f"{safe_segment(report_id)}.lock"
        self._lock_file = None
        self._fallback_claimed = False

    @staticmethod
    def _process_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _claim_fallback(self) -> None:
        """Claim with a PID sentinel when POSIX flock is unavailable."""
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    owner = int(self.path.read_text("utf-8").strip())
                except (OSError, ValueError):
                    owner = 0
                if self._process_is_running(owner):
                    raise FileExistsError(
                        f"report generation already active: {self.path.stem}"
                    )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w") as lock_file:
                lock_file.write(str(os.getpid()))
            self._fallback_claimed = True
            return

    def __enter__(self) -> _ReportClaim:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is None:
            self._claim_fallback()
            return self
        self._lock_file = self.path.open("a+")
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lock_file.close()
            self._lock_file = None
            raise FileExistsError(
                f"report generation already active: {self.path.stem}"
            ) from exc
        self._lock_file.seek(0)
        self._lock_file.truncate()
        self._lock_file.write(str(os.getpid()))
        self._lock_file.flush()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._lock_file is not None:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
        if self._fallback_claimed:
            self.path.unlink(missing_ok=True)
            self._fallback_claimed = False


class SnapshotWriter:
    """Build a complete report snapshot off-line, then publish it atomically.

    Page-shard ``sha256`` values are hashes of the canonical shard object before
    its ``sha256`` field is added. This avoids self-referential hashing while
    allowing readers to independently verify every shard.
    """

    def __init__(self, report_root: Path, generator_version: str):
        self.report_root = Path(report_root)
        self.generator_version = generator_version

    def write(
        self,
        *,
        version: ReportVersion,
        title: str,
        case_description: str,
        evidence: list[EvidenceSource],
        contexts: list[AdapterContext],
        adapters: Iterable[ReportAdapter],
        analysis: dict,
    ) -> Path:
        staging = self.report_root / ".staging" / version.report_id
        final_dir = (
            self.report_root
            / version.scope_type.value
            / safe_segment(version.scope_id)
            / version.report_id
        )
        if final_dir.exists():
            raise FileExistsError(f"immutable report already exists: {final_dir}")

        # Report adapters may be a one-shot iterable, but must run per evidence.
        adapters = tuple(adapters)
        with _ReportClaim(self.report_root, version.report_id):
            if final_dir.exists():
                raise FileExistsError(f"immutable report already exists: {final_dir}")
            shutil.rmtree(staging, ignore_errors=True)
            try:
                staging.mkdir(parents=True)
                search = SnapshotSearchIndex(staging / "search.sqlite3")
                warnings: list[AdapterWarning] = []
                indexes: list[CategoryIndex] = []
                platforms: set[str] = set()

                for context in contexts:
                    for adapter in adapters:
                        try:
                            probe = adapter.probe(context)
                        except Exception as exc:
                            warnings.append(
                                AdapterWarning(
                                    adapter=adapter.name,
                                    evidence_id=context.evidence_id,
                                    code="probe_failed",
                                    message=str(exc),
                                )
                            )
                            continue
                        if not probe.available:
                            continue
                        try:
                            for category in adapter.categories(context):
                                try:
                                    index = self._write_category(
                                        staging, search, context, adapter, category
                                    )
                                except Exception as exc:
                                    warnings.append(
                                        AdapterWarning(
                                            adapter=adapter.name,
                                            evidence_id=context.evidence_id,
                                            category_id=category.category_id,
                                            code="category_failed",
                                            message=str(exc),
                                        )
                                    )
                                    continue
                                if index.total > 0:
                                    indexes.append(index)
                                    platforms.add(category.platform)
                        except Exception as exc:
                            warnings.append(
                                AdapterWarning(
                                    adapter=adapter.name,
                                    evidence_id=context.evidence_id,
                                    code="categories_failed",
                                    message=str(exc),
                                )
                            )

                manifest = ReportManifest(
                    report_id=version.report_id,
                    version=version.version,
                    scope_type=version.scope_type,
                    scope_id=version.scope_id,
                    status=ReportStatus.READY,
                    title=title,
                    case_description=case_description,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    generated_by="TraceLens",
                    generator_version=self.generator_version,
                    platforms=sorted(platforms),
                    task_ids=version.task_ids,
                    evidence=evidence,
                    directory=self._build_directory(evidence, indexes),
                    categories=indexes,
                    analysis=analysis,
                    source_fingerprints={
                        f"{item.evidence_id}:{name}": fingerprint
                        for item in evidence
                        for name, fingerprint in item.source_fingerprints.items()
                    },
                    warnings=warnings,
                )
                (staging / "manifest.json").write_bytes(
                    _canonical_json(manifest.model_dump(mode="json"))
                )
                final_dir.parent.mkdir(parents=True, exist_ok=True)
                if final_dir.exists():
                    raise FileExistsError(f"immutable report already exists: {final_dir}")
                os.replace(staging, final_dir)
                return final_dir
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise

    def _write_category(
        self,
        staging: Path,
        search: SnapshotSearchIndex,
        context: AdapterContext,
        adapter: ReportAdapter,
        category: CategorySpec,
    ) -> CategoryIndex:
        category_dir = (
            staging
            / "data"
            / safe_segment(context.evidence_id)
            / category.platform
            / safe_segment(category.category_id)
        )
        if category_dir.exists():
            raise FileExistsError(f"duplicate category output: {category_dir}")

        work_dir = staging / ".category-staging" / uuid.uuid4().hex
        category_search_path = staging / ".category-search" / f"{uuid.uuid4().hex}.sqlite3"
        category_search = SnapshotSearchIndex(category_search_path)
        work_dir.mkdir(parents=True)
        page_records = []
        page_paths: list[str] = []
        search_document_ids: list[int] = []
        published = False
        totals = {
            "total": 0,
            "deleted": 0,
            "recovered": 0,
            "high_risk": 0,
            "relevant": 0,
            "referenced": 0,
        }

        def flush_page(page_number: int) -> None:
            payload = {
                "schema_version": "1.0",
                "category_id": category.category_id,
                "page": page_number,
                "page_size": category.page_size,
                "total": totals["total"],
                "records": [record.model_dump(mode="json") for record in page_records],
            }
            payload["sha256"] = hashlib.sha256(_canonical_json(payload)).hexdigest()
            relative = category_dir.relative_to(staging) / f"{page_number}.json"
            (work_dir / f"{page_number}.json").write_bytes(_canonical_json(payload))
            page_paths.append(relative.as_posix())

        try:
            for record in adapter.iter_records(context, category):
                totals["total"] += 1
                totals["deleted"] += record.data_state.value == "deleted"
                totals["recovered"] += record.data_state.value == "recovered"
                totals["high_risk"] += record.severity in (
                    Severity.HIGH,
                    Severity.CRITICAL,
                )
                totals["relevant"] += record.is_relevant
                totals["referenced"] += bool(record.analysis_references)
                page_number = math.ceil(totals["total"] / category.page_size)
                category_search.add_document(
                    kind="record",
                    title=record.title,
                    search_text=" ".join(
                        [
                            record.title,
                            record.source_path or "",
                            *record.hashes.values(),
                            *[
                                str(record.fields.get(name, ""))
                                for name in category.searchable_fields
                            ],
                        ]
                    ),
                    record_id=record.record_id,
                    evidence_id=context.evidence_id,
                    platform=category.platform,
                    category_id=category.category_id,
                    page=page_number,
                )
                page_records.append(record)
                if len(page_records) == category.page_size:
                    flush_page(page_number)
                    page_records.clear()

            if page_records:
                flush_page(math.ceil(totals["total"] / category.page_size))
            category_dir.parent.mkdir(parents=True, exist_ok=True)
            search_document_ids = search.add_documents(category_search.documents())
            os.replace(work_dir, category_dir)
            published = True
            return CategoryIndex(
                category_id=category.category_id,
                evidence_id=context.evidence_id,
                platform=category.platform,
                title=category.title,
                renderer=category.renderer,
                page_size=category.page_size,
                pages=len(page_paths),
                page_paths=page_paths,
                **totals,
            )
        except Exception:
            search.delete_documents(search_document_ids)
            if published:
                shutil.rmtree(category_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            category_search_path.unlink(missing_ok=True)

    @staticmethod
    def _build_directory(
        evidence: list[EvidenceSource], indexes: list[CategoryIndex]
    ) -> list[dict]:
        result = []
        for item in evidence:
            item_indexes = [
                index for index in indexes if index.evidence_id == item.evidence_id
            ]
            platforms = []
            for platform in sorted({index.platform for index in item_indexes}):
                categories = [
                    index.model_dump(mode="json")
                    for index in item_indexes
                    if index.platform == platform
                ]
                platforms.append(
                    {"id": platform, "title": platform.title(), "children": categories}
                )
            result.append(
                {"id": item.evidence_id, "title": item.name, "children": platforms}
            )
        return result
