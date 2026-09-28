"""Synthetic-only field delivery regression; no real evidence is touched."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import evidence_intake
from httpserver.services.android_artifact_reader import artifact_detail, list_artifacts
from httpserver.services.android_field_package import build_package, verify_package
from httpserver.services import android_report_import as reports, evidence_preflight


@pytest.fixture
def task_fixture(tmp_path):
    db = tmp_path / "android.db"
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, address TEXT, body TEXT, date INTEGER, type INTEGER)")
    writer.execute("CREATE TABLE contacts(id INTEGER PRIMARY KEY, display_name TEXT, phone_number TEXT)")
    writer.execute("CREATE TABLE installed_packages(id INTEGER PRIMARY KEY, package_name TEXT, version TEXT)")
    writer.execute("CREATE TABLE wifi_networks(id INTEGER PRIMARY KEY, ssid TEXT, pre_shared_key TEXT, key_mgmt TEXT)")
    writer.execute("CREATE TABLE android_source_coverage(artifact_kind TEXT, source_path TEXT, status TEXT, detail TEXT)")
    writer.execute("CREATE TABLE android_source_provenance(source_container TEXT, source_container_sha256 TEXT, "
                   "source_member_path TEXT, normalized_android_path TEXT, member_size INTEGER, "
                   "member_sha256 TEXT, adapter_type TEXT, adapter_version TEXT)")
    writer.executemany("INSERT INTO sms_messages VALUES(?,?,?,?,?)", [
        (1, "10086", "独立预期消息", 1720000000000, 1),
        (2, "10086", "独立预期消息", 1720000000000, 1),
    ])
    writer.execute("INSERT INTO contacts VALUES(1,'张 三','123')")
    writer.execute("INSERT INTO installed_packages VALUES(1,'com.example.app','1.2')")
    writer.execute("INSERT INTO wifi_networks VALUES(1,'现场 Wi-Fi','do-not-disclose','WPA2')")
    source = "data/data/com.android.providers.telephony/databases/mmssms.db"
    writer.execute("INSERT INTO android_source_coverage VALUES('sms',?,'staged_for_parser','bundle read')", (source,))
    writer.execute("INSERT INTO android_source_provenance VALUES(?,?,?,?,?,?,?,?)",
                   ("synthetic.zip", "a" * 64, source, source, 42, "b" * 64, "zip", "test"))
    writer.commit()
    task = {"id": "synthetic-task", "android_source": "zip", "output_files_db": str(tmp_path / "files.db")}
    yield task, writer
    writer.close()


def test_query_multiset_and_candidate_provenance(task_fixture):
    task, _ = task_fixture
    found = list_artifacts(task, "sms", query="独立预期")
    assert found["total"] == 2
    assert [item["body"] for item in found["records"]] == ["独立预期消息"] * 2
    assert list_artifacts(task, "sms", query="%")["total"] == 0
    detail = artifact_detail(task, "sms", 1)
    assert detail["source"]["original_path"].endswith("mmssms.db")
    assert detail["source"]["verified_row_source"] is False
    assert detail["source"]["original_primary_key"] is None
    assert artifact_detail(task, "wifi", 1)["record"]["pre_shared_key"] == "[redacted]"
    with pytest.raises(ValueError):
        list_artifacts(task, "sqlite_master")
    with pytest.raises(FileNotFoundError):
        artifact_detail(task, "sms", 999)


def test_wal_snapshot_matches_jsonl_and_offline_verification(task_fixture, tmp_path, monkeypatch):
    task, writer = task_fixture
    job_id = "a" * 32
    job = tmp_path / "preflight" / job_id
    job.mkdir(parents=True)
    (job / "manifest.jsonl").write_text('{"source":"synthetic"}\n', encoding="utf-8")
    monkeypatch.setattr(evidence_preflight, "job_root", lambda: tmp_path / "preflight")
    task["metadata"] = {"preflight_job_id": job_id}
    # Keep the source connection open and the WAL uncheckpointed.
    writer.execute("INSERT INTO sms_messages VALUES(3,'12345','WAL-only row',1720000001000,2)")
    writer.commit()
    output = tmp_path / "delivery"
    manifest = build_package(output=output, task=task)
    assert manifest["counts"] == {"sms_messages": 3, "contacts": 1,
                                  "installed_packages": 1, "wifi_networks": 1}
    assert manifest["completeness"] == "UNVERIFIED"
    assert verify_package(output)["valid"] is True
    cli = Path(__file__).resolve().parents[3] / "scripts" / "android_field_package.py"
    assert subprocess.run([sys.executable, str(cli), "--verify", str(output)],
                          capture_output=True, text=True, timeout=20).returncode == 0
    exported = [json.loads(line) for line in (output / "records.jsonl").read_text().splitlines()]
    assert [row["record"]["body"] for row in exported if row["table"] == "sms_messages"] == [
        "独立预期消息", "独立预期消息", "WAL-only row"]
    assert not (output / "android.db-wal").exists()
    assert (output / "preflight_manifest.jsonl").is_file()
    with pytest.raises(ValueError):
        build_package(output=output, task=task)
    (output / "records.jsonl").write_text("tampered\n")
    with pytest.raises(ValueError):
        verify_package(output)


def test_new_row_api_fails_closed_without_field_token(task_fixture, monkeypatch):
    task, _ = task_fixture
    async def get_task(_task_id):
        return task
    monkeypatch.setattr(evidence_intake, "get_task_record", get_task)
    monkeypatch.delenv("TRACELENS_FIELD_API_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(evidence_intake.router, prefix="/api/evidence-intake")
    client = TestClient(app)
    route = "/api/evidence-intake/tasks/synthetic-task/android-artifacts/sms"
    assert client.get(route).status_code == 503
    monkeypatch.setenv("TRACELENS_FIELD_API_TOKEN", "x" * 40)
    assert client.get(route).status_code == 401
    assert client.get(route, headers={"x-tracelens-field-token": "x" * 40}).json()["total"] == 2
    assert client.get(route + "/1", headers={"x-tracelens-field-token": "x" * 40}).json()["source"]["verified_row_source"] is False
    assert client.post(route + "/search", json={"query": "独立预期", "page": 1},
                       headers={"x-tracelens-field-token": "x" * 40}).json()["total"] == 2
    assert client.post(route + "/search", json={"query": "x" * 201},
                       headers={"x-tracelens-field-token": "x" * 40}).status_code == 400
    assert client.get(route.replace("synthetic-task", "other"),
                      headers={"x-tracelens-field-token": "x" * 40}).status_code == 404


def test_external_html_package_preserves_partial_status(tmp_path, monkeypatch):
    root = tmp_path / "report-source"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    page_dir = root / "report" / "sample-phone" / "report" / "content"
    page_dir.mkdir(parents=True)
    with sqlite3.connect(root / "report" / "sample-phone" / "export.db") as metadata:
        metadata.execute("CREATE TABLE archiveInfo(softName TEXT, softVersion TEXT)")
        metadata.execute("INSERT INTO archiveInfo VALUES ('Synthetic Exporter', '1.0')")
    (root / "report" / "content0.html").write_text(
        "<h3>设备信息</h3><table><tr><td>安卓设备</td></tr></table>", encoding="utf-8")
    (page_dir / "content1.html").write_text(
        '<h3>短信</h3><table><tr><th>时间</th><th>内容</th></tr>'
        '<tr><td>2026-07-17 10:15:50</td><td>独立报告记录'
        '<img src="../resource/attachment/missing.jpg"></td></tr></table>', encoding="utf-8")
    monkeypatch.setattr(reports, "import_root", lambda: tmp_path / "imports")
    imported = reports.create_import(str(root))
    assert imported["source_type"] == "external_html_report"
    result = build_package(output=tmp_path / "report-delivery", import_id=imported["import_id"])
    assert result["source_type"] == "external_html_report"
    assert result["counts"]["records"] >= 1
    assert verify_package(tmp_path / "report-delivery")["valid"] is True
    assert result["completeness"] != "COMPLETE"
    indexed_manifest = tmp_path / "imports" / imported["import_id"] / "report_manifest.json"
    moved = tmp_path / "detached-manifest.json"
    indexed_manifest.rename(moved)
    indexed_manifest.symlink_to(moved)
    with pytest.raises(ValueError, match="symlink"):
        build_package(output=tmp_path / "rejected-delivery", import_id=imported["import_id"])
