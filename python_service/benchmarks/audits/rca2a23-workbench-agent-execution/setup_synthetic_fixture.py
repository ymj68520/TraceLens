"""Synthetic Investigation Fixture Generator for RCA-2A.23 Workbench Agent Execution Acceptance.

Task ID: synthetic-rca2a23-workbench-001
Investigation ID: inv-rca2a23-agent

Contains:
- raw.db
- files.db
- events.db
- investigation.db
- Pre-flight SHA-256 calculation
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

# Ensure python_service is in sys.path
sys_path_root = Path(__file__).resolve().parents[3]
if str(sys_path_root) not in sys.path:
    sys.path.insert(0, str(sys_path_root))

from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    canonical_state_json,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)
from httpserver.services.investigation.repository import InvestigationRepository


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_synthetic_fixture(target_dir: Path, reset_evidence: bool = True) -> dict[str, str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    task_id = "synthetic-rca2a23-workbench-001"
    inv_id = "inv-rca2a23-agent"

    raw_db_path = target_dir / "raw.db"
    files_db_path = target_dir / "files.db"
    events_db_path = target_dir / "events.db"
    inv_db_path = target_dir / "investigation.db"

    if reset_evidence:
        # 1. raw.db
        if raw_db_path.exists():
            raw_db_path.unlink()
        conn_raw = sqlite3.connect(raw_db_path)
        conn_raw.execute("CREATE TABLE IF NOT EXISTS raw_meta (key TEXT PRIMARY KEY, val TEXT)")
        conn_raw.execute("INSERT INTO raw_meta VALUES ('version', '1.0')")
        conn_raw.execute("INSERT INTO raw_meta VALUES ('case', 'synthetic-rca2a23')")
        conn_raw.commit()
        conn_raw.close()

        # 2. files.db
        if files_db_path.exists():
            files_db_path.unlink()
        conn_files = sqlite3.connect(files_db_path)
        conn_files.execute(
            """CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, name TEXT, extension TEXT,
                category TEXT, type TEXT, size INTEGER, mtime INTEGER,
                ctime INTEGER, is_deleted INTEGER DEFAULT 0, md5 TEXT,
                llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
                llm_analyzed_at INTEGER, llm_model_used TEXT,
                scene_type TEXT, scene_priority INTEGER,
                scene_relevant INTEGER DEFAULT 0)"""
        )
        conn_files.execute(
            """INSERT INTO files (path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, llm_description, llm_analyzed_at)
               VALUES ('C/Windows/System32/config/SAM', 'SAM', '', 'system', 'file', 65536, 1690000000, 1690000000, 0, 'sam_hash_001', 'Security Account Manager registry hive containing credential hashes', 1690000050)"""
        )
        conn_files.execute(
            """INSERT INTO files (path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, llm_description, llm_analyzed_at)
               VALUES ('C/Users/Public/malware.exe', 'malware.exe', 'exe', 'executable', 'file', 131072, 1690000050, 1690000050, 0, 'malware_hash_001', 'Suspicious standalone binary executing from Public directory', 1690000050)"""
        )
        conn_files.commit()
        conn_files.close()

        # 3. events.db
        if events_db_path.exists():
            events_db_path.unlink()
        conn_events = sqlite3.connect(events_db_path)
        conn_events.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER,
                event_type TEXT,
                file_path TEXT,
                details TEXT,
                source TEXT,
                llm_summary TEXT,
                llm_description TEXT,
                llm_analyzed_at INTEGER)"""
        )
        conn_events.execute(
            """INSERT INTO events (id, timestamp, event_type, file_path, details, source, llm_summary, llm_description, llm_analyzed_at)
               VALUES (1, 1690000050, 'logon_4624', 'C/Windows/System32/config/SAM', 'Logon Event for account TargetAdmin with elevated privileges', 'Security.evtx', 'TargetAdmin Logon Event', 'Logon Event for account TargetAdmin with elevated privileges', 1690000055)"""
        )
        conn_events.execute(
            """INSERT INTO events (id, timestamp, event_type, file_path, details, source, llm_summary, llm_description, llm_analyzed_at)
               VALUES (2, 1690000060, 'process_creation', 'C/Users/Public/malware.exe', 'Process spawned malware.exe with hidden window', 'Sysmon.evtx', 'Process Creation malware.exe', 'Process spawned malware.exe with hidden window', 1690000065)"""
        )
        conn_events.commit()
        conn_events.close()

    # 4. investigation.db
    if inv_db_path.exists():
        inv_db_path.unlink()
    repo = InvestigationRepository(inv_db_path, task_id)
    runtime = AgentRuntimeRepository(repo)

    initial_state = AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=inv_id,
        objective="Investigate suspicious credential extraction and malware execution on workstation",
        questions=(
            WorkingQuestion(
                question_id="Q1",
                text="Did unauthorized credential access occur?",
                source=QuestionSource.user_directive,
                priority=QuestionPriority.high,
                status=QuestionStatus.open,
            ),
            WorkingQuestion(
                question_id="Q2",
                text="What spawned malware.exe in Public user folder?",
                source=QuestionSource.user_directive,
                priority=QuestionPriority.normal,
                status=QuestionStatus.open,
            ),
        ),
        hypotheses=(),
    )
    runtime.create_investigation(
        initial_state.model_dump(mode="json"),
        investigation_id=inv_id,
    )

    # 5. Create synthetic Investigation Event for timeline & event analysis
    evt = repo.create_event(
        title="TargetAdmin Logon Event",
        summary="Logon Event for account TargetAdmin with elevated privileges",
        created_by="synthetic",
    )
    with repo._connect() as conn:
        conn.execute(
            """INSERT INTO evidence_snapshots
            (task_id, evidence_key, evidence_type, normalized_path, unix_minute, event_type, snapshot_json, captured_at)
            VALUES (?, 'file:C/Windows/System32/config/SAM', 'file', 'C/Windows/System32/config/SAM', NULL, NULL, '{}', 1690000000)""",
            [task_id],
        )
        conn.execute(
            """INSERT INTO investigation_event_evidence
            (task_id, event_id, evidence_key, linked_at, linked_by)
            VALUES (?, ?, 'file:C/Windows/System32/config/SAM', '2026-10-17T12:00:00Z', 'synthetic')""",
            [task_id, evt.event_id],
        )
        conn.commit()

    hashes = {
        "raw_db_sha256": compute_sha256(raw_db_path),
        "files_db_sha256": compute_sha256(files_db_path),
        "events_db_sha256": compute_sha256(events_db_path),
        "investigation_db_sha256": compute_sha256(inv_db_path),
        "task_id": task_id,
        "investigation_id": inv_id,
    }
    return hashes


if __name__ == "__main__":
    base = Path(__file__).resolve().parent / "fixtures" / "synthetic-rca2a23-workbench-001"
    res = create_synthetic_fixture(base)
    print(json.dumps(res, indent=2))
