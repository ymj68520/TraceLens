#!/usr/bin/env python3
"""Minimal Chrome CDP smoke harness for Phase E browser validation.

The harness is intentionally dependency-free. It serves the checked-in Vite
build behind a synthetic API, launches a local Chrome instance, and records
navigation/render observations for the product routes that were previously
blocked by the unavailable browser backend.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from isolated_target import IsolatedTarget, IsolationViolation, require_private_loopback_namespace
from field_frontend_build import _source_digest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "web" / "dist"
MOCK_6B_RESULT_SET = "a" * 64
MOCK_6B_KEY = f"android_artifact:v1:phase-e-small:{MOCK_6B_RESULT_SET}:sms:1"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def task_id_from_query(path: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    return (query.get("task_id") or query.get("taskId") or ["phase-e-small"])[0]


def synthetic_files(task_id: str, count: int) -> list[dict[str, Any]]:
    return [
        {
            "path": f"/synthetic/{task_id}/evidence-{index:05d}.txt",
            "name": f"evidence-{index:05d}.txt",
            "extension": ".txt",
            "size": 1024 + index,
            "llm_description": None,
        }
        for index in range(count)
    ]


def graph_payload(task_id: str, count: int) -> dict[str, Any]:
    nodes = [
        {
            "id": f"evidence:e-{index:05d}",
            "name": f"Evidence {index:05d}",
            "label": "Evidence",
            "source": "investigation",
            "confirmed": True,
            "provenance": {
                "evidence_key": f"file:/synthetic/{task_id}/e-{index:05d}.txt",
                "evidence_type": "file",
            },
        }
        for index in range(count)
    ]
    return {
        "task_id": task_id,
        "base_graph_available": False,
        "base_max_nodes": 200,
        "nodes": nodes,
        "links": [],
        "warnings": ["base_graph_unavailable"],
    }


def json_response(path: str) -> Any:
    task_id = task_id_from_query(path)
    size = 1000 if "large" in task_id else (100 if "medium" in task_id else 10)
    parsed = urllib.parse.urlsplit(path)
    route = parsed.path

    if route == "/api/investigation/workbench/phase-e-small":
        return {"task": {"id": "phase-e-small"}, "initialized": True,
                "event_count": 0, "analysis_count": 0, "report_evidence_count": 0,
                "evidence": [], "events": [], "analyses": [], "report_evidence": []}
    if route == "/api/investigation/workbench/phase-e-small/events":
        return {"success": True, "events": []}
    if route == "/api/investigation/workbench/phase-e-small/file-timeline":
        return {"success": True, "files": [], "total_count": 0,
                "axis": {"start": None, "end": None}, "citation_ids_by_path": {}}

    if route.endswith("/evidence/detail") and "/api/investigation/workbench/" in route:
        return {"success": True, "evidence": {
            "task_id": "phase-e-small", "evidence_key": MOCK_6B_KEY,
            "evidence_type": "android_artifact", "title": "Android sms #1",
            "snapshot": {"task_id": "phase-e-small", "evidence_key": MOCK_6B_KEY,
                "evidence_type": "android_artifact", "captured_at": 1700000000,
                "payload": {"result_set_id": MOCK_6B_RESULT_SET, "artifact_kind": "sms", "record_id": 1,
                    "record_hash": "b" * 64, "record_fields": {"id": 1, "body": "合成短信"},
                    "timestamp_unit": None, "timestamp_timezone": None,
                    "provenance": {"input_file": "candidate_only", "original_primary_key": None},
                    "coverage": {}, "warnings": ["候选文件不能证明原始行"]}},
            "analyses": [], "report_evidence": None}}
    if route.endswith("/evidence/analysis") and "/api/investigation/workbench/" in route:
        return {"success": True, "versions": []}
    if route == "/api/investigation/evidence/snapshot":
        return {"task_id": "phase-e-small", "evidence_key": MOCK_6B_KEY,
                "evidence_type": "android_artifact", "captured_at": 1700000000,
                "payload": {"evidence_type": "android_artifact", "artifact_kind": "sms",
                    "result_set_id": MOCK_6B_RESULT_SET, "record_id": 1,
                    "record_fields": {"id": 1, "body": "合成短信"},
                    "provenance": {"input_file": "candidate_only", "original_primary_key": None},
                    "warnings": ["候选来源，原始行未核实"]}}

    if route in {"/api/tasks", "/tasks"}:
        return {
            "tasks": [
                {
                    "id": "phase-e-small",
                    "name": "Phase E Small",
                    "status": "completed",
                    "progress": 100,
                },
                {
                    "id": "phase-e-large",
                    "name": "Phase E Large",
                    "status": "completed",
                    "progress": 100,
                },
                {
                    "id": "phase-e-medium",
                    "name": "Phase E Medium",
                    "status": "completed",
                    "progress": 100,
                },
            ],
            "pagination": {"total": 3, "limit": 20, "offset": 0},
        }
    if route.endswith("/files/largest"):
        return {"largest_files": synthetic_files(task_id, size)}
    if route.endswith("/files/paged"):
        query = urllib.parse.parse_qs(parsed.query)
        page = max(int((query.get("page") or ["1"])[0]), 1)
        page_size = max(int((query.get("page_size") or ["100"])[0]), 1)
        files = synthetic_files(task_id, size)
        start = (page - 1) * page_size
        return {
            "files": files[start : start + page_size],
            "page": page,
            "page_size": page_size,
            "total": size,
            "total_pages": max((size + page_size - 1) // page_size, 1),
            "view": (query.get("view") or ["all"])[0],
        }
    if route.endswith("/files/extensions-analysis"):
        return {
            "extension_analysis": [
                {"extension": "txt", "file_count": size, "total_size": size * 1024}
            ],
            "total_count": size,
        }
    if route == "/api/investigation/graph":
        return graph_payload(task_id, size)
    if route == "/api/investigation/evidence":
        return []
    if route == "/api/investigation/events":
        return []
    if route.startswith("/api/graphiti/status"):
        return {"status": "unavailable", "neo4j_connected": False}
    if route == "/api/graphiti/tasks":
        return {"task_ids": []}
    if route.startswith("/api/llm/status"):
        return {"status": "unavailable"}
    if route.startswith("/api/llm/models"):
        return {"models": []}
    if route.startswith("/api/reports"):
        if route == "/api/reports/narrative/versions/phase-e-r2":
            return {"task_id": "phase-e-small", "report_id": "phase-e-r2",
                    "version": 1, "status": "ready", "generation_id": "rg_mock",
                    "title": "合成 Android R2 报告", "created_at": "2026-09-27T00:00:00Z",
                    "model": "test-only-mock", "prompt_version": "final-report:v3",
                    "input_hash": "f" * 64,
                    "sections": [{"heading": "短信证据", "content": "冻结的合成短信支持此处的分析。",
                                  "citation_ids": ["c001"]}],
                    "citations": [{"citation_id": "c001", "evidence_key": MOCK_6B_KEY,
                                   "analysis_id": None, "claim_id": None,
                                   "evidence_captured_at": 1700000000,
                                   "analysis_version": None, "claim_type": None}]}
        if route == "/api/reports" and task_id == "phase-e-small":
            return [{"report_id": "phase-e-r2", "report_kind": "llm_generation",
                     "scope_type": "task", "scope_id": "phase-e-small",
                     "status": "ready", "version": 1}]
        if route.endswith("/status"):
            return {"status": "not_ready"}
        if route.endswith("/manifest"):
            return {"report_id": "phase-e-report", "versions": []}
        if route.endswith("/versions"):
            return []
        return {"items": [], "versions": [], "status": "not_ready"}
    if route == "/api/system/health":
        return {"status": "healthy"}
    if route.endswith("/android-coverage"):
        return {"success": True, "coverage": {"available": True,
            "warnings": [], "artifact_counts": {"sms_messages": 1}, "sources": []}}
    if "/android-artifacts/" in route:
        if route.rsplit("/", 1)[-1].isdigit():
            return {"success": True, "record": {"id": 1, "body": "合成短信"},
                    "source": None, "warning": "候选文件不能证明原始行",
                    "record_hash": "b" * 64, "source_revision": "c" * 64}
        return {"success": True, "total": 1, "page": 1, "page_size": 50,
                "records": [{"id": 1, "body": "合成短信", "address": "10086"}]}
    if route.startswith("/api/forensics"):
        return []
    return {}


class MockHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "TraceLensPhaseEBrowser/1.0"
    instance_id = ""

    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        self._directory = directory
        super().__init__(*args, directory=directory, **kwargs)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/__isolation__/identity":
            self._send_json({"instance_id": self.instance_id})
            return
        if self.path.startswith("/python/api/"):
            self._send_json(json_response(self.path.removeprefix("/python")))
            return
        if self.path.startswith("/api/") or self.path.startswith("/tasks"):
            self._send_json(json_response(self.path))
            return
        requested = Path(urllib.parse.urlsplit(self.path).path.lstrip("/"))
        if requested.suffix or requested.name == "favicon.ico":
            super().do_GET()
            return
        self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/python/api/field-auth/login":
            self._send_json({"access_token": "synthetic-browser-user-token", "token_type": "bearer",
                             "expires_in": 900, "principal": {"id": "synthetic-analyst", "role": "analyst"}})
            return
        if "/android-artifacts/" in self.path and self.path.endswith("/search"):
            self._send_json({"success": True, "total": 1, "page": 1, "page_size": 50,
                             "records": [{"id": 1, "body": "合成短信", "address": "10086"}]})
            return
        if self.path.endswith("/android-artifacts/sms/1/capture"):
            self._send_json({"success": True, "evidence_key": MOCK_6B_KEY,
                "snapshot": {"evidence_type": "android_artifact", "payload": {
                    "result_set_id": MOCK_6B_RESULT_SET, "artifact_kind": "sms", "record_id": 1}}})
            return
        if self.path.startswith("/api/"):
            self._send_json({"status": "accepted", "generation_id": "phase-e-generation"}, 202)
            return
        self._send_json({"detail": "not found"}, 404)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


class TrapHandler(http.server.BaseHTTPRequestHandler):
    received = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).received += 1
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        return


class WebSocket:
    """Small RFC6455 client sufficient for local Chrome DevTools Protocol."""

    def __init__(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=5)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {parsed.path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        response = self._read_http_headers()
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"Chrome CDP websocket handshake failed: {response[:120]!r}")
        self.sock.settimeout(10)

    def _read_http_headers(self) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def send(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        length = len(payload)
        first = 0x81
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv(self) -> bytes:
        header = self._read_exact(2)
        first, second = header
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        masked = bool(second & 0x80)
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if (first & 0x0F) == 0x8:
            raise RuntimeError("Chrome CDP websocket closed")
        return payload

    def _read_exact(self, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise RuntimeError("Chrome CDP websocket closed unexpectedly")
            data += chunk
        return data

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CdpPage:
    def __init__(self, websocket_url: str, target: IsolatedTarget) -> None:
        self.ws = WebSocket(websocket_url)
        self.command_id = 0
        self.target = target
        self.network_requests = 0
        self.blocked_requests = 0
        self.trap_origin: str | None = None
        self.trap_blocks = 0
        self.guard_installed = False

    def _intercept(self, message: dict) -> None:
        method = message.get("method")
        if method == "Fetch.requestPaused":
            request = message.get("params", {}).get("request", {})
            url = request.get("url", "")
            self.network_requests += 1
            allowed = self.target.permits(url)
            if not allowed:
                parsed = urllib.parse.urlsplit(url)
                if self.trap_origin and f"{parsed.scheme}://{parsed.netloc}" == self.trap_origin:
                    self.trap_blocks += 1
                else:
                    self.blocked_requests += 1
            self.command_id += 1
            self.ws.send({"id": self.command_id,
                          "method": "Fetch.continueRequest" if allowed else "Fetch.failRequest",
                          "params": {"requestId": message["params"]["requestId"],
                                     **({} if allowed else {"errorReason": "BlockedByClient"})}})
        elif method == "Network.webSocketCreated":
            # CDP Fetch cannot pause WebSocket handshakes. A private netns
            # blocks host services; any unexpected attempt still fails test.
            self.network_requests += 1
            if not self.target.permits(message.get("params", {}).get("url", "")):
                self.blocked_requests += 1

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.command_id += 1
        command_id = self.command_id
        self.ws.send({"id": command_id, "method": method, "params": params or {}})
        while True:
            message = json.loads(self.ws.recv().decode("utf-8"))
            if "method" in message:
                self._intercept(message)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})

    def evaluate(self, expression: str) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        remote = result.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(str(result["exceptionDetails"]))
        return remote.get("value")

    def navigate(self, url: str) -> None:
        self.command("Page.navigate", {"url": url})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                ready = self.evaluate("document.readyState")
                if ready == "complete":
                    return
            except (RuntimeError, socket.timeout):
                pass
            time.sleep(0.05)
        raise TimeoutError(f"page did not reach complete state: {url}")

    def close(self) -> None:
        self.ws.close()


def chrome_binary() -> str | None:
    candidates = [
        os.environ.get("CHROME_BIN"),
        "google-chrome",
        "chromium",
        "chromium-browser",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        found = next(
            (part for part in os.environ.get("PATH", "").split(os.pathsep) if Path(part, candidate).is_file()),
            None,
        )
        if found:
            return str(Path(found, candidate))
    return None


class NoControlRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise IsolationViolation("CDP control endpoint redirected")


def wait_for_json(url: str, *, allowed_origin: str, timeout: float = 10) -> Any:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or
            f"{parsed.scheme}://{parsed.netloc}" != allowed_origin):
        raise IsolationViolation("CDP control request left its selected instance")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoControlRedirect())
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError, ValueError) as error:
            last_error = error
            time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def collect_metrics(page: CdpPage) -> dict[str, Any]:
    expression = """
(() => {
  const resources = performance.getEntriesByType('resource');
  const transferBytes = resources.reduce((sum, entry) => sum + (entry.transferSize || 0), 0);
  const text = document.body?.innerText || '';
  const taskSelect = [...document.querySelectorAll('select')].find((select) =>
    [...select.options].some((option) => option.value.startsWith('phase-e-'))
  );
  return {
    url: location.href,
    dom_nodes: document.getElementsByTagName('*').length,
    transfer_bytes: transferBytes,
    resource_count: resources.length,
    first_meaningful_render_ms: performance.now(),
    js_heap_used_bytes: performance.memory?.usedJSHeapSize ?? null,
    task_marker: taskSelect?.value || null,
    error_boundary: text.includes('Something went wrong'),
    android_artifacts_visible: text.includes('AndroidAnalyzer 原生工件'),
    body_text_sample: text.slice(0, 160),
  };
})()
"""
    return page.evaluate(expression)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.mode != "ISOLATED_TEST":
        raise IsolationViolation("browser harness only supports ISOLATED_TEST; production smoke needs separate approval")
    netns = require_private_loopback_namespace()
    dist = Path(args.dist).resolve()
    if not (dist / "index.html").is_file():
        raise RuntimeError(f"frontend build not found: {dist / 'index.html'}")
    build_manifest_path = dist / "frontend_build_manifest.json"
    if not build_manifest_path.is_file() or build_manifest_path.is_symlink():
        raise IsolationViolation("frontend lacks an attested isolated field build manifest")
    build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    if (build_manifest.get("format") != "tracelens-field-frontend-candidate-v1"
            or build_manifest.get("field_auth") != "enabled"
            or build_manifest.get("routing") != {"cpp": "same_origin", "python": "/python", "cs": "/cs-disabled"}
            or build_manifest.get("source_tree_sha256") != _source_digest()):
        raise IsolationViolation("frontend build config or source identity differs from the attested candidate")
    actual_assets = {path.relative_to(dist).as_posix() for path in dist.rglob("*") if path.is_file()}
    if actual_assets != set(build_manifest.get("files", {})) | {"frontend_build_manifest.json"}:
        raise IsolationViolation("frontend contains unlisted or missing build assets")
    for name, expected_hash in build_manifest.get("files", {}).items():
        candidate = dist / name
        path = candidate.resolve()
        if candidate.is_symlink() or not path.is_relative_to(dist) or not path.is_file():
            raise IsolationViolation("frontend asset escaped its attested directory")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_hash:
            raise IsolationViolation("frontend asset hash differs from the attested candidate")
    chrome = chrome_binary()
    if not chrome:
        return {"status": "ENVIRONMENT BLOCKED", "reason": "Chrome/Chromium executable not found"}

    web_port = free_port()
    cdp_port = free_port()
    instance_id = secrets.token_hex(16)
    MockHandler.instance_id = instance_id
    target_policy = IsolatedTarget(instance_id, f"http://127.0.0.1:{web_port}")
    handler = lambda *handler_args, **handler_kwargs: MockHandler(
        *handler_args, directory=str(dist), **handler_kwargs
    )
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", web_port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    target_policy.verify_identity()
    trap_port = free_port()
    TrapHandler.received = 0
    trapd = socketserver.ThreadingTCPServer(("127.0.0.1", trap_port), TrapHandler)
    trapd.daemon_threads = True
    trap_thread = threading.Thread(target=trapd.serve_forever, daemon=True)
    trap_thread.start()

    profile = tempfile.TemporaryDirectory(
        prefix="tracelens-phase-e-chrome-",
        ignore_cleanup_errors=True,
    )
    chrome_process = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-component-update",
            "--no-first-run",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile.name}",
            f"--remote-debugging-port={cdp_port}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    page: CdpPage | None = None
    try:
        if os.readlink(f"/proc/{chrome_process.pid}/ns/net") != netns:
            raise IsolationViolation("Chrome did not inherit the private network namespace")
        control_origin = f"http://127.0.0.1:{cdp_port}"
        try:
            version = wait_for_json(f"http://127.0.0.1:{cdp_port}/json/version", allowed_origin=control_origin)
        except Exception as error:
            raise RuntimeError(f"CDP version discovery failed: {error}") from error
        try:
            targets = wait_for_json(f"http://127.0.0.1:{cdp_port}/json/list", allowed_origin=control_origin)
        except Exception as error:
            raise RuntimeError(f"CDP target discovery failed: {error}") from error
        target = next((item for item in targets if item.get("type") == "page"), None)
        if target is None:
            raise RuntimeError("Chrome exposed no page target")
        debug_url = urllib.parse.urlsplit(target["webSocketDebuggerUrl"])
        if debug_url.scheme != "ws" or debug_url.hostname != "127.0.0.1" or debug_url.port != cdp_port:
            raise IsolationViolation("Chrome page debugger target escaped its selected control port")
        try:
            page = CdpPage(target["webSocketDebuggerUrl"], target_policy)
            page.command("Page.enable")
            page.command("Runtime.enable")
            page.command("Network.enable")
            page.command("Network.setBypassServiceWorker", {"bypass": True})
            page.command("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
            page.guard_installed = True
        except Exception as error:
            raise RuntimeError(f"CDP websocket setup failed: {error}") from error
        results: dict[str, Any] = {"status": "PASS", "browser": chrome, "routes": {},
                                  "build_source_sha256": build_manifest["source_tree_sha256"],
                                  "build_publishable": build_manifest["publishable"]}
        validation_errors: list[str] = []

        def finalize_isolation() -> None:
            results["isolation"] = {
                "mode": "ISOLATED_TEST", "network_namespace": netns,
                "instance_id": instance_id, "allowed_origin": target_policy.origin,
                "guard_before_first_page": page.guard_installed,
                "service_worker_bypassed": True,
                "intercepted_requests": page.network_requests,
                "unexpected_blocked_requests": page.blocked_requests,
                "synthetic_trap_blocked": page.trap_blocks,
                "synthetic_trap_received": TrapHandler.received,
            }
            if (not page.guard_installed or page.blocked_requests
                    or page.trap_blocks != 1 or TrapHandler.received):
                validation_errors.append("isolation: an unexpected request was attempted or the pre-send guard failed")

        def exercise_synthetic_trap() -> None:
            if page.trap_blocks:
                return
            page.trap_origin = f"http://127.0.0.1:{trap_port}"
            page.evaluate(f"fetch('http://127.0.0.1:{trap_port}/synthetic-denied').then(() => 'sent').catch(() => 'blocked')")
            page.trap_origin = None

        def navigate_route(url: str) -> None:
            target_policy.require(url)
            if args.field_mode:
                route = url.removeprefix(target_policy.origin)
                page.evaluate("(() => { history.pushState({}, '', " + json.dumps(route) + "); window.dispatchEvent(new PopStateEvent('popstate')); })()")
            else:
                page.navigate(url)

        if args.field_mode:
            page.navigate(f"http://127.0.0.1:{web_port}/login")
            exercise_synthetic_trap()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not page.evaluate("Boolean(document.querySelector('input[type=password]'))"):
                time.sleep(0.05)
            page.evaluate("""(async () => {
              const fields = [...document.querySelectorAll('input')];
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              setter.call(fields.find(x => x.type === 'text'), 'synthetic-analyst');
              fields.find(x => x.type === 'text').dispatchEvent(new Event('input', {bubbles:true}));
              setter.call(fields.find(x => x.type === 'password'), 'synthetic-password');
              fields.find(x => x.type === 'password').dispatchEvent(new Event('input', {bubbles:true}));
              await new Promise(resolve => setTimeout(resolve, 50));
              document.querySelector('button[type=submit]').click();
              return true;
            })()""")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and page.evaluate("location.pathname") != "/dashboard":
                time.sleep(0.05)
            results["login_route"] = page.evaluate("location.pathname")
            if results["login_route"] != "/dashboard":
                validation_errors.append("field login did not reach dashboard")
                results["status"] = "FAIL"
                results["validation_errors"] = validation_errors
                finalize_isolation()
                results["cdp_version"] = version.get("Browser")
                return results

        routes = {
            "files": f"/files?task_id=phase-e-small",
            "investigation": f"/investigation?taskId=phase-e-medium",
            "knowledge_graph": f"/knowledge-graph?task_id=phase-e-medium",
            "case_intelligence": f"/case-intelligence?task_id=phase-e-large",
            "android": f"/android?task_id=phase-e-small",
        }
        for name, route in routes.items():
            expected_task = task_id_from_query(route)
            started = time.perf_counter()
            navigate_route(f"http://127.0.0.1:{web_port}{route}")
            render_deadline = time.monotonic() + 5
            while time.monotonic() < render_deadline:
                metrics = collect_metrics(page)
                if metrics.get("error_boundary") or (
                    metrics.get("dom_nodes", 0) > 10
                    and metrics.get("task_marker") == expected_task
                    and (name != "android" or metrics.get("android_artifacts_visible"))
                ):
                    break
                time.sleep(0.05)
            metrics["navigation_ms"] = round((time.perf_counter() - started) * 1000, 3)
            results["routes"][name] = metrics
            if metrics.get("error_boundary"):
                validation_errors.append(f"{name}: error boundary rendered")
            if metrics.get("task_marker") != expected_task:
                validation_errors.append(
                    f"{name}: expected task marker {expected_task}, got {metrics.get('task_marker')}"
                )
            if name == "android" and not metrics.get("android_artifacts_visible"):
                validation_errors.append("android: native artifacts card missing")
            if name == "files":
                exercise_synthetic_trap()

        if args.android_6b:
            # This browser probe uses only the same-origin synthetic handler.
            # It checks the user-visible selection and exact-key deep link;
            # real analysis/review/R2 persistence is exercised by isolated HTTP tests.
            row_deadline = time.monotonic() + 5
            while time.monotonic() < row_deadline and not page.evaluate(
                "document.body.innerText.includes('合成短信')"
            ):
                time.sleep(0.05)
            opened = page.evaluate("""(() => {
              const row = [...document.querySelectorAll('button')].find(b => b.textContent.includes('合成短信'));
              if (!row) return false;
              row.click(); return true;
            })()""")
            capture_deadline = time.monotonic() + 5
            while time.monotonic() < capture_deadline and not page.evaluate(
                "document.body.innerText.includes('将此单条记录加入调查研判')"
            ):
                time.sleep(0.05)
            captured = page.evaluate("""(() => {
              const button = [...document.querySelectorAll('button')].find(b => b.textContent.includes('将此单条记录加入调查研判'));
              if (!button) return false;
              button.click(); return true;
            })()""")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and page.evaluate("location.pathname") != "/investigation":
                time.sleep(0.05)
            # The same frozen key must reach the Investigation workbench, not
            # a dynamic Android list or a fabricated file: key.
            selected = page.evaluate("""(() => ({
              path: location.pathname,
              key: new URLSearchParams(location.search).get('evidence_key'),
              panel: document.body.innerText.includes('冻结记录与来源核对'),
              error_boundary: document.body.innerText.includes('Something went wrong'),
              body_tail: document.body.innerText.slice(-900),
            }))()""")
            panel_deadline = time.monotonic() + 5
            while time.monotonic() < panel_deadline and not selected["panel"] and not selected["error_boundary"]:
                time.sleep(0.05)
                selected = page.evaluate("""(() => ({
                  path: location.pathname,
                  key: new URLSearchParams(location.search).get('evidence_key'),
                  panel: document.body.innerText.includes('冻结记录与来源核对'),
                  error_boundary: document.body.innerText.includes('Something went wrong'),
                  body_tail: document.body.innerText.slice(-900),
                }))()""")
            results["android_6b"] = {"row_opened": opened, "capture_clicked": captured, **selected}
            if not opened or not captured or selected["key"] != MOCK_6B_KEY or not selected["panel"] or selected["error_boundary"]:
                validation_errors.append("android_6b: selected record did not reach frozen Investigation panel")
            citation_url = (f"http://127.0.0.1:{web_port}/investigation?task_id=phase-e-small"
                            f"&evidence_key={urllib.parse.quote(MOCK_6B_KEY, safe='')}"
                            "&report_id=phase-e-r2&citation_id=c001")
            navigate_route(citation_url)
            citation_deadline = time.monotonic() + 5
            citation_view = None
            while time.monotonic() < citation_deadline:
                citation_view = page.evaluate("""(() => ({
                  key: new URLSearchParams(location.search).get('evidence_key'),
                  report_id: new URLSearchParams(location.search).get('report_id'),
                  citation_id: new URLSearchParams(location.search).get('citation_id'),
                  panel: document.body.innerText.includes('冻结记录与来源核对'),
                  result_set: document.body.innerText.includes('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
                  error_boundary: document.body.innerText.includes('Something went wrong'),
                }))()""")
                if citation_view["panel"] or citation_view["error_boundary"]:
                    break
                time.sleep(0.05)
            results["android_6b_citation_deep_link"] = citation_view
            if (citation_view["key"] != MOCK_6B_KEY or citation_view["report_id"] != "phase-e-r2"
                    or citation_view["citation_id"] != "c001" or not citation_view["panel"]
                    or not citation_view["result_set"] or citation_view["error_boundary"]):
                validation_errors.append("android_6b: citation deep link did not reopen exact frozen result")
            navigate_route(f"http://127.0.0.1:{web_port}/case-intelligence?task_id=phase-e-small&tab=forensic&report_id=phase-e-r2")
            report_deadline = time.monotonic() + 5
            while time.monotonic() < report_deadline and not page.evaluate(
                "Boolean(document.querySelector('[data-testid=\"citation-chip-c001\"]'))"
            ):
                time.sleep(0.05)
            opened_citation = page.evaluate("""(() => {
              const marker = document.querySelector('[data-testid="citation-chip-c001"]');
              if (!marker) return false;
              const details = marker.closest('details'); if (details) details.open = true;
              marker.click(); return true;
            })()""")
            panel_deadline = time.monotonic() + 5
            link_href = None
            while time.monotonic() < panel_deadline:
                link_href = page.evaluate("document.querySelector('[data-testid=\"evidence-key-link\"]')?.getAttribute('href') || null")
                if link_href:
                    break
                time.sleep(0.05)
            link_expected = (f"/investigation?task_id=phase-e-small"
                             f"&evidence_key={urllib.parse.quote(MOCK_6B_KEY, safe='')}"
                             "&report_id=phase-e-r2&citation_id=c001")
            results["android_6b_report_click"] = {
                "citation_opened": opened_citation,
                "link_href": link_href,
                "exact_frozen_link": link_href == link_expected,
            }
            if not opened_citation or link_href != link_expected:
                validation_errors.append("android_6b: report citation did not expose the exact frozen link")
            else:
                if args.field_mode:
                    page.evaluate("document.querySelector('[data-testid=\"evidence-key-link\"]').click()")
                else:
                    navigate_route(f"http://127.0.0.1:{web_port}{link_href}")
                follow_deadline = time.monotonic() + 5
                while time.monotonic() < follow_deadline and not page.evaluate(
                    "document.body.innerText.includes('冻结记录与来源核对')"
                ):
                    time.sleep(0.05)
                results["android_6b_report_click"]["followed_to_frozen_panel"] = page.evaluate(
                    "document.body.innerText.includes('冻结记录与来源核对') && !document.body.innerText.includes('Something went wrong')"
                )
                if not results["android_6b_report_click"]["followed_to_frozen_panel"]:
                    validation_errors.append("android_6b: report citation link did not reopen frozen panel")

        navigate_route(f"http://127.0.0.1:{web_port}/files?task_id=phase-e-small")
        navigate_route(f"http://127.0.0.1:{web_port}/files?task_id=phase-e-large")
        switch_deadline = time.monotonic() + 5
        while True:
            switch = collect_metrics(page)
            if switch.get("error_boundary") or switch.get("task_marker") == "phase-e-large":
                break
            if time.monotonic() >= switch_deadline:
                break
            time.sleep(0.05)
        switch["stale_small_marker_absent"] = switch.get("task_marker") != "phase-e-small"
        results["task_switch"] = switch
        if switch.get("error_boundary"):
            validation_errors.append("task_switch: error boundary rendered")
        if switch.get("task_marker") != "phase-e-large":
            validation_errors.append(
                f"task_switch: expected task marker phase-e-large, got {switch.get('task_marker')}"
            )
        finalize_isolation()
        if validation_errors:
            results["status"] = "FAIL"
            results["validation_errors"] = validation_errors
        results["cdp_version"] = version.get("Browser")
        return results
    finally:
        if page:
            page.close()
        chrome_process.terminate()
        try:
            chrome_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_process.kill()
        profile.cleanup()
        httpd.shutdown()
        httpd.server_close()
        trapd.shutdown()
        trapd.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Phase E Chrome browser smoke harness")
    parser.add_argument("--dist", default=str(DEFAULT_DIST), help="Vite output directory")
    parser.add_argument("--mode", required=True, choices=("ISOLATED_TEST", "PRODUCTION_SMOKE"),
                        help="ISOLATED_TEST requires a private network namespace; production smoke is not implemented without approval")
    parser.add_argument("--output", help="Write JSON results to this path")
    parser.add_argument("--field-mode", action="store_true", help="exercise synthetic field login and same-origin Android page")
    parser.add_argument("--android-6b", action="store_true", help="exercise synthetic single-row capture and frozen workbench deep link")
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as error:  # pragma: no cover - environment dependent
        import traceback
        traceback.print_exc(file=sys.stderr)
        result = {"status": "ENVIRONMENT BLOCKED", "reason": f"{type(error).__name__}: {error}"}
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
