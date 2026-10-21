"""Offline, immutable-by-convention delivery of one Android task or report import.

The caller supplies an already trusted task record or a validated report
import ID. This module never copies source images or report attachments.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .android_coverage import read_coverage, resolve_android_db
from . import android_report_import
from . import evidence_preflight

PARSER_VERSION = "android-field-package-v1"
ANDROID_TABLES = ("sms_messages", "contacts", "installed_packages", "wifi_networks")
MAX_FROZEN_RESULT_BYTES = 2 * 1024 * 1024 * 1024


def _selected_android_evidence(task: dict) -> list[dict]:
    """Strictly read selected single-row snapshots for offline provenance.

    Never infer selected rows from the current android.db or copy an image.
    A missing/tampered frozen result makes delivery fail, not silently omit it.
    """
    from .android_result_sets import read_frozen_artifact
    from .evidence.keys import parse_evidence_key
    from .investigation.paths import investigation_db_path_for_task
    investigation = investigation_db_path_for_task(task)
    if not investigation.is_file() or investigation.is_symlink():
        return []
    selected = []
    uri = f"file:{quote(str(investigation.resolve()), safe='/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        if con.execute("PRAGMA user_version").fetchone()[0] not in (7, 8):
            raise ValueError("unsupported investigation store for delivery")
        has_report = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'").fetchone()
        report_cols = "r.report_status,r.analysis_id" if has_report else "NULL AS report_status,NULL AS analysis_id"
        report_join = ("LEFT JOIN report_evidence r ON r.task_id=s.task_id AND r.evidence_key=s.evidence_key "
                       if has_report else "")
        for row in con.execute(
            "SELECT s.evidence_key,s.snapshot_json,s.captured_at," + report_cols +
            " FROM evidence_snapshots s " + report_join +
            "WHERE s.task_id=? AND s.evidence_type='android_artifact' ORDER BY s.evidence_key",
            (task["id"],),
        ):
            key = parse_evidence_key(row["evidence_key"])
            payload = json.loads(row["snapshot_json"])
            if key.artifact_task_id != task["id"] or (
                payload.get("result_set_id"), payload.get("artifact_kind"), payload.get("record_id")
            ) != (key.result_set_id, key.artifact_kind, key.artifact_record_id):
                raise ValueError("Android snapshot identity mismatch in delivery")
            frozen = read_frozen_artifact(task, key.result_set_id, key.artifact_kind, key.artifact_record_id)
            if (payload.get("task_id") != task["id"] or payload.get("source_type") != "android_analyzer"
                    or frozen["record_hash"] != payload.get("record_hash")
                    or frozen["result_manifest"]["snapshot_sha256"] != payload.get("snapshot_sha256")
                    or frozen["record"] != payload.get("record_fields")):
                raise ValueError("Android selected record hash mismatch in delivery")
            analysis = None
            if row["analysis_id"]:
                bound = con.execute(
                    "SELECT analysis_id,version,status,decided_by,decided_at,decision_reason,input_hash "
                    "FROM secondary_analyses WHERE task_id=? AND evidence_key=? AND analysis_id=?",
                    (task["id"], row["evidence_key"], row["analysis_id"]),
                ).fetchone()
                if bound is None or bound["status"] != "accepted":
                    raise ValueError("selected Android report binding is not accepted")
                analysis = dict(bound)
            selected.append({"evidence_key": row["evidence_key"], "snapshot": payload,
                             "captured_at": row["captured_at"], "report_status": row["report_status"],
                             "bound_analysis_id": row["analysis_id"], "bound_analysis": analysis,
                             "frozen_record": frozen["record"],
                             "source": frozen["source"]})
    return selected


def _selected_report_citations(task_id: str, selected_keys: set[str], report_root: Path | None) -> list[dict]:
    if report_root is None or not selected_keys:
        return []
    from .forensic_report.narrative_reader import read_narrative_version_strict
    root = Path(report_root).resolve(strict=True)
    if Path(report_root).is_symlink() or not root.is_dir():
        raise ValueError("unsafe report root")
    db_path = root / "reports.db"
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("report store is unavailable")
    uri = f"file:{quote(str(db_path), safe='/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as con:
        con.execute("PRAGMA query_only=ON")
        rows = con.execute(
            "SELECT report_id FROM report_versions WHERE scope_type='task' AND scope_id=? "
            "AND report_kind='llm_generation' AND status='ready' ORDER BY version LIMIT 1001", (task_id,)
        ).fetchall()
    if len(rows) > 1000:
        raise ValueError("report version count exceeds delivery limit")
    citations = []
    for (report_id,) in rows:
        result = read_narrative_version_strict(db_path, root, task_id, report_id)
        if result is None:
            raise ValueError("report version disappeared during delivery")
        version, manifest = result
        for citation in manifest.citations:
            if citation.evidence_key in selected_keys:
                citations.append({"report_id": report_id, "report_version": version.version,
                                  "report_input_hash": manifest.input_hash,
                                  **citation.model_dump(mode="json")})
    return citations


def _include_frozen_result_sets(stage: Path, task: dict, selected: list[dict]) -> None:
    """Carry only result versions actually referenced by selected evidence."""
    from .android_result_sets import read_result_set
    versions = {item["snapshot"]["result_set_id"] for item in selected}
    total = 0
    for result_set_id in sorted(versions):
        manifest, source = read_result_set(task, result_set_id)
        size = source.stat().st_size
        total += size
        if total > MAX_FROZEN_RESULT_BYTES:
            raise ValueError("selected frozen result databases exceed delivery limit")
        target = stage / f"android-result-{result_set_id}.db"
        with source.open("rb") as original, target.open("xb") as copy:
            shutil.copyfileobj(original, copy, length=1024 * 1024)
        if _hash(target) != manifest["snapshot_sha256"]:
            raise ValueError("selected frozen result changed during delivery")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _snapshot(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("source database is not a regular file")
    uri = f"file:{quote(str(source.resolve()), safe='/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as original:
        original.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(target)) as copy:
            original.backup(copy, pages=1000, sleep=0.05)
            # The backup may retain the source's WAL journal mode. A standalone
            # delivery must not need unlisted -wal/-shm sidecars.
            copy.execute("PRAGMA journal_mode=DELETE")
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("database snapshot integrity check failed")


def _export_rows(snapshot: Path, target: Path, tables: tuple[str, ...]) -> dict:
    counts = {}
    with closing(sqlite3.connect(f"file:{quote(str(snapshot), safe='/')}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with target.open("w", encoding="utf-8") as out:
            for table in tables:
                if table not in present:
                    counts[table] = None
                    continue
                count = 0
                for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                    out.write(json.dumps({"table": table, "record": dict(row)}, ensure_ascii=False, default=str) + "\n")
                    count += 1
                counts[table] = count
    return counts


def _commit() -> str | None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _toolchain_inventory() -> dict:
    root = Path(__file__).resolve().parents[3]
    source_names = (
        "src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp",
        "src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp",
        "python_service/httpserver/services/android_field_package.py",
        "python_service/httpserver/services/android_artifact_reader.py",
        "web/src/components/AndroidArtifactsCard.jsx",
    )
    binary_names = (
        "build/forensic_analyzer", ".deps/qnxprobe/qnxprobe.py",
        ".deps/qnxprobe/ewfprobe.py", ".deps/aosp-android10-r36/bin/lp_inventory",
        ".deps/aosp-android10-r36/bin/lpunpack", ".deps/aosp-android10-r36/bin/liblp.so",
    )
    hashes = {name: _hash(root / name) for name in (*source_names, *binary_names, "THIRD_PARTY_LICENSES.md")
              if (root / name).is_file() and not (root / name).is_symlink()}
    if Path("/usr/bin/simg2img").is_file():
        hashes["/usr/bin/simg2img"] = _hash(Path("/usr/bin/simg2img"))
    packages = {}
    for name in ("fastapi", "pydantic", "cryptography", "pytest", "uvicorn"):
        try:
            dist = importlib.metadata.distribution(name)
            packages[name] = {"version": dist.version, "license": dist.metadata.get("License") or "see installed metadata"}
        except importlib.metadata.PackageNotFoundError:
            packages[name] = {"version": None, "license": "not installed"}
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                           capture_output=True, text=True, timeout=10, check=False)
    return {"commit": _commit(), "worktree_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
            "file_sha256": hashes, "python_dependencies": packages,
            "license_notice": "THIRD_PARTY_LICENSES.md (hash above); not a complete SBOM",
            "unlisted_dependencies": "Use an approved build/release SBOM before formal redistribution"}


def build_package(*, output: Path, task: dict | None = None, import_id: str | None = None,
                  report_root: Path | None = None) -> dict:
    """Build a fresh delivery directory; never overwrite a prior package.

    The manifest hashes every other file and is intentionally not self-listed.
    On error, an `.incomplete-*` staging directory remains visibly invalid.
    """
    if (task is None) == (import_id is None):
        raise ValueError("select exactly one task or report import")
    output = Path(output).absolute()
    if output.exists() or output.parent.is_symlink() or not output.parent.is_dir():
        raise ValueError("output must be a new directory under an existing parent")
    source_type = "android_analyzer" if task is not None else "external_html_report"
    if task is not None:
        source = resolve_android_db(task)
        if source is None:
            raise FileNotFoundError("task has no readable android.db")
        coverage = read_coverage(task)
        source_id = task["id"]
        source_manifest = coverage.get("manifest")
        normalization = coverage.get("normalization_manifest")
        warnings = list(coverage.get("warnings", []))
        tables = ANDROID_TABLES
        completeness = "UNVERIFIED"
    else:
        import_dir = android_report_import._import_dir(import_id)
        if import_dir.is_symlink():
            raise ValueError("report import directory is a symlink")
        if any((import_dir / name).is_symlink() for name in
               ("records.db", "report_manifest.json", "report_import_coverage.json")):
            raise ValueError("report import metadata is a symlink")
        source = android_report_import._db_path(import_id)
        coverage = android_report_import.read_coverage(import_id)
        source_manifest = android_report_import.read_manifest(import_id)
        normalization = None
        warnings = source_manifest.get("warnings", [])
        source_id = import_id
        tables = ("records",)
        completeness = source_manifest.get("status", "UNVERIFIED")
    prior_umask = os.umask(0o077)
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.incomplete-", dir=output.parent))
        try:
            snapshot = stage / ("android.db" if task is not None else "records.db")
            _snapshot(source, snapshot)
            if task is not None:
                with closing(sqlite3.connect(f"file:{quote(str(snapshot), safe='/')}?mode=ro", uri=True)) as con:
                    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mobile_artifacts'").fetchone():
                        tables = (*ANDROID_TABLES, "mobile_artifacts")
            counts = _export_rows(snapshot, stage / "records.jsonl", tables)
            _json(stage / "coverage.json", coverage)
            if task is not None:
                selected = _selected_android_evidence(task)
                _json(stage / "selected_android_evidence.json", selected)
                _include_frozen_result_sets(stage, task, selected)
                _json(stage / "selected_android_citations.json", _selected_report_citations(
                    task["id"], {item["evidence_key"] for item in selected}, report_root))
                if selected and report_root is None:
                    warnings.append("R2 report root was not supplied; citation mapping is not included")
                job_id = (task.get("metadata") or {}).get("preflight_job_id")
                if isinstance(job_id, str) and job_id:
                    try:
                        preflight = evidence_preflight._job_dir(job_id) / "manifest.jsonl"
                        if (not preflight.parent.is_symlink() and not preflight.is_symlink()
                                and preflight.resolve(strict=False).is_relative_to(evidence_preflight.job_root().resolve())
                                and preflight.is_file() and preflight.stat().st_size <= 256 * 1024 * 1024):
                            with preflight.open("rb") as src, (stage / "preflight_manifest.jsonl").open("wb") as dst:
                                shutil.copyfileobj(src, dst, length=1024 * 1024)
                        else:
                            warnings.append("preflight manifest unavailable or exceeds 256 MiB delivery limit")
                    except (ValueError, OSError):
                        warnings.append("preflight manifest could not be safely included")
            if source_manifest is not None:
                _json(stage / "source_manifest.json", source_manifest)
            if normalization is not None:
                _json(stage / "normalization_manifest.json", normalization)
            _json(stage / "warnings.json", warnings)
            _json(stage / "toolchain_inventory.json", _toolchain_inventory())
            summary = (f"# TraceLens Android 结果包\n\n来源：{source_type} ({source_id})\n"
                       f"生成时间：{datetime.now(timezone.utc).isoformat()}\n"
                       f"完整性/验收状态：{completeness}\n\n"
                       "此包不包含原始镜像或附件；records.jsonl 与一致性数据库快照来自同一快照。\n"
                       "第三方报告为派生记录，不是 AndroidAnalyzer 从原始镜像提取的工件。\n\n"
                       f"记录数：{json.dumps(counts, ensure_ascii=False)}\n"
                       f"警告数：{len(warnings)}；详见 warnings.json 与 coverage.json。\n"
                       "来源路径/原库行/WAL frame 若无逐条证据，不得从本包推断。\n")
            (stage / "README.md").write_text(summary, encoding="utf-8")
            files = {path.name: {"sha256": _hash(path), "size": path.stat().st_size}
                     for path in sorted(stage.iterdir()) if path.is_file()}
            package_manifest = {"format": PARSER_VERSION, "source_type": source_type,
                "source_id": source_id, "generated_at": datetime.now(timezone.utc).isoformat(),
                "commit": _commit(), "source_database_path": str(source),
                "snapshot_sha256": files[snapshot.name]["sha256"], "counts": counts,
                "completeness": completeness, "files": files,
                "manifest_not_self_hashed": True}
            _json(stage / "package_manifest.json", package_manifest)
            # mkdir is exclusive; the target remains explicitly invalid until
            # every member is published. Never replace another delivery.
            output.mkdir(mode=0o700, exist_ok=False)
            marker = output / "INCOMPLETE"
            marker.write_text("Publishing package; not valid yet\n", encoding="utf-8")
            for member in stage.iterdir():
                member.rename(output / member.name)
            stage.rmdir()
            marker.unlink()
            return package_manifest
        except Exception:
            if stage.exists():
                (stage / "INCOMPLETE").write_text("Not a valid delivery package\n", encoding="utf-8")
            raise
    finally:
        os.umask(prior_umask)


def verify_package(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink() or (path / "package_manifest.json").is_symlink():
        raise ValueError("unsafe package path")
    if (path / "INCOMPLETE").exists():
        raise ValueError("incomplete delivery package")
    manifest = json.loads((path / "package_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source_type") not in {"android_analyzer", "external_html_report"}:
        raise ValueError("unknown package source type")
    allowed_tables = set(manifest["counts"])
    valid_table_sets = [set(ANDROID_TABLES), set(ANDROID_TABLES) | {"mobile_artifacts"}] \
        if manifest["source_type"] == "android_analyzer" else [{"records"}]
    if allowed_tables not in valid_table_sets:
        raise ValueError("unexpected package tables")
    members = list(path.iterdir())
    if any(member.is_symlink() or not member.is_file() for member in members):
        raise ValueError("unsafe or unexpected package member")
    actual_files = {member.name for member in members}
    if actual_files != set(manifest["files"]) | {"package_manifest.json"}:
        raise ValueError("package file inventory differs from manifest")
    for name, expected in manifest["files"].items():
        if name != Path(name).name or (path / name).is_symlink():
            raise ValueError("unsafe package member")
        target = path / name
        if not target.is_file() or _hash(target) != expected["sha256"] or target.stat().st_size != expected["size"]:
            raise ValueError(f"package member failed verification: {name}")
    snapshot = path / ("android.db" if manifest["source_type"] == "android_analyzer" else "records.db")
    with closing(sqlite3.connect(f"file:{quote(str(snapshot.resolve()), safe='/')}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("snapshot integrity check failed")
        for table, expected_count in manifest["counts"].items():
            if expected_count is not None and db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] != expected_count:
                raise ValueError("snapshot count mismatch")
    selected_path = path / "selected_android_evidence.json"
    if manifest["source_type"] == "android_analyzer" and selected_path.is_file():
        from .android_artifact_reader import raw_row_hash, read_raw_row
        from .evidence.keys import parse_evidence_key
        selected = json.loads(selected_path.read_text(encoding="utf-8"))
        for item in selected:
            key = parse_evidence_key(item["evidence_key"])
            frozen = item["snapshot"]
            if (key.evidence_type != "android_artifact" or key.artifact_task_id != manifest["source_id"]
                    or (frozen.get("result_set_id"), frozen.get("artifact_kind"), frozen.get("record_id"))
                    != (key.result_set_id, key.artifact_kind, key.artifact_record_id)):
                raise ValueError("selected evidence identity mismatch")
            member = path / f"android-result-{key.result_set_id}.db"
            if (member.name not in manifest["files"] or not member.is_file()
                    or manifest["files"][member.name]["sha256"] != frozen.get("snapshot_sha256")):
                raise ValueError("selected frozen result is missing or changed")
            if raw_row_hash(read_raw_row(member, key.artifact_kind, key.artifact_record_id)) != frozen.get("record_hash"):
                raise ValueError("selected frozen row differs from snapshot")
    return {"valid": True, "counts": manifest["counts"], "completeness": manifest["completeness"]}
