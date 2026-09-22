"""File-centric timeline projection for the Investigation workbench.

Node set = files "judged as analyzed" — every file the task's Investigation
actually covers: direct ``file:`` evidence links, plus the file paths surfaced
by the clusters linked to Investigation Events (per cluster bounded to
``MAX_RELATED_EVIDENCE`` member paths, mirroring the evidence resolver's
related-evidence discipline). Each node carries the file's four MACB
timestamps (crtime/mtime/atime/ctime from the task's raw store, falling back
to files.db mtime/ctime) with the latest of them as the axis position; the
associated Investigation Events ride along as corroborating references.

Read-only: GET paths never create investigation.db or any task store, and
missing source DBs degrade to empty projections instead of errors.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Any

from ..investigation_evidence import (
    CLUSTER_KEY_PREFIX,
    FILE_KEY_PREFIX,
    MAX_RELATED_EVIDENCE,
    normalize_forensic_path,
    parse_cluster_key,
    parse_file_evidence_key,
    trunc_div,
)
from ..investigation_errors import InvalidEvidenceKey
from .graph_reader import InvestigationGraphReader

MACB_KEYS = ("crtime", "mtime", "atime", "ctime")


def _normalize_fast(value: Any) -> str:
    """normalize_forensic_path 的快速通道：已规范的路径跳过正则与重建。"""
    path = value or ""
    if isinstance(path, str) and "\\" not in path and "//" not in path and not path.endswith("/"):
        return path
    return normalize_forensic_path(path)


def _connect_ro(path: str) -> sqlite3.Connection:
    # Same discipline as InvestigationGraphReader._connect: mode=ro refuses to
    # create or write; the path is server-trusted but still URI-quoted.
    uri = f"file:{urllib.parse.quote(str(path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _fallback_db(task: dict, suffix: str) -> str:
    files_db = task.get("output_files_db") or ""
    if files_db.endswith("_files.db"):
        return files_db[: -len("_files.db")] + suffix
    if files_db.endswith("files.db"):
        return files_db[: -len("files.db")] + suffix
    return ""


def _cluster_member_paths_batch(
    events_db: str, cluster_keys: list[str]
) -> dict[str, list[str]]:
    """File paths surfaced by each cluster's first member events.

    Bounded like the evidence resolver's related-file keys: at most
    ``MAX_RELATED_EVIDENCE`` distinct normalized paths per cluster. One
    streaming pass over events.db (rowid order, so results are
    insertion-deterministic) resolves every cluster in a single scan —
    per-cluster queries would re-walk huge minute-bucket index ranges.
    """
    wanted: dict[tuple[int, str], str] = {}
    for key in cluster_keys:
        try:
            time_window, event_type = parse_cluster_key(key)
        except InvalidEvidenceKey:
            continue
        wanted[(time_window, event_type)] = key
    seen: dict[str, set[str]] = {key: set() for key in cluster_keys}
    result: dict[str, list[str]] = {key: [] for key in cluster_keys}
    if not wanted or not events_db or not os.path.exists(events_db):
        return result
    try:
        with contextlib.closing(_connect_ro(events_db)) as conn:
            for event_id, timestamp, event_type, file_path in conn.execute(
                "SELECT id, timestamp, event_type, file_path FROM events "
                "WHERE file_path IS NOT NULL"
            ):
                if not isinstance(timestamp, int):
                    continue
                key = wanted.get((trunc_div(timestamp, 60), event_type))
                if key is None:
                    continue
                bucket = seen[key]
                path = _normalize_fast(file_path)
                if path and path not in bucket:
                    bucket.add(path)
                    result[key].append(path)
                    if len(bucket) >= MAX_RELATED_EVIDENCE:
                        del wanted[(
                            trunc_div(timestamp, 60), event_type
                        )]
                        if not wanted:
                            break
    except sqlite3.Error:
        pass
    return result


def _load_file_metadata(
    files_db: str, raw_db: str, paths: set[str]
) -> dict[str, dict[str, Any]]:
    """Merge files.db descriptors with raw.db MACB times, keyed by path.

    Neither store indexes ``path``, so each DB is streamed exactly once and
    filtered in Python instead of issuing per-chunk ``IN`` scans.
    """
    merged: dict[str, dict[str, Any]] = {}

    def _key(value: Any) -> str:
        return _normalize_fast(value or "")

    if files_db and os.path.exists(files_db):
        try:
            with contextlib.closing(_connect_ro(files_db)) as conn:
                for row in conn.execute(
                    "SELECT path, name, size, extension, category, llm_summary, "
                    "mtime, ctime FROM files"
                ):
                    key = _key(row["path"])
                    if key not in paths:
                        continue
                    merged[key] = {
                        "name": row["name"],
                        "size": row["size"],
                        "extension": row["extension"],
                        "category": row["category"],
                        "llm_summary": row["llm_summary"],
                        # files.db carries no atime/crtime; raw.db (when
                        # present) overwrites mtime/ctime with its fuller set.
                        "mtime": row["mtime"],
                        "ctime": row["ctime"],
                    }
        except sqlite3.Error:
            pass

    if raw_db and os.path.exists(raw_db):
        try:
            with contextlib.closing(_connect_ro(raw_db)) as conn:
                for row in conn.execute(
                    "SELECT path, crtime, mtime, atime, ctime, is_deleted FROM files"
                ):
                    key = _key(row["path"])
                    if key not in paths:
                        continue
                    entry = merged.setdefault(key, {})
                    for macb in MACB_KEYS:
                        if row[macb] is not None:
                            entry[macb] = row[macb]
                    if row["is_deleted"] is not None:
                        entry["is_deleted"] = row["is_deleted"]
        except sqlite3.Error:
            pass

    return merged


def load_analyzed_paths(files_db: str) -> set[str]:
    """已分析文件集:files.db 中 ``llm_analyzed_at`` 非空的 path(去重)。

    文件中心口径的单一来源 —— 初管全量入报(seed-analyzed)与文件时间线
    投影共用。与判定页 file-candidates 读模型同一 files 表、同一 path
    空间;真实镜像可能携带重复 path 行(多分区/多副本),按 path 去重。
    只读:库不存在或无该表时返回空集,绝不发明文件。
    """
    if not files_db or not os.path.exists(files_db):
        return set()
    analyzed: set[str] = set()
    try:
        with contextlib.closing(_connect_ro(files_db)) as conn:
            for row in conn.execute(
                "SELECT path FROM files WHERE llm_analyzed_at IS NOT NULL"
            ):
                path = row["path"]
                if path:
                    analyzed.add(path)
    except sqlite3.DatabaseError:
        return set()
    return analyzed


def covered_file_event_map(
    db_path: Path,
    task_id: str,
    task: dict,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """初管覆盖口径：任务调查实际覆盖的文件 → 关联事件 id 集合。

    直接 ``file:`` 证据链 + 关联簇按 ``MAX_RELATED_EVIDENCE`` 截断的成员
    路径。时间线投影与"全量列入证据"的种子端点共用，保证两侧对"已分析
    文件"的判定口径永远一致。返回 (映射, 诊断计数)。
    """
    reader = InvestigationGraphReader(db_path, task_id)
    links = reader.list_event_evidence_links()

    events_db = task.get("output_events_db") or ""
    cluster_keys = sorted(
        {
            link.evidence_key
            for link in links
            if link.evidence_key.startswith(CLUSTER_KEY_PREFIX)
        }
    )
    cluster_members = _cluster_member_paths_batch(events_db, cluster_keys)

    file_events: dict[str, set[str]] = {}
    for link in links:
        key = link.evidence_key
        if key.startswith(FILE_KEY_PREFIX):
            try:
                path = normalize_forensic_path(parse_file_evidence_key(key))
            except InvalidEvidenceKey:
                continue
            if path:
                file_events.setdefault(path, set()).add(link.event_id)
        else:
            for path in cluster_members.get(key, ()):
                file_events.setdefault(path, set()).add(link.event_id)
    return file_events, {"link_count": len(links), "cluster_count": len(cluster_keys)}


def collect_file_timeline(
    db_path: Path,
    task_id: str,
    task: dict,
    *,
    limit: int = 500,
    ensure_paths: "list[str] | tuple[str, ...] | set[str]" = (),
) -> dict[str, Any]:
    """Build the file-centric timeline projection (sync; run via to_thread).

    ``task`` is the trusted server-side task record — its DB paths are the only
    forensic sources consulted; client input never reaches a path. Nodes are
    ordered newest-first by MACB latest time so the timeline surfaces the most
    recent file activity; time-less files trail at the bottom.

    节点集(文件中心口径):调查覆盖的文件(直接 ``file:`` 关联 + 关联簇成员)
    ∪ **已分析文件**(``llm_analyzed_at IS NOT NULL``,与 file-candidates /
    seed-analyzed 同口径)。后者是工作台在最小模式(事件簇 LLM 关闭、零事件
    关联)下的兜底节点源;前端的节点契约本就是"时间线节点 = 已分析文件"。

    ``ensure_paths``: deep-link support (report citation → workbench). Paths
    the limit cut would drop are appended so the caller can always position
    on the requested file. Covered files are always rescued; paths that are
    merely analyzed (present in the task's file stores, e.g. report evidence
    with no event link) are rescued too, as undated/event-less nodes; unknown
    paths are ignored — the projection never invents files.

    只读:investigation.db 缺失时退化为纯"已分析文件"投影(事件关联与判定
    三态为空),绝不物化该库。
    """
    store_exists = db_path.exists()
    reader = InvestigationGraphReader(db_path, task_id)
    events = reader.list_events() if store_exists else []

    files_db = task.get("output_files_db") or ""
    raw_db = task.get("output_raw_db") or _fallback_db(task, "raw.db")

    if store_exists:
        file_events, diagnostics = covered_file_event_map(db_path, task_id, task)
        cluster_count = diagnostics["cluster_count"]
    else:
        file_events = {}
        diagnostics = {"link_count": 0, "cluster_count": 0}
        cluster_count = 0
    analyzed_paths = {_normalize_fast(p) for p in load_analyzed_paths(files_db)}

    known_event_ids = {event.event_id for event in events}
    ensure_normalized = [
        path
        for path in (_normalize_fast(raw) for raw in ensure_paths)
        if path
    ]
    metadata = _load_file_metadata(
        files_db, raw_db, set(file_events) | analyzed_paths | set(ensure_normalized)
    )

    # 判定状态（R1 report_evidence）：文件节点的报告证据三态直接随投影下发，
    # 前端节点/卡片无需再逐文件回查 evidence detail。从未判定 → None。
    report_status_by_path: dict[str, str] = {}
    if store_exists:
        for item in reader.list_report_evidence():
            key = item.evidence_key
            if not key.startswith(FILE_KEY_PREFIX):
                continue
            try:
                judged_path = normalize_forensic_path(parse_file_evidence_key(key))
            except InvalidEvidenceKey:
                continue
            if judged_path:
                report_status_by_path[judged_path] = item.report_status

    node_paths = set(file_events) | analyzed_paths
    files: list[dict[str, Any]] = []
    for path in sorted(node_paths):
        event_ids = sorted(
            event_id
            for event_id in file_events.get(path, ())
            if event_id in known_event_ids
        )
        entry = dict(metadata.get(path) or {})
        entry.update(
            path=path,
            name=entry.get("name") or path.rstrip("/").rsplit("/", 1)[-1],
            event_ids=event_ids,
            event_count=len(event_ids),
            report_status=report_status_by_path.get(path),
        )
        times = {key: entry[key] for key in MACB_KEYS if entry.get(key)}
        entry["latest_time"] = max(times.values()) if times else None
        files.append(entry)

    # 深链目标若"已分析但未挂任何事件"（典型：报告证据文件），以无事件
    # 节点补入投影；文件库中不存在的路径绝不发明。
    for path in ensure_normalized:
        if path in node_paths or not metadata.get(path):
            continue
        entry = dict(metadata[path])
        entry.update(
            path=path,
            name=entry.get("name") or path.rstrip("/").rsplit("/", 1)[-1],
            event_ids=[],
            event_count=0,
            report_status=report_status_by_path.get(path),
        )
        times = {key: entry[key] for key in MACB_KEYS if entry.get(key)}
        entry["latest_time"] = max(times.values()) if times else None
        files.append(entry)

    dated = sorted(
        (item for item in files if item["latest_time"] is not None),
        key=lambda item: (-item["latest_time"], item["path"]),
    )
    undated = sorted(
        (item for item in files if item["latest_time"] is None),
        key=lambda item: item["path"],
    )
    ordered = (dated + undated)[:limit]
    total = len(dated) + len(undated)

    # 深链保障：limit 截断会丢掉时间轴尾部之外的文件，而报告引用深链必须
    # 能落到目标节点。覆盖文件与"已分析未挂事件"的文件都可补回，投影外
    # 的未知路径忽略。
    ensured_paths: list[str] = []
    if ensure_paths:
        included = {item["path"] for item in ordered}
        by_path = {item["path"]: item for item in files}
        for raw in ensure_paths:
            path = _normalize_fast(raw)
            if not path or path in included:
                continue
            entry = by_path.get(path)
            if entry is not None:
                ordered.append(entry)
                included.add(path)
                ensured_paths.append(path)

    return {
        "task_id": task_id,
        "files": ordered,
        "total_count": total,
        "axis": {
            "start": dated[-1]["latest_time"] if dated else None,
            "end": dated[0]["latest_time"] if dated else None,
        },
        "scope": {
            "event_count": len(events),
            "link_count": diagnostics["link_count"],
            "cluster_count": cluster_count,
            "undated_file_count": len(undated),
            "limited": total > limit,
            "ensured_paths": ensured_paths,
        },
    }


def empty_file_timeline(task_id: str) -> dict[str, Any]:
    """Missing-store result: GET never materializes investigation.db."""
    return {
        "task_id": task_id,
        "files": [],
        "total_count": 0,
        "axis": {"start": None, "end": None},
        "scope": {
            "event_count": 0,
            "link_count": 0,
            "cluster_count": 0,
            "undated_file_count": 0,
            "limited": False,
            "ensured_paths": [],
        },
    }
