#!/usr/bin/env python3
"""Exercise Python and Node pre-send allowlists against synthetic servers."""

from __future__ import annotations

import http.server
import json
import os
import secrets
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

from isolated_target import IsolatedTarget, IsolationViolation, require_private_loopback_namespace

ROOT = Path(__file__).resolve().parents[1]


class Handler(http.server.BaseHTTPRequestHandler):
    identity = ""
    hits = 0

    def do_GET(self):  # noqa: N802
        type(self).hits += 1
        payload = ({"instance_id": self.identity} if self.path == "/__isolation__/identity"
                   else {"ok": True})
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        return


class Trap(Handler):
    pass


def run() -> dict:
    netns = require_private_loopback_namespace()
    instance_id = secrets.token_hex(16)
    Handler.identity, Handler.hits, Trap.hits = instance_id, 0, 0
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    trap = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Trap)
    threads = [threading.Thread(target=item.serve_forever, daemon=True) for item in (server, trap)]
    for thread in threads:
        thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        trap_origin = f"http://127.0.0.1:{trap.server_address[1]}"
        policy = IsolatedTarget(instance_id, origin)
        policy.verify_identity()
        blocked = 0
        for candidate in (trap_origin + "/synthetic-forbidden", origin.replace("127.0.0.1", "localhost") + "/alias",
                          origin.replace("http:", "https:") + "/wrong-protocol"):
            try:
                policy.require(candidate)
            except IsolationViolation:
                blocked += 1
        if blocked != 3 or Trap.hits:
            raise IsolationViolation("Python allowlist did not reject all synthetic forbidden targets")
        code = """(async () => {
          await __tracelensIsolation.verifyIdentity();
          const allowed = await fetch(process.env.TRACELENS_TEST_ORIGIN + '/allowed');
          let denied = false;
          try { await fetch(process.env.TRACELENS_TEST_TRAP + '/forbidden'); }
          catch (error) { denied = error.message.includes('selected synthetic instance'); }
          if (!allowed.ok || !denied) process.exitCode = 3;
          process.stdout.write(JSON.stringify({identity_verified:true, allowed:allowed.ok, denied}));
        })().catch((error) => { process.stderr.write(String(error.message + ' cause=' + (error.cause?.message || '')).slice(0, 300)); process.exitCode = 4; });"""
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "NVM_DIR"}}
        env.update({"TRACELENS_TEST_MODE": "ISOLATED_TEST", "TRACELENS_TEST_INSTANCE_ID": instance_id,
                    "TRACELENS_TEST_ORIGIN": origin, "TRACELENS_TEST_TRAP": trap_origin})
        outcome = subprocess.run(["node", "--require", str(ROOT / "scripts/isolated_node_guard.cjs"), "-e", code],
                                 env=env, cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
        if outcome.returncode or Trap.hits:
            raise IsolationViolation(f"Node synthetic target test failed: exit={outcome.returncode}, "
                                     f"trap_hits={Trap.hits}, stderr={outcome.stderr[:350]!r}, "
                                     f"stdout={outcome.stdout[:150]!r}")
        result = json.loads(outcome.stdout)
        return {"status": "PASS_ISOLATED_TARGET_POLICY", "network_namespace": netns,
                "python_forbidden_targets_rejected": blocked,
                "node": result, "forbidden_server_hits": Trap.hits,
                "allowed_server_hits": Handler.hits}
    finally:
        server.shutdown(); server.server_close()
        trap.shutdown(); trap.server_close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
