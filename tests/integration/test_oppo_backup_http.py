"""OPPO (ThunderForensic) backup over the HTTP task pipeline.

Boots the real server with a stubbed intelligence tail (no model calls),
creates tasks for both the tar and project-directory forms of a synthetic
ThunderForensic extraction, and asserts the vendor-neutral mobile tables and
the shared backup-overview query surface the OPPO manifest.
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

from test_oppo_backup_cli import create_project_dir, create_thunderforensic_tar


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
            self.send_json({"status": "COMPLETED", "progress": 100, "current_phase": "completed"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), TailStub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="oppo-http-") as temp:
            root = Path(temp)
            tar_path = create_thunderforensic_tar(root / "20261025OPPO.tar")
            project = create_project_dir(root / "sources")
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

                    # (label, source path, requested android_source, expected source)
                    cases = [
                        ("tar", tar_path, "oppo-backup", "oppo-backup"),
                        ("dir-auto-promote", project, "dir", "oppo-backup"),
                    ]
                    for label, source, requested, expected in cases:
                        status, created = request(base + "/api/tasks", {
                            "image_path": str(source), "android_source": requested,
                            "scenarios": ["android"], "platform_analyze": True,
                            "llm_analyze": False, "filter_profile": "general_forensics"})
                        assert status == 201, (label, created)
                        task_id = created["id"]
                        for _ in range(600):
                            _, task = request(base + "/api/tasks/" + task_id)
                            if task["status"].lower() in {"completed", "failed", "cancelled"}:
                                break
                            time.sleep(0.1)
                        assert task["status"].lower() == "completed", (label, task)
                        assert task["android_source"] == expected, (label, task)
                        android_db = task["metadata"]["android_db"]
                        with sqlite3.connect(android_db) as con:
                            manifest = con.execute(
                                "SELECT platform, device, adapter_version "
                                "FROM mobile_backup_manifest").fetchone()
                            assert manifest == ("Android", "OPPO PBEM00",
                                                "oppo-thunderforensic-v1"), (label, manifest)
                            artifacts = con.execute(
                                "SELECT COUNT(*) FROM mobile_artifacts").fetchone()[0]
                            assert artifacts >= 10, (label, artifacts)
                        _, overview = request(
                            base + f"/api/forensics/android/backup-overview?task_id={task_id}")
                        assert overview.get("manifest", {}).get("device") == "OPPO PBEM00", \
                            (label, overview.get("manifest"))
                        counts = {row["kind"]: row["count"]
                                  for row in overview.get("artifact_counts", [])}
                        assert counts.get("application") == 1, (label, counts)
    finally:
        stub.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True)
    args = parser.parse_args()
    main(Path(args.analyzer).resolve())
    print("OPPO backup HTTP end-to-end tests passed")
