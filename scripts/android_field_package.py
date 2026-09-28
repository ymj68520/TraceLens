#!/usr/bin/env python3
"""Operator-only offline package builder. Never accepts paths over HTTP."""

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_service"))
from httpserver.services.android_field_package import build_package, verify_package


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("task service redirected away from loopback")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-record", type=Path, help="operator-supplied local task record JSON")
    group.add_argument("--task-id", help="fetch one task from an explicit loopback C++ service")
    group.add_argument("--import-id", help="indexed report import ID under DATA_DIR")
    group.add_argument("--verify", type=Path, help="verify an existing offline package")
    parser.add_argument("--cpp-url", default="http://127.0.0.1:8666", help="loopback C++ API only")
    parser.add_argument("--output", type=Path, help="new output directory; never overwritten")
    parser.add_argument("--report-root", type=Path,
                        help="trusted local R2 report root for exact citation mapping (operator-only)")
    args = parser.parse_args()
    if args.verify:
        result = verify_package(args.verify)
    else:
        if not args.output:
            parser.error("--output is required when building")
        task = json.loads(args.task_record.read_text(encoding="utf-8")) if args.task_record else None
        if args.task_id:
            parsed = urlsplit(args.cpp_url)
            try:
                loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
            except ValueError:
                loopback = False
            if (parsed.scheme != "http" or not loopback or parsed.username or parsed.password
                    or parsed.path.strip("/") or parsed.query or parsed.fragment):
                parser.error("--cpp-url must be a plain loopback HTTP service")
            if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", args.task_id):
                parser.error("invalid task ID")
            with build_opener(NoRedirect()).open(args.cpp_url.rstrip("/") + "/api/tasks/" + args.task_id, timeout=5) as response:
                task = json.load(response)
            if task.get("id") != args.task_id:
                parser.error("task ID mismatch")
        result = build_package(output=args.output, task=task, import_id=args.import_id,
                               report_root=args.report_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
