"""Synthetic, read-only preflight fixtures for unknown forensic sources."""

import hashlib
import json
import stat
import time
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes.evidence_intake import router
from httpserver.services import evidence_preflight as intake


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    source = tmp_path / "inbox"
    source.mkdir()
    monkeypatch.setattr(intake, "evidence_inbox", lambda: source.resolve())
    monkeypatch.setattr(intake, "job_root", lambda: tmp_path / "jobs")
    return source


def _finished(job_id, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = intake.get_job(job_id)
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.02)
    pytest.fail("preflight job did not finish")


def test_bounded_candidate_detection_and_symlink_exclusion(inbox, tmp_path):
    (inbox / "unknown.mfc").write_bytes(b"opaque vendor bytes")
    (inbox / "android-sparse.img").write_bytes(b"\x3a\xff\x26\xed" + b"\0" * 64)
    (inbox / "sample.db").write_bytes(b"SQLite format 3\x00" + b"\0" * 100)
    (inbox / "sample.db-wal").write_bytes(b"wal")
    report = inbox / "report-export" / "report" / "phone"
    report.mkdir(parents=True)
    (inbox / "report-export" / "index.html").write_text("report")
    (report / "export.db").write_bytes(b"metadata")
    miui = inbox / "backup"
    miui.mkdir()
    (miui / "descript.xml").write_text("<MIUI-backup/>")
    (miui / "contacts.bak").write_bytes(b"bak")
    logical = inbox / "android" / "data" / "data"
    logical.mkdir(parents=True)
    (inbox / "outside-link").symlink_to(tmp_path / "outside")
    result = {item["name"]: item for item in intake.list_candidates()}
    assert result["unknown.mfc"]["kind"] == "vendor_container_unknown"
    assert result["unknown.mfc"]["adapter"] is None
    assert result["android-sparse.img"]["kind"] == "android_sparse_image"
    assert result["android-sparse.img"]["adapter"] is None
    assert result["sample.db"]["kind"] == "sqlite_database"
    assert result["sample.db"]["sidecars_present"] == ["-wal"]
    assert result["report-export"]["kind"] == "derived_html_report"
    assert result["backup"]["adapter"] == "miui-backup"
    assert result["android"]["adapter"] == "dir"
    assert "outside-link" not in result


def test_zip_metadata_is_listed_without_extraction(inbox):
    path = inbox / "data.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/data/com.example/databases/main.db", b"SQLite format 3\x00")
        archive.writestr("../escape.txt", b"bad member")
    before = path.read_bytes()
    candidate = next(item for item in intake.list_candidates() if item["name"] == "data.zip")
    job = _finished(intake.start_job(candidate["id"])["id"])
    assert job["status"] == "completed"
    assert job["detected"]["kind"] == "zip_container_unsafe"
    assert job["detected"]["adapter"] is None
    assert "archive_path_escape" in job["archive"]["warnings"]
    assert job["integrity_status"] == "not_calculated"
    assert path.read_bytes() == before
    assert not (inbox / "escape.txt").exists()


def test_safe_android_zip_can_route_to_existing_adapter(inbox):
    path = inbox / "phone.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/data/com.tencent.mm/MicroMsg/account/EnMicroMsg.db", b"SQLite format 3\x00")
    candidate = next(item for item in intake.list_candidates() if item["name"] == "phone.zip")
    job = _finished(intake.start_job(candidate["id"])["id"])
    assert job["detected"]["kind"] == "android_logical_zip"
    assert job["detected"]["adapter"] == "zip"


def test_zip_symlink_is_not_routed_to_android_parser(inbox):
    path = inbox / "linked.zip"
    link = zipfile.ZipInfo("data/data/com.tencent.mm/MicroMsg/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/data/com.tencent.mm/MicroMsg/account/EnMicroMsg.db", b"data")
        archive.writestr(link, "../../outside")
    candidate = next(item for item in intake.list_candidates() if item["name"] == "linked.zip")
    job = _finished(intake.start_job(candidate["id"])["id"])
    assert job["detected"]["adapter"] is None
    assert "archive_symlink" in job["archive"]["warnings"]


def test_background_full_hash_and_manifest(inbox):
    path = inbox / "disk.img"
    content = b"evidence" * 4096
    path.write_bytes(content)
    candidate = next(item for item in intake.list_candidates() if item["name"] == "disk.img")
    result = _finished(intake.start_job(candidate["id"], full_hash=True)["id"])
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    assert result["bytes_read"] == len(content)
    assert result["integrity_status"] == "verified"
    assert result["detected"]["confidence"] == "extension_only"
    assert path.read_bytes() == content

    directory = inbox / "phone" / "data" / "data"
    directory.mkdir(parents=True)
    (directory / "a.db").write_bytes(b"record")
    (directory / "inner.zip").write_bytes(b"not opened by directory scan")
    candidate = next(item for item in intake.list_candidates() if item["name"] == "phone")
    job = _finished(intake.start_job(candidate["id"], full_hash=True)["id"])
    assert job["file_count"] == 2
    assert job["nested_candidates"] == ["data/data/inner.zip"]
    assert job["extension_counts"][".db"] == 1
    assert job["manifest_available"] is True
    assert job["tree_manifest_sha256"]
    manifest = (intake._job_dir(job["id"]) / "manifest.jsonl").read_text()
    assert json.loads(manifest.splitlines()[0])["path"] == "data/data/a.db"
    assert job["integrity_status"] == "manifest_hashed"


def test_http_api_requires_registered_candidate(inbox):
    (inbox / "unknown.m01").write_bytes(b"vendor")
    app = FastAPI()
    app.include_router(router, prefix="/api/evidence-intake")
    client = TestClient(app)
    candidate = client.get("/api/evidence-intake/candidates").json()["candidates"][0]
    assert client.post("/api/evidence-intake/jobs", json={"path": "/etc/passwd"}).status_code == 400
    assert client.post("/api/evidence-intake/jobs", json={"candidate_id": "../bad"}).status_code == 400
    response = client.post("/api/evidence-intake/jobs", json={"candidate_id": candidate["id"]})
    assert response.status_code == 202
    job = _finished(response.json()["job"]["id"])
    assert client.get(f"/api/evidence-intake/jobs/{job['id']}").json()["job"]["detected"]["adapter"] is None
    assert client.get("/api/evidence-intake/jobs/not-a-job").status_code == 400


def test_interrupted_job_is_not_reported_as_verified(inbox):
    job_id = "a" * 32
    intake._write_job(job_id, {"id": job_id, "status": "running", "integrity_status": "not_calculated"})
    assert intake.get_job(job_id)["status"] == "interrupted"
    app = FastAPI()
    app.include_router(router, prefix="/api/evidence-intake")
    assert TestClient(app).get(f"/api/evidence-intake/jobs/{job_id}/manifest").status_code == 409


def test_quick_directory_scan_is_time_bounded(inbox, monkeypatch):
    directory = inbox / "many-files"
    directory.mkdir()
    for index in range(5):
        (directory / f"{index}.txt").write_text("evidence")
    monkeypatch.setattr(intake, "_QUICK_SECONDS", 0)
    candidate = next(item for item in intake.list_candidates() if item["name"] == "many-files")
    job = _finished(intake.start_job(candidate["id"])["id"])
    assert job["status"] == "partial"
    assert job["inventory_truncated"] is True
    assert job["integrity_status"] == "not_calculated"
