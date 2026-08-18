#!/usr/bin/env python3
"""Run deterministic local SQLite performance measurements outside pytest.

The harness creates temporary synthetic stores from the repository's current
schemas. It never uses real evidence, external services, or benchmark files in
Git. Results are written as JSON so the same command can be compared before
and after a measured change.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]


def _inject_site_packages() -> None:
    candidates = (
        PYTHON_SERVICE_ROOT
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
        PYTHON_SERVICE_ROOT / ".venv" / "lib" / "python3.12" / "site-packages",
    )
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break


_inject_site_packages()
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.forensic_report.repository import ReportRepository  # noqa: E402
from httpserver.services.forensic_report.search_index import SnapshotSearchIndex  # noqa: E402
from httpserver.services.forensic_report.models import ScopeType  # noqa: E402
from httpserver.services.investigation import InvestigationRepository  # noqa: E402
from httpserver.services.investigation.graph_reader import InvestigationGraphReader  # noqa: E402

SEED = 20260818
TIERS = {
    "small": {"evidence": 100, "events": 25, "reports": 100},
    "medium": {"evidence": 1000, "events": 250, "reports": 1000},
    "large": {"evidence": 5000, "events": 1250, "reports": 5000},
}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def _result_count(result: Any) -> int:
    if isinstance(result, tuple) and result and isinstance(result[0], int):
        return result[0]
    if hasattr(result, "events"):
        return sum(
            len(getattr(result, field))
            for field in ("events", "event_links", "selections", "claims", "evidence_types")
        )
    if result is None:
        return 0
    if hasattr(result, "__len__"):
        return len(result)
    return 1


def _measure(name: str, operation: Callable[[], Any], *, warmup: int, samples: int) -> dict[str, Any]:
    for _ in range(warmup):
        operation()
    timings: list[float] = []
    result_count = None
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in range(samples):
        started = time.perf_counter_ns()
        result = operation()
        timings.append((time.perf_counter_ns() - started) / 1_000_000.0)
        if result_count is None:
            result_count = _result_count(result)
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "operation": name,
        "samples": samples,
        "median_ms": round(statistics.median(timings), 4),
        "p95_ms": round(_percentile(timings, 0.95), 4),
        "max_ms": round(max(timings), 4),
        "min_ms": round(min(timings), 4),
        "rough_rss_delta_kb": max(0, rss_after - rss_before),
        "result_count": result_count,
    }


def _create_investigation_store(path: Path, task_id: str, counts: dict[str, int]) -> None:
    repository = InvestigationRepository(path, task_id)
    evidence_count = counts["evidence"]
    event_count = counts["events"]
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        snapshots = []
        analyses = []
        claims = []
        refs = []
        now = "2026-08-18T00:00:00+00:00"
        for index in range(evidence_count):
            key = f"file:/synthetic/{index:06d}.bin"
            payload = {
                "evidence_type": "file",
                "normalized_path": f"/synthetic/{index:06d}.bin",
                "name": f"{index:06d}.bin",
                "extension": ".bin",
                "category": "synthetic",
                "type": "application/octet-stream",
                "size": 1024 + index,
                "md5": f"{index:064x}"[-32:],
                "mtime": 1700000000 + index,
                "ctime": 1700000000 + index,
                "is_deleted": 0,
                "initial_summary": None,
                "initial_description": None,
                "initial_keywords": None,
                "initial_model": None,
                "initial_analyzed_at": None,
                "scene_type": None,
                "scene_priority": None,
                "scene_relevant": None,
            }
            snapshots.append(("bench", key, "file", f"/synthetic/{index:06d}.bin", None, None,
                              json.dumps(payload, sort_keys=True, separators=(",", ":")),
                              1700000000 + index))
        connection.executemany(
            "INSERT INTO evidence_snapshots "
            "(task_id,evidence_key,evidence_type,normalized_path,unix_minute,event_type,snapshot_json,captured_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            snapshots,
        )
        for index in range(evidence_count):
            key = f"file:/synthetic/{index:06d}.bin"
            analysis_id = f"sa_bench_{index:06d}"
            status = "accepted" if index % 3 else "review_pending"
            envelope = json.dumps({"evidence_key": key, "seed": SEED, "index": index}, sort_keys=True)
            analyses.append((analysis_id, "bench", key, index + 1, 1, status,
                             f"hash-{index:064d}"[-64:], envelope, "bench-v1",
                             None, f"synthetic summary {index}", "bench", now, now, now if status == "accepted" else None,
                             now if status == "accepted" else None, "bench" if status == "accepted" else None,
                             None, None, None))
            if index % 2 == 0:
                claim_id = f"cl_bench_{index:06d}"
                claims.append((claim_id, analysis_id, 0, "FACT", f"Synthetic fact {index}", "grounded", None, now))
                refs.append((claim_id, key))
        connection.executemany(
            "INSERT INTO secondary_analyses "
            "(analysis_id,task_id,evidence_key,snapshot_id,version,status,input_hash,input_envelope_json,prompt_version," 
            "description,summary,model,created_at,started_at,review_pending_at,decided_at,decided_by,error_code,error_message,failed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            analyses,
        )
        connection.executemany(
            "INSERT INTO analysis_claims "
            "(claim_id,analysis_id,claim_index,claim_type,claim_text,grounding_status,warning_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            claims,
        )
        connection.executemany(
            "INSERT INTO claim_evidence_refs (claim_id,evidence_key) VALUES (?,?)", refs
        )
        for index in range(event_count):
            event_id = f"ie_bench_{index:06d}"
            connection.execute(
                "INSERT INTO investigation_events "
                "(event_id,task_id,needs_refresh,created_at,updated_at) VALUES (?,?,?,?,?)",
                (event_id, "bench", index % 5 == 0, now, now),
            )
            connection.execute(
                "INSERT INTO investigation_event_versions "
                "(task_id,event_id,version,title,summary,created_at,created_by) VALUES (?,?,?,?,?,?,?)",
                ("bench", event_id, 1, f"Synthetic event {index}", "Synthetic event summary", now, "bench"),
            )
            key = f"file:/synthetic/{(index * 7) % evidence_count:06d}.bin"
            connection.execute(
                "INSERT INTO investigation_event_evidence "
                "(task_id,event_id,evidence_key,linked_at,linked_by) VALUES (?,?,?,?,?)",
                ("bench", event_id, key, now, "bench"),
            )
    # Keep the local variable alive until all rows are committed and validated.
    del repository


def _create_report_store(path: Path, index_path: Path, count: int) -> tuple[ReportRepository, SnapshotSearchIndex]:
    repository = ReportRepository(path)
    index = SnapshotSearchIndex(index_path)
    documents = [
        {
            "kind": "synthetic",
            "title": f"Synthetic report {item:06d}",
            "search_text": f"synthetic report evidence finding {item:06d}",
            "record_id": f"report-{item:06d}",
            "evidence_id": f"file:/synthetic/{item:06d}.bin",
            "platform": "bench",
            "category_id": "synthetic",
            "page": item,
        }
        for item in range(count)
    ]
    index.add_documents(documents)
    now = "2026-08-18T00:00:00+00:00"
    rows = [
        (
            f"report_bench_{item:06d}", item + 1, ScopeType.TASK.value, "bench", "ready",
            f"Synthetic report {item}", json.dumps(["bench"]), "ready", 100, now,
            f"snapshots/bench/{item:06d}/manifest.json", None, "[]", None, now, "deterministic",
        )
        for item in range(count)
    ]
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO report_versions "
            "(report_id,version,scope_type,scope_id,status,title,task_ids_json,stage,progress,generated_at," 
            "manifest_path,offline_bundle_path,warnings_json,error,created_at,report_kind) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return repository, index


def _query_plans(path: Path) -> dict[str, list[str]]:
    with sqlite3.connect(path) as connection:
        plans = {}
        queries = {
            "snapshot_task": "SELECT * FROM evidence_snapshots WHERE task_id = ? ORDER BY evidence_key",
            "analysis_selection": "SELECT evidence_key, analysis_id, version FROM secondary_analyses WHERE task_id = ? AND status IN ('accepted','review_pending') ORDER BY evidence_key",
            "event_task": "SELECT * FROM investigation_events WHERE task_id = ? ORDER BY event_id",
        }
        for name, query in queries.items():
            plans[name] = [" ".join(str(value) for value in row) for row in connection.execute("EXPLAIN QUERY PLAN " + query, ("bench",))]
    return plans


def _environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "os": platform.platform(),
        "machine": platform.machine(),
        "cwd": str(Path.cwd()),
    }


def run(tier: str, samples: int) -> dict[str, Any]:
    counts = TIERS[tier]
    root = Path(tempfile.mkdtemp(prefix=f"tracelens-d6-{tier}-"))
    try:
        investigation_path = root / "investigation.db"
        report_path = root / "reports.db"
        search_path = root / "search.db"
        _create_investigation_store(investigation_path, "bench", counts)
        report_repository, search_index = _create_report_store(report_path, search_path, counts["reports"])
        reader = InvestigationGraphReader(investigation_path, "bench")
        results = [
            _measure("graph_overlay_read", reader.read, warmup=1, samples=samples),
            _measure("graph_evidence_list", reader.list_evidence, warmup=1, samples=samples),
            _measure("graph_event_list", reader.list_events, warmup=1, samples=samples),
            _measure("report_search", lambda: search_index.search("evidence finding", 0, 50), warmup=1, samples=samples),
            _measure("report_version_list", lambda: report_repository.list_versions(ScopeType.TASK, "bench"), warmup=1, samples=samples),
        ]
        init_samples = max(1, min(samples, 5))
        def initialize_once() -> int:
            path = root / f"init-{time.perf_counter_ns()}.db"
            InvestigationRepository(path, "bench")
            size = path.stat().st_size
            for sidecar in (Path(f"{path}-wal"), Path(f"{path}-shm")):
                sidecar.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            return size
        results.insert(0, _measure("investigation_fresh_initialization", initialize_once, warmup=0, samples=init_samples))
        return {
            "harness": "TraceLens D6 local SQLite benchmark",
            "seed": SEED,
            "tier": tier,
            "dataset": counts,
            "environment": _environment(),
            "results": results,
            "query_plans": _query_plans(investigation_path),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=sorted(TIERS), default="small")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be positive")
    result = run(args.tier, args.samples)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
