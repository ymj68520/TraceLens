"""Isolated live C++/Python field-auth smoke; only generated Task/report data."""

import argparse
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from passlib.context import CryptContext

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "python_service/.venv/bin/python"
sys.path.insert(0, str(ROOT / "python_service"))
sys.path.insert(0, str(ROOT / "tests/integration"))
sys.path.insert(0, str(ROOT / "scripts"))
from httpserver.services.android_field_package import build_package, verify_package
from android_field_check import check as check_field_runtime
from test_android_container_cli_e2e import build_tree
from isolated_target import IsolationViolation, require_private_loopback_namespace

_ALLOWED_TEST_ORIGINS: set[str] = set()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise IsolationViolation("isolated test response redirected outside its instance")


def _require_target(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.username or parsed.password or
            f"{parsed.scheme}://{parsed.netloc}" not in _ALLOWED_TEST_ORIGINS):
        raise IsolationViolation("HTTP target is not one of the selected synthetic instances")


def _verify_child_instance(pid: int, instance_id: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if os.readlink(f"/proc/{pid}/ns/net") != os.readlink("/proc/self/ns/net"):
            raise IsolationViolation("test service escaped the isolated network namespace")
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        if f"TRACELENS_TEST_INSTANCE_ID={instance_id}".encode() in entries:
            return
        time.sleep(0.02)
    raise IsolationViolation("test service does not carry the selected instance identity")


def port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(base, path, *, method="GET", token="", service="", data=None):
    _require_target(base + path)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if service:
        headers["X-TraceLens-Service-Token"] = service
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=10) as response:
            content = response.read(2 * 1024 * 1024)
            return response.status, json.loads(content) if "json" in response.headers.get("Content-Type", "") else content
    except urllib.error.HTTPError as exc:
        return exc.code, None


def stream_status(base, path, token):
    _require_target(base + path)
    req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=3) as response:
            return response.status, response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def wait_alive(base, process=None, unit=None):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise AssertionError("isolated field service exited before readiness")
        if unit is not None:
            state = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState", "--value"],
                                   capture_output=True, text=True, timeout=3, check=False).stdout.strip()
            if state in {"failed", "inactive", "deactivating"}:
                raise AssertionError("isolated field systemd unit exited before readiness")
        try:
            code, body = request(base, "/health/live")
            if code == 200 and body == {"status": "alive"}:
                return
        except OSError:
            pass
        time.sleep(0.2)
    raise AssertionError("isolated field service did not become ready")


def synthetic_report(root: Path):
    report = root / "report-source"
    page_dir = report / "report" / "synthetic-phone" / "report" / "content"
    page_dir.mkdir(parents=True)
    (report / "index.html").write_text("<html><body>Synthetic only</body></html>", encoding="utf-8")
    with sqlite3.connect(report / "report" / "synthetic-phone" / "export.db") as db:
        db.execute("CREATE TABLE archiveInfo(softName TEXT, softVersion TEXT)")
        db.execute("INSERT INTO archiveInfo VALUES ('Synthetic Exporter', '1.0')")
    (page_dir / "content1.html").write_text(
        '<h3>短信</h3><table><tr><th>时间</th><th>内容</th></tr>'
        '<tr><td>2026-07-17 10:15:50</td><td>FIELD_SYNTHETIC_MESSAGE</td></tr></table>',
        encoding="utf-8")
    return report


def run(binary: Path, *, systemd: bool = False, release_root: Path | None = None,
        release_id: str | None = None):
    require_private_loopback_namespace()
    if systemd:
        raise IsolationViolation("systemd-run leaves this private test namespace; use the separate OS policy probe")
    if release_root is not None and not release_id:
        raise IsolationViolation("release drill requires a baked release ID")
    runtime_root = release_root.resolve() if release_root is not None else ROOT
    python_exe = (runtime_root / "python_service/.venv/bin/python") if release_root is not None else PYTHON
    if not python_exe.is_file():
        raise IsolationViolation("release Python runtime is unavailable")
    with tempfile.TemporaryDirectory(prefix="tracelens-field-auth-e2e-") as temporary:
        root = Path(temporary)
        runtime = root / "runtime"
        runtime.mkdir()
        python_cwd = root / "app"
        python_cwd.mkdir()
        synthetic_logs = runtime / "logs"
        synthetic_logs.mkdir(parents=True)
        (synthetic_logs / "python_service.log").write_text("SYNTHETIC_LOG_ONLY\n", encoding="utf-8")
        (synthetic_logs / "cpp_server.log").write_text("SYNTHETIC_LOG_ONLY\n", encoding="utf-8")
        user_file = root / "users.json"
        user_file.write_text(json.dumps({"users": {
            "analyst": {"password_hash": CryptContext(schemes=["bcrypt"]).hash("synthetic-password-123"),
                        "role": "analyst", "active": True, "token_version": 1},
            "admin": {"password_hash": CryptContext(schemes=["bcrypt"]).hash("synthetic-admin-123"),
                      "role": "admin", "active": True, "token_version": 1},
        }}), encoding="utf-8")
        user_file.chmod(0o600)
        synthetic_report(root)
        report_db_before = None
        if release_root is not None:
            from httpserver.services.forensic_report.repository import ReportRepository
            import hashlib
            report_dir = root / "report-output"
            report_dir.mkdir()
            ReportRepository(report_dir / "reports.db")  # synthetic old state before startup
            report_db_before = hashlib.sha256((report_dir / "reports.db").read_bytes()).hexdigest()
        logical = root / "logical"
        logical.mkdir()
        build_tree(logical)
        cpp_port, python_port = port(), port()
        while python_port == cpp_port:
            python_port = port()
        cpp_base = f"http://127.0.0.1:{cpp_port}"
        python_base = f"http://127.0.0.1:{python_port}"
        _ALLOWED_TEST_ORIGINS.clear()
        _ALLOWED_TEST_ORIGINS.update({cpp_base, python_base})
        instance_id = secrets.token_hex(16)
        secret, c2p, p2c = (secrets.token_urlsafe(48) for _ in range(3))
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "NVM_DIR"}}
        env.update({"TRACELENS_FIELD_AUTH": "enabled", "TRACELENS_REQUIRE_FIELD_AUTH": "1",
                    "FIELD_OUTBOUND_POLICY": "disabled",
                    "FIELD_AUTH_URL": python_base, "FIELD_USER_FILE": str(user_file),
                    "FIELD_JWT_SECRET": secret, "FIELD_CPP_TO_PYTHON_TOKEN": c2p,
                    "FIELD_PYTHON_TO_CPP_TOKEN": p2c,
                    "HTTP_SERVER_HOST": "127.0.0.1", "PYTHON_HTTP_HOST": "127.0.0.1",
                    "PYTHON_HTTP_PORT": str(python_port), "CPP_BACKEND_URL": cpp_base,
                    "PYTHON_SERVICE_URL": python_base, "DATA_DIR": str(runtime),
                    "FORENSIC_REPORT_DIR": str(root / "report-output"),
                    "TRACELENS_EVIDENCE_INBOX": str(root), "ANDROID_REPORT_SEARCH_ROOT": str(root),
                    "TRACELENS_LOG_ROOT": str(synthetic_logs),
                    "TRACELENS_TEST_INSTANCE_ID": instance_id,
                    "LLM_ENABLED": "false", "GRAPHITI_ENABLED": "false",
                    "LLM_BASE_URL": "", "LLM_TEXT_BASE_URL": "", "LLM_VISION_BASE_URL": "",
                    "EMBEDDING_BASE_URL": "", "OSS_ENDPOINT": ""})
        if release_root is not None:
            env.update({"TRACELENS_REQUIRE_RELEASE_LAYOUT": "1",
                        "TRACELENS_RELEASE_ID": release_id,
                        "TRACELENS_RELEASE_ROOT": str(runtime_root),
                        "TRACELENS_PYTHON_BIN": str(python_exe),
                        "TRACELENS_QNXPROBE_ROOT": str(runtime_root / ".deps/qnxprobe")})
        unit_cpp = unit_python = None
        with (root / "cpp.log").open("w") as cpp_log, (root / "python.log").open("w") as py_log:
            if systemd:
                field_file = root / "field-runtime.env"
                keys = ("TRACELENS_FIELD_AUTH", "TRACELENS_REQUIRE_FIELD_AUTH", "FIELD_OUTBOUND_POLICY",
                    "FIELD_AUTH_URL", "FIELD_USER_FILE", "FIELD_JWT_SECRET", "FIELD_CPP_TO_PYTHON_TOKEN",
                    "FIELD_PYTHON_TO_CPP_TOKEN", "HTTP_SERVER_HOST", "PYTHON_HTTP_HOST", "PYTHON_HTTP_PORT",
                    "CPP_BACKEND_URL", "PYTHON_SERVICE_URL", "DATA_DIR", "FORENSIC_REPORT_DIR",
                    "TRACELENS_EVIDENCE_INBOX", "ANDROID_REPORT_SEARCH_ROOT", "LLM_ENABLED",
                    "GRAPHITI_ENABLED", "LLM_BASE_URL", "LLM_TEXT_BASE_URL", "LLM_VISION_BASE_URL",
                    "EMBEDDING_BASE_URL", "OSS_ENDPOINT")
                field_file.write_text("\n".join(f"{key}={env[key]}" for key in keys) +
                                      f"\nPYTHONPATH={ROOT / 'python_service'}\n", encoding="utf-8")
                field_file.chmod(0o600)
                suffix = uuid.uuid4().hex[:8]
                unit_cpp = f"tracelens-field-test-cpp-{suffix}.service"
                unit_python = f"tracelens-field-test-python-{suffix}.service"
                common = ["systemd-run", "--property=IPAddressDeny=any",
                          "--property=IPAddressAllow=localhost",
                          f"--property=EnvironmentFile={field_file}"]
                subprocess.run([*common, f"--working-directory={ROOT}", f"--unit={unit_cpp}",
                                str(binary), "--http-server", str(cpp_port)],
                               check=True, capture_output=True, text=True, timeout=10)
                cpp = None
            else:
                cpp = subprocess.Popen([str(binary), "--http-server", str(cpp_port)],
                                       env=env, cwd=runtime_root / "build" if release_root is not None else ROOT,
                                       stdout=cpp_log, stderr=subprocess.STDOUT)
            py = None
            try:
                if cpp is not None:
                    _verify_child_instance(cpp.pid, instance_id)
                wait_alive(cpp_base, cpp, unit_cpp)
                if systemd:
                    subprocess.run([*common, f"--working-directory={python_cwd}",
                                    f"--unit={unit_python}", str(PYTHON), "-m", "httpserver.main"],
                                   check=True, capture_output=True, text=True, timeout=10)
                else:
                    py = subprocess.Popen([str(python_exe), "-m", "httpserver.main"],
                                          env={**env, "PYTHONPATH": str(runtime_root / "python_service")},
                                          cwd=runtime_root / "python_service" if release_root is not None else python_cwd,
                                          stdout=py_log, stderr=subprocess.STDOUT)
                    _verify_child_instance(py.pid, instance_id)
                wait_alive(python_base, py, unit_python)
                _require_target(cpp_base + "/login")
                with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
                    cpp_base + "/login", timeout=3) as static_page:
                    assert static_page.status == 200
                    assert "connect-src 'self'" in static_page.headers.get("Content-Security-Policy", "")
                assert request(cpp_base, "/api/tasks")[0] == 401
                assert request(cpp_base, "/api/unknown")[0] == 401
                assert request(cpp_base, "/api/forensics/files/paged")[0] == 401
                assert request(cpp_base, "/api/search/fulltext")[0] == 401
                assert request(cpp_base, "/api/tasks", method="POST")[0] == 401
                assert request(cpp_base, "/api/tasks/no-task/cancel", method="POST")[0] == 401
                assert request(cpp_base, "/api/tasks/no-task", method="DELETE")[0] == 401
                assert request(python_base, "/api/android-report/imports")[0] == 401
                assert request(python_base, "/api/system/logs/python")[0] == 401
                assert request(python_base, "/api/system/logs-stream/python")[0] == 401
                assert request(python_base, "/api/evidence-intake/candidates")[0] == 401
                assert request(python_base, "/api/investigation/events")[0] == 401
                assert request(python_base, "/api/reports")[0] == 401
                assert request(python_base, "/api/evidence-intake/tasks/no-task/android-artifacts/sms/1")[0] == 401
                assert request(cpp_base, "/api/security/status", token="invalid")[0] == 401
                assert request(python_base, "/api/field-auth/status", token="invalid")[0] == 401
                login_code, logged_in = request(python_base, "/api/field-auth/login", method="POST",
                    data={"username": "analyst", "password": "synthetic-password-123"})
                assert login_code == 200 and logged_in["token_type"] == "bearer"
                token = logged_in["access_token"]
                cpp_status = request(cpp_base, "/api/security/status", token=token)[1]
                python_status = request(python_base, "/api/field-auth/status", token=token)[1]
                assert cpp_status["field_auth"] is True and python_status["field_auth"] is True
                if release_root is not None:
                    assert cpp_status["release_id"] == python_status["release_id"] == release_id
                assert request(cpp_base, "/api/tasks", token=token)[0] == 200
                assert request(python_base, "/api/android-report/imports", token=token)[0] == 200
                if release_root is not None:
                    status, old_reports = request(python_base, "/api/reports?scope_type=task&scope_id=synthetic-old",
                                                  token=token)
                    assert status == 200 and old_reports == []
                    assert request(python_base, "/api/reports", method="POST", token=token,
                                   data={"scope_type": "task", "scope_id": "synthetic-old"})[0] == 503
                    assert request(python_base, "/api/reports/generate", method="POST", token=token,
                                   data={"task_id": "synthetic-old", "requested_by": "synthetic-analyst"})[0] == 503
                    assert hashlib.sha256((root / "report-output/reports.db").read_bytes()).hexdigest() == report_db_before
                stream_code, stream_type = stream_status(python_base, "/api/system/logs-stream/python", token)
                assert stream_code == 200 and "text/event-stream" in stream_type, (stream_code, stream_type)
                assert request(cpp_base, "/api/tasks/nonexistent", method="DELETE", token=token)[0] == 403
                assert request(cpp_base, "/api/forensics/export/events/json", token=token)[0] == 403
                assert request(python_base, "/api/reports/evidence", method="POST", token=token)[0] == 403
                assert request(python_base, "/api/graphiti/ingest", method="POST", token=token)[0] == 503
                assert request(cpp_base, "/api/tasks", method="POST", token=token,
                    data={"image_path": str(logical), "scenarios": ["server_cloud"]})[0] == 400
                assert request(cpp_base, "/api/security/status", service=p2c)[0] == 200
                assert request(cpp_base, "/api/tasks/nonexistent", method="DELETE", service=p2c)[0] == 403
                assert request(cpp_base, "/api/security/status", service=c2p)[0] == 401
                assert request(python_base, "/api/field-auth/introspect", method="POST", service=c2p,
                    data={"authorization": "Bearer " + token, "method": "GET", "path": "/api/tasks"})[0] == 200
                for selected in (cpp_port, python_port):
                    with socket.socket(socket.AF_INET6) as probe:
                        probe.settimeout(1)
                        assert probe.connect_ex(("::1", selected)) != 0  # IPv6 is not listening in this profile
                status, candidates = request(python_base, "/api/android-report/candidates", token=token)
                assert status == 200
                candidate = next(item for item in candidates["candidates"] if item["name"] == "report-source")
                status, imported = request(python_base, "/api/android-report/imports", method="POST", token=token,
                                            data={"candidate_id": candidate["id"]})
                assert status == 201
                import_id = imported["import"]["import_id"]
                status, records = request(python_base, f"/api/android-report/imports/{import_id}/records", token=token)
                assert status == 200 and records["records"]
                record_id = records["records"][0]["id"]
                assert request(python_base, f"/api/android-report/imports/{import_id}/records/{record_id}", token=token)[0] == 200
                assert request(python_base, f"/api/android-report/imports/{import_id}/source-location/{record_id}", token=token)[0] == 200
                status, created = request(cpp_base, "/api/tasks", method="POST", token=token,
                    data={"image_path": str(logical), "android_source": "dir",
                          "scenarios": ["android"], "platform_analyze": True})
                assert status == 201 and created.get("id")
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    _, task = request(cpp_base, f"/api/tasks/{created['id']}", token=token)
                    if str(task.get("status", "")).lower() in {"completed", "failed", "cancelled"}:
                        break
                    time.sleep(0.2)
                else:
                    raise AssertionError("isolated synthetic Task timed out")
                assert str(task["status"]).lower() == "completed"
                assert task.get("llm_analyze") is False
                assert task.get("metadata", {}).get("field_outbound_policy") == "disabled"
                assert task.get("metadata", {}).get("requested_by") == "analyst"
                result_db = Path(task["output_files_db"])
                with sqlite3.connect(result_db) as db:
                    counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                              for table in ("sms_messages", "contacts", "installed_packages", "wifi_networks")}
                assert counts == {"sms_messages": 2, "contacts": 1, "installed_packages": 1, "wifi_networks": 1}
                package_path = root / "synthetic-delivery"
                build_package(output=package_path, task=task)
                assert verify_package(package_path)["valid"] is True
                check_file = root / "field-check.env"
                check_file.write_text("\n".join((
                    "TRACELENS_FIELD_AUTH=enabled", "TRACELENS_REQUIRE_FIELD_AUTH=1",
                    "FIELD_OUTBOUND_POLICY=disabled",
                    "HTTP_SERVER_HOST=127.0.0.1", "PYTHON_HTTP_HOST=127.0.0.1",
                    f"FIELD_JWT_SECRET={secret}", f"FIELD_CPP_TO_PYTHON_TOKEN={c2p}",
                    f"FIELD_PYTHON_TO_CPP_TOKEN={p2c}",
                    *( ("TRACELENS_REQUIRE_RELEASE_LAYOUT=1",
                        f"TRACELENS_RELEASE_ID={release_id}",
                        f"TRACELENS_RELEASE_ROOT={runtime_root}",
                        f"TRACELENS_PYTHON_BIN={python_exe}",
                        f"TRACELENS_LOG_ROOT={synthetic_logs}",
                        f"DATA_DIR={runtime}") if release_root is not None else () ),
                )) + "\n", encoding="utf-8")
                check_file.chmod(0o600)
                checked = check_field_runtime(check_file, cpp_url=cpp_base, python_url=python_base,
                                              username="analyst", password="synthetic-password-123", isolated=True)
                assert checked["security_baseline_status"] == (
                    "PASS_SECURITY_BASELINE" if systemd else "BLOCKED"), {
                        "status": checked["security_baseline_status"],
                        "blockers": checked["blockers"],
                        "egress": [item for item in checked["findings"] if "os_egress" in item or "controlled_os_egress_probe" in item],
                    }
                assert any(item.get("field_security_version") == "6a-v1" for item in checked["findings"])
                if release_root is not None:
                    import hashlib
                    candidate_manifest = root / "candidate-release-manifest.json"
                    frontend_manifest = json.loads((runtime_root / "build/web/dist/frontend_build_manifest.json").read_text())
                    candidate_manifest.write_text(json.dumps({
                        "release_id": release_id,
                        "cpp_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                        "frontend_index_sha256": frontend_manifest["files"]["index.html"],
                        "publishable": False,
                    }), encoding="utf-8")
                    identity_check = check_field_runtime(
                        check_file, cpp_url=cpp_base, python_url=python_base,
                        username="analyst", password="synthetic-password-123", isolated=True,
                        release_manifest=candidate_manifest)
                    assert any(item.get("loaded_cpp_binary_matches_release") is True
                               for item in identity_check["findings"])
                    assert any(item.get("frontend_index_matches_release") is True
                               for item in identity_check["findings"])
                    assert all(item.get("working_directory_matches_release") is True
                               for item in identity_check["findings"]
                               if "working_directory_matches_release" in item)
                    assert {item.get("release_id") for item in identity_check["findings"]
                            if item.get("loaded_service") in {"cpp", "python"} and
                            "release_id" in item} == {release_id}
                    assert identity_check["security_baseline_status"] == "BLOCKED"  # dirty drill, not publishable
                if systemd:
                    subprocess.run(["systemctl", "stop", unit_python], capture_output=True,
                                   timeout=10, check=True)
                else:
                    py.terminate()
                    py.wait(timeout=10)
                assert request(cpp_base, "/api/security/status", token=token)[0] == 503
                return {"anonymous_cpp": 401, "anonymous_python": 401, "user_read": 200,
                        "loaded_release_id": release_id if release_root is not None else None,
                        "analyst_delete": 403, "analyst_review": 403, "analyst_export": 403,
                        "internal_cpp": 200, "internal_python": 200,
                        "html_report_records": records["total"], "synthetic_task_artifacts": counts,
                        "package_valid": True, "outbound_policy": "disabled",
                        "isolated_code_loaded": True, "ipv6_direct": "NOT_LISTENING",
                        "os_egress_process_scope": "VERIFIED_UNIT" if systemd else "ISOLATED_NETNS_ONLY",
                        "auth_service_unavailable": 503}
            finally:
                for process in (py, cpp):
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                for unit in (unit_python, unit_cpp):
                    if unit:
                        subprocess.run(["systemctl", "stop", unit], capture_output=True,
                                       timeout=10, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("ISOLATED_TEST", "PRODUCTION_SMOKE"))
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--release-id")
    parser.add_argument("--systemd", action="store_true", help="start synthetic services in isolated transient systemd units")
    args = parser.parse_args()
    if args.mode != "ISOLATED_TEST":
        parser.error("production smoke is not implemented without explicit approval")
    result = run(args.binary.resolve(strict=True), systemd=args.systemd,
                 release_root=args.release_root, release_id=args.release_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
