"""Historical v7 GET remains readable; writes return explicit 409 without mutation."""

import hashlib
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation, report_evidence
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.investigation.read import InvestigationReadService
from httpserver.services.investigation.report_evidence import ReportEvidenceService
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.investigation.service import InvestigationCaptureService


def test_v7_get_and_both_write_routes_require_migration_without_side_effect(tmp_path):
    files = tmp_path / "files.db"
    with sqlite3.connect(files) as con:
        con.execute("CREATE TABLE files(path TEXT)")
        con.execute("INSERT INTO files VALUES('/old.txt')")
    db = tmp_path / "investigation.db"
    repo = InvestigationRepository.__new__(InvestigationRepository)
    repo.db_path, repo.task_id, repo.existing_only = db, "synthetic-old", False
    repo._initialize_v7_atomically()
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES(?,?,?,?,?,?)",
                    ("synthetic-old", "file:/old.txt", "file", "/old.txt",
                     '{"evidence_type":"file","normalized_path":"/old.txt"}', 1))
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    class Cpp:
        async def get_task(self, task_id):
            return {"id": task_id, "output_files_db": str(files)} if task_id == "synthetic-old" else None

    cpp = Cpp()
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.include_router(report_evidence.router, prefix="/api/reports")
    app.dependency_overrides[investigation.get_investigation_service] = lambda: InvestigationCaptureService(
        cpp, EvidenceResolver(cpp))
    app.dependency_overrides[investigation.get_investigation_read_service] = lambda: InvestigationReadService(cpp)
    app.dependency_overrides[report_evidence.get_report_evidence_service] = lambda: ReportEvidenceService(cpp)
    client = TestClient(app)
    snapshot = client.get("/api/investigation/evidence/snapshot", params={
        "task_id": "synthetic-old", "evidence_key": "file:/old.txt"})
    assert snapshot.status_code == 200
    assert snapshot.json()["payload"]["normalized_path"] == "/old.txt"
    assert client.get("/api/reports/evidence", params={"task_id": "synthetic-old"}).json() == []
    capture = client.post("/api/investigation/snapshots", json={
        "task_id": "synthetic-old", "evidence_key": "file:/old.txt"})
    assert capture.status_code == 409 and "MIGRATION_REQUIRED" in capture.json()["detail"]
    judgment = client.post("/api/reports/evidence", json={
        "task_id": "synthetic-old", "evidence_key": "file:/old.txt",
        "report_status": "main", "added_by": "synthetic-reviewer"})
    assert judgment.status_code == 409 and "MIGRATION_REQUIRED" in judgment.json()["detail"]
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 7
