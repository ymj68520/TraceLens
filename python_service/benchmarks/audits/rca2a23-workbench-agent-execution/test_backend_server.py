"""Dedicated Test Backend Server for RCA-2A.23 Workbench Agent Execution Acceptance.

Binds to 127.0.0.1:8098.
Hosts the synthetic investigation task: synthetic-rca2a23-workbench-001.
Zero real LLM provider requests (REAL_PROVIDER_REQUESTS_ZERO = True).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

# Ensure python_service is in sys.path
sys_path_root = Path(__file__).resolve().parents[3]
if str(sys_path_root) not in sys.path:
    sys.path.insert(0, str(sys_path_root))

from httpserver.config import Settings
from httpserver.routes import investigation, investigation_workbench
from httpserver.services import get_service_manager
from httpserver.services.investigation.agent_orchestrator import CycleOutcome
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    canonical_state_json,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
    working_state_from_json,
)
from httpserver.services.investigation.repository import InvestigationRepository


class SyntheticCppBackend:
    """Mock C++ backend serving synthetic task metadata and DB queries."""

    def __init__(self, task_dir: Path):
        self.task_id = "synthetic-rca2a23-workbench-001"
        self.task_dir = task_dir
        self.files_db_path = task_dir / "files.db"
        self.events_db_path = task_dir / "events.db"
        self.raw_db_path = task_dir / "raw.db"
        self.investigation_db_path = task_dir / "investigation.db"

        self.task_data = {
            "id": self.task_id,
            "name": "Synthetic RCA-2A.23 Investigation Case",
            "image_path": "/case/synthetic-rca2a23-image.raw",
            "status": "ready",
            "output_files_db": str(self.files_db_path),
            "output_events_db": str(self.events_db_path),
            "scenarios": ["windows"],
            "scenario_databases": {},
        }
        self.tasks = {self.task_id: self.task_data}

    async def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def list_tasks(self):
        return [
            {
                "id": self.task_id,
                "name": self.task_data["name"],
                "image_path": self.task_data["image_path"],
                "status": "ready",
                "created_at": "2026-10-17T12:00:00Z",
            }
        ]

    async def get_task_files_paginated(self, task_id: str, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return {"files": [], "total_count": 0}
        conn = sqlite3.connect(task["output_files_db"])
        cursor = conn.cursor()
        cursor.execute("SELECT path, name, extension, size, md5, is_deleted, llm_description, mtime FROM files")
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
        return {"files": files, "total_count": len(files)}

    async def get_events(self, task_id: str, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return []
        conn = sqlite3.connect(task["output_events_db"])
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, event_type, file_path, details, source FROM events")
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


def create_test_app(task_dir: Path) -> FastAPI:
    from httpserver.config import get_settings
    settings = get_settings()
    settings.agent_execution_enabled = True
    settings.agent_review_local_only = True
    settings.llm_text_base_url = "http://mock-provider.invalid:8000"

    manager = get_service_manager()
    # Explicitly configure features on service manager settings for RCA-2A.23 test mode
    manager.settings.agent_execution_enabled = True
    manager.settings.agent_review_local_only = True
    manager.settings.llm_text_base_url = "http://mock-provider.invalid:8000"

    cpp_backend = SyntheticCppBackend(task_dir)
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

    # Configure deterministic offline agent orchestrator
    orchestrator = manager._create_agent_orchestrator()
    manager._agent_orchestrator = orchestrator
    manager._agent_orchestrator_ready = True

    inv_db_path = task_dir / "investigation.db"

    # Deterministic offline cycle executor
    async def deterministic_execute_cycle(task_id: str, investigation_id: str, **kwargs):
        # Open SQLite repository
        repo = InvestigationRepository(inv_db_path, task_id)
        runtime = AgentRuntimeRepository(repo)

        latest = runtime.get_latest_working_state(investigation_id)
        current_rev = latest.revision if latest else 1
        new_rev = current_rev + 1

        cycle_id = f"cycle_rca2a23_{new_rev:03d}"
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

        # Admitted delegation
        from httpserver.services.investigation.agent_runtime import DelegationSpec, DelegationStatus
        admitted = runtime.admit_delegations(
            run_id,
            (
                DelegationSpec(
                    question_ref="Q1",
                    based_on_state_revision=current_rev,
                    idempotency_key=f"plan:rca2a23:{new_rev}",
                ),
            ),
        )
        del_id = admitted[0].delegation_id
        runtime.start_delegation(del_id)

        # Generate evidence-grounded candidate depending on cycle revision
        cand_id = f"finding:disp_rca2a23_cand_{new_rev:02d}"
        cand_text = "Security Account Manager registry hive accessed via suspicious handle indicating credential extraction"
        cand_class = "INFERENCE"
        cand_refs = ["file:C/Windows/System32/config/SAM"]

        if new_rev > 2:
            cand_id = f"finding:disp_rca2a23_cand_{new_rev:02d}"
            cand_text = "Standalone binary executed from user Public directory without digital signature"
            cand_class = "INFERENCE"
            cand_refs = ["file:C/Users/Public/malware.exe"]

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
                    f"prop_rca2a23_{new_rev}",
                    f"disp_rca2a23_{new_rev}",
                    cand_text,
                    cand_class,
                    canonical_state_json({"refs": cand_refs}),
                    canonical_state_json({"refs": []}),
                    None,
                    f"grnd_rca2a23_{new_rev}",
                    canonical_state_json({"limitations": []}),
                ],
            )
            conn.commit()

        # Update working state
        st = working_state_from_json(task_id, investigation_id, latest.state)
        updated_questions = []
        for q in st.questions:
            if q.question_id == "Q1":
                updated_questions.append(
                    q.model_copy(update={"status": QuestionStatus.answered, "disposition": QuestionDisposition.supported})
                )
            else:
                updated_questions.append(q)

        # Update findings count and revision
        updated_finding_refs = list(st.finding_refs) + [cand_id]
        updated_state = st.model_copy(
            update={
                "questions": tuple(updated_questions),
                "finding_refs": tuple(updated_finding_refs),
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
            result={"summary": f"Completed investigation for {cand_id}"},
            result_hash=f"res_hash_{new_rev}",
            context_hash=f"ctx_hash_{new_rev}",
            tool_registry_hash="tr_hash_rca2a23",
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

    orchestrator.execute_cycle = deterministic_execute_cycle

    app = FastAPI(title="TraceLens RCA-2A.23 Test Backend")

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

    # Minimal tasks endpoint for frontend task selector
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

    @app.get("/api/system/features")
    async def get_system_features():
        return {
            "agent_execution_enabled": True,
            "workbench_llm_enabled": False,
            "memory_forensics_enabled": False,
            "oss_analysis_enabled": False,
            "combined_case_enabled": True,
        }

    @app.get("/health")
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "synthetic_rca2a23_agent_execution"}

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    task_dir = Path(__file__).resolve().parent / "fixtures" / "synthetic-rca2a23-workbench-001"
    if not task_dir.exists():
        from setup_synthetic_fixture import create_synthetic_fixture
        create_synthetic_fixture(task_dir)

    app = create_test_app(task_dir)
    print(f"Starting RCA-2A.23 Test Backend on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
