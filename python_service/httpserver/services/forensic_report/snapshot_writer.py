from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
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
        category_dir.mkdir(parents=True, exist_ok=True)
        page_records = []
        page_paths: list[str] = []
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
            (staging / relative).write_bytes(_canonical_json(payload))
            page_paths.append(relative.as_posix())

        for record in adapter.iter_records(context, category):
            totals["total"] += 1
            totals["deleted"] += record.data_state.value == "deleted"
            totals["recovered"] += record.data_state.value == "recovered"
            totals["high_risk"] += record.severity in (Severity.HIGH, Severity.CRITICAL)
            totals["relevant"] += record.is_relevant
            totals["referenced"] += bool(record.analysis_references)
            page_number = math.ceil(totals["total"] / category.page_size)
            search.add_document(
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
