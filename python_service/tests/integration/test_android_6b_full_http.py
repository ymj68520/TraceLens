"""6B synthetic-only HTTP workflow using real 6A auth and existing R2 routes.

The two model responders are in-memory test stubs, never production defaults.
No real C++ Task, image, outbound model or historical report is accessed.
"""

import json
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient
from passlib.context import CryptContext

from httpserver.main import create_app
from httpserver.config import get_settings
from httpserver.routes import evidence_intake, investigation, report_evidence, report_generation, report_narrative
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.forensic_report.generation import ReportGenerationAdmissionService
from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.investigation.execution import SecondaryAnalysisExecutor
from httpserver.services.investigation.read import InvestigationReadService
from httpserver.services.investigation.report_evidence import ReportEvidenceService
from httpserver.services.investigation.review import InvestigationReviewService
from httpserver.services.investigation.service import InvestigationCaptureService


def test_synthetic_sms_auth_analysis_review_r2_http(tmp_path, monkeypatch, request):
    task_id = "synthetic-http-6b"
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY,address TEXT,body TEXT,date INTEGER,type INTEGER)")
        con.execute("INSERT INTO sms_messages VALUES(1,'10086','HTTP 合成短信',1700000000000,1)")
        con.execute("INSERT INTO sms_messages VALUES(2,'10086','HTTP 合成短信',1700000000000,1)")
    task = {"id": task_id, "output_files_db": str(db), "android_source": "dir",
            "case_description": "合成测试案件，仅供接口验收"}

    class Cpp:
        async def get_task(self, queried):
            return task if queried == task_id else None

    cpp = Cpp()
    selected_key = None

    class AnalysisStub:
        async def chat_completion(self, system, user):
            assert "简体中文" in system
            assert selected_key in user and ":sms:2" not in user
            return {"model": "test-only-mock", "content": json.dumps({
                "description": "仅冻结解析行1", "summary": "短信原始行未核实",
                "claims": [{"claim_type": "FACT", "claim_text": "冻结结果行含该短信",
                            "evidence_refs": [selected_key]}],
            }, ensure_ascii=False)}

    class ReportStub:
        def __init__(self):
            self.calls = 0

        async def chat_completion(self, system, user, **kwargs):
            if '"classifications"' in system:
                body = json.loads(user)
                return {"model": "test-only-mock", "content": json.dumps({"classifications": [
                    {"evidence_key": item["evidence_key"], "material_type": "android_artifact",
                     "topics": ["communications"], "relations": [], "key_issue": False,
                     "reason": "冻结短信记录", "basis_quote": item["basis_text"][:80]}
                    for item in body["materials"]]}, ensure_ascii=False)}
            assert "简体中文" in system
            self.calls += 1
            assert ":sms:2" not in user
            responses = [
                {"title": "合成 R2 报告", "sections": [
                    {"heading": "案件背景与检材概况", "brief": "合成范围", "group_ids": []},
                    {"heading": "短信证据", "brief": "单条派生记录", "group_ids": ["communications"]},
                    {"heading": "综合结论", "brief": "来源限制", "group_ids": []}]},
                {"heading": "案件背景与检材概况", "content": "仅供合成测试。", "citations": []},
                {"heading": "短信证据", "content": "冻结记录显示 HTTP 合成短信。", "citations": [
                    {"citation_id": "c001", "evidence_key": selected_key, "analysis_id": analysis_id}]},
                {"heading": "综合结论", "content": "原库行与时区未知。", "citations": []},
            ]
            return {"model": "test-only-mock", "content": json.dumps(responses[self.calls - 1], ensure_ascii=False)}

    report_root = tmp_path / "reports"
    report_root.mkdir()
    capture = InvestigationCaptureService(cpp, EvidenceResolver(cpp))
    analysis_executor = SecondaryAnalysisExecutor(cpp, AnalysisStub(), capture)
    report_repo = ReportRepository(report_root / "reports.db")
    report_stub = ReportStub()
    manager = SimpleNamespace(
        cpp_backend=cpp, investigation_service=capture,
        secondary_analysis_executor=analysis_executor,
        investigation_review_service=InvestigationReviewService(cpp),
        investigation_read_service=InvestigationReadService(cpp),
        report_evidence_service=ReportEvidenceService(cpp),
        report_generation_service=ReportGenerationAdmissionService(cpp, report_repo),
        report_generation_executor=ReportGenerationExecutor(
            report_repo, GenerationReportWriter(report_root), report_stub),
    )

    async def get_task(queried):
        if queried != task_id:
            raise evidence_intake.TaskStoreError("task_not_found", "task not found")
        return task

    for module in (evidence_intake, investigation, report_evidence, report_generation):
        monkeypatch.setattr(module, "get_service_manager", lambda: manager)
    monkeypatch.setattr(evidence_intake, "get_task_record", get_task)
    monkeypatch.setattr(report_generation, "_report_root", lambda: report_root)
    monkeypatch.setattr(report_narrative, "_report_root", lambda: report_root)

    password_hash = CryptContext(schemes=["bcrypt"]).hash
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": {
        role: {"password_hash": password_hash("synthetic-" + role),
               "role": role, "active": True, "token_version": 0}
        for role in ("viewer", "analyst", "reviewer", "admin")
    }}), encoding="utf-8")
    users.chmod(0o600)
    for name, value in {
        "TRACELENS_FIELD_AUTH": "enabled", "TRACELENS_REQUIRE_FIELD_AUTH": "1",
        "FIELD_USER_FILE": str(users), "FIELD_JWT_SECRET": secrets.token_urlsafe(48),
        "FIELD_CPP_TO_PYTHON_TOKEN": secrets.token_urlsafe(48),
        "FIELD_PYTHON_TO_CPP_TOKEN": secrets.token_urlsafe(48),
        "FIELD_OUTBOUND_POLICY": "local_only", "FIELD_MODEL_ORIGINS": "http://127.0.0.1:39091",
        "LLM_BASE_URL": "http://127.0.0.1:39091", "LLM_TEXT_BASE_URL": "http://127.0.0.1:39091",
        "LLM_VISION_BASE_URL": "http://127.0.0.1:39091", "EMBEDDING_BASE_URL": "http://127.0.0.1:39091",
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    request.addfinalizer(get_settings.cache_clear)

    app = create_app()

    @asynccontextmanager
    async def no_services(_app):
        yield  # all dependencies are isolated objects above

    app.router.lifespan_context = no_services
    with TestClient(app, client=("127.0.0.1", 50123)) as client:
        def token(role):
            login = client.post("/api/field-auth/login", json={
                "username": role, "password": "synthetic-" + role})
            assert login.status_code == 200, login.text
            return {"Authorization": "Bearer " + login.json()["access_token"]}

        viewer, analyst, reviewer, admin = token("viewer"), token("analyst"), token("reviewer"), token("admin")
        base = f"/api/evidence-intake/tasks/{task_id}/android-artifacts/sms/1"
        assert client.get(base).status_code == 401
        assert client.get(base, headers={"X-User": "admin"}).status_code == 401
        detail = client.get(base, headers=analyst).json()
        assert client.get(base, headers=viewer).status_code == 200
        assert client.post(base + "/capture", headers=viewer, json={
            "record_hash": detail["record_hash"], "source_revision": detail["source_revision"]}).status_code == 403
        assert client.post(base + "/capture", headers=analyst, json={
            "record_hash": detail["record_hash"], "source_revision": detail["source_revision"],
            "database_path": "/etc/passwd"}).status_code == 400
        assert client.get(f"/api/evidence-intake/tasks/{task_id}/android-artifacts/evil_table/1",
                          headers=analyst).status_code == 400
        selected = client.post(base + "/capture", headers=analyst, json={
            "record_hash": detail["record_hash"], "source_revision": detail["source_revision"]})
        assert selected.status_code == 200, selected.text
        selected_key = selected.json()["evidence_key"]
        result_set = selected.json()["snapshot"]["payload"]["result_set_id"]
        snapshot = client.get("/api/investigation/evidence/snapshot", headers=analyst,
                              params={"task_id": task_id, "evidence_key": selected_key})
        assert snapshot.status_code == 200
        assert snapshot.json()["payload"]["record_fields"] == {
            "id": 1, "address": "10086", "body": "HTTP 合成短信",
            "date": 1700000000000, "type": 1,
        }
        admitted = client.post("/api/investigation/analyses", headers=analyst,
                               json={"task_id": task_id, "evidence_key": selected_key})
        assert admitted.status_code == 202, admitted.text
        analysis_id = admitted.json()["analysis_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            analysis = client.get(f"/api/investigation/analyses/{analysis_id}", headers=analyst,
                                  params={"task_id": task_id}).json()
            if analysis["status"] in ("review_pending", "failed"):
                break
            time.sleep(.02)
        assert analysis["status"] == "review_pending", analysis
        report_evidence_body = {"task_id": task_id, "evidence_key": selected_key,
                                "report_status": "main", "analysis_id": analysis_id,
                                "added_by": "forged-client-name"}
        assert client.post("/api/reports/evidence", headers=reviewer,
                           json=report_evidence_body).status_code == 409
        review_url = f"/api/investigation/analyses/{analysis_id}/review"
        decision = {"task_id": task_id, "decision": "accepted", "reviewer": "forged-client-name"}
        assert client.post(review_url, headers=analyst, json=decision).status_code == 403
        assert client.post(review_url, headers={"X-TraceLens-Service-Token": "wrong"}, json=decision).status_code == 401
        assert client.post(review_url, headers={
            "X-TraceLens-Service-Token": app.state.field_policy.python_to_cpp}, json=decision).status_code == 401
        assert client.post(review_url, headers={
            "X-TraceLens-Service-Token": app.state.field_policy.cpp_to_python}, json=decision).status_code == 403
        reviewed = client.post(review_url, headers=reviewer, json=decision)
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["decided_by"] == "reviewer"
        assert client.post("/api/reports/evidence", headers=analyst, json=report_evidence_body).status_code == 403
        added = client.post("/api/reports/evidence", headers=reviewer, json=report_evidence_body)
        assert added.status_code == 200, added.text
        assert added.json()["added_by"] == "reviewer"
        generated = client.post("/api/reports/generate", headers=analyst,
                                json={"task_id": task_id, "requested_by": "forged-client-name"})
        assert generated.status_code == 202, generated.text
        generation_id = generated.json()["generation_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            report_state = client.get(f"/api/reports/generations/{generation_id}", headers=analyst,
                                      params={"task_id": task_id}).json()
            if report_state["status"] in ("completed", "failed"):
                break
            time.sleep(.02)
        assert report_state["status"] == "completed", json.dumps(report_state, ensure_ascii=False)
        assert report_state["requested_by"] == "analyst"
        report_id = report_state["report_id"]
        narrative = client.get(f"/api/reports/narrative/versions/{report_id}", headers=analyst,
                               params={"task_id": task_id})
        assert narrative.status_code == 200, narrative.text
        citations = narrative.json()["citations"]
        assert len(citations) == 1 and citations[0]["evidence_key"] == selected_key
        assert citations[0]["citation_id"] == "c001"
        assert citations[0]["analysis_id"] == analysis_id
        second = client.post("/api/investigation/analyses", headers=analyst,
                             json={"task_id": task_id, "evidence_key": selected_key})
        assert second.status_code == 202
        second_id = second.json()["analysis_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            latest = client.get(f"/api/investigation/analyses/{second_id}", headers=analyst,
                                params={"task_id": task_id}).json()
            if latest["status"] in ("review_pending", "failed"):
                break
            time.sleep(.02)
        assert latest["status"] == "review_pending"
        assert client.post(f"/api/investigation/analyses/{second_id}/review", headers=reviewer,
                           json={"task_id": task_id, "decision": "accepted", "reviewer": "forged"}).status_code == 200
        bindings = client.get("/api/reports/evidence", headers=analyst, params={"task_id": task_id})
        assert bindings.status_code == 200
        assert bindings.json()[0]["analysis_id"] == analysis_id  # no implicit rebind
        frozen = client.get(f"/api/evidence-intake/tasks/{task_id}/android-result-sets/{result_set}/sms/1",
                            headers=analyst)
        assert frozen.status_code == 200 and frozen.json()["record"]["body"] == "HTTP 合成短信"
        assert client.get(f"/api/evidence-intake/tasks/other/android-result-sets/{result_set}/sms/1",
                          headers=analyst).status_code == 404
        # The same item and hash are retained, even if the dynamic result later changes.
        with sqlite3.connect(db) as con:
            con.execute("UPDATE sms_messages SET body='newer' WHERE id=1")
        assert client.get(f"/api/evidence-intake/tasks/{task_id}/android-result-sets/{result_set}/sms/1",
                          headers=analyst).json()["record"]["body"] == "HTTP 合成短信"
        assert client.get("/api/investigation/evidence/snapshot", headers=analyst,
                          params={"task_id": task_id, "evidence_key": selected_key}).json()["payload"]["record_fields"]["body"] == "HTTP 合成短信"
        assert client.get(f"/api/reports/narrative/versions/{report_id}", headers=analyst,
                          params={"task_id": task_id}).json()["citations"][0]["evidence_key"] == selected_key
        assert report_stub.calls == 4
        # 6A export *policy* remains admin-only; this route shape is not a real exporter.
        assert client.get("/api/reports/export", headers=analyst).status_code == 403
        assert client.get("/api/reports/export", headers=admin).status_code == 404
        with sqlite3.connect(tmp_path / "investigation.db") as con:
            snapshot_id = con.execute("SELECT id FROM evidence_snapshots WHERE task_id=? AND evidence_key=?",
                                      (task_id, selected_key)).fetchone()[0]
        print("SYNTHETIC_6B_HTTP=" + json.dumps({
            "task_id": task_id, "result_set_id": result_set, "evidence_key": selected_key,
            "snapshot_id": snapshot_id, "analysis_id": analysis_id, "review_status": reviewed.json()["status"],
            "report_id": report_id, "citation_id": "c001",
            "model": "test-only-mock", "auth": "real-6A-isolated",
        }))
