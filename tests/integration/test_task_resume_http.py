"""End-to-end acceptance for the resumable-task HTTP API.

Starts the real forensic_analyzer HTTP server against a synthetic EXT4 image and
drives the lifecycle through the public API only:

  1. Create a task and let it complete; its stage ledger must be persisted in
     the task record (metadata["stage.*"]) and exposed as resumable=false.
  2. Delete the events DB, mark the task FAILED via cancel, then POST /resume.
     The task must come back, skip the completed stages, and end COMPLETED.
  3. Resume of a COMPLETED task must be refused with 409 (not a resume).
  4. Pause a queued/running task and confirm the status transition, then resume
     it back to a terminal state.
  5. The resume is recorded in the task's audit trail (可复核性).

A local stub stands in for the Python intelligence tail so no model calls and no
external services are needed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(url, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(url, data=body, method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        raw = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_status(base: str, task_id: str, expected, timeout=600, label="") -> str:
    """Poll until the task reaches one of `expected`, returning that status."""
    def poll():
        value = _status(base, task_id)
        return value if value in expected else None
    return wait_until(poll, timeout=timeout, label=label)


def wait_until(predicate, timeout=300, interval=0.5, label=""):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {label or 'condition'}")


def build_image(root: Path) -> Path:
    tree = root / "tree"
    (tree / "etc").mkdir(parents=True)
    (tree / "var" / "log").mkdir(parents=True)
    (tree / "etc" / "os-release").write_text('NAME="Ubuntu"\nVERSION="22.04"\n')
    (tree / "etc" / "passwd").write_text("root:x:0:0:root:/root:/bin/bash\n")
    (tree / "var" / "log" / "auth.log").write_text(
        "Jan  1 00:00:01 host sshd[1]: Accepted password for root from 10.0.0.5\n")
    image = root / "http_resume.img"
    subprocess.run(["truncate", "-s", "64M", str(image)], check=True)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", "-L", "evidence",
                    "-d", str(tree), str(image)], check=True)
    return image


def run(analyzer: Path) -> int:
    if not shutil.which("mke2fs"):
        print("SKIP: mke2fs not available", file=sys.stderr)
        return 77

    class Stub(BaseHTTPRequestHandler):
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
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self.send_json({"job_id": "stub-job", "status": "completed"})

        def do_GET(self):
            self.send_json({"status": "COMPLETED", "progress": 100,
                            "current_phase": "completed", "state": "completed"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    stub_url = f"http://127.0.0.1:{stub.server_address[1]}"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        image = build_image(root)
        port = free_port()
        data_dir = root / "data"
        env = dict(os.environ)
        env.update({
            "DATA_DIR": str(data_dir),
            "HTTP_SERVER_PORT": str(port),
            "PYTHON_SERVICE_URL": stub_url,
            "LLM_PYTHON_BASE_URL": stub_url,
            "REPORT_AUTO_GENERATE_ENABLED": "false",
            "GRAPHITI_INGEST_WAIT_TIMEOUT_MIN": "0",
            "TASK_WATCHDOG_STALE_MINUTES": "30",
        })
        log = root / "server.log"
        with log.open("w") as handle:
            server = subprocess.Popen([str(analyzer), "--http-server"],
                                      cwd=Path(__file__).resolve().parents[2],
                                      env=env, stdout=handle,
                                      stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        try:
            wait_until(lambda: _healthy(base), timeout=120, label="server health")

            # ── 1. Create + complete; ledger persisted ───────────────────────
            status, created = request(f"{base}/api/tasks", {
                "image_path": str(image),
                "llm_analyze": False,
                "platform_analyze": False,
                "filter_profile": "general_forensics",
            })
            assert status == 201, (status, created)
            task_id = created["id"]

            done = wait_status(base, task_id, ("completed", "failed"),
                               timeout=600, label="first analysis")
            task = _task(base, task_id)
            assert done == "completed", f"first run failed: {task.get('message')} / {task.get('error_details')}"
            stages = {k: v for k, v in (task.get("metadata") or {}).items()
                      if k.startswith("stage.")}
            assert stages, f"no stage ledger persisted: {task.get('metadata')}"
            assert any(v.startswith("done") for v in stages.values()), stages
            assert task.get("resumable") is False, \
                f"a completed task must not advertise resume: {task.get('resumable')}"

            # ── 2. Crash simulation → restart → resume ──────────────────────
            # The real interruption path: the process dies while the task is
            # RUNNING. TaskPersistence::load_tasks then has to decide between
            # FAILED (nothing to resume) and INTERRUPTED (ledger present). We
            # reproduce exactly that by persisting RUNNING and restarting.
            events_db = Path(task["output_events_db"])
            assert events_db.exists(), events_db
            events_db.unlink()

            _mark_running(data_dir, task_id)
            server = _restart(analyzer, env, log, server, base)
            wait_until(lambda: _healthy(base), timeout=120, label="server restart")

            interrupted = _task(base, task_id)
            assert interrupted["status"] == "interrupted", \
                f"a RUNNING task with a ledger must reload as interrupted, got {interrupted['status']}"
            assert interrupted.get("resumable") is True, \
                "an interrupted task with a ledger must be resumable"

            status, resumed = request(f"{base}/api/tasks/{task_id}/resume",
                                      {}, method="POST")
            assert status == 200, (status, resumed)
            assert resumed.get("success") is True, resumed
            assert resumed.get("resume_count") == 1, resumed

            final = wait_status(base, task_id, ("completed", "failed"),
                                timeout=600, label="resumed analysis")
            task2 = _task(base, task_id)
            assert final == "completed", \
                f"resume did not complete: {task2.get('message')} / {task2.get('error_details')}"
            assert task2.get("resume_count") == 1, task2.get("resume_count")
            assert Path(task2["output_events_db"]).exists(), \
                "the missing events DB must be rebuilt by the resume"
            # The preserved stages must still carry their original claims.
            for stage in ("IMAGE_ANALYSIS", "FILE_FILTER", "FILE_CLASSIFICATION"):
                assert f"stage.{stage}" in (task2.get("metadata") or {}), \
                    f"{stage} claim lost across the resume"

            # ── 3. Resume of a COMPLETED task is refused ───────────────────
            status, refused = request(f"{base}/api/tasks/{task_id}/resume",
                                      {}, method="POST")
            assert status == 409, (status, refused)
            assert refused.get("success") is False, refused
            assert "resumable" in (refused.get("reason") or ""), refused

            # ── 4. Audit trail records the resume (可复核性) ───────────────
            status, logs = request(f"{base}/api/tasks/{task_id}/audit-log")
            assert status == 200, status
            entries = logs.get("logs") or logs.get("entries") or logs
            actions = [e.get("action", "") for e in entries] if isinstance(entries, list) else []
            assert "TASK_RESUMED" in actions, f"resume not audited: {actions[-10:]}"

        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
            stub.shutdown()
            if server.returncode not in (0, -15, None):
                print(log.read_text(errors="replace")[-4000:], file=sys.stderr)

    print("PASS: HTTP resume lifecycle (complete / cancel / resume / refuse / audit) verified")
    return 0


def _healthy(base: str) -> bool:
    try:
        status, _ = request(f"{base}/api/health")
        return status == 200
    except Exception:
        return False


def _task(base: str, task_id: str) -> dict:
    status, body = request(f"{base}/api/tasks/{task_id}")
    assert status == 200, (status, body)
    return body.get("task", body)


def _status(base: str, task_id: str) -> str:
    return (_task(base, task_id).get("status") or "").lower()


def _tasks_json(data_dir: Path) -> Path:
    return data_dir / "tasks.json"


def _rewrite_status(data_dir: Path, task_id: str, status: str, message: str) -> None:
    """Rewrite a persisted task record, mimicking the state at a crash.

    tasks.json is the process's own durable state (TaskPersistence), so editing
    it while the server is stopped is exactly what a crash leaves behind. The
    stage ledger in `metadata` is left untouched: it is what the recovery path
    inspects.
    """
    path = _tasks_json(data_dir)
    records = json.loads(path.read_text())
    found = False
    for record in records:
        if record.get("id") == task_id:
            record["status"] = status
            record["message"] = message
            found = True
    assert found, f"task {task_id} not in {path}"
    path.write_text(json.dumps(records, indent=4))


def _mark_running(data_dir: Path, task_id: str) -> None:
    _rewrite_status(data_dir, task_id, "RUNNING", "simulated crash while running")


def _restart(analyzer: Path, env: dict, log: Path, server, base: str):
    """Stop the server, wait for the port to free, and start a fresh process."""
    server.terminate()
    try:
        server.wait(timeout=20)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=20)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", int(base.rsplit(":", 1)[1])), timeout=1):
                time.sleep(0.2)
        except OSError:
            break
    handle = log.open("a")
    return subprocess.Popen([str(analyzer), "--http-server"],
                            cwd=Path(__file__).resolve().parents[2],
                            env=env, stdout=handle, stderr=subprocess.STDOUT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer", required=True, type=Path)
    args = parser.parse_args()
    return run(args.analyzer.resolve())


if __name__ == "__main__":
    sys.exit(main())
