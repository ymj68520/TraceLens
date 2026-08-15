"""Unified, read-only evidence resolution for Investigation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .investigation_errors import InvalidEvidenceKey

CLUSTER_KEY_VERSION = "v1"
FILE_KEY_PREFIX = "file:"
CLUSTER_KEY_PREFIX = f"cluster:{CLUSTER_KEY_VERSION}:"
MAX_CLUSTER_EVENTS_FOR_LLM = 50
MAX_RELATED_EVIDENCE = 20
MAX_CONTENT_CHARS = 8000
TIMELINE_DEFAULT_BUCKET_SECONDS = 60
TIMELINE_MAX_BUCKET_SECONDS = 86400


def normalize_forensic_path(path: str) -> str:
    path = (path or "").replace("\\", "/")
    path = re.sub(r"/+", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def make_file_evidence_key(file_path: str) -> str:
    return FILE_KEY_PREFIX + normalize_forensic_path(file_path)


def parse_file_evidence_key(evidence_key: str) -> str:
    if not isinstance(evidence_key, str) or not evidence_key.startswith(FILE_KEY_PREFIX):
        raise InvalidEvidenceKey(f"not a file evidence key: {evidence_key!r}")
    path = evidence_key[len(FILE_KEY_PREFIX):]
    if not path:
        raise InvalidEvidenceKey("empty file evidence path")
    return path


def make_cluster_key(time_window: int, event_type: str) -> str:
    try:
        minute = int(time_window)
    except (TypeError, ValueError) as exc:
        raise InvalidEvidenceKey(f"invalid cluster time window: {time_window!r}") from exc
    event_type = str(event_type or "")
    if not event_type:
        raise InvalidEvidenceKey("empty cluster event type")
    return f"{CLUSTER_KEY_PREFIX}{minute}:{urllib.parse.quote(event_type, safe='')}"


def parse_cluster_key(key: str) -> tuple[int, str]:
    if not isinstance(key, str) or not key.startswith(CLUSTER_KEY_PREFIX):
        raise InvalidEvidenceKey(f"not a cluster key: {key!r}")
    rest = key[len(CLUSTER_KEY_PREFIX):]
    minute, sep, encoded = rest.partition(":")
    if not sep or not minute or not encoded:
        raise InvalidEvidenceKey(f"malformed cluster key: {key!r}")
    try:
        parsed_minute = int(minute)
    except ValueError as exc:
        raise InvalidEvidenceKey(f"invalid cluster time window: {minute!r}") from exc
    event_type = urllib.parse.unquote(encoded)
    if not event_type:
        raise InvalidEvidenceKey("empty cluster event type")
    return parsed_minute, event_type


def validate_timeline_group_descriptor(descriptor: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the backend-owned Timeline bucket descriptor."""
    if not isinstance(descriptor, dict):
        raise ValueError("timeline group descriptor must be an object")
    try:
        bucket_index = int(descriptor["bucket_index"])
        bucket_seconds = int(descriptor["bucket_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("timeline descriptor requires integer bucket_index and bucket_seconds") from exc
    if bucket_seconds < 1 or bucket_seconds > TIMELINE_MAX_BUCKET_SECONDS:
        raise ValueError("timeline descriptor bucket_seconds is out of range")
    event_type = descriptor.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("timeline descriptor event_type must be non-empty")
    parent_directory = descriptor.get("parent_directory", "")
    if not isinstance(parent_directory, str):
        raise ValueError("timeline descriptor parent_directory must be a string")
    canonical = {
        "bucket_index": bucket_index,
        "bucket_seconds": bucket_seconds,
        "event_type": event_type,
        "parent_directory": parent_directory,
        "bucket_start_timestamp": bucket_index * bucket_seconds,
    }
    supplied_start = descriptor.get("bucket_start_timestamp")
    if supplied_start is not None and int(supplied_start) != canonical["bucket_start_timestamp"]:
        raise ValueError("timeline descriptor bucket_start_timestamp does not match bucket_index")
    return canonical


def read_timeline_group_members(
    events_db: str, descriptor: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Read actual Timeline members from a task-selected events database."""
    canonical = validate_timeline_group_descriptor(descriptor)
    if not events_db or not os.path.exists(events_db):
        return []
    parent_dir_expr = (
        "(CASE WHEN file_path LIKE '%/%' "
        "THEN RTRIM(file_path, REPLACE(file_path, '/', '')) ELSE '' END)"
    )
    with EvidenceResolver._connect_readonly(events_db) as conn:
        rows = conn.execute(
            "SELECT id, timestamp, event_type, file_path, description, inode FROM events "
            "WHERE (timestamp / ?) = ? AND event_type = ? "
            f"AND {parent_dir_expr} = ? "
            "ORDER BY timestamp ASC, id ASC",
            (
                canonical["bucket_seconds"],
                canonical["bucket_index"],
                canonical["event_type"],
                canonical["parent_directory"],
            ),
        ).fetchall()
    return [dict(row) for row in rows]


def expand_timeline_group_rows(descriptor: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    """Project trusted backend member rows into canonical cluster Evidence keys."""
    canonical = validate_timeline_group_descriptor(descriptor)
    pairs = set()
    for row in rows:
        timestamp = row.get("timestamp")
        if timestamp is None or int(timestamp) < 0:
            raise ValueError("timeline expansion does not support negative timestamps")
        event_type = row.get("event_type")
        if event_type != canonical["event_type"]:
            raise ValueError("timeline member event_type does not match descriptor")
        pairs.add((int(timestamp) // 60, event_type))
    return [make_cluster_key(minute, event_type) for minute, event_type in sorted(pairs)]


def canonicalize_analysis_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stable, ID-free analysis input representation."""
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): clean(value[k]) for k in sorted(value)}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    result = clean(payload)
    if not isinstance(result, dict):
        raise ValueError("analysis input must be an object")
    for key in ("related_evidence", "related_evidence_keys", "allowed_evidence_ids"):
        if isinstance(result.get(key), list):
            result[key] = sorted(result[key], key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return result


def compute_analysis_input_hash(payload: Dict[str, Any]) -> str:
    canonical = canonicalize_analysis_input(payload)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class ResolvedEvidence:
    task_id: str
    evidence_key: str
    evidence_type: str
    title: Optional[str] = None
    timestamp: Optional[int] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    content: Any = None
    initial_description: Optional[str] = None
    initial_summary: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    related_evidence_keys: List[str] = field(default_factory=list)
    source_hash: Optional[str] = None
    source_size: Optional[int] = None
    source_mtime: Optional[int] = None
    source_updated_at: Optional[int] = None
    file_path: Optional[str] = None
    content_path: Optional[str] = None
    md5: Optional[str] = None
    extension: Optional[str] = None
    is_deleted: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceResolver:
    """Resolve file and Investigation cluster keys without mutating source DBs."""

    def __init__(
        self,
        task_loader: Callable[[str], Awaitable[Dict[str, Any]]],
        content_reader: Optional[Callable[[str], Awaitable[str]]] = None,
    ):
        self._task_loader = task_loader
        self._content_reader = content_reader

    @staticmethod
    def _paths(task_info: Dict[str, Any]) -> Dict[str, str]:
        files_db = task_info.get("output_files_db") or ""
        events_db = task_info.get("output_events_db") or ""
        raw_db = task_info.get("output_raw_db") or ""
        if files_db and not events_db:
            if files_db.endswith("_files.db"):
                events_db = files_db[:-len("_files.db")] + "_events.db"
            elif files_db.endswith("files.db"):
                events_db = files_db[:-len("files.db")] + "events.db"
        if files_db and not raw_db:
            if files_db.endswith("_files.db"):
                raw_db = files_db[:-len("_files.db")] + "_raw.db"
            elif files_db.endswith("files.db"):
                raw_db = files_db[:-len("files.db")] + "raw.db"
        return {"files_db": files_db, "events_db": events_db, "raw_db": raw_db}

    @staticmethod
    def _connect_readonly(db_path: str) -> sqlite3.Connection:
        if not db_path or not os.path.exists(db_path):
            raise FileNotFoundError(db_path)
        uri = f"file:{Path(db_path).resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _existing_file_paths(files_db: str, paths: List[str]) -> set[str]:
        if not files_db or not paths or not os.path.exists(files_db):
            return set()
        normalized = sorted({normalize_forensic_path(path) for path in paths if path})
        found: set[str] = set()
        try:
            with EvidenceResolver._connect_readonly(files_db) as conn:
                for index in range(0, len(normalized), 400):
                    chunk = normalized[index:index + 400]
                    placeholders = ", ".join("?" for _ in chunk)
                    rows = conn.execute(
                        "SELECT path FROM files WHERE path IN (" + placeholders + ") "
                        "OR REPLACE(path, '\\\\', '/') IN (" + placeholders + ")",
                        (*chunk, *chunk),
                    ).fetchall()
                    found.update(normalize_forensic_path(row["path"]) for row in rows if row["path"])
        except (FileNotFoundError, sqlite3.Error):
            return set()
        return found

    @staticmethod
    def _load_file_row(files_db: str, normalized_path: str) -> Optional[Dict[str, Any]]:
        try:
            with EvidenceResolver._connect_readonly(files_db) as conn:
                row = conn.execute("SELECT * FROM files WHERE path = ? LIMIT 1", (normalized_path,)).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT * FROM files WHERE REPLACE(path, '\\\\', '/') = ? LIMIT 1",
                        (normalized_path,),
                    ).fetchone()
                return dict(row) if row else None
        except (FileNotFoundError, sqlite3.Error):
            return None

    async def resolve(self, task_id: str, evidence_key: str) -> Optional[ResolvedEvidence]:
        task_info = await self._task_loader(task_id)
        paths = self._paths(task_info)
        if evidence_key.startswith(FILE_KEY_PREFIX):
            return self._resolve_file(task_id, evidence_key, task_info, paths)
        if evidence_key.startswith(CLUSTER_KEY_PREFIX):
            return self._resolve_cluster(task_id, evidence_key, task_info, paths)
        raise InvalidEvidenceKey(f"unsupported evidence key: {evidence_key!r}")

    def _resolve_file(self, task_id: str, key: str, task_info: Dict[str, Any], paths: Dict[str, str]) -> Optional[ResolvedEvidence]:
        normalized = parse_file_evidence_key(key)
        row = self._load_file_row(paths["files_db"], normalized)
        if row is None:
            return None
        forensic_path = row.get("path") or normalized
        content_path = forensic_path if os.path.exists(forensic_path) else None
        extraction_dir = task_info.get("extraction_directory") or ""
        if not content_path and extraction_dir:
            relative = normalize_forensic_path(forensic_path).lstrip("/")
            candidates = [Path(extraction_dir) / relative, Path(extraction_dir) / os.path.basename(relative)]
            content_path = next((str(item) for item in candidates if item.exists()), None)
        return ResolvedEvidence(
            task_id=task_id, evidence_key=key, evidence_type="file",
            title=row.get("name") or os.path.basename(normalized),
            timestamp=row.get("mtime") or row.get("ctime"),
            start_time=row.get("mtime") or row.get("ctime"),
            end_time=row.get("mtime") or row.get("ctime"),
            metadata=row, initial_description=row.get("llm_description"),
            initial_summary=row.get("llm_summary"), source_refs=[forensic_path],
            related_evidence_keys=[], source_hash=row.get("md5"), source_size=row.get("size"),
            source_mtime=row.get("mtime") or row.get("ctime"), source_updated_at=row.get("llm_analyzed_at"),
            file_path=forensic_path, content_path=content_path, md5=row.get("md5"),
            extension=row.get("extension"), is_deleted=row.get("is_deleted"),
        )

    def _resolve_cluster(self, task_id: str, key: str, task_info: Dict[str, Any], paths: Dict[str, str]) -> Optional[ResolvedEvidence]:
        time_window, event_type = parse_cluster_key(key)
        try:
            with self._connect_readonly(paths["events_db"]) as conn:
                if time_window >= 0:
                    cursor = conn.execute(
                        "SELECT * FROM events WHERE timestamp >= ? AND timestamp < ? "
                        "AND event_type = ? ORDER BY timestamp ASC, id ASC",
                        (time_window * 60, (time_window + 1) * 60, event_type),
                    )
                else:
                    # Preserve historical SQLite integer-division behavior for
                    # signed keys; new Timeline expansion rejects negative rows.
                    cursor = conn.execute(
                        "SELECT * FROM events WHERE (timestamp / 60) = ? AND event_type = ? "
                        "ORDER BY timestamp ASC, id ASC",
                        (time_window, event_type),
                    )
                hasher = hashlib.sha256()
                sampled: List[Dict[str, Any]] = []
                candidate_paths = set()
                event_count = 0
                start: Optional[int] = None
                end: Optional[int] = None
                initial_summary: Optional[str] = None
                initial_description: Optional[str] = None
                digest_fields = (
                    "id", "timestamp", "event_type", "file_path", "inode",
                    "description", "file_size", "file_type", "system_context",
                    "priority", "severity", "event_source", "event_category",
                    "normalized_type", "source_id",
                )
                for source_row in cursor:
                    row = dict(source_row)
                    event_count += 1
                    timestamp = row.get("timestamp")
                    if timestamp is not None:
                        start = timestamp if start is None else min(start, timestamp)
                        end = timestamp if end is None else max(end, timestamp)
                    if initial_summary is None and row.get("llm_summary"):
                        initial_summary = row["llm_summary"]
                    if initial_description is None and row.get("llm_description"):
                        initial_description = row["llm_description"]
                    canonical_member = {field: row.get(field) for field in digest_fields}
                    hasher.update(json.dumps(canonical_member, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                    hasher.update(b"\n")
                    if row.get("file_path"):
                        candidate_paths.add(str(row["file_path"]))
                    if len(sampled) < MAX_CLUSTER_EVENTS_FOR_LLM:
                        sampled.append(row)
        except (FileNotFoundError, sqlite3.Error):
            return None
        if not event_count:
            return None
        source_hash = hasher.hexdigest()
        source_refs = sorted(candidate_paths)
        existing_paths = self._existing_file_paths(paths["files_db"], source_refs)
        related_keys = [
            make_file_evidence_key(path)
            for path in source_refs
            if normalize_forensic_path(path) in existing_paths
        ][:MAX_RELATED_EVIDENCE]
        content = "\n".join(
            f"[{row.get('timestamp')}] {row.get('event_type')} {row.get('file_path') or ''}: {row.get('description') or row.get('llm_description') or row.get('llm_summary') or ''}"[:400]
            for row in sampled
        )[:MAX_CONTENT_CHARS]
        metadata = {
            "event_type": event_type,
            "time_window": time_window,
            "event_count": event_count,
            "sampled_event_count": len(sampled),
            "truncated": len(sampled) < event_count,
            "snapshot_digest_kind": "full_cluster_events",
            "cluster_digest_algorithm": "cluster-members-immutable-v1",
            "events": sampled,
        }
        return ResolvedEvidence(
            task_id=task_id, evidence_key=key, evidence_type="event_cluster",
            title=initial_summary or f"{event_type} 活动聚类（{event_count} 个事件）",
            timestamp=start, start_time=start, end_time=end, metadata=metadata, content=content,
            initial_description=initial_description,
            initial_summary=initial_summary,
            source_refs=source_refs, related_evidence_keys=related_keys,
            source_hash=source_hash, source_size=event_count, source_mtime=start,
            source_updated_at=None,
        )

    async def bounded_content(self, resolved: ResolvedEvidence) -> str:
        if resolved.evidence_type == "event_cluster":
            return str(resolved.content or "")[:MAX_CONTENT_CHARS]
        if not resolved.content_path:
            return ""
        if self._content_reader:
            return (await self._content_reader(resolved.content_path))[:MAX_CONTENT_CHARS]
        try:
            with open(resolved.content_path, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read(MAX_CONTENT_CHARS)
        except OSError:
            return ""
