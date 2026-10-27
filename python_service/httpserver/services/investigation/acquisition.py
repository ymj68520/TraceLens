"""Snapshot acquisition: read the trusted source DB at capture time (Phase C4a).

Both file and cluster snapshots are acquired by re-reading the task's source
database (mode=ro) at the moment of capture, so a Snapshot always reflects
"source state at capture time" (symmetric for file/cluster). No LLM is ever
invoked; missing fields stay NULL. The candidate is fully built OUTSIDE the
investigation write transaction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.models import ResolvedEvidence
from ..android_artifact_reader import artifact_detail_from_database
from ..android_field_package import _hash
from .models import AndroidArtifactSnapshotPayload, ClusterSnapshotPayload, FileSnapshotPayload, SnapshotCandidate

logger = logging.getLogger(__name__)


def _connect_ro(path: str) -> sqlite3.Connection:
    """Open a read-only sqlite connection (mirrors evidence._connect_ro)."""
    candidate = Path(path)
    if not candidate.is_file():
        raise EvidenceStoreError(f"source database file not found: {path!r}")
    uri = f"file:{quote(str(candidate.resolve()), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def canonical_json(payload) -> str:
    """Deterministic JSON serialization (S8)."""
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


_FILE_COLUMNS = (
    "path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, "
    "llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used, "
    "scene_type, scene_priority, scene_relevant"
)


def _acquire_file(resolved: ResolvedEvidence) -> FileSnapshotPayload:
    try:
        conn = _connect_ro(resolved.source_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open files.db {resolved.source_db!r}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        from ..source_identity import file_row, SourceIdentityError
        row, locator = file_row(conn,resolved.normalized_path,resolved.source_id)
    except SourceIdentityError as exc:
        if exc.code=='SOURCE_NOT_FOUND':raise EvidenceNotFoundError(exc.message) from exc
        raise
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query files table: {exc}") from exc
    finally:
        conn.close()
    if row is None:
        raise EvidenceNotFoundError(
            f"file evidence not found in task {resolved.task_id}: {resolved.normalized_path!r}"
        )
    return FileSnapshotPayload(
        normalized_path=row["path"],
        source_id=resolved.source_id,source_locator=locator,
        name=row["name"],
        extension=row["extension"],
        category=row["category"],
        type=row["type"],
        size=row["size"],
        md5=row["md5"],
        mtime=row["mtime"],
        ctime=row["ctime"],
        is_deleted=row["is_deleted"],
        initial_summary=row["llm_summary"],
        initial_description=row["llm_description"],
        initial_keywords=row["llm_keywords"],
        initial_model=row["llm_model_used"],
        initial_analyzed_at=row["llm_analyzed_at"],
        scene_type=row["scene_type"],
        scene_priority=row["scene_priority"],
        scene_relevant=row["scene_relevant"],
    )


def _acquire_cluster(resolved: ResolvedEvidence) -> ClusterSnapshotPayload:
    try:
        conn = _connect_ro(resolved.source_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open events.db {resolved.source_db!r}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT MIN(timestamp) AS cluster_start,
                   MAX(timestamp) AS cluster_end,
                   COUNT(*) AS event_count,
                   MIN(timestamp) AS representative_timestamp
            FROM events
            WHERE (timestamp / 60) = ? AND event_type = ?
            GROUP BY (timestamp / 60), event_type
            """,
            [resolved.unix_minute, resolved.event_type],
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query events table: {exc}") from exc
    finally:
        conn.close()
    if row is None:
        raise EvidenceNotFoundError(
            f"cluster evidence not found in task {resolved.task_id}: "
            f"(unix_minute={resolved.unix_minute}, event_type={resolved.event_type!r})"
        )
    return ClusterSnapshotPayload(
        unix_minute=resolved.unix_minute,
        event_type=resolved.event_type,
        cluster_start=row["cluster_start"],
        cluster_end=row["cluster_end"],
        event_count=row["event_count"],
        representative_timestamp=row["representative_timestamp"],
        # S7: no deterministic cluster-level AI value at 2-part granularity
        initial_summary=None,
        initial_description=None,
        initial_keywords=None,
    )


def _acquire_android_artifact(resolved: ResolvedEvidence) -> AndroidArtifactSnapshotPayload:
    manifest = resolved.result_manifest
    database = Path(resolved.source_db)
    if not database.is_file() or database.is_symlink() or _hash(database) != manifest.get("snapshot_sha256"):
        raise EvidenceStoreError("frozen Android result set changed before capture")
    detail = artifact_detail_from_database(
        database, resolved.task_id, resolved.artifact_kind, resolved.artifact_record_id,
    )
    fields = detail["record"]  # Wi-Fi credentials stay redacted in snapshots/reports.
    normalized_names = {
        "sms": ("address", "body", "date", "type"),
        "contacts": ("display_name", "phone_number", "email", "account_name"),
        "apps": ("package_name", "version", "installer"),
        "wifi": ("ssid", "key_mgmt", "last_connected"),
        "mobile": ("kind", "package_name", "app_index", "record_json", "timestamp_raw", "time_unit", "timestamp_seconds"),
    }[resolved.artifact_kind]
    source = detail.get("source")
    coverage = manifest.get("coverage") or {}
    source_items = [item for item in coverage.get("sources", [])
                    if item.get("artifact_kind") == {"apps": "installed_apps"}.get(
                        resolved.artifact_kind, fields.get("kind") if resolved.artifact_kind == "mobile" else resolved.artifact_kind)]
    provenance = {
        "derived_result_record": "exact",
        # A unique candidate with a file hash is still not proof that this
        # *row* came from that file. The old parser has no row-level binding.
        "input_file": "candidate_only" if detail.get("source_candidates") else "unknown",
        "candidate_file_hash_available": bool(source and source.get("original_path") and source.get("sha256")),
        "original_database_record": "unknown",
        "original_table": None,
        "original_primary_key": None,
        "disk_offset": None,
        "wal_frame": None,
        "source": source,
        "source_candidates": detail.get("source_candidates", []),
    }
    warnings = list(coverage.get("warnings") or [])
    if resolved.artifact_kind == "mobile" and source:
        provenance.update(input_file="hashed_database_bundle", original_database_record="parser_bound_table_key",
                          original_table=source.get("original_table"), original_primary_key=source.get("original_primary_key"))
    if resolved.artifact_kind == "mobile" and source and source.get("source_format") == "protobuf":
        provenance.update(input_file="hashed_binary_backup", original_database_record="not_applicable",
                          binary_record="parser_bound_field_and_byte_offset")
    warnings.append(detail["warning"])
    return AndroidArtifactSnapshotPayload(
        task_id=resolved.task_id,
        result_set_id=resolved.result_set_id,
        artifact_kind=resolved.artifact_kind,
        record_id=resolved.artifact_record_id,
        snapshot_sha256=manifest["snapshot_sha256"],
        source_revision=manifest["source_revision"],
        record_hash=detail["record_hash"],
        record_fields=fields,
        redacted_fields=("pre_shared_key",) if resolved.artifact_kind == "wifi" and "pre_shared_key" in fields else (),
        normalized_fields={**{name: fields.get(name) for name in normalized_names if name in fields},
                           **({"platform": "Android / MIUI" if str(fields.get("parser_version", "")).startswith(("xiaomi-", "miui-notes-")) else "HarmonyOS"} if resolved.artifact_kind == "mobile" else {})},
        raw_timestamp=fields.get("timestamp_raw") if resolved.artifact_kind == "mobile" else
                      fields.get("date") if resolved.artifact_kind == "sms" else
                      fields.get("last_connected") if resolved.artifact_kind == "wifi" else None,
        timestamp_unit=fields.get("time_unit") if resolved.artifact_kind == "mobile" else None,
        timestamp_timezone="UTC" if resolved.artifact_kind == "mobile" and fields.get("time_unit") in {"epoch_s", "epoch_ms"} else None,
        timestamp_basis="source_database_value" if resolved.artifact_kind == "mobile" else None,
        parser_name=("AndroidAnalyzer/XiaomiImage" if str(fields.get("parser_version", "")).startswith(("xiaomi-", "miui-notes-")) else "AndroidAnalyzer/HarmonyBackup") if resolved.artifact_kind == "mobile" else
                    manifest.get("parser_name") or "AndroidAnalyzer",
        parser_version=fields.get("parser_version") or manifest.get("parser_version"),
        android_user=None,
        account=fields.get("account_name") if resolved.artifact_kind == "contacts" else None,
        provenance=provenance,
        coverage={"artifact_counts": coverage.get("artifact_counts", {}),
                  "relevant_sources": source_items},
        warnings=tuple(str(warning) for warning in warnings),
    )


def build_snapshot_candidate(resolved: ResolvedEvidence) -> SnapshotCandidate:
    """Acquire current source state and build a complete, immutable candidate."""
    if resolved.evidence_type == "file":
        payload = _acquire_file(resolved)
        return SnapshotCandidate(
            task_id=resolved.task_id,
            evidence_key=resolved.evidence_key,
            evidence_type="file",
            captured_at=int(time.time()),
            payload=payload,
            normalized_path=payload.normalized_path,
        )
    if resolved.evidence_type=='windows_artifact':
        from .models import WindowsArtifactSnapshotPayload
        from ..windows_activity_reader import detail
        value=detail(resolved.source_db,resolved.task_id,resolved.result_set_id,resolved.artifact_kind,resolved.artifact_record_id)
        record=value['record'];fields=dict(record.get('fields') or {})
        # Password bytes are not part of a default report projection. The exact
        # source hash continues to identify the private immutable source row.
        redacted=[name for name in ('encrypted_password',) if name in fields]
        for name in redacted:fields.pop(name)
        record={**record,'fields':fields}
        payload=WindowsArtifactSnapshotPayload(task_id=resolved.task_id,result_set_id=resolved.result_set_id,
            artifact_kind=resolved.artifact_kind,record_id=resolved.artifact_record_id,record_hash=value['record_hash'],
            source_revision=value['source_revision'],record_fields=record,
            provenance={'source_table':value['source_table'],'source_row_id':value['source_row_id'],
                        'import_version':value['import_version'],'source':record.get('source'),'redacted_fields':redacted},
            coverage=value['coverage'].get('tables',{}).get(resolved.artifact_kind,{}),
            warnings=tuple(['时间与活动含义以原始字段为限，不据配置推断实际执行']+
                           (['原始来源路径未唯一绑定；记录身份由结果集和表主键确定'] if record.get('source',{}).get('binding_status')!='unique' else [])))
        return SnapshotCandidate(task_id=resolved.task_id,evidence_key=resolved.evidence_key,evidence_type='windows_artifact',
                                 captured_at=int(time.time()),payload=payload)
    if resolved.evidence_type == "android_artifact":
        payload = _acquire_android_artifact(resolved)
        return SnapshotCandidate(
            task_id=resolved.task_id, evidence_key=resolved.evidence_key,
            evidence_type="android_artifact", captured_at=int(time.time()), payload=payload,
        )
    payload = _acquire_cluster(resolved)
    return SnapshotCandidate(
        task_id=resolved.task_id,
        evidence_key=resolved.evidence_key,
        evidence_type="cluster",
        captured_at=int(time.time()),
        payload=payload,
        unix_minute=payload.unix_minute,
        event_type=payload.event_type,
    )
