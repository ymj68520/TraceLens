#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit local RAID selection. No production service or evidence auto-scan."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raid.core import RaidError, RaidSession, digest_json
from raid.export import export_array, verify_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "export", "verify", "infer", "raw-export", "files", "source", "analyze"))
    parser.add_argument("--inbox", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--max-bytes", type=int, default=1024**3)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-memory-mib", type=int, default=512)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--plan", type=Path, help="explicit RAW plan or chosen inference candidate JSON")
    parser.add_argument("--max-orders", type=int, default=4096)
    parser.add_argument("--allow-partial", action="store_true", help="explicitly inspect/export observed parity mismatches; never mark COMPLETE")
    parser.add_argument("--volume-offset", type=int)
    parser.add_argument("--record-id")
    parser.add_argument("--analyzer", type=Path)
    args = parser.parse_args()
    if not 128 <= args.max_memory_mib <= 4096 or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise RaidError("INVALID_WORKER_RESOURCE_LIMIT")
    # The CLI is a dedicated worker, never the long-running HTTP process.
    # Bound hostile EWF indexes too, not just logical block/chunk reads.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (args.max_memory_mib * 1024**2,) * 2)
        cpu_seconds = max(1, math.ceil(args.timeout))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    except (ImportError, OSError, ValueError) as exc:
        raise RaidError("WORKER_RESOURCE_CONTROL_UNAVAILABLE") from exc
    if args.action == "verify":
        if args.package is None:
            parser.error("verify requires --package")
        result = verify_package(args.package, allow_partial=args.allow_partial)
    elif args.action in ("files", "source", "analyze"):
        if args.package is None:
            raise RaidError("EXPLICIT_PACKAGE_REQUIRED")
        package = args.package.resolve(strict=True)
        if args.action == "analyze":
            from raid.pipeline import analyze_package
            if args.analyzer is None: raise RaidError("EXPLICIT_ANALYZER_REQUIRED")
            result = analyze_package(package, args.analyzer, allow_partial=args.allow_partial, timeout=args.timeout)
        else:
            if args.inbox is None: raise RaidError("EXPLICIT_ORIGINAL_SOURCE_ROOT_REQUIRED")
            from raid.results import create_results, read_back
            if args.action == "source":
                if args.record_id is None: raise RaidError("EXPLICIT_RECORD_ID_REQUIRED")
                result = read_back(args.inbox, package, args.record_id, allow_partial=args.allow_partial)
            else:
                if args.volume_offset is None: raise RaidError("EXPLICIT_VOLUME_OFFSET_REQUIRED")
                result = create_results(args.inbox, package, volume_offset=args.volume_offset, allow_partial=args.allow_partial)
    else:
        if args.inbox is None or args.selection is None:
            parser.error("explicit --inbox and --selection required")
        if args.selection.stat().st_size > 128 * 1024:
            raise RaidError("SELECTION_SIZE_LIMIT")
        selection = json.loads(args.selection.read_text())
        if set(selection) != {"schema_version", "members"} or selection["schema_version"] != 1:
            raise RaidError("UNSUPPORTED_SELECTION_SCHEMA")
        if args.action == "infer":
            from raid.infer import infer
            result = infer(args.inbox, selection["members"], timeout=args.timeout, max_orders=args.max_orders)
            print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))
            return
        if args.action == "raw-export":
            from raid.raw import RawRaidSession
            if args.plan is None or args.plan.stat().st_size > 128 * 1024:
                raise RaidError("EXPLICIT_RAW_PLAN_REQUIRED")
            chosen = json.loads(args.plan.read_text())
            plan = chosen.get("plan", chosen)
            session_factory = lambda: RawRaidSession(args.inbox, selection["members"], plan,
                                                     inference=chosen if "plan" in chosen else None,
                                                     parity_mode="observe" if args.allow_partial else "strict")
        else:
            session_factory = lambda: RaidSession(args.inbox, selection["members"])
        with session_factory() as session:
            if args.action == "raw-export" and chosen.get("source_revision") and \
                    chosen["source_revision"] != digest_json(session._fingerprints):
                raise RaidError("SOURCE_CHANGED_SINCE_INFERENCE")
            if args.action == "inspect":
                result = session.manifest()
            else:
                if args.output_root is None:
                    parser.error("export requires --output-root")
                result = export_array(session, args.output_root,
                                      max_bytes=args.max_bytes, timeout=args.timeout)
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, RaidError) else "INVALID_SELECTION_OR_DEPENDENCY"
        print(json.dumps({"status": "FAILED", "code": code}), file=sys.stderr)
        raise SystemExit(2)
