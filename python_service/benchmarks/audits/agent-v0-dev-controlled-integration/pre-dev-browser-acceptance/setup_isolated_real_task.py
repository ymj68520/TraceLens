"""Helper to safely create an isolated real-task replica for Track B2 testing.

Clones the real-case databases (raw.db, files.db, events.db, windows.db) from:
  /home/ymj68520/projects/TraceLens/build/data/tasks/60dedf82-7f35-48be-a104-b4d283a4fe92/
into:
  /home/ymj68520/projects/TraceLens/build/data/tasks/isolated-real-b2-test-001/
using SQLite's online backup API in strict read-only mode on the source.

Initializes an isolated v16 investigation.db with seed questions.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

# Add python_service to sys.path
sys_path_root = Path(__file__).resolve().parents[4]
if str(sys_path_root) not in sys.path:
    sys.path.insert(0, str(sys_path_root))

from httpserver.services.investigation.agent_runtime import AgentRuntimeRepository
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    HypothesisStatus,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
    working_state_to_json,
)
from httpserver.services.investigation.repository import InvestigationRepository

REAL_TASK_DIR = Path("/home/ymj68520/projects/TraceLens/build/data/tasks/60dedf82-7f35-48be-a104-b4d283a4fe92")
ISOLATED_TASK_DIR = Path("/home/ymj68520/projects/TraceLens/build/data/tasks/isolated-real-b2-test-001")
ISOLATED_TASK_ID = "isolated-real-b2-test-001"
ISOLATED_INV_ID = "inv_isolated_b2_001"


def backup_sqlite(src_path: Path, dst_path: Path) -> str:
    """Safe copy of SQLite database using backup API with mode=ro on source."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{src_path}?mode=ro", uri=True) as src, sqlite3.connect(dst_path) as dst:
        src.backup(dst)
    return hashlib.sha256(dst_path.read_bytes()).hexdigest()


def setup_isolated_real_task() -> dict[str, str]:
    """Sets up the isolated real-task replica and returns file hashes."""
    ISOLATED_TASK_DIR.mkdir(parents=True, exist_ok=True)

    copied_hashes = {}
    for db_name in ["raw.db", "files.db", "events.db", "windows.db"]:
        src = REAL_TASK_DIR / db_name
        dst = ISOLATED_TASK_DIR / db_name
        if src.exists():
            h = backup_sqlite(src, dst)
            copied_hashes[db_name] = h

    # Initialize isolated v16 investigation.db
    inv_db_path = ISOLATED_TASK_DIR / "investigation.db"
    if inv_db_path.exists():
        inv_db_path.unlink()

    store = InvestigationRepository(inv_db_path, ISOLATED_TASK_ID)
    runtime = AgentRuntimeRepository(store)

    initial_state = AgentWorkingStateV1(
        task_id=ISOLATED_TASK_ID,
        investigation_id=ISOLATED_INV_ID,
        objective="涉诈投资平台（杀猪盘）窝点作案终端案：固定窝点话术体系、受害人与客源数据、赃款归集线索与反取证行为，并闭环终端与平台关联",
        questions=(
            WorkingQuestion(
                question_id="Q1",
                text="磁盘根目录是否存在涉诈话术培训资料库及虚假宣传剧本？",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
                status=QuestionStatus.open,
            ),
            WorkingQuestion(
                question_id="Q2",
                text="最近使用痕迹中是否存在定向诱导的重点目标受害人清单？",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
                status=QuestionStatus.open,
            ),
        ),
        hypotheses=(
            Hypothesis(
                hypothesis_id="hyp-01",
                text="涉案终端为诈骗窝点作案工作站，存有系统化诈骗话术库与受害者清单",
                status=HypothesisStatus.active,
            ),
        ),
    )

    inv, rev = runtime.create_investigation(
        working_state_to_json(initial_state),
        investigation_id=ISOLATED_INV_ID,
    )
    copied_hashes["investigation.db"] = hashlib.sha256(inv_db_path.read_bytes()).hexdigest()
    copied_hashes["task_id"] = ISOLATED_TASK_ID
    copied_hashes["investigation_id"] = ISOLATED_INV_ID
    return copied_hashes


def create_synthetic_fixture(
    target_dir: Path,
    reset_evidence: bool = True,
    task_id: str = "synthetic-rca2a24-rc-001",
    inv_id: str = "inv-rca2a24-agent",
) -> dict[str, str]:
    """Generates clean synthetic fixture for synthetic-rca2a24-rc-001 or synthetic-task-b at Rev 1."""
    target_dir.mkdir(parents=True, exist_ok=True)

    raw_db_path = target_dir / "raw.db"
    files_db_path = target_dir / "files.db"
    events_db_path = target_dir / "events.db"
    inv_db_path = target_dir / "investigation.db"

    if reset_evidence:
        if raw_db_path.exists():
            raw_db_path.unlink()
        conn_raw = sqlite3.connect(raw_db_path)
        conn_raw.execute("CREATE TABLE IF NOT EXISTS raw_meta (key TEXT PRIMARY KEY, val TEXT)")
        conn_raw.execute("INSERT INTO raw_meta VALUES ('version', '1.0')")
        conn_raw.execute("INSERT INTO raw_meta VALUES ('case', 'synthetic-rca2a24')")
        conn_raw.commit()
        conn_raw.close()

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
               VALUES ('C/Windows/System32/config/SAM', 'SAM', '', 'system', 'file', 65536, 1690000000, 1690000000, 0, 'sam_hash_rc24', 'Security Account Manager registry hive containing credential hashes', 1690000050)"""
        )
        conn_files.execute(
            """INSERT INTO files (path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, llm_description, llm_analyzed_at)
               VALUES ('C/Users/Public/malware.exe', 'malware.exe', 'exe', 'executable', 'file', 131072, 1690000050, 1690000050, 0, 'malware_hash_rc24', 'Suspicious standalone binary executing from Public directory', 1690000050)"""
        )
        conn_files.commit()
        conn_files.close()

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

    if inv_db_path.exists():
        inv_db_path.unlink()
    repo = InvestigationRepository(inv_db_path, task_id)
    runtime = AgentRuntimeRepository(repo)

    initial_state = AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=inv_id,
        objective="Investigate suspicious credential extraction and unauthorized process spawning on host",
        questions=(
            WorkingQuestion(
                question_id="Q1",
                text="Was the SAM registry hive accessed for credential dumping?",
                source=QuestionSource.user_directive,
                priority=QuestionPriority.high,
                status=QuestionStatus.open,
            ),
            WorkingQuestion(
                question_id="Q2",
                text="What executed malware.exe from the Public user profile?",
                source=QuestionSource.user_directive,
                priority=QuestionPriority.normal,
                status=QuestionStatus.open,
            ),
        ),
        hypotheses=(),
    )
    runtime.create_investigation(
        working_state_to_json(initial_state),
        investigation_id=inv_id,
    )

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

    return {
        "raw_db_sha256": hashlib.sha256(raw_db_path.read_bytes()).hexdigest(),
        "files_db_sha256": hashlib.sha256(files_db_path.read_bytes()).hexdigest(),
        "events_db_sha256": hashlib.sha256(events_db_path.read_bytes()).hexdigest(),
        "investigation_db_sha256": hashlib.sha256(inv_db_path.read_bytes()).hexdigest(),
        "task_id": task_id,
        "investigation_id": inv_id,
    }


if __name__ == "__main__":
    hashes = setup_isolated_real_task()
    print("Isolated task setup complete:", hashes)

