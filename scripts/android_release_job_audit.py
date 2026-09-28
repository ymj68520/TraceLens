#!/usr/bin/env python3
"""Read-only, redacted live-job inventory before a TraceLens field cutover.

Requires explicit state locations. Never returns evidence paths, record bodies,
credentials, queue payloads or report prose. UNKNOWN is intentional when a
process/worker cannot be tied to a persisted job.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlsplit


ACTIVE = frozenset({"queued", "running", "generating", "in_progress", "assigned", "pending"})


def _ro(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("audit database is missing or is a symlink")
    conn = sqlite3.connect(f"file:{quote(str(path.resolve()), safe='/')}?mode=ro", uri=True, timeout=3)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _statuses(conn, table: str) -> dict[str, int]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
        return {}
    # Fixed names only; no SQL is supplied by the caller.
    return dict(conn.execute(f'SELECT status,COUNT(*) FROM "{table}" GROUP BY status'))


def _open_file_owners(source: Path, job_dir: Path) -> list[dict]:
    source = source.resolve(strict=False)
    job_dir = job_dir.resolve(strict=False)
    hits = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            fds = list((process / "fd").iterdir())
        except OSError:
            continue
        kinds = set()
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target == str(source) or target.startswith(str(source) + os.sep):
                kinds.add("source")
            if target == str(job_dir) or target.startswith(str(job_dir) + os.sep):
                kinds.add("job")
        if kinds:
            try:
                comm = (process / "comm").read_text(encoding="utf-8").strip()
            except OSError:
                comm = "unknown"
            hits.append({"pid": int(process.name), "comm": comm, "open_kinds": sorted(kinds)})
    return hits


def _preflight(root: Path) -> dict:
    counts = collections.Counter()
    ambiguous = []
    for job in sorted(root.glob("*/job.json")):
        if job.is_symlink():
            counts["unsafe_job_path"] += 1
            continue
        try:
            data = json.loads(job.read_text(encoding="utf-8"))
            status = str(data.get("status", "UNKNOWN"))
            counts[status] += 1
            if status in ACTIVE:
                source = Path(str(data.get("source_path", "")))
                owners = _open_file_owners(source, job.parent) if source.is_absolute() else []
                ambiguous.append({
                    "job_id": job.parent.name,
                    "stored_status": status,
                    "created_at": data.get("created_at"),
                    "started_at": data.get("started_at"),
                    "job_mtime": dt.datetime.fromtimestamp(job.stat().st_mtime, dt.timezone.utc).isoformat(),
                    "bytes_read": data.get("bytes_read"),
                    "file_count": data.get("file_count"),
                    "manifest_available": data.get("manifest_available"),
                    "recorded_owner_pid": data.get("owner_pid"),
                    "recorded_heartbeat": data.get("heartbeat"),
                    "source_exists": source.exists() if source.is_absolute() else False,
                    "matching_open_files": owners,
                    "external_executor_excluded": False,
                    "conclusion": "UNKNOWN",
                })
        except (OSError, ValueError, TypeError):
            counts["unreadable_job"] += 1
    return {"stored_statuses": dict(counts), "ambiguous_jobs": ambiguous,
            "startup_replay_note": "get_job labels unowned queued/running as interrupted in memory; it does not persist a terminal state"}


def _task_and_analysis(tasks_json: Path) -> dict:
    if tasks_json.is_symlink():
        raise ValueError("task store is a symlink")
    tasks = json.loads(tasks_json.read_text(encoding="utf-8"))
    statuses = collections.Counter(str(item.get("status", "UNKNOWN")) for item in tasks)
    db_paths = set()
    for item in tasks:
        trusted = item.get("output_files_db") or item.get("output_events_db") or item.get("output_raw_db")
        if trusted:
            db_paths.add(Path(trusted).resolve(strict=False).parent / "investigation.db")
    stores = collections.Counter()
    secondary = collections.Counter()
    refresh = collections.Counter()
    for db_path in db_paths:
        if not db_path.is_file() or db_path.is_symlink():
            continue
        try:
            with _ro(db_path) as conn:
                stores[conn.execute("PRAGMA user_version").fetchone()[0]] += 1
                secondary.update(_statuses(conn, "secondary_analyses"))
                refresh.update(_statuses(conn, "investigation_event_refreshes"))
        except (sqlite3.DatabaseError, ValueError):
            stores["unreadable"] += 1
    return {"task_statuses": dict(statuses), "investigation_schema_versions": dict(stores),
            "secondary_analysis_statuses": dict(secondary), "event_refresh_statuses": dict(refresh),
            "task_running_is_not_global_quiescence": True}


def _reports(db_path: Path) -> dict:
    try:
        with _ro(db_path) as conn:
            return {"generation_statuses": _statuses(conn, "report_generation_inputs"),
                    "report_version_statuses": _statuses(conn, "report_versions")}
    except (sqlite3.DatabaseError, ValueError):
        return {"status": "UNKNOWN_UNREADABLE"}


def _imports(root: Path) -> dict:
    counts = collections.Counter()
    missing = 0
    for directory in root.iterdir() if root.is_dir() else ():
        if not directory.is_dir() or directory.is_symlink():
            continue
        manifest = directory / "report_manifest.json"
        if not manifest.is_file() or manifest.is_symlink():
            missing += 1
            continue
        try:
            counts[str(json.loads(manifest.read_text(encoding="utf-8")).get("status", "UNKNOWN"))] += 1
        except (OSError, ValueError):
            counts["unreadable"] += 1
    return {"manifest_statuses": dict(counts), "directories_without_manifest": missing,
            "active_import_request_observable": False}


def _redis() -> dict:
    try:
        import redis
        client = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2, decode_responses=True)
        statuses = collections.Counter()
        for key in client.scan_iter(match="job:*", count=100):
            statuses[client.hget(key, "status") or "UNKNOWN"] += 1
        return {"ingestion_queue_length": client.llen("ingestion_queue"),
                "ingestion_job_statuses": dict(statuses)}
    except Exception:
        return {"status": "UNKNOWN_REDIS_UNAVAILABLE"}


def _cs(cs_pid: int | None) -> dict:
    if not cs_pid:
        return {"status": "NOT_SELECTED"}
    try:
        entries = Path(f"/proc/{cs_pid}/environ").read_bytes().split(b"\0")
        raw = next((value.split(b"=", 1)[1].decode("utf-8") for value in entries
                    if value.startswith(b"DATABASE_URL=")), None)
        if raw is None or urlsplit(raw).scheme not in {"postgresql", "postgresql+psycopg2"}:
            return {"status": "UNKNOWN_DATABASE_CONFIGURATION"}
        from sqlalchemy import create_engine
        engine = create_engine(raw, connect_args={"connect_timeout": 3}, pool_pre_ping=False)
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                return {"command_statuses": dict(conn.exec_driver_sql(
                            "SELECT status::text,COUNT(*) FROM command_queue GROUP BY status").all()),
                        "analysis_task_statuses": dict(conn.exec_driver_sql(
                            "SELECT status::text,COUNT(*) FROM analysis_tasks GROUP BY status").all()),
                        "client_statuses": dict(conn.exec_driver_sql(
                            "SELECT status::text,COUNT(*) FROM clients GROUP BY status").all())}
        finally:
            engine.dispose()
    except Exception:
        return {"status": "UNKNOWN_CS_DATABASE_UNAVAILABLE"}


def audit(tasks_json: Path, python_data: Path, reports_db: Path, cs_pid: int | None) -> dict:
    if not tasks_json.is_file() or not python_data.is_dir():
        raise ValueError("explicit task and Python data roots are required")
    report = {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "tasks_and_investigation": _task_and_analysis(tasks_json),
              "preflight": _preflight(python_data / "evidence_preflight"),
              "third_party_reports": _imports(python_data / "android_report_imports"),
              "r2": _reports(reports_db), "graphiti_embedding": _redis(), "cs": _cs(cs_pid),
              "normalization_external_processes": "UNKNOWN_NOT_TRACKED_BY_TASK_STATUS",
              "offline_exports": "UNKNOWN_NO_PERSISTENT_JOB_REGISTRY"}
    report["cutover_quiescence_confirmed"] = False
    report["unproven_activity_domains"] = [
        "unowned_preflight", "incomplete_report_import", "normalization_process_ownership",
        "in_flight_HTTP_requests", "offline_export_processes",
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-json", type=Path, required=True)
    parser.add_argument("--python-data", type=Path, required=True)
    parser.add_argument("--reports-db", type=Path, required=True)
    parser.add_argument("--cs-pid", type=int)
    args = parser.parse_args()
    print(json.dumps(audit(args.tasks_json, args.python_data, args.reports_db, args.cs_pid),
                     ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
