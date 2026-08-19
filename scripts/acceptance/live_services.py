#!/usr/bin/env python3
"""Run TraceLens live services in an isolated acceptance workspace.

This is a process harness, not a replacement launcher. It starts the existing
service entrypoints, waits on their real health endpoints, runs a small smoke
profile, and collects diagnostics on failure. No repository data or .env file
is used by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
PYTHON_SERVICE = ROOT / "python_service"
PYTHON_BIN = PYTHON_SERVICE / ".venv" / "bin" / "python"
CPP_BIN = BUILD / "forensic_analyzer"


class HarnessError(RuntimeError):
    """A diagnosable acceptance setup or runtime failure."""


class FakeLLMHandler(BaseHTTPRequestHandler):
    server_version = "TraceLensFakeLLM/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "healthy", "model": "tracelens-fake"})
            return
        if self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": "tracelens-fake"}]})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        state = self.server.fake_state  # type: ignore[attr-defined]
        if state["delay"]:
            time.sleep(state["delay"])
        if state["failure"]:
            self._send(state["failure_status"], {"error": "fake provider failure"})
            return
        evidence_ref = getattr(self.server, "evidence_key", None) or "file:fixture/notes.txt"
        prompt_text = "\n".join(
            str(message.get("content", ""))
            for message in request.get("messages", [])
            if isinstance(message, dict)
        )
        if state["invalid"]:
            content = "this is intentionally not valid structured output"
        elif "冻结 Report" in prompt_text or "最终报告" in prompt_text:
            report_evidence = getattr(self.server, "report_evidence_key", evidence_ref)
            report_analysis = getattr(self.server, "report_analysis_id", None)
            report_claim = getattr(self.server, "report_claim_id", None)
            original_evidence = getattr(self.server, "report_original_key", None)
            citations = [
                {
                    "citation_id": "citation-analysis",
                    "evidence_key": report_evidence,
                    "analysis_id": report_analysis,
                    "claim_id": report_claim,
                }
            ]
            citation_ids = ["citation-analysis"]
            if original_evidence:
                citations.append(
                    {
                        "citation_id": "citation-original",
                        "evidence_key": original_evidence,
                        "analysis_id": None,
                        "claim_id": None,
                    }
                )
                citation_ids.append("citation-original")
            content = json.dumps(
                {
                    "title": "Deterministic live acceptance report",
                    "sections": [
                        {
                            "heading": "Findings",
                            "content": "The accepted analysis and original evidence were preserved in the report envelope.",
                            "citation_ids": citation_ids,
                        }
                    ],
                    "citations": citations,
                },
                ensure_ascii=False,
            )
        elif "Event ID:" in prompt_text:
            content = json.dumps(
                {
                    "title": "Refreshed live acceptance event",
                    "summary": "The event narrative was refreshed from its frozen evidence input.",
                },
                ensure_ascii=False,
            )
        else:
            content = json.dumps(
                {
                    "description": "Deterministic fake analysis for live acceptance.",
                    "summary": "Fixture evidence is available for review.",
                    "claims": [
                        {
                            "claim_type": "FACT",
                            "claim_text": "The fixture contains a deterministic evidence record.",
                            "evidence_refs": [evidence_ref],
                        },
                        {
                            "claim_type": "INFERENCE",
                            "claim_text": "The record is suitable for an analyst workflow smoke test.",
                            "evidence_refs": [evidence_ref],
                        },
                        {
                            "claim_type": "HYPOTHESIS",
                            "claim_text": "A later event may correlate with this record.",
                            "evidence_refs": [evidence_ref],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        model = request.get("model") or "tracelens-fake"
        self._send(
            200,
            {
                "id": "chatcmpl-tracelens-fake",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


class FakeLLMServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, delay: float, failure: bool, invalid: bool) -> None:
        super().__init__(address, FakeLLMHandler)
        self.fake_state = {
            "delay": delay,
            "failure": failure,
            "invalid": invalid,
            "failure_status": 503,
        }
        self.evidence_key: str | None = None
        self.report_evidence_key: str | None = None
        self.report_original_key: str | None = None
        self.report_analysis_id: str | None = None
        self.report_claim_id: str | None = None


@dataclass
class ServiceProcess:
    name: str
    process: subprocess.Popen[str]
    log_path: Path
    url: str
    health_path: str


class LiveHarness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.workspace = Path(tempfile.mkdtemp(prefix="tracelens-acceptance-"))
        self.keep_workspace = args.keep_on_failure
        self.processes: list[ServiceProcess] = []
        self.fake_llm: FakeLLMServer | None = None
        self.fake_thread: threading.Thread | None = None
        self.ports: dict[str, int] = {}
        self.evidence_key: str | None = None
        self.evidence_keys: list[str] = []
        self.task_id: str | None = None
        self.analysis_id: str | None = None
        self.claim_id: str | None = None
        self.event_id: str | None = None
        self.refresh_id: str | None = None
        self.logs = self.workspace / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self._write_fixture_and_config()

    def _write_fixture_and_config(self) -> None:
        data = self.workspace / "data"
        (data / "tasks").mkdir(parents=True, exist_ok=True)
        (data / "audit").mkdir(parents=True, exist_ok=True)
        (data / "logs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "output").mkdir(parents=True, exist_ok=True)
        (self.workspace / "reports").mkdir(parents=True, exist_ok=True)
        fixture = self.workspace / "fixture"
        fixture.mkdir(parents=True, exist_ok=True)
        self.fixture_dir = fixture
        self.input_image: Path | None = None
        self.office_fixture: Path | None = None
        self.pe_fixture: Path | None = None
        (fixture / "notes.txt").write_text(
            "TraceLens deterministic acceptance fixture.\n", encoding="utf-8"
        )
        (fixture / "events.txt").write_text(
            "2026-08-19T00:00:00Z fixture event\n", encoding="utf-8"
        )
        if self.args.profile in {"task", "analyst", "restart", "matrix"}:
            self.input_image = self.workspace / "fixture.img"
            source_image = ROOT / "test_image.img"
            if source_image.is_file():
                shutil.copy2(source_image, self.input_image)
            else:
                raise HarnessError(
                    "ENVIRONMENT BLOCKED: reusable test_image.img is missing; "
                    "create it with scripts/create_test_image.sh before task acceptance"
                )
        if self.args.profile == "matrix":
            self.office_fixture = self.workspace / "fixture" / "acceptance.xlsx"
            create_xlsx_fixture(self.office_fixture)
            pe_source = ROOT / "tests" / "samples" / "pe" / "test_minimal.exe"
            if pe_source.is_file():
                self.pe_fixture = self.workspace / "fixture" / "test_minimal.exe"
                shutil.copy2(pe_source, self.pe_fixture)
        web_link = self.workspace / "web"
        web_dist = BUILD / "web"
        if not web_dist.exists():
            raise HarnessError(f"frontend distribution is missing: {web_dist}")
        web_link.symlink_to(web_dist, target_is_directory=True)

        self.ports = {
            "cpp": free_port(),
            "python": free_port(),
            "fake_llm": free_port(),
        }
        if self.args.with_distributed:
            self.ports["distributed"] = free_port()

        self.fake_llm = FakeLLMServer(
            ("127.0.0.1", self.ports["fake_llm"]),
            delay=self.args.llm_delay,
            failure=self.args.llm_failure,
            invalid=self.args.llm_invalid,
        )
        self.fake_thread = threading.Thread(target=self.fake_llm.serve_forever, daemon=True)
        self.fake_thread.start()

        env_lines = {
            "PROJECT_ROOT": str(self.workspace),
            "DATA_DIR": str(data),
            "HTTP_SERVER_PORT": str(self.ports["cpp"]),
            "PYTHON_HTTP_PORT": str(self.ports["python"]),
            "PYTHON_HTTP_HOST": "127.0.0.1",
            "CS_PORT": str(self.ports.get("distributed", 8091)),
            "PYTHON_SERVICE_URL": f"http://127.0.0.1:{self.ports['python']}",
            "CPP_BACKEND_URL": f"http://127.0.0.1:{self.ports['cpp']}",
            "DLL_CPP_BACKEND_URL": f"http://127.0.0.1:{self.ports['cpp']}",
            "DB_OUTPUT_DIR": str(self.workspace / "output"),
            "FORENSIC_REPORT_DIR": str(self.workspace / "reports"),
            "AUDIT_LOG_DB": str(data / "audit" / "forensics_audit.db"),
            "LLM_BASE_URL": f"http://127.0.0.1:{self.ports['fake_llm']}",
            "LLM_TEXT_BASE_URL": f"http://127.0.0.1:{self.ports['fake_llm']}",
            "LLM_VISION_BASE_URL": f"http://127.0.0.1:{self.ports['fake_llm']}",
            "LLM_ENDPOINT": "/v1/chat/completions",
            "LLM_TEXT_MODEL": "tracelens-fake",
            "LLM_VISION_MODEL": "tracelens-fake",
            "GRAPHITI_ENABLED": "false",
            "GRAPHITI_USE_LOCAL_LLM": "false",
            "NEO4J_URI": "neo4j://127.0.0.1:1",
            "REDIS_URL": "redis://127.0.0.1:1",
            "LOG_LEVEL": "INFO",
            "ENVIRONMENT": "test",
        }
        if self.args.with_distributed:
            if not self.args.distributed_database_url:
                raise HarnessError(
                    "distributed service requires --distributed-database-url "
                    "for an isolated PostgreSQL database; its schema uses JSONB"
                )
            env_lines["DATABASE_URL"] = self.args.distributed_database_url
            env_lines["PORT"] = str(self.ports["distributed"])
        (self.workspace / ".env").write_text(
            "\n".join(f"{key}={value}" for key, value in env_lines.items()) + "\n",
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        self.env.update(env_lines)
        self.env.update(
            {
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
                "PYTHONPATH": str(PYTHON_SERVICE),
            }
        )

    def start(self) -> None:
        if not CPP_BIN.is_file():
            raise HarnessError(f"C++ binary is missing: {CPP_BIN}")
        if not PYTHON_BIN.is_file():
            raise HarnessError(f"Python virtualenv is missing: {PYTHON_BIN}")
        self._start(
            "cpp",
            [str(CPP_BIN), "--http-server", str(self.ports["cpp"])],
            cwd=self.workspace,
            url=f"http://127.0.0.1:{self.ports['cpp']}",
            health_path="/api/system/health",
        )
        self.wait_ready(self.processes[-1])
        self._start(
            "python",
            [str(PYTHON_BIN), "-m", "httpserver.main"],
            cwd=self.workspace,
            url=f"http://127.0.0.1:{self.ports['python']}",
            health_path="/health",
        )
        self.wait_ready(self.processes[-1])
        if self.args.with_distributed:
            self._start(
                "distributed",
                [str(PYTHON_BIN), "-m", "server.main"],
                cwd=self.workspace,
                url=f"http://127.0.0.1:{self.ports['distributed']}",
                health_path="/health",
            )
            self.wait_ready(self.processes[-1])

    def _start(self, name: str, command: list[str], *, cwd: Path, url: str, health_path: str) -> None:
        log_path = self.logs / f"{name}.log"
        log_file = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=self.env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        log_file.close()
        self.processes.append(ServiceProcess(name, process, log_path, url, health_path))

    def wait_ready(self, service: ServiceProcess) -> None:
        deadline = time.monotonic() + self.args.timeout
        last_error = "no response"
        while time.monotonic() < deadline:
            if service.process.poll() is not None:
                raise HarnessError(self.diagnostic(service, f"exit code {service.process.returncode}"))
            try:
                status, payload = request_json(service.url + service.health_path, timeout=1.0)
                if status == 200:
                    print(f"ready {service.name}: HTTP {status}")
                    return
                last_error = f"HTTP {status}: {payload}"
            except (OSError, URLError, TimeoutError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.25)
        raise HarnessError(self.diagnostic(service, f"health timeout: {last_error}"))

    def smoke(self) -> None:
        checks = [("cpp", "/api/tasks"), ("python", "/health"), ("cpp", "/")]
        if self.args.with_distributed:
            checks.append(("distributed", "/health"))
        by_name = {service.name: service for service in self.processes}
        for name, path in checks:
            service = by_name[name]
            status, payload = request_json(service.url + path, timeout=self.args.timeout)
            if status < 200 or status >= 400:
                raise HarnessError(self.diagnostic(service, f"smoke {path} returned HTTP {status}: {payload}"))
            print(f"smoke {name}{path}: HTTP {status}")

        fake_status, fake_payload = request_json(
            f"http://127.0.0.1:{self.ports['fake_llm']}/v1/models",
            timeout=self.args.timeout,
        )
        if fake_status != 200 or not isinstance(fake_payload, dict):
            raise HarnessError(f"fake LLM model discovery failed: HTTP {fake_status}: {fake_payload}")
        fake_status, fake_payload = request_json(
            f"http://127.0.0.1:{self.ports['fake_llm']}/v1/chat/completions",
            timeout=self.args.timeout,
            method="POST",
            payload={"model": "tracelens-fake", "messages": [{"role": "user", "content": "smoke"}]},
        )
        if fake_status != 200 or not isinstance(fake_payload, dict):
            raise HarnessError(f"fake LLM completion failed: HTTP {fake_status}: {fake_payload}")
        print("smoke fake-llm: HTTP 200")

    def set_evidence_key(self, evidence_key: str) -> None:
        self.evidence_key = evidence_key
        if self.fake_llm is not None:
            self.fake_llm.evidence_key = evidence_key

    def task_journey(self) -> None:
        """Run Journey A through the live C++ and Python HTTP services."""
        by_name = {service.name: service for service in self.processes}
        cpp = by_name["cpp"]
        python = by_name["python"]
        create_status, created = request_json(
            cpp.url + "/api/tasks",
            timeout=self.args.timeout,
            method="POST",
            payload={
                "image_path": str(self.input_image),
                "scenarios": [],
                "llm_analyze": False,
                "priority": "normal",
            },
        )
        if create_status != 201 or not isinstance(created, dict) or not created.get("id"):
            raise HarnessError(self.diagnostic(cpp, f"task create returned HTTP {create_status}: {created}"))
        task_id = str(created["id"])
        self.task_id = task_id
        print(f"task created: {task_id}")

        deadline = time.monotonic() + self.args.task_timeout
        task = None
        while time.monotonic() < deadline:
            status, payload = request_json(
                cpp.url + f"/api/tasks/{task_id}", timeout=min(self.args.timeout, 10.0)
            )
            if status != 200 or not isinstance(payload, dict):
                raise HarnessError(self.diagnostic(cpp, f"task poll returned HTTP {status}: {payload}"))
            task = payload
            state = str(payload.get("status", "")).lower()
            if state in {"completed", "failed", "cancelled"}:
                break
            time.sleep(1.0)
        if not task or str(task.get("status", "")).lower() != "completed":
            raise HarnessError(self.diagnostic(cpp, f"task did not complete: {task}"))
        time.sleep(3.0)
        print("task completed")

        db_paths = {
            item.get("type"): Path(item.get("path", ""))
            for item in self._require_json(cpp, f"/api/tasks/{task_id}/databases").get("databases", [])
            if item.get("type") and item.get("path")
        }
        expected = {"raw", "events", "files"}
        if not expected.issubset(db_paths):
            raise HarnessError(f"task databases incomplete: {sorted(db_paths)}")
        before_hash = hashlib.sha256(db_paths["files"].read_bytes()).hexdigest()
        for db_type, db_path in db_paths.items():
            if not db_path.is_file() or not db_path.resolve().is_relative_to(self.workspace.resolve()):
                raise HarnessError(f"{db_type}.db is missing or outside isolated workspace: {db_path}")
            with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise HarnessError(f"{db_type}.db integrity_check={integrity!r}")
        print("task databases: raw/events/files present; integrity_check=ok")

        files_status, files_payload = request_json(
            cpp.url + "/api/forensics/files/largest?" + urlencode({"task_id": task_id, "limit": 20}),
            timeout=self.args.timeout,
        )
        if files_status != 200 or not isinstance(files_payload, dict):
            raise HarnessError(self.diagnostic(cpp, f"Files route returned HTTP {files_status}: {files_payload}"))
        timeline_status, timeline_payload = request_json(
            cpp.url + "/api/forensics/timeline/comprehensive?" + urlencode({"task_id": task_id}),
            timeout=self.args.timeout,
        )
        if timeline_status != 200 or not isinstance(timeline_payload, dict):
            raise HarnessError(self.diagnostic(cpp, f"Timeline route returned HTTP {timeline_status}: {timeline_payload}"))
        print("Files/Timeline live reads: HTTP 200")

        with sqlite3.connect(f"file:{db_paths['files'].resolve()}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT path FROM files WHERE path IS NOT NULL AND path != '' ORDER BY inode LIMIT 1").fetchone()
        if not row:
            raise HarnessError("files.db contains no parsed file suitable for Evidence identity")
        evidence_path = normalize_evidence_path(str(row[0]))
        evidence_key = f"file:{evidence_path}"
        self.evidence_key = evidence_key
        self.evidence_keys = [evidence_key]
        self.set_evidence_key(evidence_key)
        capture_payload = {"task_id": task_id, "evidence_key": evidence_key}
        first_status, first = request_json(
            python.url + "/api/investigation/snapshots",
            timeout=self.args.timeout,
            method="POST",
            payload=capture_payload,
        )
        second_status, second = request_json(
            python.url + "/api/investigation/snapshots",
            timeout=self.args.timeout,
            method="POST",
            payload=capture_payload,
        )
        if first_status != 200 or second_status != 200 or not isinstance(first, dict) or not isinstance(second, dict):
            raise HarnessError(f"snapshot capture failed: first={first_status}/{first}, second={second_status}/{second}")
        if first.get("evidence_key") != evidence_key or second.get("evidence_key") != evidence_key:
            raise HarnessError(f"snapshot identity mismatch: {first} / {second}")
        if first != second:
            raise HarnessError("repeated snapshot capture changed the immutable snapshot")
        after_hash = hashlib.sha256(db_paths["files"].read_bytes()).hexdigest()
        if before_hash != after_hash:
            raise HarnessError("files.db hash changed during the live Task -> Evidence journey")
        print(f"evidence snapshot: {evidence_key}")
        print("Evidence hash unchanged")

    def analyst_journey(self) -> None:
        """Run Journey B through secondary analysis, event, graph, and report APIs."""
        if not self.task_id or not self.evidence_key:
            raise HarnessError("F3 requires the completed F2 Task -> Evidence journey")
        by_name = {service.name: service for service in self.processes}
        python = by_name["python"]
        task_id = self.task_id
        evidence_key = self.evidence_key

        status, analysis = request_json(
            python.url + "/api/investigation/analyses",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "evidence_key": evidence_key, "analyst_note": "live acceptance", "case_context": "deterministic fixture"},
        )
        if status != 202 or not isinstance(analysis, dict) or not analysis.get("analysis_id"):
            raise HarnessError(f"secondary admission failed: HTTP {status}: {analysis}")
        analysis_id = str(analysis["analysis_id"])
        self.analysis_id = analysis_id
        analysis = self._poll_secondary(python, task_id, analysis_id)
        if analysis.get("status") != "review_pending":
            raise HarnessError(f"secondary did not reach review_pending: {analysis}")
        print(f"secondary review_pending: {analysis_id}")

        status, reviewed = request_json(
            python.url + f"/api/investigation/analyses/{analysis_id}/review",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "decision": "accepted", "reviewer": "live-analyst", "reason": "acceptance"},
        )
        if status != 200 or not isinstance(reviewed, dict) or reviewed.get("status") != "accepted":
            raise HarnessError(f"secondary review failed: HTTP {status}: {reviewed}")
        status, claims = request_json(
            python.url + f"/api/investigation/analyses/{analysis_id}/claims?task_id={task_id}",
            timeout=self.args.timeout,
        )
        if status != 200 or not isinstance(claims, dict) or not claims.get("claims"):
            raise HarnessError(f"analysis claims read failed: HTTP {status}: {claims}")
        claim_id = claims["claims"][0].get("claim_id")
        if not claim_id:
            raise HarnessError(f"analysis claim has no stable claim_id: {claims}")
        self.claim_id = str(claim_id)

        status, event = request_json(
            python.url + "/api/investigation/events",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "title": "Live acceptance event", "summary": "Initial event narrative", "created_by": "live-analyst"},
        )
        if status != 201 or not isinstance(event, dict) or not event.get("event_id"):
            raise HarnessError(f"event create failed: HTTP {status}: {event}")
        event_id = str(event["event_id"])
        self.event_id = event_id
        status, link = request_json(
            python.url + f"/api/investigation/events/{event_id}/evidence",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "evidence_key": evidence_key, "linked_by": "live-analyst"},
        )
        if status != 200 or not isinstance(link, dict) or link.get("evidence_key") != evidence_key:
            raise HarnessError(f"event evidence link failed: HTTP {status}: {link}")
        print(f"event linked: {event_id}")

        status, refresh = request_json(
            python.url + f"/api/investigation/events/{event_id}/refresh",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "requested_by": "live-analyst"},
        )
        if status != 201 or not isinstance(refresh, dict) or not refresh.get("refresh_id"):
            raise HarnessError(f"event refresh admission failed: HTTP {status}: {refresh}")
        refresh_id = str(refresh["refresh_id"])
        self.refresh_id = refresh_id
        refresh = self._poll_refresh(python, task_id, event_id, refresh_id)
        if refresh.get("status") != "completed" or not refresh.get("produced_version"):
            raise HarnessError(f"event refresh did not complete: {refresh}")
        print(f"event refresh completed: {refresh_id}")

        status, graph = request_json(
            python.url + "/api/investigation/graph?" + urlencode({"task_id": task_id}),
            timeout=self.args.timeout,
        )
        if status != 200 or not isinstance(graph, dict):
            raise HarnessError(f"graph failed: HTTP {status}: {graph}")
        node_ids = {node.get("id") for node in graph.get("nodes", [])}
        if f"evidence:{evidence_key}" not in node_ids or f"analysis:{analysis_id}" not in node_ids:
            raise HarnessError(f"graph missing accepted overlay nodes: {sorted(node_ids)}")
        print("graph overlay: evidence and accepted analysis present")

        report_status, report_evidence = request_json(
            python.url + "/api/reports/evidence",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "evidence_key": evidence_key, "report_status": "main", "analysis_id": analysis_id, "added_by": "live-analyst"},
        )
        if report_status != 200 or not isinstance(report_evidence, dict) or report_evidence.get("analysis_id") != analysis_id:
            raise HarnessError(f"report evidence binding failed: HTTP {report_status}: {report_evidence}")
        self._configure_report_fake(evidence_key, analysis_id, report_evidence)
        generation_status, generation = request_json(
            python.url + "/api/reports/generate",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "requested_by": "live-analyst"},
        )
        if generation_status != 202 or not isinstance(generation, dict) or not generation.get("generation_id"):
            raise HarnessError(f"report generation admission failed: HTTP {generation_status}: {generation}")
        generation_id = str(generation["generation_id"])
        generation = self._poll_generation(python, task_id, generation_id)
        if generation.get("status") != "completed" or not generation.get("report_id"):
            raise HarnessError(f"report generation did not complete: {generation}")
        manifest = generation.get("report") or {}
        citations = manifest.get("citations") or []
        if not citations or citations[0].get("evidence_key") != evidence_key or citations[0].get("analysis_id") != analysis_id:
            raise HarnessError(f"report citation traceback is not exact: {citations}")
        print(f"report completed: {generation_id} -> {generation['report_id']}")

    def matrix_journey(self) -> None:
        """Run the bounded real socket extractor handoff matrix."""
        python = next(service for service in self.processes if service.name == "python")
        cpp = next(service for service in self.processes if service.name == "cpp")
        if self.input_image is not None:
            status, task = request_json(
                cpp.url + "/api/tasks",
                timeout=self.args.timeout,
                method="POST",
                payload={"image_path": str(self.input_image), "scenarios": [], "llm_analyze": True, "llm_mode": "smart", "case_description": "live markitdown proxy"},
            )
            if status != 201 or not isinstance(task, dict) or not task.get("id"):
                raise HarnessError(f"C++ Markitdown proxy task admission failed: HTTP {status}: {task}")
            proxy_task_id = str(task["id"])
            deadline = time.monotonic() + self.args.task_timeout
            while time.monotonic() < deadline:
                status, current = request_json(cpp.url + f"/api/tasks/{proxy_task_id}", timeout=self.args.timeout)
                if status != 200 or not isinstance(current, dict):
                    raise HarnessError(f"C++ Markitdown proxy task poll failed: HTTP {status}: {current}")
                if current.get("status") in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(1.0)
            if current.get("status") != "completed":
                raise HarnessError(f"C++ Markitdown proxy task did not complete: {current}")
            print("C++ -> Python Markitdown proxy task: PASS")
        notes = self.fixture_dir / "notes.txt"
        status, payload = request_json(python.url + "/api/markitdown/status", timeout=self.args.timeout)
        if status != 200 or not isinstance(payload, dict):
            raise HarnessError(f"Markitdown status failed: HTTP {status}: {payload}")
        print(f"Markitdown status: HTTP 200 available={payload.get('available')}")
        status, converted = request_json(
            python.url + "/api/markitdown/convert",
            timeout=self.args.timeout,
            method="POST",
            payload={"workspace_root": str(self.workspace), "file_path": str(notes)},
        )
        if status != 200 or not isinstance(converted, dict) or not converted.get("success"):
            raise HarnessError(f"Markitdown live conversion failed: HTTP {status}: {converted}")
        print("Markitdown live conversion: PASS")

        status, supported = request_json(python.url + "/api/office/supported-types", timeout=self.args.timeout)
        if status != 200 or not isinstance(supported, dict) or not supported.get("supported_types"):
            raise HarnessError(f"Office supported-types failed: HTTP {status}: {supported}")
        status, office_result = request_json(
            python.url + "/api/office/parse",
            timeout=self.args.timeout,
            method="POST",
            payload={"workspace_root": str(self.workspace), "file_path": str(self.office_fixture)},
        )
        if status != 200 or not isinstance(office_result, dict) or not office_result.get("success"):
            raise HarnessError(f"Office live parse failed: HTTP {status}: {office_result}")
        print("Office live parse: PASS")

        if self.pe_fixture is None:
            print("DLL live handoff: NOT APPLICABLE (repository PE fixture missing)")
            return
        status, dll_result = request_json(
            cpp.url + "/api/forensics/dlls/analyze",
            timeout=max(self.args.timeout, 45.0),
            method="POST",
            payload={"file_path": str(self.pe_fixture)},
        )
        if status != 200 or not isinstance(dll_result, dict) or not dll_result.get("success"):
            raise HarnessError(f"C++ DLL analysis failed: HTTP {status}: {dll_result}")
        print("C++ DLL live analysis: PASS")
        status, py_dll_result = request_json(
            python.url + "/api/llm/analyze/dll",
            timeout=max(self.args.timeout, 45.0),
            method="POST",
            payload={"file_path": str(self.pe_fixture)},
        )
        if status != 200 or not isinstance(py_dll_result, dict) or not py_dll_result.get("success"):
            raise HarnessError(f"Python -> C++ DLL handoff failed: HTTP {status}: {py_dll_result}")
        print("DLL Python -> C++ live handoff: PASS")

    def restart_journey(self) -> None:
        """Exercise process-level stale-job recovery on the live Python service."""
        if not self.task_id or not self.evidence_key or not self.event_id:
            raise HarnessError("F5 requires the live analyst journey state")
        python = next(service for service in self.processes if service.name == "python")
        task_id = self.task_id
        evidence_key = self.evidence_key
        event_id = self.event_id

        status, analysis = request_json(
            python.url + "/api/investigation/analyses",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "evidence_key": evidence_key, "analyst_note": "restart acceptance"},
        )
        if status != 202 or not isinstance(analysis, dict):
            raise HarnessError(f"restart secondary admission failed: HTTP {status}: {analysis}")
        analysis_id = str(analysis["analysis_id"])
        self._wait_for_analysis_running(python, task_id, analysis_id)
        print(f"secondary running before restart: {analysis_id}")
        self._restart_python(python)
        python = self._start_python_again()
        failed_analysis = self._poll_secondary(python, task_id, analysis_id)
        if failed_analysis.get("status") != "failed" or failed_analysis.get("error_code") != "service_restart":
            raise HarnessError(f"secondary restart recovery mismatch: {failed_analysis}")
        print("secondary restart recovery: failed(service_restart), no replay")

        status, refresh = request_json(
            python.url + f"/api/investigation/events/{event_id}/refresh",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "requested_by": "restart-analyst"},
        )
        if status != 201 or not isinstance(refresh, dict):
            raise HarnessError(f"restart refresh admission failed: HTTP {status}: {refresh}")
        refresh_id = str(refresh["refresh_id"])
        self._wait_for_refresh_running(python, task_id, event_id, refresh_id)
        self._restart_python(python)
        python = self._start_python_again()
        failed_refresh = self._poll_refresh(python, task_id, event_id, refresh_id)
        if failed_refresh.get("status") != "failed" or failed_refresh.get("error_code") != "service_restart":
            raise HarnessError(f"refresh restart recovery mismatch: {failed_refresh}")
        print("refresh restart recovery: failed(service_restart), history preserved")

        report_status, report_evidence = request_json(
            python.url + "/api/reports/evidence",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "evidence_key": evidence_key, "report_status": "main", "added_by": "restart-analyst"},
        )
        if report_status not in {200, 409}:
            raise HarnessError(f"restart report evidence setup failed: HTTP {report_status}: {report_evidence}")
        generation_status, generation = request_json(
            python.url + "/api/reports/generate",
            timeout=self.args.timeout,
            method="POST",
            payload={"task_id": task_id, "requested_by": "restart-analyst"},
        )
        if generation_status != 202 or not isinstance(generation, dict):
            raise HarnessError(f"restart report admission failed: HTTP {generation_status}: {generation}")
        generation_id = str(generation["generation_id"])
        self._wait_for_generation_running(python, task_id, generation_id)
        self._restart_python(python)
        python = self._start_python_again()
        failed_generation = self._poll_generation(python, task_id, generation_id)
        if failed_generation.get("status") != "failed" or failed_generation.get("error_code") != "service_restart":
            raise HarnessError(f"report restart recovery mismatch: {failed_generation}")
        if failed_generation.get("report_id") is not None or failed_generation.get("report") is not None:
            raise HarnessError(f"report restart published partial output: {failed_generation}")
        print("report restart recovery: failed(service_restart), no publication")

    def _wait_for_generation_running(self, service: ServiceProcess, task_id: str, generation_id: str) -> None:
        deadline = time.monotonic() + self.args.task_timeout
        while time.monotonic() < deadline:
            status, payload = request_json(service.url + f"/api/reports/generations/{generation_id}?task_id={task_id}", timeout=self.args.timeout)
            if status == 200 and isinstance(payload, dict) and payload.get("status") == "running":
                return
            if status == 200 and isinstance(payload, dict) and payload.get("status") not in {"admitted", "running"}:
                raise HarnessError(f"generation did not enter running before restart: {payload}")
            time.sleep(0.2)
        raise HarnessError(f"generation did not enter running before restart: {generation_id}")

    def _wait_for_analysis_running(self, service: ServiceProcess, task_id: str, analysis_id: str) -> None:
        deadline = time.monotonic() + self.args.task_timeout
        while time.monotonic() < deadline:
            status, payload = request_json(service.url + f"/api/investigation/analyses/{analysis_id}?task_id={task_id}", timeout=self.args.timeout)
            if status == 200 and isinstance(payload, dict) and payload.get("status") == "running":
                return
            if status == 200 and isinstance(payload, dict) and payload.get("status") not in {"queued", "running"}:
                raise HarnessError(f"secondary did not enter running before restart: {payload}")
            time.sleep(0.2)
        raise HarnessError(f"secondary did not enter running before restart: {analysis_id}")

    def _wait_for_refresh_running(self, service: ServiceProcess, task_id: str, event_id: str, refresh_id: str) -> None:
        deadline = time.monotonic() + self.args.task_timeout
        while time.monotonic() < deadline:
            status, payload = request_json(service.url + f"/api/investigation/events/{event_id}/refreshes?task_id={task_id}", timeout=self.args.timeout)
            if status == 200 and isinstance(payload, list):
                match = next((row for row in payload if row.get("refresh_id") == refresh_id), None)
                if match and match.get("status") == "running":
                    return
                if match and match.get("status") not in {"queued", "running"}:
                    raise HarnessError(f"refresh did not enter running before restart: {match}")
            time.sleep(0.2)
        raise HarnessError(f"refresh did not enter running before restart: {refresh_id}")

    def _restart_python(self, service: ServiceProcess) -> None:
        if service.process.poll() is None:
            os.killpg(service.process.pid, signal.SIGKILL)
            try:
                service.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                service.process.kill()
                service.process.wait(timeout=3)
        self.processes = [current for current in self.processes if current.name != "python"]

    def _start_python_again(self) -> ServiceProcess:
        self._start(
            "python",
            [str(PYTHON_BIN), "-m", "httpserver.main"],
            cwd=self.workspace,
            url=f"http://127.0.0.1:{self.ports['python']}",
            health_path="/health",
        )
        service = self.processes[-1]
        self.wait_ready(service)
        return service

    def _poll_secondary(self, service: ServiceProcess, task_id: str, analysis_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.task_timeout
        while time.monotonic() < deadline:
            status, payload = request_json(service.url + f"/api/investigation/analyses/{analysis_id}?task_id={task_id}", timeout=self.args.timeout)
            if status != 200 or not isinstance(payload, dict):
                raise HarnessError(f"secondary poll failed: HTTP {status}: {payload}")
            if payload.get("status") not in {"queued", "running"}:
                return payload
            time.sleep(0.5)
        raise HarnessError(f"secondary poll timed out: {analysis_id}")

    def _poll_refresh(self, service: ServiceProcess, task_id: str, event_id: str, refresh_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.task_timeout
        while time.monotonic() < deadline:
            status, payload = request_json(service.url + f"/api/investigation/events/{event_id}/refreshes?task_id={task_id}", timeout=self.args.timeout)
            if status != 200 or not isinstance(payload, list):
                raise HarnessError(f"refresh poll failed: HTTP {status}: {payload}")
            match = next((row for row in payload if row.get("refresh_id") == refresh_id), None)
            if match and match.get("status") not in {"queued", "running"}:
                return match
            time.sleep(0.5)
        raise HarnessError(f"refresh poll timed out: {refresh_id}")

    def _poll_generation(self, service: ServiceProcess, task_id: str, generation_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.task_timeout
        while time.monotonic() < deadline:
            status, payload = request_json(service.url + f"/api/reports/generations/{generation_id}?task_id={task_id}", timeout=self.args.timeout)
            if status != 200 or not isinstance(payload, dict):
                raise HarnessError(f"generation poll failed: HTTP {status}: {payload}")
            if payload.get("status") not in {"admitted", "running"}:
                return payload
            time.sleep(0.5)
        raise HarnessError(f"generation poll timed out: {generation_id}")

    def _configure_report_fake(self, evidence_key: str, analysis_id: str, report_evidence: dict[str, Any]) -> None:
        if self.fake_llm is None:
            return
        self.fake_llm.report_evidence_key = evidence_key
        self.fake_llm.report_analysis_id = analysis_id
        self.fake_llm.report_claim_id = self.claim_id

    def _require_json(self, service: ServiceProcess, path: str) -> dict[str, Any]:
        status, payload = request_json(service.url + path, timeout=self.args.timeout)
        if status != 200 or not isinstance(payload, dict):
            raise HarnessError(self.diagnostic(service, f"{path} returned HTTP {status}: {payload}"))
        return payload

    def diagnostic(self, service: ServiceProcess, reason: str) -> str:
        lines = [
            f"service={service.name}",
            f"pid={service.process.pid}",
            f"exit_code={service.process.poll()}",
            f"health={service.url + service.health_path}",
            f"reason={reason}",
            f"log={service.log_path}",
            "last_logs:",
        ]
        try:
            lines.extend(service.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        except OSError as exc:
            lines.append(f"<unable to read log: {exc}>")
        return "\n".join(lines)

    def stop(self) -> None:
        for service in reversed(self.processes):
            if service.process.poll() is None:
                try:
                    os.killpg(service.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    service.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(service.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    service.process.wait(timeout=3)
        self.processes.clear()
        if self.fake_llm is not None:
            self.fake_llm.shutdown()
            self.fake_llm.server_close()
            self.fake_llm = None

    def close_workspace(self, failed: bool) -> None:
        if failed and self.keep_workspace:
            print(f"acceptance artifacts preserved at {self.workspace}", file=sys.stderr)
            return
        shutil.rmtree(self.workspace, ignore_errors=True)


def create_xlsx_fixture(path: Path) -> None:
    """Create a minimal valid XLSX without adding a document dependency."""
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>TraceLens acceptance</t></is></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def normalize_evidence_path(path: str) -> str:
    """Apply the frozen file Evidence identity normalization rules."""
    path = path.replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    timeout: float,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            return response.status, decode_payload(body)
    except HTTPError as exc:
        body = exc.read()
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = body.decode("utf-8", errors="replace")
        return exc.code, payload


def decode_payload(body: bytes) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:400]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "task", "analyst", "restart", "matrix"), default="smoke")
    parser.add_argument("--timeout", type=float, default=30.0, help="readiness timeout per service")
    parser.add_argument("--task-timeout", type=float, default=180.0, help="task completion timeout for --profile task")
    parser.add_argument("--keep-on-failure", action="store_true", help="preserve isolated workspace and logs after failure")
    parser.add_argument("--with-distributed", action="store_true", help="also launch the distributed/control service")
    parser.add_argument(
        "--distributed-database-url",
        default="",
        help="isolated PostgreSQL URL for --with-distributed; SQLite is not supported by its JSONB schema",
    )
    parser.add_argument("--llm-delay", type=float, default=0.0, help="fake LLM response delay in seconds")
    parser.add_argument("--llm-failure", action="store_true", help="make fake LLM calls return HTTP 503")
    parser.add_argument("--llm-invalid", action="store_true", help="make fake LLM calls return invalid structured output")
    parser.add_argument("--no-smoke", action="store_true", help="only start and readiness-check services")
    parser.add_argument("--serve", action="store_true", help="keep the isolated analyst workspace and services running for GUI validation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    harness: LiveHarness | None = None
    failed = False
    try:
        harness = LiveHarness(args)
        print(f"workspace: {harness.workspace}")
        print("topology: " + ", ".join(f"{name}=127.0.0.1:{port}" for name, port in harness.ports.items()))
        if args.profile in {"smoke", "task", "analyst", "restart", "matrix"}:
            harness.start()
            if not args.no_smoke:
                harness.smoke()
        if args.profile in {"task", "analyst", "restart"}:
            harness.task_journey()
        if args.profile == "analyst":
            harness.analyst_journey()
        if args.profile == "restart":
            harness.analyst_journey()
            harness.restart_journey()
        if args.profile == "matrix":
            harness.matrix_journey()
        if args.serve:
            runtime = {
                "workspace": str(harness.workspace),
                "cpp_url": next(service.url for service in harness.processes if service.name == "cpp"),
                "python_url": next(service.url for service in harness.processes if service.name == "python"),
                "task_id": harness.task_id,
                "evidence_key": harness.evidence_key,
                "analysis_id": harness.analysis_id,
                "event_id": harness.event_id,
            }
            (harness.workspace / "runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
            harness.keep_workspace = True
            print(json.dumps(runtime, indent=2))
            while True:
                time.sleep(1.0)
        print(f"LIVE HARNESS {args.profile.upper()} PASS")
        return 0
    except (HarnessError, OSError) as exc:
        failed = True
        print(f"LIVE HARNESS FAIL\n{exc}", file=sys.stderr)
        return 1
    finally:
        if harness is not None:
            harness.stop()
            harness.close_workspace(failed)


if __name__ == "__main__":
    raise SystemExit(main())
