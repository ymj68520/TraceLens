"""Isolated synthetic HTTP capture and exact-version traceback; no real Task."""

import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import evidence_intake
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.investigation.service import InvestigationCaptureService


def test_selected_row_http_auth_capture_and_frozen_readback(tmp_path, monkeypatch):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY,address TEXT,body TEXT,date INTEGER,type INTEGER)")
        con.execute("INSERT INTO sms_messages VALUES(1,'10010','合成内容',123456,1)")
    task = {"id": "synthetic-task", "output_files_db": str(db), "android_source": "dir"}

    class Cpp:
        async def get_task(self, task_id):
            return task if task_id == task["id"] else None

    cpp = Cpp()
    capture = InvestigationCaptureService(cpp, EvidenceResolver(cpp))

    async def get_task(task_id):
        if task_id != task["id"]:
            raise evidence_intake.TaskStoreError("task_not_found", "task not found")
        return task

    monkeypatch.setattr(evidence_intake, "get_task_record", get_task)
    monkeypatch.setattr(evidence_intake, "get_service_manager", lambda: SimpleNamespace(investigation_service=capture))
    monkeypatch.setenv("TRACELENS_FIELD_API_TOKEN", "s" * 40)
    app = FastAPI()
    app.include_router(evidence_intake.router, prefix="/api/evidence-intake")
    client = TestClient(app)
    base = "/api/evidence-intake/tasks/synthetic-task/android-artifacts/sms/1"
    assert client.get(base).status_code == 401
    assert client.post(base + "/capture", json={"record_hash": "a" * 64, "source_revision": "b" * 64}).status_code == 401
    headers = {"x-tracelens-field-token": "s" * 40, "x-user": "forged-analyst"}
    detail = client.get(base, headers=headers)
    assert detail.status_code == 200
    selected = detail.json()
    response = client.post(base + "/capture", headers=headers, json={
        "record_hash": selected["record_hash"], "source_revision": selected["source_revision"]})
    assert response.status_code == 200, response.text
    captured = response.json()
    assert captured["snapshot"]["evidence_type"] == "android_artifact"
    assert captured["snapshot"]["payload"]["record_fields"]["body"] == "合成内容"
    assert captured["snapshot"]["payload"]["timestamp_unit"] is None
    result_set = captured["snapshot"]["payload"]["result_set_id"]
    frozen = f"/api/evidence-intake/tasks/synthetic-task/android-result-sets/{result_set}/sms/1"
    assert client.get(frozen).status_code == 401
    assert client.get(frozen, headers=headers).json()["record"]["body"] == "合成内容"
    assert client.get(frozen.replace("synthetic-task", "other-task"), headers=headers).status_code == 404
    assert client.post(base + "/capture", headers=headers, json={
        "record_hash": "a" * 64, "source_revision": selected["source_revision"]}).status_code == 409
    with sqlite3.connect(tmp_path / "investigation.db") as con:
        assert con.execute("SELECT count(*) FROM evidence_snapshots").fetchone()[0] == 1
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
