#!/usr/bin/env python3
"""Verify systemd IPAddressDeny against one self-hosted synthetic marker."""

import ipaddress
import subprocess
import sys
from pathlib import Path

PROBE = Path(__file__).with_name("field_egress_probe.py")


def verify() -> dict:
    try:
        addresses = subprocess.run(["hostname", "-I"], capture_output=True, text=True,
                                   timeout=3, check=True).stdout.split()
        own = next((address for address in addresses if ipaddress.ip_address(address).version == 4
                    and not ipaddress.ip_address(address).is_loopback), None)
        if not own:
            return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED", "reason": "no non-loopback test address"}
        server = subprocess.Popen([sys.executable, str(PROBE), "--serve"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            line = server.stdout.readline().strip()
            port = int(line)
            private_url = f"http://{own}:{port}"
            local_url = f"http://127.0.0.1:{port}"
            baseline = subprocess.run([sys.executable, str(PROBE), "--probe", private_url],
                                      capture_output=True, timeout=5, check=False)
            if baseline.returncode != 0:
                return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED", "reason": "synthetic target was not reachable before restriction"}
            prefix = ["systemd-run", "--wait", "--collect", "--pipe",
                      "-p", "IPAddressDeny=any", "-p", "IPAddressAllow=localhost",
                      sys.executable, str(PROBE), "--probe"]
            local = subprocess.run([*prefix, local_url], capture_output=True, timeout=8, check=False)
            denied = subprocess.run([*prefix, private_url], capture_output=True, timeout=8, check=False)
            if local.returncode == 0 and denied.returncode == 2:
                return {"status": "SYNTHETIC_SYSTEMD_EGRESS_DENIAL_VERIFIED",
                        "ordinary_target_reachable": True, "restricted_loopback_reachable": True,
                        "restricted_non_loopback_denied": True}
            return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED",
                    "reason": "transient systemd policy did not produce the expected controlled outcome"}
        finally:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        return {"status": "OS_EGRESS_ENFORCEMENT_UNVERIFIED", "reason": "systemd synthetic probe unavailable"}


if __name__ == "__main__":
    import json
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "SYNTHETIC_SYSTEMD_EGRESS_DENIAL_VERIFIED" else 2)
