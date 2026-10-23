"""Actual C++ task completion must wait for ingestion and report terminal states."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_harmony_backup_cli import create_fixture
from test_harmony_backup_http import request


def main(binary):
    report_started = threading.Event()
    release = threading.Event()
    fail = threading.Event()
    ingestion_polls = {}
    calls = []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *_):
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
            if self.path == "/api/graphiti/ingest":
                self.send_json({"job_id": "job-" + body["task_id"], "status": "pending"})
            elif self.path == "/api/reports/pipeline-tail":
                report_started.set()
                self.send_json({"state": "running", "generation_id": None, "report_id": None, "error_code": None})
            else:
                self.send_json({"success": True})

        def do_GET(self):
            if self.path.startswith("/api/graphiti/jobs/"):
                count = ingestion_polls.get(self.path, 0) + 1
                ingestion_polls[self.path] = count
                self.send_json({"status": "RUNNING" if count == 1 else "COMPLETED",
                    "progress": 50 if count == 1 else 100, "current_phase": "ingesting",
                    "started_at": None, "completed_at": None, "error": None})
            elif self.path.startswith("/api/reports/pipeline-tail/status"):
                state = "failed" if fail.is_set() else "completed" if release.is_set() else "running"
                self.send_json({"state": state, "generation_id": None, "report_id": None,
                                "error_code": "fixture_report_failure" if fail.is_set() else None})
            else:
                self.send_json({"status": "healthy"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="report-gate-http-") as temp:
            root = Path(temp)
            create_fixture(root / "backup")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            env = dict(os.environ, DATA_DIR=str(root / "data"), LLM_ENABLED="false",
                       PYTHON_SERVICE_URL=f"http://127.0.0.1:{stub.server_port}",
                       REPORT_AUTO_GENERATE_ENABLED="true", REPORT_TAIL_WAIT_TIMEOUT_MIN="1",
                       REPORT_TAIL_POLL_SECONDS="1", REPORT_TAIL_RETRIES="0",
                       GRAPHITI_INGEST_WAIT_TIMEOUT_MIN="1", GRAPHITI_INGEST_POLL_SECONDS="1",
                       GRAPHITI_INGEST_RETRIES="0")
            with (root / "server.log").open("w") as log:
                server = subprocess.Popen([str(binary), "--http-server", str(port)],
                    cwd=Path(__file__).resolve().parents[2], env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    for _ in range(300):
                        try:
                            if request(base + "/api/health")[0] == 200:
                                break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise AssertionError("server did not start")
                    for outcome in ("completed", "failed"):
                        report_started.clear()
                        release.clear()
                        fail.clear()
                        status, task = request(base + "/api/tasks", {
                            "image_path": str(root / "backup"), "android_source": "harmony-backup",
                            "scenarios": ["android"], "platform_analyze": True,
                            "llm_analyze": True, "filter_profile": "general_forensics"})
                        assert status == 201, task
                        url = base + "/api/tasks/" + task["id"]
                        assert report_started.wait(55), request(url)
                        # Running report includes null IDs. It must not complete early.
                        time.sleep(1.5)
                        assert request(url)[1]["status"].lower() == "running"
                        (release if outcome == "completed" else fail).set()
                        for _ in range(200):
                            task = request(url)[1]
                            if task["status"].lower() in ("completed", "failed"):
                                break
                            time.sleep(.1)
                        assert task["status"].lower() == outcome, task
                        assert Path(task["output_files_db"]).is_file(), task
                    assert all(count >= 2 for count in ingestion_polls.values())
                    text = (root / "server.log").read_text(errors="replace")
                    assert "get_job_status exception" not in text
                    print("PASS: running/null ingestion, report wait, successful report completion, failed report blocks completion; artifacts retained")
                except Exception:
                    print((root / "server.log").read_text(errors="replace")[-8000:])
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
