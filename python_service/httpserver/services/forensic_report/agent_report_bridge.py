"""Bridge between Agent Autonomous Cycles and R2 Forensic Narrative Reports.

Whenever an Agent autonomous investigation cycle completes or findings are reviewed:
1. sync_agent_evidence(): Synchronizes evidence from investigation_findings and
   captured snapshots into the task's `report_evidence` table.
2. trigger_agent_cycle_report(): Safely admits a new frozen report generation
   and submits it to ReportGenerationExecutor in the background.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..investigation.paths import investigation_db_path_for_task

logger = logging.getLogger(__name__)

AGENT_CYCLE_REQUESTER = "agent_cycle"


def sync_agent_evidence_sync(task_id: str, db_path: Path, files_db_path: Optional[str] = None) -> int:
    """Synchronize evidence items from findings and snapshots into report_evidence.

    Returns the count of seeded report_evidence items.
    """
    if not db_path.exists():
        return 0

    now = datetime.now(timezone.utc).isoformat()
    now_ts = int(time.time())

    with sqlite3.connect(str(db_path), timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        # 1. Collect all evidence keys from findings (supporting FQER)
        finding_file_paths: set[tuple[str, str]] = set()  # (ev_key, normalized_path)
        findings = conn.execute(
            "SELECT evidence_refs_json FROM investigation_findings WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        for f in findings:
            if not f["evidence_refs_json"]:
                continue
            try:
                refs = json.loads(f["evidence_refs_json"]).get("refs", [])
                for ref in refs:
                    if not isinstance(ref, str):
                        continue
                    if ":file:" in ref or ref.startswith("file:"):
                        norm_p = ref.split(":file:", 1)[1] if ":file:" in ref else ref[5:]
                        finding_file_paths.add((ref, norm_p))
            except Exception:
                pass

        # 2. If files_db exists, ensure any referenced finding files are in evidence_snapshots
        if files_db_path and Path(files_db_path).exists() and finding_file_paths:
            try:
                with sqlite3.connect(f"file:{files_db_path}?mode=ro", uri=True) as files_conn:
                    files_conn.row_factory = sqlite3.Row
                    for ev_key, path in finding_file_paths:
                        exists = conn.execute(
                            "SELECT 1 FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                            (task_id, ev_key),
                        ).fetchone()
                        if not exists:
                            row = files_conn.execute(
                                "SELECT * FROM files WHERE path = ? LIMIT 1", (path,)
                            ).fetchone()
                            if row is not None:
                                r_dict = dict(row)
                                snap_json = json.dumps(
                                    {
                                        "evidence_type": "file",
                                        "normalized_path": path,
                                        "name": r_dict.get("name"),
                                        "extension": r_dict.get("extension"),
                                        "category": r_dict.get("category"),
                                        "type": r_dict.get("type"),
                                        "size": r_dict.get("size"),
                                        "md5": r_dict.get("md5"),
                                        "mtime": r_dict.get("mtime"),
                                        "ctime": r_dict.get("ctime"),
                                        "is_deleted": r_dict.get("is_deleted"),
                                        "initial_summary": r_dict.get("llm_summary"),
                                        "initial_description": r_dict.get("llm_description"),
                                        "initial_keywords": r_dict.get("llm_keywords"),
                                        "initial_model": r_dict.get("llm_model_used"),
                                        "initial_analyzed_at": r_dict.get("llm_analyzed_at"),
                                        "scene_type": r_dict.get("scene_type"),
                                        "scene_priority": r_dict.get("scene_priority"),
                                        "scene_relevant": r_dict.get("scene_relevant"),
                                    },
                                    ensure_ascii=False,
                                )
                                conn.execute(
                                    """INSERT OR IGNORE INTO evidence_snapshots
                                       (task_id, evidence_key, evidence_type, normalized_path, snapshot_json, captured_at)
                                       VALUES (?, ?, 'file', ?, ?, ?)""",
                                    (task_id, ev_key, path, snap_json, now_ts),
                                )
            except Exception as e:
                logger.warning("Error seeding files from files.db into snapshots: %s", e)

        # 3. Ensure all file snapshots are entered into report_evidence as 'main'
        file_snaps = conn.execute(
            "SELECT evidence_key FROM evidence_snapshots WHERE task_id = ? AND evidence_type = 'file'",
            (task_id,),
        ).fetchall()

        seeded_count = 0
        for s in file_snaps:
            ev_key = s["evidence_key"]
            conn.execute(
                """INSERT OR IGNORE INTO report_evidence
                   (task_id, evidence_key, report_status, analysis_id, added_by, created_at, updated_at)
                   VALUES (?, ?, 'main', NULL, ?, ?, ?)""",
                (task_id, ev_key, AGENT_CYCLE_REQUESTER, now, now),
            )
            seeded_count += 1

        conn.commit()
        return seeded_count


async def trigger_agent_cycle_report(
    task_id: str,
    *,
    manager: Any,
    requested_by: str = AGENT_CYCLE_REQUESTER,
) -> Optional[str]:
    """Background entrypoint to sync evidence and trigger R2 narrative report generation."""
    try:
        task = await manager.cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            logger.warning("Task %s not found; skipping agent report generation", task_id)
            return None

        db_path = investigation_db_path_for_task(task)
        if not db_path.exists():
            logger.warning("Investigation db missing for task %s; skipping report", task_id)
            return None

        files_db = task.get("output_files_db")
        seeded = await asyncio.to_thread(sync_agent_evidence_sync, task_id, db_path, files_db)
        if seeded == 0:
            logger.info("Task %s has no evidence snapshots yet; skipping report generation", task_id)
            return None

        # Check if reports.db already has an active generation for this task
        from ...config import get_project_root
        root = Path(manager.settings.report_output_dir)
        if not root.is_absolute():
            root = get_project_root() / root
        reports_db = root / "reports.db"
        if reports_db.exists():
            with sqlite3.connect(str(reports_db), timeout=10) as rconn:
                active = rconn.execute(
                    "SELECT 1 FROM report_generation_inputs WHERE task_id = ? AND status IN ('admitted', 'running')",
                    (task_id,),
                ).fetchone()
                if active:
                    logger.info("Task %s already has an active report generation in progress; skipping duplicate trigger", task_id)
                    return None

        admission = manager.report_generation_service
        executor = manager.report_generation_executor

        generation = await admission.admit(task_id, requested_by=requested_by)
        await executor.submit(generation.generation_id)
        logger.info(
            "Auto narrative report generation %s submitted for task %s (requested_by=%s)",
            generation.generation_id,
            task_id,
            requested_by,
        )
        return generation.generation_id

    except Exception as exc:
        logger.warning(
            "Non-fatal error in auto narrative report generation for task %s: %s",
            task_id,
            exc,
            exc_info=True,
        )
        return None


__all__ = ["AGENT_CYCLE_REQUESTER", "sync_agent_evidence_sync", "trigger_agent_cycle_report"]
