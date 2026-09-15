#!/usr/bin/env python3
"""Backfill migrated event-cluster analysis rows into task ``_events.db`` files.

Thin CLI shell over ``httpserver.services.case_analysis.backfill`` (SPEC:
event-cluster-analysis-redesign §3.3). Idempotent — databases that already
carry analysis rows are skipped.

Usage:
    python scripts/backfill_cluster_analyses.py /path/a_events.db /path/b_events.db
    python scripts/backfill_cluster_analyses.py --tasks-json /path/tasks.json
    python scripts/backfill_cluster_analyses.py            # auto-discover tasks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.case_analysis.backfill import backfill_events_db  # noqa: E402


def _discover_events_dbs(tasks_json: Path) -> list[tuple[str, str]]:
    """Return (task_id, events_db) pairs recorded in a tasks.json file."""
    data = json.loads(tasks_json.read_text(encoding="utf-8"))
    records = list(data.values()) if isinstance(data, dict) else list(data)
    pairs = []
    for record in records:
        if not isinstance(record, dict):
            continue
        events_db = record.get("output_events_db") or ""
        task_id = str(record.get("id") or record.get("task_id") or "")
        if events_db:
            pairs.append((task_id, events_db))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events_dbs", nargs="*", help="Paths to *_events.db files")
    parser.add_argument(
        "--tasks-json",
        type=Path,
        default=None,
        help="tasks.json to discover task databases from (default: auto-discover)",
    )
    arguments = parser.parse_args()

    targets: list[tuple[str, str]] = []
    for path in arguments.events_dbs:
        targets.append(("", path))

    tasks_json = arguments.tasks_json
    if tasks_json is None and not targets:
        for candidate in (
            PYTHON_SERVICE_ROOT.parent / "data" / "tasks.json",
            PYTHON_SERVICE_ROOT.parent / "build" / "data" / "tasks.json",
            PYTHON_SERVICE_ROOT / "data" / "tasks.json",
        ):
            if candidate.exists():
                tasks_json = candidate
                break

    if tasks_json is not None:
        if not tasks_json.exists():
            print(f"tasks.json not found: {tasks_json}", file=sys.stderr)
            return 2
        discovered = _discover_events_dbs(tasks_json)
        print(f"Discovered {len(discovered)} task database(s) from {tasks_json}")
        targets.extend(discovered)

    if not targets:
        print("No databases given and no tasks.json discovered.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 2

    failures = 0
    for task_id, events_db in targets:
        if not Path(events_db).exists():
            print(f"[missing] task={task_id or '?'} {events_db}")
            failures += 1
            continue
        try:
            summary = backfill_events_db(events_db, task_id=task_id)
        except Exception as exc:  # keep going across databases
            print(f"[error]   task={task_id or '?'} {events_db}: {exc}")
            failures += 1
            continue
        print(f"[{summary['status']}] task={task_id or '?'} {events_db}: {summary}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
