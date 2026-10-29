#!/usr/bin/env python3
"""Generic ThunderForensic backup over the HTTP task pipeline.

Boots the real server with a stubbed intelligence tail (no model calls),
creates tasks for OPPO / OnePlus / vivo extractions in tar and project-folder
forms, and asserts that every path is normalized to the generic
`thunder-backup` source, that the vendor-neutral mobile tables carry the
parsed artifacts, and that the shared backup-overview query surfaces them.
"""

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from test_thunderforensic_backup_cli import (
    VENDOR, create_project_dir, create_thunderforensic_tar)


def request(url, data=None):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return response.status, json.load(response)


def main(binary):
    class TailStub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.send_json({"job_id": "fixture-ingestion", "status": "completed"})

        def do_GET(self):
            self.send_json({"status": "COMPLETED", "progress": 100,
                            "current_phase": "completed"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), TailStub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="thunder-http-") as temp:
            root = Path(temp)
            cases = [
                # label, source path, requested source, expected canonical source
                ("OPPO-tar", create_thunderforensic_tar(root / "20261025OPPO.tar", "OPPO"),
                 "thunder-backup", "OPPO"),
                ("OnePlus-dir-auto-promote",
                 create_project_dir(root / "sources", "OnePlus"), "dir", "OnePlus"),
                ("VIVO-legacy-alias",
                 create_thunderforensic_tar(root / "20261025VIVO.tar", "VIVO"),
                 "oppo-backup", "VIVO"),
            ]
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            env = dict(os.environ, DATA_DIR=str(root / "data"), LLM_ENABLED="false",
                       PYTHON_SERVICE_URL=f"http://127.0.0.1:{stub.server_port}",
                       GRAPHITI_INGEST_WAIT_TIMEOUT_MIN="1")
            with (root / "server.log").open("w") as log:
                server = subprocess.Popen([str(binary), "--http-server", str(port)],
                    cwd=Path(__file__).resolve().parents[2], env=env, stdout=log,
                    stderr=subprocess.STDOUT)
                for _ in range(200):
                    try:
                        if request(base + "/api/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("isolated server did not start")

                for label, source, requested, vendor in cases:
                    status, created = request(base + "/api/tasks", {
                        "image_path": str(source), "android_source": requested,
                        "scenarios": ["android"], "platform_analyze": True,
                        "llm_analyze": False, "filter_profile": "general_forensics"})
                    assert status == 201, (label, created)
                    task_id = created["id"]
                    for _ in range(1800):
                        _, task = request(base + "/api/tasks/" + task_id)
                        if task["status"].lower() in {"completed", "failed", "cancelled"}:
                            break
                        time.sleep(0.1)
                    assert task["status"].lower() == "completed", (label, task)
                    assert task["android_source"] == "thunder-backup", (label, task)
                    info = VENDOR[vendor]
                    expected_device = f"{info['brand']} {info['model']}"
                    metadata = task["metadata"]
                    assert metadata.get("device_brand") == info["brand"], (label, metadata)
                    assert metadata.get("device_model") == info["model"], (label, metadata)
                    android_db = Path(metadata["android_db"])
                    with sqlite3.connect(android_db) as con:
                        manifest = con.execute(
                            "SELECT platform, device, adapter_version "
                            "FROM mobile_backup_manifest").fetchone()
                        assert manifest == ("Android", expected_device,
                                            "thunderforensic-v2"), (label, manifest)
                        artifacts = con.execute(
                            "SELECT COUNT(*) FROM mobile_artifacts").fetchone()[0]
                        assert artifacts >= 20, (label, artifacts)
                        kinds = dict(con.execute(
                            "SELECT kind, COUNT(*) FROM mobile_artifacts GROUP BY kind"))
                        assert kinds.get("application") == 2, (label, kinds)
                        assert kinds.get("contact") == 1, (label, kinds)
                        if vendor == "VIVO":
                            assert kinds.get("note_archive") == 2, (label, kinds)
                            assert kinds.get("app_data_container", 0) >= 1, (label, kinds)
                            wifi = con.execute(
                                "SELECT COUNT(*) FROM wifi_networks").fetchone()[0]
                            assert wifi == 2, (label, wifi)
                    # Unified extraction package: the task path must hand over
                    # the same format the CLI produces.
                    package = metadata.get("mobile_evidence_package")
                    assert package and Path(package).is_file(), (label, metadata)
                    with sqlite3.connect(package) as con:
                        adapter = con.execute(
                            "SELECT value FROM mobile_evidence_meta "
                            "WHERE key='adapter_name'").fetchone()
                        assert adapter and adapter[0] == "thunder-backup", (label, adapter)
                        records = con.execute(
                            "SELECT COUNT(*) FROM mobile_evidence_record").fetchone()[0]
                        assert records >= 20, (label, records)
                    _, overview = request(
                        base + f"/api/forensics/android/backup-overview?task_id={task_id}")
                    assert overview.get("manifest", {}).get("device") == expected_device, \
                        (label, overview.get("manifest"))
                    counts = {row["kind"]: row["count"]
                              for row in overview.get("artifact_counts", [])}
                    assert counts.get("application") == 2, (label, counts)
                    assert counts.get("contact") == 1, (label, counts)
    finally:
        stub.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True)
    args = parser.parse_args()
    main(Path(args.analyzer).resolve())
    print("ThunderForensic generic HTTP end-to-end tests passed")
