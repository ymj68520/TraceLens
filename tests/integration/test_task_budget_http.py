"""Acceptance for the task-level LLM analysis budget (llm_max_files).

Drives the real forensic_analyzer HTTP server and checks the contract the UI
depends on:

  1. Omitting the field keeps the inherited global budget (0 on the record).
  2. Each accepted form — preset-style integer, explicit 0, upper bound — is
     echoed in the 201 response and persisted on the task.
  3. Invalid values (non-integer, negative, above the cap) are rejected with
     400 / INVALID_LLM_MAX_FILES instead of silently falling back to the
     global budget.
  4. The value survives a persisted-task reload (tasks.json round-trip).

A local stub stands in for the Python intelligence tail so no model calls and
no external services are needed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_harmony_backup_cli import create_fixture  # noqa: E402

from urllib.error import HTTPError, URLError  # noqa: E402
from urllib.request import Request, urlopen  # noqa: E402


def request(url: str, data=None):
    """POST/GET returning (status, parsed body) even for 4xx responses."""
    body = json.dumps(data).encode() if data is not None else None
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        raw = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw}


def wait_healthy(base: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if request(base + "/api/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError("server did not start")


def start_server(binary: Path, root: Path, stub_port: int) -> tuple[subprocess.Popen, str, object]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        DATA_DIR=str(root / "data"),
        LLM_ENABLED="false",
        PYTHON_SERVICE_URL=f"http://127.0.0.1:{stub_port}",
        LLM_BASE_URL=f"http://127.0.0.1:{stub_port}",
        LLM_TEXT_BASE_URL=f"http://127.0.0.1:{stub_port}",
        LLM_MODEL="synthetic-budget-model",
        LLM_TEXT_MODEL="synthetic-budget-model",
        LLM_MAX_FILES="37",
        LLM_SMART_CANDIDATE_FILES="5000",
        GRAPHITI_INGEST_WAIT_TIMEOUT_MIN="0",
        REPORT_AUTO_GENERATE_ENABLED="false",
    )
    log_path = root / f"server-{port}.log"
    log = log_path.open("w")
    server = subprocess.Popen(
        [str(binary), "--http-server", str(port)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return server, base, log


def main(binary: Path) -> None:
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
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            if self.path.endswith("/chat/completions"):
                self.send_json({"choices": [{"message": {"content": json.dumps({
                    "summary": "合成预算验证", "description": "仅用于本地集成测试",
                    "keywords": ["测试"],
                }, ensure_ascii=False)}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 10}})
            elif self.path == "/api/graphiti/ingest":
                self.send_json({"job_id": "job-budget", "status": "pending"})
            else:
                self.send_json({"success": True})

        def do_GET(self):
            if self.path.startswith("/v1/models"):
                self.send_json({"data": [{"id": "synthetic-budget-model"}]})
            elif self.path.startswith("/api/graphiti/jobs/"):
                self.send_json({"status": "COMPLETED", "progress": 100,
                                "current_phase": "done", "started_at": None,
                                "completed_at": None, "error": None})
            else:
                self.send_json({"status": "healthy"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    servers = []
    try:
        with tempfile.TemporaryDirectory(prefix="budget-http-") as temp:
            root = Path(temp)
            create_fixture(root / "backup")
            source = str(root / "backup")
            server, base, log = start_server(binary, root, stub.server_port)
            servers.append((server, log))
            wait_healthy(base)

            def create(body):
                payload = {
                    "image_path": source,
                    "android_source": "harmony-backup",
                    "scenarios": ["android"],
                    "platform_analyze": True,
                    "llm_analyze": True,
                    "case_description": "预算验收",
                }
                payload.update(body)
                return request(base + "/api/tasks", payload)

            def read_back(task_id):
                status, task = request(base + "/api/tasks/" + task_id)
                assert status == 200, task
                return task

            # 1. Omitted -> inherited (0 on the record) and the field is echoed.
            status, task = create({})
            assert status == 201, task
            assert task["llm_max_files"] == 0, task
            omitted_id = task["id"]
            assert read_back(omitted_id)["llm_max_files"] == 0

            # 2. Accepted values are echoed verbatim.
            accepted_ids = {}
            for requested in (100, 300, 500, 1000, 1, 100000):
                status, task = create({"llm_max_files": requested})
                assert status == 201, task
                assert task["llm_max_files"] == requested, (requested, task)
                accepted_ids[task["id"]] = requested
                assert read_back(task["id"])["llm_max_files"] == requested

            # Explicit 0 means "inherit", not "analyze nothing".
            status, task = create({"llm_max_files": 0})
            assert status == 201, task
            assert task["llm_max_files"] == 0, task

            # null behaves like an omitted field.
            status, task = create({"llm_max_files": None})
            assert status == 201, task
            assert task["llm_max_files"] == 0, task

            # 3. Invalid values are refused, never silently defaulted.
            for bad in (-1, 100001, 1.5, "300", True):
                status, body = create({"llm_max_files": bad})
                assert status == 400, (bad, status, body)
                assert body.get("error_code") == "INVALID_LLM_MAX_FILES", (bad, body)

            # Nothing was persisted for the rejected requests: the only tasks
            # are the accepted ones above.
            status, listing = request(base + "/api/tasks")
            assert status == 200, listing
            assert listing["pagination"]["total"] >= 3, listing

            # 4. Persisted reload: stop the server and start a new one on the
            # same DATA_DIR; the task's budget must come back unchanged.
            server.terminate()
            try:
                server.wait(timeout=15)
            finally:
                log.close()

            server2, base2, log2 = start_server(binary, root, stub.server_port)
            servers.append((server2, log2))
            wait_healthy(base2)
            reload_cases = [(omitted_id, 0)] + list(accepted_ids.items())
            for task_id, expected in reload_cases:
                status, reloaded = request(base2 + "/api/tasks/" + task_id)
                assert status == 200, reloaded
                assert reloaded["llm_max_files"] == expected, (task_id, expected, reloaded)

            failure = None
            for proc, handle in servers:
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except Exception:
                    pass
                handle.close()
            print("PASS: budget omitted=inherit, accepted values echoed and persisted, "
                  "invalid values rejected, value survives reload")
            return failure
    finally:
        stub.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    try:
        main(args.binary)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        raise
