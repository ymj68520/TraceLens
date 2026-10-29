"""File-centric investigation events.

The workbench's left column is anchored on a *file*, so its event nodes must be
derived from that file — not from an event cluster keyed on
``(minute, event_type)``. This module builds one event per analyzed file,
drawing on two evidence sources:

1. ``events.db`` — the file's MACB history (created / modified / accessed /
   changed). These rows already exist for every analyzed file.
2. the task's scenario artifact DB (``windows.db`` / ``linux.db``) — rows
   the platform analyzer attributed to this file, e.g. a Prefetch entry with
   its run count and execution times, or an nginx access log.

Only (1) is guaranteed. (2) is best-effort: a missing DB, a missing table or
an unreadable timestamp degrades to "no artifact rows" instead of failing the
seed, because a task can legitimately have no platform analysis.

Artifact rows are matched on the file's forensic path, not on any
host-extracted path: ``prefetch_files.file_path`` points at
``<task>/windows_extracted_files/prefetch/X.pf`` while ``files.path`` is
``/Windows/Prefetch/X.pf``. ``_normalize_artifact_path`` bridges the two.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Artifact rows are bounded per file so one chatty log file cannot turn a
# single event node into a thousand-line prompt.
MAX_ARTIFACT_ROWS_PER_FILE = 20

# Timestamps outside this window are parser artifacts, not observations:
# 0/None from an unparsed field, or a FILETIME read as Unix seconds.
_MIN_TS = 978307200      # 2001-01-01
_MAX_TS = 4102444800     # 2100-01-01


def _connect_ro(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{quote(path, safe='/')}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda data: data.decode("utf-8", "replace")
        return conn
    except sqlite3.Error as exc:
        logger.warning("artifact db unavailable %s: %s", path, exc)
        return None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]
    ).fetchone()
    return row is not None


def _sane_ts(value: Any) -> Optional[int]:
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return ts if _MIN_TS <= ts <= _MAX_TS else None


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards for a literal suffix match (ESCAPE '\\')."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------


def _normalize_artifact_path(raw: str) -> Optional[str]:
    """Map an artifact-side path onto the forensic ``files.path`` space.

    Android/Linux analyzers keep extracted copies under the task directory, so
    the same artifact can be referenced by a host path or by its in-image path:

      * Windows extraction  ``<task>/windows_extracted_files/prefetch/A.pf``
        -> ``/Windows/Prefetch/A.pf``
      * Linux extraction    ``<task>/linux_extracted_files/var/log/messages``
        -> ``/var/log/messages``
      * Windows drive path  ``C:\\Users\\admin\\x.txt`` -> ``/Users/admin/x.txt``
      * already-forensic    ``/var/log/messages`` (returned as-is)

    Everything under the extraction root is already laid out with the in-image
    directory structure, so the prefix is simply stripped. Prefetch is the one
    exception: the extractor writes it to ``prefetch/`` while the image path is
    ``/Windows/Prefetch/``, so that segment is canonicalised.
    """
    if not raw:
        return None
    path = str(raw).replace("\\", "/")

    for marker in ("windows_extracted_files/", "linux_extracted_files/",
                   "android_extracted_files/", "extracted_files/"):
        if marker in path:
            rest = path.split(marker, 1)[1]
            if not rest:
                return None
            head, sep, tail = rest.partition("/")
            if head.lower() == "prefetch" and sep:
                return f"/Windows/Prefetch/{tail}"
            if head.lower() in ("shortcuts", "recyclebin") and sep:
                # These copies are renamed by the extractor (inode prefix /
                # $I file id), so they carry no stable identity of their own.
                return None
            # Otherwise the remainder already is the in-image path.
            return "/" + rest

    if len(path) > 1 and path[1] == ":":
        # C:\Users\... -> /Users/...
        return "/" + path[3:].lstrip("/") if len(path) > 3 else None

    if path.startswith("/"):
        return path
    return None


# ---------------------------------------------------------------------------
# Artifact readers (one per platform)
# ---------------------------------------------------------------------------

def _read_windows_artifacts(
    db_path: str, forensic_path: str
) -> List[Dict[str, Any]]:
    conn = _connect_ro(db_path)
    if conn is None:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        # Prefetch: the .pf file itself is a files.path row, and it carries
        # the executable's execution history.
        if _has_table(conn, "prefetch_files"):
            for row in conn.execute(
                "SELECT executable_name, run_count, last_run_time, file_path "
                "FROM prefetch_files"
            ):
                mapped = _normalize_artifact_path(row["file_path"] or "")
                if not mapped or mapped.lower() != forensic_path.lower():
                    continue
                rows.append({
                    "source": "prefetch",
                    "kind": "execution",
                    "executable": row["executable_name"],
                    "run_count": row["run_count"],
                    "timestamp": _sane_ts(row["last_run_time"]),
                })
                if len(rows) >= MAX_ARTIFACT_ROWS_PER_FILE:
                    return rows

        if _has_table(conn, "event_logs"):
            for row in conn.execute(
                "SELECT log_source, event_id, message, timestamp FROM event_logs "
                "WHERE 1=0"
            ):
                pass  # event_logs have no file association; kept explicit
    finally:
        conn.close()
    return rows


_LINUX_PATH_COLUMNS = (
    ("linux_nginx_access_logs", "source_file", ("method", "url", "status_code")),
    ("linux_apache_access_logs", "source_file", ("method", "url", "status_code")),
    ("linux_audit_events", "source_file", ("syscall_name", "exe", "success")),
    ("linux_audit_logs", "source_file", ("type", "action", "result")),
    ("linux_shell_history", "history_file", ("username", "command")),
    ("linux_recent_documents", "file_path", ("username", "mime_type")),
    ("linux_log_entries", "log_file", ("process", "level", "message")),
    ("linux_setuid_files", "file_path", ("owner", "permissions", "is_suspicious")),
)


def _read_linux_artifacts(
    db_path: str, forensic_path: str
) -> List[Dict[str, Any]]:
    conn = _connect_ro(db_path)
    if conn is None:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for table, path_column, detail_columns in _LINUX_PATH_COLUMNS:
            if not _has_table(conn, table):
                continue
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if path_column not in columns:
                continue
            # linux_log_entries keeps a display string in `timestamp`
            # ("May 28 15:11:01") and the parseable value in `unix_timestamp`.
            ts_column = "unix_timestamp" if "unix_timestamp" in columns else (
                "timestamp" if "timestamp" in columns else None
            )
            select = [path_column] + [c for c in detail_columns if c in columns]
            if ts_column:
                select.append(ts_column)

            def _emit(result_rows):
                for row in result_rows:
                    detail = {
                        key: row[key] for key in row.keys()
                        if key != path_column and key != ts_column
                    }
                    rows.append({
                        "source": table,
                        "kind": "log_record",
                        "detail": detail,
                        "timestamp": _sane_ts(row[ts_column]) if ts_column else None,
                    })

            sql = f"SELECT {', '.join(select)} FROM {table} WHERE {path_column} = ? LIMIT ?"
            _emit(conn.execute(sql, [forensic_path, MAX_ARTIFACT_ROWS_PER_FILE]).fetchall())

            if len(rows) < MAX_ARTIFACT_ROWS_PER_FILE:
                # The analyzers keep extracted copies under the task directory,
                # and log-style columns then store that host path
                # (<task>/linux_extracted_files/var/log/messages). Suffix match
                # bridges both spellings of the same in-image file.
                pattern = "%" + _like_escape(forensic_path)
                sql = (
                    f"SELECT {', '.join(select)} FROM {table} "
                    f"WHERE {path_column} LIKE ? ESCAPE '\\' AND {path_column} <> ? "
                    f"LIMIT ?"
                )
                _emit(conn.execute(
                    sql,
                    [pattern, forensic_path, MAX_ARTIFACT_ROWS_PER_FILE - len(rows)],
                ).fetchall())

            if len(rows) >= MAX_ARTIFACT_ROWS_PER_FILE:
                return rows[:MAX_ARTIFACT_ROWS_PER_FILE]
    finally:
        conn.close()
    return rows[:MAX_ARTIFACT_ROWS_PER_FILE]


def read_file_artifacts(task: Dict[str, Any], forensic_path: str) -> List[Dict[str, Any]]:
    """Return the artifact rows the platform analyzers attributed to a file."""
    if not forensic_path:
        return []
    scenario_dbs = task.get("scenario_databases") or {}
    flat = {
        "windows": task.get("output_windows_db") or scenario_dbs.get("windows") or "",
        "linux": task.get("output_linux_db") or scenario_dbs.get("linux") or "",
    }
    rows: List[Dict[str, Any]] = []
    if flat["windows"]:
        rows.extend(_read_windows_artifacts(flat["windows"], forensic_path))
    if flat["linux"]:
        rows.extend(_read_linux_artifacts(flat["linux"], forensic_path))
    return rows[:MAX_ARTIFACT_ROWS_PER_FILE]


# ---------------------------------------------------------------------------
# MACB history (always available)
# ---------------------------------------------------------------------------

_MACB = (("crtime", "创建"), ("mtime", "修改"), ("atime", "访问"), ("ctime", "变更"))

# Prompt for the one optional narrative call per file-with-artifacts. It is
# deliberately short and constrained: the model restates the collected rows as
# an investigative observation, and is told not to speculate beyond them.
_NARRATIVE_PROMPT = (
    "你是电子数据取证分析员。下面给出某个文件及其关联的系统痕迹记录。"
    "请用 2-4 句中文总结这个文件反映的调查上有意义的事实，"
    "只依据给定记录，不要推测未出现的内容，不要编造时间或次数。"
    "输出纯文本，不要标题、不要 Markdown。"
)


def read_macb_events(task: Dict[str, Any], forensic_path: str) -> List[Dict[str, Any]]:
    """The file's own MACB timestamps as discrete observations."""
    events_db = task.get("output_events_db") or ""
    if not events_db or not os.path.isfile(events_db):
        return []
    conn = _connect_ro(events_db)
    if conn is None:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        if not _has_table(conn, "events"):
            return []
        for row in conn.execute(
            "SELECT timestamp, event_type, description FROM events "
            "WHERE file_path = ? ORDER BY timestamp LIMIT 64",
            [forensic_path],
        ):
            ts = _sane_ts(row["timestamp"])
            if ts is None:
                continue
            rows.append({
                "source": "filesystem",
                "kind": "macb",
                "event_type": row["event_type"],
                "description": row["description"],
                "timestamp": ts,
            })
    finally:
        conn.close()
    return rows


# ---------------------------------------------------------------------------
# Event node construction
# ---------------------------------------------------------------------------

def build_file_event_node(
    task: Dict[str, Any],
    file_row: Dict[str, Any],
    artifacts: List[Dict[str, Any]],
    macb: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compose one event node's title/summary from its evidence.

    Deterministic on purpose: this runs once per analyzed file inside the file
    analysis stage, and the same inputs must always produce the same node so
    re-seeding is idempotent. The summary states only what the rows contain —
    no inference beyond counting and naming the sources.
    """
    name = file_row.get("name") or (file_row.get("path") or "").rsplit("/", 1)[-1]
    parts: List[str] = []

    if artifacts:
        sources = sorted({row["source"] for row in artifacts})
        parts.append(f"{name} 关联 {len(artifacts)} 条平台工件记录（{', '.join(sources)}）。")
    else:
        parts.append(f"{name} 仅有文件系统时间记录。")

    for row in artifacts:
        if row["source"] == "prefetch":
            exec_name = row.get("executable") or name
            runs = row.get("run_count")
            ts = row.get("timestamp")
            if runs and ts:
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                parts.append(f"Prefetch 显示 {exec_name} 共执行 {runs} 次，最近一次 {when}。")
            elif runs:
                parts.append(f"Prefetch 显示 {exec_name} 共执行 {runs} 次。")
            elif ts:
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                parts.append(f"Prefetch 显示 {exec_name} 最近一次执行于 {when}。")
        elif row.get("detail"):
            detail = "，".join(f"{k}={v}" for k, v in row["detail"].items() if v not in (None, ""))
            if detail:
                parts.append(f"{row['source']}: {detail[:160]}")

    if macb:
        kind_count: Dict[str, int] = {}
        for row in macb:
            kind_count[row["event_type"]] = kind_count.get(row["event_type"], 0) + 1
        summary_kinds = "，".join(f"{k}×{v}" for k, v in sorted(kind_count.items()))
        first = min(r["timestamp"] for r in macb)
        last = max(r["timestamp"] for r in macb)
        parts.append(
            "文件系统记录 %d 条（%s），时间范围 %s ~ %s。"
            % (
                len(macb), summary_kinds,
                time.strftime("%Y-%m-%d %H:%M", time.localtime(first)),
                time.strftime("%Y-%m-%d %H:%M", time.localtime(last)),
            )
        )

    timestamps = [r["timestamp"] for r in artifacts if r.get("timestamp")]
    timestamps += [r["timestamp"] for r in macb if r.get("timestamp")]
    start = min(timestamps) if timestamps else None
    end = max(timestamps) if timestamps else None

    title = f"{name} 活动"
    if artifacts:
        title = f"{name} · {len(artifacts)} 条工件记录"

    return {
        "title": title[:200],
        "summary": "\n".join(parts)[:4000],
        "start_time": start,
        "end_time": end,
        "evidence_keys": [f"file:{file_row.get('path') or ''}"],
        "source_counts": {
            "artifact": len(artifacts),
            "macb": len(macb),
        },
    }


def build_file_event_nodes(
    task: Dict[str, Any], limit: int = 5000
) -> List[Dict[str, Any]]:
    """Build one event node per LLM-analyzed file (bootstrap input)."""
    files_db = task.get("output_files_db") or ""
    if not files_db or not os.path.isfile(files_db):
        return []
    conn = _connect_ro(files_db)
    if conn is None:
        return []
    try:
        if not _has_table(conn, "files"):
            return []
        rows = conn.execute(
            "SELECT path, name, llm_summary, llm_description, llm_analyzed_at "
            "FROM files WHERE llm_analyzed_at IS NOT NULL "
            "ORDER BY llm_analyzed_at DESC LIMIT ?",
            [limit],
        ).fetchall()
    finally:
        conn.close()

    nodes: List[Dict[str, Any]] = []
    for row in rows:
        path = row["path"] or ""
        if not path:
            continue
        try:
            artifacts = read_file_artifacts(task, path)
        except sqlite3.Error as exc:
            logger.warning("artifact read failed for %s: %s", path, exc)
            artifacts = []
        try:
            macb = read_macb_events(task, path)
        except sqlite3.Error as exc:
            logger.warning("macb read failed for %s: %s", path, exc)
            macb = []
        node = build_file_event_node(
            task,
            {"path": path, "name": row["name"] or path.rsplit("/", 1)[-1]},
            artifacts,
            macb,
        )
        node["file_path"] = path
        # The file's own LLM analysis seeds the node's narrative; the events
        # above extend it. Reusing it keeps the seed LLM-free.
        node["initial_summary"] = row["llm_summary"] or ""
        nodes.append(node)
    return nodes
