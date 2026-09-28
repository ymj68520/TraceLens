"""Isolated verified image preflight -> HTTP Task -> android.db + coverage."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from test_android_container_cli_e2e import EXPECTED, counts
from test_android_filesystem_image_e2e import fixture_images, locked_fixture
from httpserver.services import evidence_preflight as preflight


def request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def preflight_image(root, data_dir, name):
    preflight.evidence_inbox = lambda: root.resolve()
    preflight.job_root = lambda: data_dir / "evidence_preflight"
    candidate = next(item for item in preflight.list_candidates() if item["name"] == name)
    job_id = preflight.start_job(candidate["id"], full_hash=True)["id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = preflight.get_job(job_id)
        if job["status"] not in {"queued", "running"}:
            assert job["status"] == "completed" and job["integrity_status"] == "verified", job
            assert job["detected"]["adapter"] == "filesystem-image", job
            return job
        time.sleep(0.1)
    raise AssertionError("image preflight timed out")


def await_task(base, task_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        _, task = request(base + "/api/tasks/" + task_id)
        if str(task.get("status", "")).lower() in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.2)
    raise AssertionError("Android image Task timed out")


def run(analyzer: Path):
    with tempfile.TemporaryDirectory(prefix="tracelens_image_http_e2e_") as directory:
        root = Path(directory)
        data_dir = root / "runtime"
        data_dir.mkdir()
        images = fixture_images(root)
        locked = locked_fixture(root)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = dict(os.environ, DATA_DIR=str(data_dir),
                   LLM_ENABLED="false", GRAPHITI_ENABLED="false")
        log = root / "cpp.log"
        with log.open("w", encoding="utf-8") as output:
            server = subprocess.Popen([str(analyzer), "--http-server", str(port)],
                                      env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise AssertionError("C++ server exited early")
                    try:
                        if request(base + "/api/system/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("C++ server did not start")
                observed = {}
                metrics = {}
                for kind, image in images.items():
                    job = preflight_image(root, data_dir, image.name)
                    assert job["image"]["ready"], (kind, job["image"])
                    code, created = request(base + "/api/tasks", {
                        "image_path": str(image), "android_source": "filesystem-image",
                        "scenarios": ["android"], "llm_analyze": False,
                        "platform_analyze": True, "preflight_job_id": job["id"],
                        "preflight_source_sha256": job["sha256"],
                        "preflight_detected_kind": job["detected"]["kind"],
                    })
                    assert code == 201, (kind, code, created)
                    task = await_task(base, created["id"])
                    assert str(task["status"]).lower() == "completed", (kind, task, log.read_text()[-2000:])
                    db = Path(task["output_files_db"])
                    assert db.is_file() and db.name == "android.db"
                    observed[kind] = counts(db)
                    assert observed[kind] == EXPECTED, (kind, observed[kind])
                    manifest = json.loads((db.parent / "android_coverage_manifest.json").read_text())
                    assert manifest["source_image_sha256"] == job["sha256"]
                    assert manifest["artifact_types"]["sms"]["parsed_count"] == 2
                    metrics[kind] = manifest.get("performance")
                    with sqlite3.connect(db) as connection:
                        sources = connection.execute("SELECT source_image_sha256,partition_start_offset,"
                            "filesystem_type,filesystem_path,normalized_android_path,file_sha256 "
                            "FROM android_filesystem_provenance").fetchall()
                        assert any(row[0] == job["sha256"] and row[4] ==
                                   "data/data/com.android.providers.telephony/databases/mmssms.db"
                                   and len(row[5]) == 64 for row in sources), kind
                assert len({tuple(value.items()) for value in observed.values()}) == 1
                locked_job = preflight_image(root, data_dir, locked.name)
                assert locked_job["detected"]["kind"] == "android_userdata_locked"
                code, created = request(base + "/api/tasks", {
                    "image_path": str(locked), "android_source": "filesystem-image",
                    "scenarios": ["android"], "llm_analyze": False,
                    "platform_analyze": True, "preflight_job_id": locked_job["id"],
                    "preflight_source_sha256": locked_job["sha256"],
                    "preflight_detected_kind": "android_userdata_locked",
                })
                assert code == 201, (code, created)
                locked_task = await_task(base, created["id"])
                assert str(locked_task["status"]).lower() == "completed", locked_task
                assert "COMPLETED_WITH_LOCKED_USERDATA" in locked_task.get("message", "")
                locked_db = Path(locked_task["output_files_db"])
                with sqlite3.connect(locked_db) as connection:
                    status = connection.execute("SELECT status FROM android_source_coverage "
                                                "WHERE artifact_kind='userdata'").fetchone()[0]
                    assert status == "LOCKED"
                locked_manifest = json.loads((locked_db.parent / "android_coverage_manifest.json").read_text())
                assert locked_manifest["encryption"] == "LOCKED"
                old = preflight_image(root, data_dir, images["ext4"].name)
                with images["ext4"].open("ab") as sink:
                    sink.write(b"changed")
                code, rejected = request(base + "/api/tasks", {
                    "image_path": str(images["ext4"]), "android_source": "filesystem-image",
                    "preflight_job_id": old["id"], "preflight_source_sha256": old["sha256"],
                    "preflight_detected_kind": old["detected"]["kind"],
                })
                assert code == 409 and rejected["error_code"] == "EVIDENCE_CHANGED_AFTER_PREFLIGHT"
                print({"artifact_counts": observed, "performance": metrics,
                       "locked": "COMPLETED_WITH_LOCKED_USERDATA", "changed_source": "409"})
            except Exception:
                output.flush()
                print(log.read_text(encoding="utf-8", errors="replace")[-3500:])
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", type=Path, required=True)
    args = parser.parse_args()
    run(args.analyzer.resolve(strict=True))
