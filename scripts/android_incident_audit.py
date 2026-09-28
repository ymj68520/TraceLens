#!/usr/bin/env python3
"""Redacted read-only audit of the 6B browser misrouting interval.

Only existing service logs are read. Missing access records remain
IMPACT_UNCONFIRMED; source code or a later successful run is not evidence of
the methods/statuses that actually reached a previous process.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

METHOD = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS)\s+([^\s?]+)(?:\?[^\s]*)?\s+[-:]\s*(\d{3})\b")
REQUEST_ID = re.compile(r"(?:request[_ -]?id|x-request-id)[=: ]+([A-Za-z0-9-]{6,128})", re.I)


def _safe_path(path: str) -> str:
    if path.startswith("/api/") and len(path) <= 200 and re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
        return path
    return "SHA256:" + hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:16]


def audit(logs: list[Path], since: dt.datetime, until: dt.datetime) -> dict:
    coverage = []
    records = []
    for path in logs:
        if not path.is_file() or path.is_symlink():
            coverage.append({"log_class": path.name, "available": False})
            continue
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
        coverage.append({"log_class": path.name, "available": True,
                         "last_file_update": mtime.isoformat(),
                         "updated_during_window": since <= mtime <= until or mtime > until})
        if mtime < since:
            continue
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if "phase-e-" not in line and "synthetic-browser" not in line:
                    continue
                match = METHOD.search(line)
                if match:
                    rid = REQUEST_ID.search(line)
                    records.append({"method": match.group(1), "path_without_query": _safe_path(match.group(2)),
                                    "status": int(match.group(3)),
                                    "request_id_present": rid is not None,
                                    "request_id": rid.group(1) if rid else None})
    return {"window_utc": {"since": since.isoformat(), "until": until.isoformat()},
            "service_log_coverage": coverage, "matching_access_records": records,
            "impact": "IMPACT_UNCONFIRMED" if not records else "REQUIRES_ROUTE_EFFECT_REVIEW",
            "authentication_headers_observable": False,
            "response_bodies_or_credentials_included": False,
            "later_isolated_pass_does_not_erase_this_record": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-utc", required=True)
    parser.add_argument("--until-utc", required=True)
    parser.add_argument("--log", type=Path, action="append", required=True)
    args = parser.parse_args()
    since = dt.datetime.fromisoformat(args.since_utc.replace("Z", "+00:00"))
    until = dt.datetime.fromisoformat(args.until_utc.replace("Z", "+00:00"))
    if not since.tzinfo or not until.tzinfo or since >= until:
        parser.error("valid UTC interval required")
    print(json.dumps(audit(args.log, since, until), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
