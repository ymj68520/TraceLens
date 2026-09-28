"""Fail-closed target policy for synthetic field tests.

This is not production authentication. It prevents a test client from silently
falling back to existing 8666/8090/8091 services. Run the entire test process
inside a fresh network namespace as a second, process-wide boundary.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass


class IsolationViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class IsolatedTarget:
    instance_id: str
    origin: str

    def __post_init__(self):
        parsed = urllib.parse.urlsplit(self.origin)
        try:
            loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if (not self.instance_id or len(self.instance_id) < 16 or parsed.scheme != "http"
                or not loopback or not parsed.port or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise IsolationViolation("test instance requires an exact numeric loopback HTTP origin")

    def permits(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme in {"data", "blob", "about"}:
            return True  # non-network browser resources
        if parsed.username or parsed.password or parsed.scheme != "http" or not parsed.port:
            return False
        return f"{parsed.scheme}://{parsed.netloc}" == self.origin

    def require(self, url: str) -> None:
        if not self.permits(url):
            raise IsolationViolation("request target is not the selected synthetic instance")

    def get_json(self, path: str) -> dict:
        if not path.startswith("/") or path.startswith("//"):
            raise IsolationViolation("invalid synthetic instance path")
        url = self.origin + path
        self.require(url)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
        )
        with opener.open(url, timeout=3) as response:
            if response.status != 200 or response.geturl() != url:
                raise IsolationViolation("synthetic instance identity request was redirected")
            return json.load(response)

    def verify_identity(self) -> None:
        identity = self.get_json("/__isolation__/identity")
        if identity != {"instance_id": self.instance_id}:
            raise IsolationViolation("synthetic service instance identity mismatch")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise IsolationViolation("synthetic service redirected outside the allowlist")


def require_private_loopback_namespace() -> str:
    """Validate a fresh netns before enabling lo or starting any test server."""
    own = os.readlink("/proc/self/ns/net")
    init = os.readlink("/proc/1/ns/net")
    if own == init:
        raise IsolationViolation("ISOLATED_TEST requires a fresh network namespace")
    links = json.loads(subprocess.run(
        ["ip", "-j", "link", "show"], capture_output=True, text=True,
        timeout=3, check=True,
    ).stdout)
    if any(item.get("ifname") != "lo" for item in links):
        raise IsolationViolation("test namespace contains a non-loopback interface")
    subprocess.run(["ip", "link", "set", "dev", "lo", "up"],
                   capture_output=True, text=True, timeout=3, check=True)
    return own
