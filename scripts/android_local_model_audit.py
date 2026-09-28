#!/usr/bin/env python3
"""Read-only model-boundary inventory; never sends evidence or prompts."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(origin: str | None, model_pid: int | None, weight: Path | None,
          license_file: Path | None) -> dict:
    gaps = []
    parsed = urlsplit(origin or "")
    try:
        local_origin = parsed.scheme == "http" and ipaddress.ip_address(parsed.hostname or "").is_loopback \
            and bool(parsed.port) and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
    except ValueError:
        local_origin = False
    if not local_origin:
        gaps.append("EXPLICIT_NUMERIC_LOCAL_MODEL_ORIGIN_REQUIRED")
    runtime = None
    if model_pid and Path(f"/proc/{model_pid}").is_dir():
        proc = Path(f"/proc/{model_pid}")
        try:
            executable = Path(os.readlink(proc / "exe"))
            entries = (proc / "environ").read_bytes().split(b"\0")
            proxy_present = any(entry.startswith((b"HTTP_PROXY=", b"HTTPS_PROXY=", b"ALL_PROXY=",
                                                  b"http_proxy=", b"https_proxy=", b"all_proxy=")) for entry in entries)
            cgroup = (proc / "cgroup").read_text(encoding="utf-8")
            unit = next((value for value in re.findall(r"[\w@.-]+\.service", cgroup)
                         if value.startswith("tracelens-")), None)
            runtime = {"pid": model_pid, "executable_sha256": _sha(executable),
                       "proxy_env_present": proxy_present, "systemd_unit": unit,
                       "network_namespace": os.readlink(proc / "ns/net")}
            if proxy_present:
                gaps.append("MODEL_PROCESS_PROXY_ENV_PRESENT")
            if unit:
                shown = subprocess.run(["systemctl", "show", unit, "-p", "IPAddressDeny", "-p", "IPAddressAllow"],
                                       capture_output=True, text=True, timeout=3, check=False)
                props = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
                runtime["egress_restriction_reported"] = (
                    shown.returncode == 0 and "0.0.0.0/0" in props.get("IPAddressDeny", "")
                    and "::/0" in props.get("IPAddressDeny", ""))
            else:
                runtime["egress_restriction_reported"] = False
            if not runtime["egress_restriction_reported"]:
                gaps.append("MODEL_PROCESS_EGRESS_ENFORCEMENT_UNVERIFIED")
        except (OSError, subprocess.TimeoutExpired):
            gaps.append("MODEL_PROCESS_DETAILS_UNAVAILABLE")
    else:
        gaps.append("MODEL_PROCESS_NOT_IDENTIFIED")
    weight_info = None
    if weight and weight.is_file() and not weight.is_symlink():
        weight_info = {"sha256": _sha(weight), "size_bytes": weight.stat().st_size}
    else:
        gaps.append("MODEL_WEIGHT_AND_SOURCE_UNVERIFIED")
    license_info = None
    if license_file and license_file.is_file() and not license_file.is_symlink():
        license_info = {"sha256": _sha(license_file), "human_license_review": "REQUIRED"}
    else:
        gaps.append("MODEL_LICENSE_UNVERIFIED")
    gaps.extend(("LOCAL_PROXY_OR_FALLBACK_AUDIT_REQUIRED", "SYNTHETIC_REAL_MODEL_WORKFLOW_NOT_RUN"))
    return {"status": "LOCAL_MODEL_VALIDATION_REQUIRED", "origin_is_numeric_loopback": bool(local_origin),
            "runtime": runtime, "weight": weight_info, "license": license_info,
            "gaps": gaps, "real_evidence_sent": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin")
    parser.add_argument("--model-pid", type=int)
    parser.add_argument("--weight", type=Path)
    parser.add_argument("--license-file", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.origin, args.model_pid, args.weight, args.license_file),
                     ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
