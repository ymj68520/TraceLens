#!/usr/bin/env python3
"""Live, isolated RAID -> ordinary Task -> files/events/source regression.

Uses the real Python application, real field login/introspection, real RAID
worker and real C++ Task pipeline. Inputs are independently encoded synthetic
MD members; no original evidence or running service is contacted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "python_service"), str(ROOT / "tests/integration"), str(ROOT / "scripts")]
from raid_validation.fixtures import make_members
import test_field_security_e2e as security
from isolated_target import require_private_loopback_namespace
from passlib.context import CryptContext


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wait_job(base, job_id, token, *, limit=240):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        code, body = security.request(base, f"/api/evidence-intake/raid/jobs/{job_id}", token=token)
        assert code == 200, (code, body)
        job = body["job"]
        if job["status"] not in ("queued", "running"): return job
        time.sleep(.2)
    raise AssertionError("isolated RAID job timed out")


def run(binary, output, frontend=None):
    require_private_loopback_namespace()
    root = Path(tempfile.mkdtemp(prefix="tracelens-raid-task-e2e-"))
    tree = root / "tree"; tree.mkdir()
    known = {"case-note.txt": b"SYNTHETIC_RAID_CASE_NOTE\n", "accounts.txt": b"Synthetic account A\nSynthetic account B\n"}
    for name, content in known.items(): (tree / name).write_bytes(content)
    image = root / "known-ext4.img"
    with image.open("wb") as stream: stream.truncate(16 * 1024**2)
    subprocess.run(["mkfs.ext4", "-q", "-F", "-d", str(tree), str(image)], check=True)
    members, expected = make_members(root / "inbox", logical=image.read_bytes())
    before = {m["files"][0]: sha(root / "inbox" / m["files"][0]) for m in members}
    runtime = root / "data"; runtime.mkdir()
    cwd = root / "app"; cwd.mkdir()
    # Only non-secret, checked-in filter definitions; no root .env is copied.
    shutil.copytree(ROOT / "config/filter_profiles", cwd / "config/filter_profiles")
    users = root / "users.json"
    passwords = {"alice": "synthetic-raid-alice", "bob": "synthetic-raid-bob"}
    users.write_text(json.dumps({"users": {name: {"password_hash": CryptContext(schemes=["bcrypt"]).hash(password),
        "role": "admin", "active": True, "token_version": 1} for name, password in passwords.items()}}))
    users.chmod(0o600)
    cpp_port, py_port = security.port(), security.port()
    while py_port == cpp_port: py_port = security.port()
    cpp_base, py_base = f"http://127.0.0.1:{cpp_port}", f"http://127.0.0.1:{py_port}"
    security._ALLOWED_TEST_ORIGINS.update({cpp_base, py_base})
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "NVM_DIR"}}
    env.update({"DATA_DIR": str(runtime), "HTTP_SERVER_HOST": "127.0.0.1", "PYTHON_HTTP_HOST": "127.0.0.1",
        "PYTHON_HTTP_PORT": str(py_port), "CPP_BACKEND_URL": cpp_base, "PYTHON_SERVICE_URL": py_base,
        "TRACELENS_FIELD_AUTH": "enabled", "TRACELENS_REQUIRE_FIELD_AUTH": "1", "FIELD_OUTBOUND_POLICY": "disabled",
        "FIELD_AUTH_URL": py_base, "FIELD_USER_FILE": str(users), "FIELD_JWT_SECRET": secrets.token_urlsafe(48),
        "FIELD_CPP_TO_PYTHON_TOKEN": secrets.token_urlsafe(48), "FIELD_PYTHON_TO_CPP_TOKEN": secrets.token_urlsafe(48),
        "TRACELENS_RAID_INBOX": str(root / "inbox"), "TRACELENS_EVIDENCE_INBOX": str(root / "inbox"),
        "ANDROID_REPORT_SEARCH_ROOT": str(root / "inbox"), "FORENSIC_REPORT_DIR": str(root / "reports"),
        "TRACELENS_TEST_INSTANCE_ID": secrets.token_hex(16), "LLM_ENABLED": "false", "GRAPHITI_ENABLED": "false",
        "LLM_BASE_URL": "", "LLM_TEXT_BASE_URL": "", "LLM_VISION_BASE_URL": "", "EMBEDDING_BASE_URL": "", "OSS_ENDPOINT": ""})
    processes = []
    result = {"mode": "ISOLATED_TEST", "root": str(root), "binary": str(binary), "ai": "disabled", "production_modified": False}
    with (root / "cpp.private.log").open("w") as cpp_log, (root / "python.private.log").open("w") as py_log:
        try:
            cpp = subprocess.Popen([str(binary), "--http-server", str(cpp_port)], env=env, cwd=cwd,
                                   stdout=cpp_log, stderr=subprocess.STDOUT); processes.append(cpp)
            security.wait_alive(cpp_base, cpp)
            py = subprocess.Popen([str(security.PYTHON), "-m", "httpserver.main"],
                env={**env, "PYTHONPATH": str(ROOT / "python_service")}, cwd=cwd,
                stdout=py_log, stderr=subprocess.STDOUT); processes.append(py)
            security.wait_alive(py_base, py)
            tokens = {}
            for name, password in passwords.items():
                code, login = security.request(py_base, "/api/field-auth/login", method="POST", data={"username": name, "password": password})
                assert code == 200; tokens[name] = login["access_token"]
            token = tokens["alice"]
            assert security.request(cpp_base, "/api/tasks")[0] == 401
            base = "/api/evidence-intake/raid"
            code, catalog = security.request(py_base, base + "/candidates", token=token); assert code == 200
            ids = [f["id"] for f in catalog["groups"][0]["files"]]
            code, body = security.request(py_base, base + "/jobs", method="POST", token=token, data={"member_ids": ids})
            assert code == 202; job_id = body["job"]["id"]
            job = wait_job(py_base, job_id, token); assert job["status"] == "awaiting_confirmation", job
            candidate = job["inference"]["candidates"][0]["candidate_id"]
            code, _ = security.request(py_base, f"{base}/jobs/{job_id}/prepare", method="POST", token=token,
                                      data={"candidate_id": candidate, "allow_partial": False}); assert code == 202
            job = wait_job(py_base, job_id, token); assert job["status"] == "ready", job
            assert sha(job["task_source"]["image_path"]) == hashlib.sha256(expected).hexdigest()
            body = {**job["task_source"], "case_description": "Synthetic RAID integration", "filter_profile": "",
                    "scenarios": [], "llm_analyze": False, "platform_analyze": False,
                    "metadata": {"source_kind": "forged", "raid_integrity_status": "forged", "requested_by": "forged"}}
            assert security.request(cpp_base, "/api/tasks", method="POST", token=tokens["bob"], data=body)[0] == 400
            assert security.request(cpp_base, "/api/tasks", method="POST", token=token,
                data={"image_path": body["image_path"], "android_source": "tsk"})[0] == 400
            assert security.request(cpp_base, "/api/tasks/batch-create", method="POST", token=token,
                data={"image_paths": [body["image_path"]]})[0] == 400
            assert security.request(cpp_base, "/api/tasks", method="POST", token=token,
                data={**body, "raid_manifest_sha256": "0" * 64})[0] == 400
            code, task = security.request(cpp_base, "/api/tasks", method="POST", token=token, data=body)
            assert code == 201, (code, task)
            task_id = task["id"]
            end = time.monotonic() + 240
            while time.monotonic() < end:
                code, task = security.request(cpp_base, f"/api/tasks/{task_id}", token=token); assert code == 200
                if task["status"].lower() in ("completed", "failed", "cancelled"): break
                time.sleep(.2)
            assert task["status"].lower() == "completed", task
            assert task["metadata"]["source_kind"] == "raid" and task["metadata"]["requested_by"] == "alice"
            assert task["metadata"]["raid_integrity_status"] == "COMPLETE"
            assert (runtime / "tasks" / task_id / "raid_source_manifest.json").is_file()
            code, files = security.request(cpp_base, f"/api/forensics/files/paged?task_id={task_id}&page_size=100", token=token)
            assert code == 200 and files["total"] >= 2, (code, files)
            extracted = {}
            report_key = None
            with sqlite3.connect(task["output_files_db"]) as db:
                for name, content in known.items():
                    path = db.execute("SELECT path FROM files WHERE name=?", (name,)).fetchone()[0]
                    code, material = security.request(cpp_base, "/api/forensics/files/materialize", method="POST", token=token,
                                                     data={"task_id": task_id, "path": path})
                    assert code == 200, (code, material)
                    actual = Path(material["materialized_path"]).read_bytes()
                    assert actual == content; extracted[name] = hashlib.sha256(actual).hexdigest()
                    if name == "case-note.txt": report_key = "file:" + path
            code, snapshot = security.request(py_base, "/api/investigation/snapshots", method="POST", token=token,
                                              data={"task_id": task_id, "evidence_key": report_key})
            assert code == 200 and snapshot["evidence_key"] == report_key, (code, snapshot)
            code, report_evidence = security.request(py_base, f"/api/investigation/workbench/{task_id}/report-evidence",
                method="PUT", token=token, data={"evidence_key": report_key, "usage": "main", "added_by": "forged"})
            assert code == 200, (code, report_evidence)
            with sqlite3.connect(runtime / "tasks" / task_id / "investigation.db") as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 8
                assert db.execute("SELECT added_by FROM report_evidence").fetchone()[0] == "alice"
            code, timeline = security.request(cpp_base, f"/api/forensics/timeline/comprehensive?task_id={task_id}", token=token)
            assert code == 200, (code, timeline)
            code, source = security.request(py_base, f"/api/evidence-intake/tasks/{task_id}/raid-source", token=token)
            assert code == 200 and source["source"]["member_count"] == 3, (code, source)
            # Only alter the synthetic DERIVED image, never an original member.
            derived = Path(body["image_path"])
            with derived.open("r+b") as stream:
                original = stream.read(1); stream.seek(0); stream.write(bytes([original[0] ^ 1]))
            assert security.request(cpp_base, "/api/tasks", method="POST", token=token, data=body)[0] == 409
            with derived.open("r+b") as stream: stream.write(original)
            assert before == {name: sha(root / "inbox" / name) for name in before}
            result.update(status="PASS", task_id=task_id, task_status=task["status"], files=files["total"],
                          known_file_sha256=extracted, source=source["source"], member_hashes_unchanged=True,
                          investigation_snapshot=report_key, report_evidence_selection="main", trusted_actor="alice")
            if frontend:
                # Browser helper receives only synthetic credentials in a private file.
                config = root / "browser.private.json"
                config.write_text(json.dumps({"cpp": cpp_base, "python": py_base, "username": "alice", "password": passwords["alice"], "task_id": task_id,
                    "dist": str(frontend), "output": str(root / "browser.json")})); config.chmod(0o600)
                subprocess.run(["node", str(ROOT / "scripts/raid_task_browser.mjs"), str(config)], cwd=ROOT / "web", check=True, timeout=240)
                result["browser"] = json.loads((root / "browser.json").read_text())
        finally:
            for process in reversed(processes):
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"status": result["status"], "root": str(root), "output": str(output), "files": result["files"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend", type=Path)
    args = parser.parse_args()
    run(args.binary.resolve(strict=True), args.output.absolute(), args.frontend)
