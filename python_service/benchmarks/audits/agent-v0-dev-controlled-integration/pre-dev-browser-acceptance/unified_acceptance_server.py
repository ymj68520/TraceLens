"""Unified FastAPI Test Backend Server for Pre-Dev-Merge Browser Acceptance.

Supports:
- Track A: Synthetic task (synthetic-rca2a24-rc-001) & secondary switch task (synthetic-task-b)
- Track B1: Real task (60dedf82-7f35-48be-a104-b4d283a4fe92) in STRICT READ-ONLY MODE
- Track B2: Isolated real clone task (isolated-real-b2-test-001) with bounded Agent execution & reviews
- Edge / Extended Failure Paths A01-A16 and B01-B18

Strictly offline (0 real provider requests).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure python_service is in sys.path
sys_path_root = Path(__file__).resolve().parents[4]
if str(sys_path_root) not in sys.path:
    sys.path.insert(0, str(sys_path_root))

from httpserver.routes import investigation, investigation_workbench
from httpserver.services import get_service_manager
from httpserver.services.investigation.agent_orchestrator import CycleOutcome
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    canonical_state_json,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    QuestionDisposition,
    QuestionStatus,
    working_state_from_json,
)
from httpserver.services.investigation.repository import InvestigationRepository

logger = logging.getLogger("unified_acceptance_server")
logging.basicConfig(level=logging.INFO)

REAL_TASK_DIR = Path("/home/ymj68520/projects/TraceLens/build/data/tasks/60dedf82-7f35-48be-a104-b4d283a4fe92")
ISOLATED_TASK_DIR = Path("/home/ymj68520/projects/TraceLens/build/data/tasks/isolated-real-b2-test-001")
SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "rca2a24-local-rc-readiness" / "fixtures" / "synthetic-rca2a24-rc-001"
SYNTHETIC_B_DIR = Path(__file__).resolve().parents[2] / "rca2a24-local-rc-readiness" / "fixtures" / "synthetic-task-b"


class UnifiedMultiTaskCppBackend:
    """Multi-task C++ backend facade for Track A and Track B browser acceptance."""

    def __init__(self):
        self.tasks = {
            "synthetic-rca2a24-rc-001": {
                "id": "synthetic-rca2a24-rc-001",
                "name": "synthetic-rca2a24-image.raw",
                "image_path": str(SYNTHETIC_DIR / "raw.db"),
                "output_raw_db": str(SYNTHETIC_DIR / "raw.db"),
                "output_files_db": str(SYNTHETIC_DIR / "files.db"),
                "output_events_db": str(SYNTHETIC_DIR / "events.db"),
                "investigation_db": str(SYNTHETIC_DIR / "investigation.db"),
                "status": "ready",
                "total_files": 2,
                "analyzed_files": 2,
            },
            "synthetic-task-b": {
                "id": "synthetic-task-b",
                "name": "synthetic-task-b.raw",
                "image_path": str(SYNTHETIC_B_DIR / "raw.db"),
                "output_raw_db": str(SYNTHETIC_B_DIR / "raw.db"),
                "output_files_db": str(SYNTHETIC_B_DIR / "files.db"),
                "output_events_db": str(SYNTHETIC_B_DIR / "events.db"),
                "investigation_db": str(SYNTHETIC_B_DIR / "investigation.db"),
                "status": "ready",
                "total_files": 1,
                "analyzed_files": 1,
            },
            "60dedf82-7f35-48be-a104-b4d283a4fe92": {
                "id": "60dedf82-7f35-48be-a104-b4d283a4fe92",
                "name": "窝点嫌疑人计算机镜像.E01",
                "image_path": "/home/ymj68520/projects/testimgs/窝点嫌疑人计算机镜像.E01",
                "output_raw_db": str(REAL_TASK_DIR / "raw.db.filtered"),
                "output_files_db": str(REAL_TASK_DIR / "files.db"),
                "output_events_db": str(REAL_TASK_DIR / "events.db"),
                "investigation_db": str(REAL_TASK_DIR / "investigation.db"),
                "status": "completed",
                "read_only": True,
                "total_files": 2100,
                "analyzed_files": 2100,
                "case_description": "电信网络诈骗团伙窝点作案用工作站真实取证镜像（只读验证模式）",
            },
            "isolated-real-b2-test-001": {
                "id": "isolated-real-b2-test-001",
                "name": "窝点嫌疑人计算机镜像-隔离副本.E01",
                "image_path": "/home/ymj68520/projects/testimgs/窝点嫌疑人计算机镜像.E01",
                "output_raw_db": str(ISOLATED_TASK_DIR / "raw.db"),
                "output_files_db": str(ISOLATED_TASK_DIR / "files.db"),
                "output_events_db": str(ISOLATED_TASK_DIR / "events.db"),
                "investigation_db": str(ISOLATED_TASK_DIR / "investigation.db"),
                "status": "ready",
                "total_files": 2100,
                "analyzed_files": 2100,
                "case_description": "涉诈投资平台窝点作案终端案：真实物证隔离写入与自动化审核演练副本",
            },
        }

    async def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def list_tasks(self):
        return [
            {
                "id": tid,
                "name": t["name"],
                "image_path": t["image_path"],
                "status": t["status"],
                "created_at": "2026-10-18T00:00:00Z",
            }
            for tid, t in self.tasks.items()
        ]

    async def get_task_files_paginated(self, task_id: str, limit: int = 50, offset: int = 0, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return {"files": [], "total_count": 0}
        db_path = task["output_files_db"]
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM files")
        total = cursor.fetchone()[0]
        cursor.execute(
            "SELECT path, name, extension, size, md5, is_deleted, llm_description, mtime FROM files ORDER BY size DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cursor.fetchall()
        conn.close()
        files = [
            {
                "path": r[0],
                "name": r[1],
                "extension": r[2],
                "size": r[3],
                "md5": r[4],
                "is_deleted": r[5],
                "llm_description": r[6],
                "mtime": r[7],
            }
            for r in rows
        ]
        return {"files": files, "total_count": total}

    async def get_events(self, task_id: str, limit: int = 100, offset: int = 0, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return []
        db_path = task["output_events_db"]
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(events)")
        cols = {col[1] for col in cursor.fetchall()}
        desc_col = "description" if "description" in cols else ("details" if "details" in cols else "event_type")
        source_col = "event_source" if "event_source" in cols else ("source" if "source" in cols else "event_type")
        cursor.execute(
            f"SELECT id, timestamp, event_type, file_path, {desc_col}, {source_col} FROM events LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "file_path": r[3],
                "details": r[4],
                "source": r[5],
            }
            for r in rows
        ]


def create_unified_app() -> FastAPI:
    manager = get_service_manager()
    settings = manager.settings
    settings.agent_execution_enabled = True
    settings.agent_review_local_only = True
    settings.llm_text_base_url = "http://mock-offline-provider.invalid:8000"

    cpp_backend = UnifiedMultiTaskCppBackend()
    manager._cpp_backend = cpp_backend
    manager._cpp_backend_ready = True
    manager._initialized = True

    manager._investigation_service = manager._create_investigation_service()
    manager._investigation_service_ready = True
    manager._investigation_read_service = manager._create_investigation_read_service()
    manager._investigation_event_service = manager._create_investigation_event_service()
    manager._investigation_graph_service = manager._create_investigation_graph_service()
    manager._report_evidence_service = manager._create_report_evidence_service()
    manager._investigation_seed_service = manager._create_investigation_seed_service()
    manager._secondary_analysis_executor = manager._create_secondary_analysis_executor()
    manager._secondary_analysis_ready = True
    manager._agent_analyst_review_service = manager._create_agent_analyst_review_service()
    manager._agent_analyst_review_ready = True

    # State variables for edge / testing hooks
    server_control = {
        "execution_delay_sec": 0.0,
        "simulate_specialist_failure": False,
        "feature_execution_enabled": True,
    }

    # Deterministic orchestrator that handles both synthetic tasks and real isolated clone tasks
    orchestrator = manager._create_agent_orchestrator()
    manager._agent_orchestrator = orchestrator
    manager._agent_orchestrator_ready = True

    async def unified_execute_cycle(task_id: str, investigation_id: str, **kwargs):
        # Edge test A13: feature gate disabled
        if not server_control["feature_execution_enabled"]:
            raise HTTPException(status_code=403, detail="agent execution is disabled by configuration")

        # Track B1 safety gate: mutation strictly forbidden on original real task
        if task_id == "60dedf82-7f35-48be-a104-b4d283a4fe92":
            raise HTTPException(
                status_code=403,
                detail="ORIGINAL_TASK_MUTATION_FORBIDDEN: task 60dedf82-7f35-48be-a104-b4d283a4fe92 is strictly read-only",
            )

        # Edge test A02: artificial delayed response if configured
        if server_control["execution_delay_sec"] > 0:
            await asyncio.sleep(server_control["execution_delay_sec"])

        # Edge test A09: specialist failure simulation
        if server_control["simulate_specialist_failure"]:
            server_control["simulate_specialist_failure"] = False  # one-shot
            raise RuntimeError("SPECIALIST_TOOL_EXECUTION_FAILURE: simulated tool crash in worker")

        task = await cpp_backend.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

        inv_db_path = Path(task["investigation_db"])
        repo = InvestigationRepository(inv_db_path, task_id)
        runtime = AgentRuntimeRepository(repo)

        latest = runtime.get_latest_working_state(investigation_id)
        current_rev = latest.revision if latest else 1
        new_rev = current_rev + 1

        cycle_id = f"cycle_{task_id[:12]}_{new_rev:03d}"
        active_run = None
        for r in runtime.list_runs(investigation_id):
            status_val = getattr(r.status, "value", r.status)
            if str(status_val) in ("queued", "running"):
                active_run = r
                break
        if active_run is None:
            active_run = runtime.start_run(investigation_id)
            runtime.mark_run_running(active_run.run_id)
        run_id = active_run.run_id

        from httpserver.services.investigation.agent_runtime import DelegationSpec

        # Admitted delegation
        question_ref = "Q1" if new_rev == 2 else "Q2"
        admitted = runtime.admit_delegations(
            run_id,
            (
                DelegationSpec(
                    question_ref=question_ref,
                    based_on_state_revision=current_rev,
                    idempotency_key=f"plan:{task_id}:{new_rev}",
                ),
            ),
        )
        del_id = admitted[0].delegation_id
        runtime.start_delegation(del_id)

        # Generate candidates based on task scope
        if task_id == "isolated-real-b2-test-001":
            # Real evidence query execution against cloned files.db
            files_db_path = Path(task["output_files_db"])
            conn_files = sqlite3.connect(f"file:{files_db_path}?mode=ro", uri=True)
            cur = conn_files.cursor()
            cur.execute("SELECT path FROM files WHERE path LIKE '%话术%' LIMIT 2")
            found_rows = [r[0] for r in cur.fetchall()]
            conn_files.close()

            cand_id = f"finding:disp_isolated_cand_{new_rev:02d}"
            cand_refs = [f"file:{p}" for p in found_rows] or [
                "file:/话术/恋爱研习社聊天秘籍.(1).pdf",
                "file:/话术/500万聊天记录(1).pdf",
            ]
            cand_text = (
                "磁盘根目录/话术/目录下检出涉诈话术培训资料库（恋爱研习社聊天秘籍.(1).pdf、500万聊天记录(1).pdf），"
                "构建了诱导信任与出入金引流的话术脚本体系。"
            )
            cand_class = "INFERENCE"
        else:
            # Synthetic task candidates
            cand_id = f"finding:disp_rca2a24_cand_{new_rev:02d}"
            cand_class = "INFERENCE"
            if new_rev == 2:
                cand_text = "Security Account Manager registry hive accessed via suspicious handle indicating credential extraction"
                cand_refs = ["file:C/Windows/System32/config/SAM"]
            else:
                cand_text = "Standalone binary executed from user Public directory without digital signature"
                cand_refs = ["file:C/Users/Public/malware.exe"]

        # Insert candidate finding with review_pending status
        with runtime._connect() as conn:
            conn.execute(
                """INSERT INTO investigation_findings
                (finding_id, task_id, investigation_id, proposal_id, disposition_id,
                 text, assertion_class, evidence_refs_json, relationship_refs_json,
                 temporal_scope_json, grounding_id, limitations_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'review_pending', datetime('now'))""",
                [
                    cand_id,
                    task_id,
                    investigation_id,
                    f"prop_{new_rev}",
                    f"disp_{new_rev}",
                    cand_text,
                    cand_class,
                    canonical_state_json({"refs": cand_refs}),
                    canonical_state_json({"refs": []}),
                    None,
                    f"grnd_{new_rev}",
                    canonical_state_json({"limitations": []}),
                ],
            )
            conn.commit()

        # Update working state
        st = working_state_from_json(task_id, investigation_id, latest.state)
        updated_questions = []
        for q in st.questions:
            if q.question_id == question_ref:
                updated_questions.append(
                    q.model_copy(update={"status": QuestionStatus.answered, "disposition": QuestionDisposition.supported})
                )
            else:
                updated_questions.append(q)

        updated_state = st.model_copy(
            update={
                "questions": tuple(updated_questions),
                "finding_refs": tuple(list(st.finding_refs) + [cand_id]),
            }
        )

        runtime.commit_working_state(
            investigation_id,
            updated_state.model_dump(mode="json"),
            expected_revision=current_rev,
            operation_key=f"op_cycle_{new_rev}",
        )

        runtime.complete_delegation_with_result(
            del_id,
            result_version="specialist-result:v1",
            result={"summary": f"Completed forensic tool inspection for {cand_id}"},
            result_hash=f"res_hash_{new_rev}",
            context_hash=f"ctx_hash_{new_rev}",
            tool_registry_hash="tr_hash_real_v0",
        )

        return CycleOutcome(
            cycle_id=cycle_id,
            investigation_id=investigation_id,
            run_id=run_id,
            starting_revision=current_rev,
            ending_revision=new_rev,
            integration_status="committed",
            integration_revision=new_rev,
            delegation_ids=(del_id,),
            run_stop_reason=None,
            warnings=(),
            limitations=(),
        )

    orchestrator.execute_cycle = unified_execute_cycle

    app = FastAPI(title="TraceLens Unified Acceptance Server")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount investigation routes
    app.include_router(investigation_workbench.router, prefix="/api/investigation/workbench")
    app.include_router(investigation.router, prefix="/api/investigation")

    # Tasks endpoints
    @app.get("/tasks")
    @app.get("/api/tasks")
    async def list_tasks():
        tasks = await cpp_backend.list_tasks()
        return {"tasks": tasks, "total": len(tasks)}

    @app.get("/tasks/{task_id}")
    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        t = await cpp_backend.get_task(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        return t

    # Forensics endpoints
    @app.get("/api/forensics/files/largest")
    async def forensics_largest_files(task_id: str, limit: int = 50):
        res = await cpp_backend.get_task_files_paginated(task_id, limit=limit)
        return {"largest_files": res["files"], "limit": limit}

    @app.get("/api/forensics/timeline/comprehensive")
    async def forensics_timeline(task_id: str, limit: int = 50, offset: int = 0):
        evts = await cpp_backend.get_events(task_id, limit=limit, offset=offset)
        return {
            "metadata": {"total_events": len(evts), "limit": limit, "offset": offset},
            "timeline": [
                {
                    "timestamp": e["timestamp"],
                    "event_type": e["event_type"],
                    "file_path": e["file_path"],
                    "description": e["details"],
                    "cluster_count": 1,
                }
                for e in evts
            ],
        }

    @app.get("/api/system/features")
    @app.get("/features")
    async def get_system_features():
        return {
            "agent_execution_enabled": server_control["feature_execution_enabled"],
            "workbench_llm_enabled": False,
            "memory_forensics_enabled": False,
            "oss_analysis_enabled": False,
            "combined_case_enabled": True,
        }

    # Test / edge control hooks
    @app.post("/test/control")
    async def set_test_control(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        if "delay_sec" in data and data["delay_sec"] is not None:
            server_control["execution_delay_sec"] = float(data["delay_sec"])
        if "simulate_failure" in data and data["simulate_failure"] is not None:
            server_control["simulate_specialist_failure"] = bool(data["simulate_failure"])
        if "feature_enabled" in data and data["feature_enabled"] is not None:
            server_control["feature_execution_enabled"] = bool(data["feature_enabled"])
            settings.agent_execution_enabled = bool(data["feature_enabled"])
        return {"status": "ok", "control": server_control}

    @app.get("/health")
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "unified_browser_acceptance"}

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    app = create_unified_app()
    logger.info(f"Starting TraceLens Unified Acceptance Server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
