"""Existing /api/tasks chain, with local intelligence-tail stub (no model calls)."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from test_harmony_backup_cli import create_fixture


def request(url, data=None):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return response.status, json.load(response)


def main(binary):
    calls = []

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
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            calls.append((self.path, body))
            self.send_json({"job_id": "fixture-ingestion", "status": "completed"})

        def do_GET(self):
            self.send_json({"status": "COMPLETED", "progress": 100, "current_phase": "completed"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), TailStub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="harmony-http-") as temp:
            root = Path(temp)
            source = root / "backup"
            create_fixture(source)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            env = dict(os.environ, DATA_DIR=str(root / "data"), LLM_ENABLED="false",
                       PYTHON_SERVICE_URL=f"http://127.0.0.1:{stub.server_port}",
                       GRAPHITI_INGEST_WAIT_TIMEOUT_MIN="1")
            with (root / "server.log").open("w") as log:
                server = subprocess.Popen([str(binary), "--http-server", str(port)],
                    cwd=Path(__file__).resolve().parents[2], env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    for _ in range(200):
                        try:
                            if request(base + "/api/health")[0] == 200:
                                break
                        except OSError:
                            time.sleep(0.1)
                    else:
                        raise AssertionError("isolated server did not start")
                    for mode in ("harmony-backup", "dir"):
                        status, created = request(base + "/api/tasks", {
                            "image_path": str(source), "android_source": mode, "scenarios": ["android"],
                            "platform_analyze": True, "llm_analyze": False, "filter_profile": "general_forensics"})
                        assert status == 201, created
                        task_id = created["id"]
                        for _ in range(600):
                            _, task = request(base + "/api/tasks/" + task_id)
                            if task["status"].lower() in {"completed", "failed", "cancelled"}:
                                break
                            time.sleep(0.1)
                        assert task["status"].lower() == "completed", task
                        assert task["android_source"] == "harmony-backup"
                        android = task["metadata"]["android_db"]
                        assert android != task["output_files_db"]
                        with sqlite3.connect(task["output_files_db"]) as con:
                            assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 3
                        with sqlite3.connect(task["output_events_db"]) as con:
                            assert con.execute("SELECT COUNT(*) FROM events WHERE event_source='HARMONY_BACKUP'").fetchone()[0] == 2
                        _, overview = request(base + "/api/forensics/android/backup-overview?task_id=" + task_id)
                        assert overview["manifest"]["platform"] == "HarmonyOS", overview
                        assert overview["artifact_counts"] == [{"kind": "calendar", "count": 2}], overview
                        assert any(path == "/api/graphiti/ingest" and body.get("task_id") == task_id
                                   and body.get("trigger_source") == "pipeline" for path, body in calls), calls
                    print("PASS: same task API, common file/event databases, mobile overview and original ingestion/report tail")
                except Exception:
                    print((root / "server.log").read_text(errors="replace")[-7000:])
                    raise
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=10)
    finally:
        stub.shutdown()
        stub.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", type=Path, required=True)
    main(parser.parse_args().analyzer.resolve())
