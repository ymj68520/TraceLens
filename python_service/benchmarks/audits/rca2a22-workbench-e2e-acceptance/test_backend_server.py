"""Dedicated Test Backend Server for RCA-2A.22 Browser E2E Acceptance.

Binds to 127.0.0.1:8098.
Hosts the synthetic investigation task: synthetic-rca2a22-workbench-001.
Zero real LLM provider requests.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

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


class SyntheticCppBackend:
    """Mock C++ backend serving synthetic task metadata and DB queries."""

    def __init__(self, task_dir: Path):
        self.task_id = "synthetic-rca2a22-workbench-001"
        self.task_dir = task_dir
        self.files_db_path = task_dir / "files.db"
        self.events_db_path = task_dir / "events.db"
        self.raw_db_path = task_dir / "raw.db"
        self.investigation_db_path = task_dir / "investigation.db"

        self.task_data = {
            "id": self.task_id,
            "name": "Synthetic RCA-2A.22 Investigation Case",
            "image_path": "/case/synthetic-rca2a22-image.raw",
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
    settings = Settings()
    # Ensure local review mutation security is enabled
    settings.agent_review_local_only = True

    manager = get_service_manager()
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

    app = FastAPI(title="TraceLens RCA-2A.22 Test Backend")

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
            "workbench_llm_enabled": False,
            "memory_forensics_enabled": False,
            "oss_analysis_enabled": False,
            "combined_case_enabled": True,
        }

    @app.get("/health")
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "synthetic_rca2a22_acceptance"}

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    task_dir = Path(__file__).resolve().parent / "fixtures" / "synthetic-rca2a22-workbench-001"
    if not task_dir.exists():
        from setup_synthetic_fixture import create_synthetic_fixture
        create_synthetic_fixture(task_dir)

    app = create_test_app(task_dir)
    print(f"Starting RCA-2A.22 Test Backend on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
