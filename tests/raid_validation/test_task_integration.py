import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python_service"))
from httpserver.services import raid_task_intake as intake
from httpserver.routes.raid_task_intake import router
from .fixtures import make_members


@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "inbox"
    make_members(root)
    (root / "escape.img").symlink_to(tmp_path / "outside.img")
    monkeypatch.setenv("TRACELENS_RAID_INBOX", str(root))
    monkeypatch.setattr(intake, "get_data_root", lambda: tmp_path / "data")
    app = FastAPI()
    @app.middleware("http")
    async def synthetic_principal(request: Request, call_next):
        token = request.headers.get("authorization")
        if token in ("synthetic-alice", "synthetic-bob", "synthetic-viewer"):
            request.state.principal = {"id": token, "kind": "user", "role": "viewer" if token.endswith("viewer") else "admin"}
        return await call_next(request)
    app.include_router(router, prefix="/api/evidence-intake")
    return TestClient(app), root


def test_existing_intake_namespace_auth_and_selection(api):
    client, root = api
    prefix = "/api/evidence-intake/raid"
    assert client.get(prefix + "/candidates").status_code == 401
    response = client.get(prefix + "/candidates", headers={"Authorization": "synthetic-alice"})
    assert response.status_code == 200
    files = response.json()["groups"][0]["files"]
    assert len(files) == 3
    assert all(set(file) == {"id", "name", "size"} for file in files)
    assert "source_root" not in response.text
    assert client.post(prefix + "/jobs", json={"member_ids": [f["id"] for f in files]},
                       headers={"Authorization": "synthetic-viewer"}).status_code == 403
    assert client.post(prefix + "/jobs", json={"member_ids": [files[0]["id"]] * 2},
                       headers={"Authorization": "synthetic-alice"}).status_code == 400
    assert client.post(prefix + "/jobs/" + "0" * 32 + "/cancel",
                       headers={"Authorization": "synthetic-viewer"}).status_code == 403
    assert client.post(prefix + "/jobs/" + "0" * 32 + "/prepare", json={"candidate_id": "none"},
                       headers={"Authorization": "synthetic-viewer"}).status_code == 403


def test_worker_capacity_does_not_create_partial_job(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(intake, "_active", {"synthetic-one": object(), "synthetic-two": object()})
    headers = {"Authorization": "synthetic-alice"}
    prefix = "/api/evidence-intake/raid"
    files = client.get(prefix + "/candidates", headers=headers).json()["groups"][0]["files"]
    response = client.post(prefix + "/jobs", json={"member_ids": [f["id"] for f in files]}, headers=headers)
    assert response.status_code == 400 and response.json()["detail"] == "RAID_WORKER_CAPACITY"
    assert not intake.jobs_root().exists()


def test_real_prepare_yields_regular_image_task_source(api):
    client, root = api
    headers = {"Authorization": "synthetic-alice"}
    prefix = "/api/evidence-intake/raid"
    files = client.get(prefix + "/candidates", headers=headers).json()["groups"][0]["files"]
    start = client.post(prefix + "/jobs", json={"member_ids": [f["id"] for f in files]}, headers=headers)
    assert start.status_code == 202
    job_id = start.json()["job"]["id"]
    assert client.get(prefix + "/jobs/" + job_id, headers={"Authorization": "synthetic-bob"}).status_code == 403
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = client.get(prefix + "/jobs/" + job_id, headers=headers).json()["job"]
        if job["status"] not in ("queued", "running"): break
        time.sleep(.1)
    assert job["status"] == "awaiting_confirmation", job
    candidate = job["inference"]["candidates"][0]["candidate_id"]
    prepared = client.post(prefix + "/jobs/" + job_id + "/prepare", headers=headers,
                           json={"candidate_id": candidate, "allow_partial": False})
    assert prepared.status_code == 202
    while time.monotonic() < deadline:
        job = client.get(prefix + "/jobs/" + job_id, headers=headers).json()["job"]
        if job["status"] not in ("queued", "running"): break
        time.sleep(.1)
    assert job["status"] == "ready", job
    source = job["task_source"]
    assert source["android_source"] == "tsk" and source["image_source"] == "raid"
    assert Path(source["image_path"]).is_file()
    assert len(source["raid_manifest_sha256"]) == 64
