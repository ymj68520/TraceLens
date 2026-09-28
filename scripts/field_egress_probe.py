#!/usr/bin/env python3
"""Synthetic marker endpoint for systemd IPAddressDeny verification only."""

import argparse
import http.server
import urllib.request


class Marker(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"TRACELENS_SYNTHETIC_EGRESS_MARKER")

    def log_message(self, *_args):
        return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--serve", action="store_true")
    group.add_argument("--probe")
    args = parser.parse_args()
    if args.serve:
        server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Marker)
        print(server.server_port, flush=True)
        server.serve_forever()
        return 0
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(args.probe, timeout=2) as response:
            return 0 if response.read(64) == b"TRACELENS_SYNTHETIC_EGRESS_MARKER" else 3
    except (OSError, ValueError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
