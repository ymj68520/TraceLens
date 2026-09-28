#!/usr/bin/env python3
"""Read-only pre-admission check. Never prints credentials or response bodies."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_service"))
sys.path.insert(0, str(ROOT / "scripts"))
from httpserver.services.field_security import AUDIENCE, ISSUER, ALGORITHM, FIELD_SECURITY_VERSION
from field_os_egress_check import verify as verify_os_egress

MODEL_URL_KEYS = ("LLM_BASE_URL", "LLM_TEXT_BASE_URL", "LLM_VISION_BASE_URL",
                  "EMBEDDING_BASE_URL", "OSS_ENDPOINT")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def read_config(path: Path) -> dict[str, str]:
    # An explicitly selected deployment file describes the target units;
    # shell variables from the *checker* process must not override it.
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
                values[key] = value.strip().strip("\"'")
    for key, value in os.environ.items():
        if key not in values and key in (
            *MODEL_URL_KEYS, "TRACELENS_OFFLINE_MODE", "GRAPHITI_USE_LOCAL_LLM",
            "HTTP_SERVER_HOST", "PYTHON_HTTP_HOST", "CS_HOST",
            "TRACELENS_FIELD_AUTH", "TRACELENS_REQUIRE_FIELD_AUTH",
            "FIELD_OUTBOUND_POLICY", "FIELD_JWT_SECRET",
            "FIELD_CPP_TO_PYTHON_TOKEN", "FIELD_PYTHON_TO_CPP_TOKEN",
            "TRACELENS_REQUIRE_RELEASE_LAYOUT", "TRACELENS_RELEASE_ROOT",
            "TRACELENS_RELEASE_ID", "TRACELENS_PYTHON_BIN",
            "TRACELENS_LOG_ROOT", "DATA_DIR", "FIELD_BROWSER_ORIGIN",
        ):
            values[key] = value
    return values


def _host(value: str) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value if "://" in value else "https://" + value)
    return parsed.hostname


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _loopback_base(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    try:
        local = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    return parsed.scheme == "http" and local and bool(parsed.port) and not (
        parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password)


def _status(url: str) -> int | None:
    return _request(url)[0]


def _bounded_http_sha256(url: str) -> tuple[int | None, str | None]:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(urllib.request.Request(url, method="GET"), timeout=3) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
            if response.status != 200 or len(payload) > 2 * 1024 * 1024:
                return response.status, None
            return response.status, hashlib.sha256(payload).hexdigest()
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def _request(url: str, *, method: str = "GET", headers: dict | None = None,
             payload: dict | None = None, read_json: bool = False) -> tuple[int | None, dict | None]:
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method,
            headers={"User-Agent": "TraceLens-field-check", "Content-Type": "application/json", **(headers or {})})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=3) as response:
            return response.status, json.load(response) if read_json and response.status == 200 else None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None, None


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _listeners(ports: set[int]) -> list[dict]:
    ss = subprocess.run(["ss", "-H", "-ltnp"], capture_output=True, text=True, timeout=4, check=False)
    result = []
    for line in ss.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        address = parts[3]
        if address.rsplit(":", 1)[-1] not in {str(port) for port in ports}:
            continue
        pid = re.search(r"pid=(\d+)", line)
        executable = None
        if pid:
            try:
                executable = _sha256(Path(os.readlink(f"/proc/{pid.group(1)}/exe")))
            except OSError:
                pass
        result.append({"address": address, "pid": int(pid.group(1)) if pid else None,
                       "executable_sha256": executable})
    return result


def _isolated_address(address: str) -> bool:
    host = address.rsplit(":", 1)[0].strip("[]")
    return _is_loopback(host)


def _cwd_matches(pid: int | None, expected: Path) -> bool:
    if not pid:
        return False
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd")).resolve() == expected
    except OSError:
        return False


def _systemd_egress(listener: dict) -> dict:
    pid = listener.get("pid")
    if not pid:
        return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED"}
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
        unit = next((part for part in re.findall(r"[\w@.-]+\.service", cgroup)
                     if part.startswith("tracelens-field-")), None)
        if not unit:
            return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED"}
        command = subprocess.run(["systemctl", "show", unit, "-p", "IPAddressDeny", "-p", "IPAddressAllow"],
                                 capture_output=True, text=True, timeout=3, check=False)
        properties = dict(line.split("=", 1) for line in command.stdout.splitlines() if "=" in line)
        denied = set(properties.get("IPAddressDeny", "").split())
        allowed = set(properties.get("IPAddressAllow", "").split())
        try:
            only_loopback = bool(allowed) and all(
                ipaddress.ip_network(value).subnet_of(ipaddress.ip_network("127.0.0.0/8")
                                                       if ":" not in value else ipaddress.ip_network("::1/128"))
                for value in allowed)
        except ValueError:
            only_loopback = False
        if command.returncode == 0 and {"0.0.0.0/0", "::/0"} <= denied and only_loopback:
            return {"status": "POLICY_APPLIED_TO_RUNNING_UNIT", "unit": unit}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED"}


def check(env_path: Path, *, live: bool = True, cpp_url: str = "http://127.0.0.1:8666",
          python_url: str = "http://127.0.0.1:8090", username: str = "", password: str = "",
          isolated: bool = False, release_manifest: Path | None = None) -> dict:
    if not _loopback_base(cpp_url) or not _loopback_base(python_url):
        raise ValueError("security checker only probes explicit numeric loopback services")
    config = read_config(env_path)
    blockers = []
    findings = []
    release = None
    if release_manifest is not None:
        if release_manifest.is_symlink() or not release_manifest.is_file():
            raise ValueError("release manifest must be an explicit regular file")
        release = json.loads(release_manifest.read_text(encoding="utf-8"))
        if not release.get("publishable"):
            blockers.append("release candidate is not frozen/publishable")
        if not release.get("release_id") or not release.get("cpp_binary_sha256"):
            blockers.append("release manifest lacks baked identity or C++ binary digest")
    configured_auth = config.get("TRACELENS_FIELD_AUTH") == "enabled"
    configured_outbound = config.get("FIELD_OUTBOUND_POLICY", "disabled")
    for key in MODEL_URL_KEYS:
        host = _host(config.get(key, ""))
        if host and not _is_loopback(host) and not (configured_auth and configured_outbound == "disabled"):
            blockers.append(f"{key} targets non-loopback host {host}; no verified outbound allowlist")
    if configured_outbound == "local_only" and config.get("GRAPHITI_USE_LOCAL_LLM", "true").lower() not in {"true", "1", "yes"}:
        blockers.append("Graphiti local-LLM setting is disabled")
    if configured_outbound == "local_only":
        blockers.append("LOCAL_MODEL_SERVICE_EGRESS_UNVERIFIED: model endpoint may itself proxy to the internet")
    if not configured_auth:
        blockers.append("field authentication is not configured")
    elif config.get("TRACELENS_REQUIRE_FIELD_AUTH") != "1":
        blockers.append("field authentication is not marked required by deployment")
    if config.get("TRACELENS_REQUIRE_RELEASE_LAYOUT") == "1":
        release_id = config.get("TRACELENS_RELEASE_ID", "")
        release_root = Path(config.get("TRACELENS_RELEASE_ROOT", ""))
        python_bin = Path(config.get("TRACELENS_PYTHON_BIN", ""))
        log_root = Path(config.get("TRACELENS_LOG_ROOT", ""))
        data_root = Path(config.get("DATA_DIR", ""))
        if not release_id or release_id == "UNFROZEN_WORKTREE" or "REPLACE" in release_id:
            blockers.append("field release ID is not fixed")
        if not release_root.is_absolute() or not release_root.is_dir() or "REPLACE" in str(release_root):
            blockers.append("versioned release directory is not installed")
        if not python_bin.is_absolute() or not python_bin.is_file() or "REPLACE" in str(python_bin):
            blockers.append("versioned Python runtime is not installed")
        if (not data_root.is_absolute() or not log_root.is_absolute() or
                not log_root.resolve(strict=False).is_relative_to(data_root.resolve(strict=False))):
            blockers.append("field log root is outside the explicit data directory")
        if release is not None and release_id != release.get("release_id"):
            blockers.append("deployed release ID differs from selected manifest")
    for key in ("HTTP_SERVER_HOST", "PYTHON_HTTP_HOST", "CS_HOST"):
        host = config.get(key, "")
        if host and host not in {"127.0.0.1", "::1", "localhost"}:
            blockers.append(f"{key} is configured for non-loopback access")
    runtime_loaded = False
    if live:
        ports = {urllib.parse.urlsplit(cpp_url).port, urllib.parse.urlsplit(python_url).port}
        if not isolated:
            ports.add(8091)
        listeners = _listeners(ports)
        findings.append({"listeners": listeners})
        if release and config.get("TRACELENS_REQUIRE_RELEASE_LAYOUT") == "1":
            root = Path(config.get("TRACELENS_RELEASE_ROOT", "")).resolve(strict=False)
            for name, base, expected_cwd in (
                ("cpp", cpp_url, root / "build"),
                ("python", python_url, root / "python_service"),
            ):
                selected_port = str(urllib.parse.urlsplit(base).port)
                owners = [item for item in listeners if item["address"].rsplit(":", 1)[-1] == selected_port]
                loaded_from_release = bool(owners) and all(
                    _cwd_matches(item.get("pid"), expected_cwd)
                    for item in owners
                ) if expected_cwd.is_dir() else False
                findings.append({"loaded_service": name, "working_directory_matches_release": loaded_from_release})
                if not loaded_from_release:
                    blockers.append(f"{name} process working directory differs from release layout")
            expected_index = release.get("frontend_index_sha256")
            if not expected_index:
                blockers.append("release manifest lacks frontend index digest")
            else:
                code, digest = _bounded_http_sha256(cpp_url + "/index.html")
                findings.append({"frontend_index_status": code,
                                 "frontend_index_matches_release": digest == expected_index})
                if code != 200 or digest != expected_index:
                    blockers.append("running frontend index differs from release manifest")
        if release and release.get("cpp_binary_sha256"):
            cpp_port = str(urllib.parse.urlsplit(cpp_url).port)
            matches = [item.get("executable_sha256") == release["cpp_binary_sha256"]
                       for item in listeners if item["address"].rsplit(":", 1)[-1] == cpp_port]
            findings.append({"loaded_cpp_binary_matches_release": bool(matches) and all(matches)})
            if not matches or not all(matches):
                blockers.append("running C++ executable hash differs from release manifest")
        for item in listeners:
            if not _isolated_address(item["address"]):
                blockers.append(f"listener {item['address']} is not loopback")
            if not isolated and item["address"].endswith(":8091"):
                blockers.append("8091 is still running in the single-host field profile")
            if ((item["address"].startswith("[::") or item["address"].startswith(":::"))
                    and item["address"].rsplit(":", 1)[-1] in
                    {str(urllib.parse.urlsplit(cpp_url).port), str(urllib.parse.urlsplit(python_url).port)}):
                port = item["address"].rsplit(":", 1)[-1]
                route = "/api/tasks" if port == str(urllib.parse.urlsplit(cpp_url).port) else "/api/android-report/imports"
                status = _status(f"http://[::1]:{port}{route}")
                findings.append({"ipv6_unauthenticated_port": port, "status": status})
                if status != 401:
                    blockers.append(f"IPv6 backend on port {port} did not reject anonymous request")
        for label, url in (("cpp_tasks", cpp_url + "/api/tasks"),
                           ("python_report_imports", python_url + "/api/android-report/imports"),
                           ("python_files", python_url + "/api/db/"),
                           ("cpp_unknown", cpp_url + "/api/unknown-field-route")):
            status = _status(url)
            findings.append({"unauthenticated_probe": label, "status": status, "body_read": False})
            if status == 200:
                blockers.append(f"{label} permits unauthenticated access")
            elif status != 401:
                blockers.append(f"{label} did not return 401 for anonymous request")
        for name, base in (("cpp", cpp_url), ("python", python_url)):
            invalid = _request(base + ("/api/security/status" if name == "cpp" else "/api/field-auth/status"),
                               headers={"Authorization": "Bearer invalid"})[0]
            forged = _request(base + ("/api/security/status" if name == "cpp" else "/api/field-auth/status"),
                              headers={"X-User": "admin", "X-Forwarded-User": "admin"})[0]
            findings.extend([{"invalid_token": name, "status": invalid},
                             {"forged_identity": name, "status": forged}])
            if invalid != 401 or forged != 401:
                blockers.append(f"{name} rejects neither invalid token nor forged identity reliably")
        if username and password:
            login_status, logged_in = _request(python_url + "/api/field-auth/login", method="POST",
                                                payload={"username": username, "password": password}, read_json=True)
            findings.append({"login_status": login_status})
            token = logged_in.get("access_token") if isinstance(logged_in, dict) else None
            if token:
                results = []
                for name, base, route in (("cpp", cpp_url, "/api/security/status"),
                                          ("python", python_url, "/api/field-auth/status")):
                    code, body = _request(base + route, headers={"Authorization": "Bearer " + token}, read_json=True)
                    results.append(code == 200 and isinstance(body, dict) and
                                   body.get("field_security_version") == FIELD_SECURITY_VERSION and
                                   body.get("field_auth") is True and
                                   body.get("required_auth") is True and
                                   body.get("outbound_policy") == configured_outbound)
                    findings.append({"loaded_service": name, "status": code,
                                     "field_security_version": body.get("field_security_version") if isinstance(body, dict) else None,
                                     "release_id": body.get("release_id") if isinstance(body, dict) else None,
                                     "outbound_policy": body.get("outbound_policy") if isinstance(body, dict) else None})
                    if release and isinstance(body, dict) and body.get("release_id") != release.get("release_id"):
                        blockers.append(f"{name} process loaded a different release ID")
                runtime_loaded = all(results)
                now = int(time.time())
                secret = config.get("FIELD_JWT_SECRET", "")
                if secret:
                    expired = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": username,
                        "iat": now - 120, "nbf": now - 120, "exp": now - 1,
                        "jti": "field-check-expired", "ver": 0}, secret, algorithm=ALGORITHM)
                    for name, base, route in (("cpp", cpp_url, "/api/security/status"),
                                              ("python", python_url, "/api/field-auth/status")):
                        code = _request(base + route, headers={"Authorization": "Bearer " + expired})[0]
                        findings.append({"expired_token": name, "status": code})
                        if code != 401:
                            blockers.append(f"{name} did not reject expired token")
                c2p = config.get("FIELD_CPP_TO_PYTHON_TOKEN", "")
                p2c = config.get("FIELD_PYTHON_TO_CPP_TOKEN", "")
                if c2p and p2c:
                    cpp_internal = _request(cpp_url + "/api/security/status",
                        headers={"X-TraceLens-Service-Token": p2c})[0]
                    py_internal = _request(python_url + "/api/field-auth/introspect", method="POST",
                        headers={"X-TraceLens-Service-Token": c2p},
                        payload={"authorization": "Bearer " + token, "method": "GET", "path": "/api/tasks"})[0]
                    findings.append({"internal_cpp_status": cpp_internal, "internal_python_status": py_internal})
                    if cpp_internal != 200 or py_internal != 200:
                        blockers.append("service-to-service authentication failed")
                    wrong_cpp = _request(cpp_url + "/api/security/status",
                        headers={"X-TraceLens-Service-Token": c2p})[0]
                    wrong_python = _request(python_url + "/api/field-auth/introspect", method="POST",
                        headers={"X-TraceLens-Service-Token": p2c},
                        payload={"authorization": "Bearer " + token, "method": "GET", "path": "/api/tasks"})[0]
                    findings.append({"wrong_direction_cpp": wrong_cpp, "wrong_direction_python": wrong_python})
                    if wrong_cpp != 401 or wrong_python != 401:
                        blockers.append("directional service credential was accepted by the wrong backend")
            else:
                blockers.append("field login failed or returned no bearer token")
        else:
            findings.append({"valid_user_probe": "NOT_RUN; provide --username and password prompt"})
        for item in listeners:
            if item["address"].rsplit(":", 1)[-1] in {
                str(urllib.parse.urlsplit(cpp_url).port), str(urllib.parse.urlsplit(python_url).port)}:
                enforcement = _systemd_egress(item)
                findings.append({"port": item["address"].rsplit(":", 1)[-1], "os_egress": enforcement})
                if enforcement["status"] != "POLICY_APPLIED_TO_RUNNING_UNIT":
                    blockers.append("OS_EGRESS_ENFORCEMENT_UNVERIFIED for running service")
        if runtime_loaded:
            egress_probe = verify_os_egress()
            findings.append({"controlled_os_egress_probe": egress_probe})
            if egress_probe["status"] != "SYNTHETIC_SYSTEMD_EGRESS_DENIAL_VERIFIED":
                blockers.append("OS_EGRESS_ENFORCEMENT_UNVERIFIED in controlled probe")
    if not live:
        status = "DEPLOYMENT_PENDING" if configured_auth and not blockers else "BLOCKED"
    elif not runtime_loaded:
        status = "DEPLOYMENT_PENDING" if configured_auth else "BLOCKED"
    else:
        status = "BLOCKED" if blockers else "PASS_SECURITY_BASELINE"
    if release is not None and blockers:
        status = "BLOCKED"
    return {"security_baseline_status": status,
            "sensitive_evidence_admission": "BLOCKED" if status != "PASS_SECURITY_BASELINE" else "MANUAL_SAMPLE_AUTHORIZATION_REQUIRED",
            "configured_field_auth": configured_auth, "configured_outbound_policy": configured_outbound,
            "blockers": list(dict.fromkeys(blockers)), "findings": findings,
            "scope": "security baseline only; not real Android sample validation"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--cpp-url", default="http://127.0.0.1:8666")
    parser.add_argument("--python-url", default="http://127.0.0.1:8090")
    parser.add_argument("--username", help="field user for live validation; password read without echo")
    parser.add_argument("--isolated", action="store_true", help="ignore unrelated production 8091 listener")
    parser.add_argument("--release-manifest", type=Path, help="compare protected runtime release IDs and C++ executable hash")
    args = parser.parse_args()
    password = getpass.getpass("Field password: ") if args.username and not args.no_live else ""
    result = check(args.env_file, live=not args.no_live, cpp_url=args.cpp_url,
                   python_url=args.python_url, username=args.username or "", password=password,
                   isolated=args.isolated, release_manifest=args.release_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["security_baseline_status"] == "PASS_SECURITY_BASELINE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
