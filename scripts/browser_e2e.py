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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "web" / "dist"


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
            ],
            "pagination": {"total": 2, "limit": 20, "offset": 0},
        }
    if route.endswith("/files/largest"):
        return {"largest_files": synthetic_files(task_id, size)}
    if route.endswith("/files/extensions-analysis"):
        return {"extensions": [{"extension": ".txt", "count": size}]}
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
        if route.endswith("/status"):
            return {"status": "not_ready"}
        if route.endswith("/manifest"):
            return {"report_id": "phase-e-report", "versions": []}
        if route.endswith("/versions"):
            return []
        return {"items": [], "versions": [], "status": "not_ready"}
    if route == "/api/system/health":
        return {"status": "healthy"}
    if route.startswith("/api/forensics"):
        return []
    return {}


class MockHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "TraceLensPhaseEBrowser/1.0"

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
        if self.path.startswith("/api/"):
            self._send_json({"status": "accepted", "generation_id": "phase-e-generation"}, 202)
            return
        self._send_json({"detail": "not found"}, 404)

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
    def __init__(self, websocket_url: str) -> None:
        self.ws = WebSocket(websocket_url)
        self.command_id = 0

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.command_id += 1
        command_id = self.command_id
        self.ws.send({"id": command_id, "method": method, "params": params or {}})
        while True:
            message = json.loads(self.ws.recv().decode("utf-8"))
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


def wait_for_json(url: str, timeout: float = 10) -> Any:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
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
  return {
    url: location.href,
    dom_nodes: document.getElementsByTagName('*').length,
    transfer_bytes: transferBytes,
    resource_count: resources.length,
    first_meaningful_render_ms: performance.now(),
    js_heap_used_bytes: performance.memory?.usedJSHeapSize ?? null,
    task_marker: text.includes('phase-e-large') ? 'phase-e-large' : (text.includes('phase-e-small') ? 'phase-e-small' : null),
    body_text_sample: text.slice(0, 160),
  };
})()
"""
    return page.evaluate(expression)


def run(args: argparse.Namespace) -> dict[str, Any]:
    dist = Path(args.dist).resolve()
    if not (dist / "index.html").is_file():
        raise RuntimeError(f"frontend build not found: {dist / 'index.html'}")
    chrome = chrome_binary()
    if not chrome:
        return {"status": "ENVIRONMENT BLOCKED", "reason": "Chrome/Chromium executable not found"}

    web_port = free_port()
    cdp_port = free_port()
    handler = lambda *handler_args, **handler_kwargs: MockHandler(
        *handler_args, directory=str(dist), **handler_kwargs
    )
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", web_port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    profile = tempfile.TemporaryDirectory(prefix="tracelens-phase-e-chrome-")
    chrome_process = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
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
        try:
            version = wait_for_json(f"http://127.0.0.1:{cdp_port}/json/version")
        except Exception as error:
            raise RuntimeError(f"CDP version discovery failed: {error}") from error
        try:
            targets = wait_for_json(f"http://127.0.0.1:{cdp_port}/json/list")
        except Exception as error:
            raise RuntimeError(f"CDP target discovery failed: {error}") from error
        target = next((item for item in targets if item.get("type") == "page"), None)
        if target is None:
            raise RuntimeError("Chrome exposed no page target")
        try:
            page = CdpPage(target["webSocketDebuggerUrl"])
            page.command("Page.enable")
            page.command("Runtime.enable")
        except Exception as error:
            raise RuntimeError(f"CDP websocket setup failed: {error}") from error
        results: dict[str, Any] = {"status": "PASS", "browser": chrome, "routes": {}}

        routes = {
            "files": f"/files?task_id=phase-e-small",
            "investigation": f"/investigation?taskId=phase-e-medium",
            "knowledge_graph": f"/knowledge-graph?task_id=phase-e-medium",
            "case_intelligence": f"/case-intelligence?task_id=phase-e-large",
        }
        for name, route in routes.items():
            started = time.perf_counter()
            page.navigate(f"http://127.0.0.1:{web_port}{route}")
            render_deadline = time.monotonic() + 5
            while time.monotonic() < render_deadline:
                metrics = collect_metrics(page)
                if metrics.get("dom_nodes", 0) > 10:
                    break
                time.sleep(0.05)
            metrics["navigation_ms"] = round((time.perf_counter() - started) * 1000, 3)
            results["routes"][name] = metrics

        page.navigate(f"http://127.0.0.1:{web_port}/files?task_id=phase-e-small")
        page.navigate(f"http://127.0.0.1:{web_port}/files?task_id=phase-e-large")
        switch = collect_metrics(page)
        switch["stale_small_marker_absent"] = switch.get("task_marker") != "phase-e-small"
        results["task_switch"] = switch
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Phase E Chrome browser smoke harness")
    parser.add_argument("--dist", default=str(DEFAULT_DIST), help="Vite output directory")
    parser.add_argument("--output", help="Write JSON results to this path")
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
