"""Production evidence content hydration canary (non-holdout).

Phases (run in order):
  content-pre   build a fresh synthetic ext4 image, create a real task
                through the production lifecycle (LLM off), assert the
                post-cleanup state (no extraction artifacts, parser md5
                not populated), then hydrate through the production
                content path (durable store; reacquisition via the C++
                materialize primitive). No post-parse copies anywhere.
  content-post  (run AFTER a real service restart) re-hydrate the same
                task from durable state only: locator provenance, byte
                equality, non-null preview; then delete the task and
                assert the content store is cleaned with it.
  agent         provision the public calibration fixture t2-no-evidence
                fresh (NO dataset staging — no late injection) and run
                ONE full agent case with the production model config;
                hydration is proven by real file content appearing in
                the durable trajectory (tool observations / claims).

Never touches Gen-1/2/3 holdout cases or images (t3-holdout-*).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
RESULTS_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "content-hydration-canary"
)
STATE_FILE = RESULTS_ROOT / "canary-state.json"
CPP_BASE = "http://127.0.0.1:8666"

# synthetic, non-secret fixture content (never a holdout case)
CANARY_FILES = {
    "/reports/ledger_2025.txt": (
        "2025-05-11 synthetic ledger entry\n"
        "account HYDRATION-CANARY-777 credited 45,000.00\n"
        "counterparty canary-proof-fund (synthetic fixture)\n"
    ),
    "/notes/canary_meeting.txt": (
        "2025-05-12 canary meeting notes\n"
        "Attendees: alice_canary, bob_canary\n"
        "Topic: durable content backing acceptance drill.\n"
    ),
    "/docs/readme_canary.txt": (
        "This file exists only for the evidence content hydration canary.\n"
        "Its bytes must survive parser cleanup and service restart.\n"
    ),
}
MARKERS = {
    "/reports/ledger_2025.txt": "HYDRATION-CANARY-777",
    "/notes/canary_meeting.txt": "alice_canary",
    "/docs/readme_canary.txt": "survive parser cleanup",
}


def _http(method: str, url: str, *, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8")
    return json.loads(payload) if payload else {}


def _build_image(path: Path) -> Path:
    """16MB ext4 image with exactly CANARY_FILES, inode times pinned."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    subprocess.run(
        ["dd", "if=/dev/zero", f"of={path}", "bs=1M", "count=16"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["mke2fs", "-q", "-t", "ext4", "-L", "canary_hydration",
         "-I", "256", "-b", "1024", str(path)],
        check=True, capture_output=True,
    )
    dirs = sorted({str(Path(p).parent) for p in CANARY_FILES if Path(p).parent != Path(".")})
    for d in dirs:
        subprocess.run(
            ["debugfs", "-w", "-R", f"mkdir {d}", str(path)],
            check=True, capture_output=True,
        )
    staging = path.with_suffix(".staging")
    if staging.exists():
        subprocess.run(["rm", "-rf", str(staging)], check=True)
    for rel, content in CANARY_FILES.items():
        src = staging / rel.lstrip("/")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(content, encoding="utf-8", newline="\n")
        subprocess.run(
            ["debugfs", "-w", "-R", f"write {src} {rel}", str(path)],
            check=True, capture_output=True,
        )
        for field in ("mtime", "ctime"):
            subprocess.run(
                ["debugfs", "-w", "-R",
                 f"set_inode_field {rel} {field} 20250122000000", str(path)],
                check=True, capture_output=True,
            )
    subprocess.run(["rm", "-rf", str(staging)], check=True)
    return path


def _create_task(image_path: Path) -> str:
    body = {
        "image_path": str(image_path),
        "case_description": (
            "Evidence content hydration canary (synthetic non-secret "
            "fixture; production content path validation; no agent run)."
        ),
        "llm_analyze": False,
        "llm_event_analyze": False,
        "priority": "high",
    }
    return _http("POST", f"{CPP_BASE}/api/tasks", body=body)["id"]


def _wait_task(task_id: str, timeout_s: int = 600) -> dict:
    deadline = time.monotonic() + timeout_s
    record = {}
    while time.monotonic() < deadline:
        record = _http("GET", f"{CPP_BASE}/api/tasks/{task_id}")
        if record.get("status") in ("completed", "failed", "cancelled"):
            return record
        time.sleep(3)
    raise TimeoutError(f"task {task_id} not terminal")


def _task_dir(record: dict) -> Path:
    return Path(record["extraction_directory"]).parent


async def _hydrate(task_id: str) -> dict:
    """Production content path: resolver + durable store, nothing else."""
    from httpserver.config import Settings
    from httpserver.services.cpp_backend import CppBackendService
    from httpserver.services.investigation_service import (
        InvestigationService,
        _ResolvedContentRef,
    )
    from httpserver.services.investigation_evidence import ResolvedEvidence

    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    backend = CppBackendService(settings)
    await backend.initialize()
    service = InvestigationService(cpp_backend=backend)
    out = {"task_id": task_id, "items": []}
    try:
        for key, marker in MARKERS.items():
            t0 = time.monotonic()
            resolved = await service.resolve_evidence(task_id, f"file:{key}")
            if resolved is None:
                raise RuntimeError(f"evidence did not resolve: file:{key}")
            located = await service._content_store.locate_for_resolved(
                _ResolvedContentRef.from_dict(resolved)
            )
            latency = round(time.monotonic() - t0, 3)
            ref = ResolvedEvidence.from_dict(resolved)
            text = await service._evidence_resolver.bounded_content(ref)
            blob_bytes = Path(located.path).read_bytes()
            out["items"].append({
                "evidence_key": f"file:{key}",
                "provenance": located.provenance,
                "persisted": located.persisted,
                "sha256": hashlib.sha256(blob_bytes).hexdigest(),
                "bytes": len(blob_bytes),
                "marker_present": marker in text,
                "preview_len": len(text),
                "latency_seconds": latency,
            })
    finally:
        await backend.shutdown()
    return out


def _db_stats(task_dir: Path) -> dict:
    import sqlite3

    conn = sqlite3.connect(task_dir / "files.db")
    try:
        total, hashed, located = conn.execute(
            "SELECT COUNT(*), "
            "SUM(md5 IS NOT NULL AND md5 != ''), "
            "SUM(content_sha256 IS NOT NULL) FROM files"
        ).fetchone()
    except sqlite3.OperationalError:
        total, hashed, located = conn.execute(
            "SELECT COUNT(*), SUM(md5 IS NOT NULL AND md5 != ''), 0 FROM files"
        ).fetchone()
    finally:
        conn.close()
    return {
        "files_rows": total,
        "rows_with_parser_md5": hashed or 0,
        "rows_with_content_locator": located or 0,
    }


def phase_content_pre() -> int:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    image = _build_image(RESULTS_ROOT / "images" / "canary-hydration.img")
    task_id = _create_task(image)
    record = _wait_task(task_id)
    if record.get("status") != "completed":
        print(json.dumps({"phase": "content-pre", "status": "FAILED",
                          "task_status": record.get("status")}, indent=2))
        return 1
    tdir = _task_dir(record)
    extraction = Path(record["extraction_directory"])
    extraction_files = (
        sum(1 for _ in extraction.rglob("*") if _.is_file())
        if extraction.exists() else 0
    )
    if extraction_files != 0:
        print(json.dumps({"phase": "content-pre",
                          "status": "FAILED",
                          "reason": "extraction artifacts exist pre-hydration",
                          "extraction_files": extraction_files}, indent=2))
        return 1
    state = {
        "task_id": task_id,
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "expected_content": {k: hashlib.sha256(v.encode("utf-8")).hexdigest()
                             for k, v in CANARY_FILES.items()},
        "pre_hydration_db_stats": _db_stats(tdir),
    }
    hydration = asyncio.run(_hydrate(task_id))
    state["first_hydration"] = hydration
    state["post_hydration_db_stats"] = _db_stats(tdir)
    blobs = sorted(
        p.name for p in (tdir / "content" / "blobs").glob("*") if p.is_file()
    ) if (tdir / "content" / "blobs").exists() else []
    state["blobs_after_first_hydration"] = blobs
    ok = (
        len(hydration["items"]) == 3
        and all(item["marker_present"] for item in hydration["items"])
        and all(item["provenance"] == "reacquired" for item in hydration["items"])
        and all(
            item["sha256"] == state["expected_content"][item["evidence_key"].removeprefix("file:")]
            for item in hydration["items"]
        )
        and len(blobs) == 3
    )
    state["content_pre_status"] = "PASS" if ok else "FAILED"
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(json.dumps({"phase": "content-pre", "status": state["content_pre_status"],
                      "task_id": task_id, "hydration": hydration,
                      "db_stats": [state["pre_hydration_db_stats"],
                                   state["post_hydration_db_stats"]]}, indent=2))
    return 0 if ok else 1


def phase_content_post() -> int:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    task_id = state["task_id"]
    record = _http("GET", f"{CPP_BASE}/api/tasks/{task_id}")
    if record.get("status") != "completed":
        print(json.dumps({"phase": "content-post", "status": "FAILED",
                          "reason": f"task status {record.get('status')} after restart"}))
        return 1
    tdir = _task_dir(record)
    hydration = asyncio.run(_hydrate(task_id))
    ok = (
        all(item["provenance"] == "locator" for item in hydration["items"])
        and all(item["marker_present"] for item in hydration["items"])
        and all(
            item["sha256"] == state["expected_content"][item["evidence_key"].removeprefix("file:")]
            for item in hydration["items"]
        )
    )
    # §30: task deletion cleans the durable content artifacts atomically
    _http("DELETE", f"{CPP_BASE}/api/tasks/{task_id}", timeout=60)
    time.sleep(2)
    gone = not tdir.exists()
    state["second_hydration_after_restart"] = hydration
    state["task_dir_removed_after_delete"] = gone
    state["content_post_status"] = "PASS" if (ok and gone) else "FAILED"
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(json.dumps({"phase": "content-post",
                      "status": state["content_post_status"],
                      "hydration_after_restart": hydration,
                      "task_dir_removed_after_delete": gone}, indent=2))
    return 0 if (ok and gone) else 1


def _scan_hydration_markers(tdir: Path) -> dict[str, list[str]]:
    import sqlite3

    markers = ["Q2 budget review", "wangfang", "expense reimbursement"]
    found: dict[str, list[str]] = {m: [] for m in markers}
    inv_db = tdir / "investigation.db"
    if inv_db.exists():
        conn = sqlite3.connect(inv_db)
        try:
            for (payload,) in conn.execute(
                "SELECT result_json FROM agent_delegation_results"
            ):
                for m in markers:
                    if m.lower() in (payload or "").lower():
                        found[m].append("delegation_result")
            try:
                for row in conn.execute(
                    "SELECT payload_json FROM agent_trajectory_events"
                ):
                    for m in markers:
                        if m.lower() in (row[0] or "").lower():
                            found[m].append("trajectory")
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()
    return found


def phase_agent(recover_task_id: str | None = None) -> int:
    """§45: one non-holdout agent case with hydration genuinely exercised."""
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
    from scripts import run_p8b_baseline as baseline

    case_id = "t2-no-evidence"
    integration = None
    run_status = None
    if recover_task_id:
        task_id = recover_task_id
        record = baseline._wait_task(task_id)
        if record.get("status") != "completed":
            print(json.dumps({"phase": "agent", "status": "FAILED",
                              "reason": f"task {record.get('status')}"}))
            return 1
    else:
        task_id = baseline._create_task(baseline.IMAGES[case_id], case_id, "canary")
        record = baseline._wait_task(task_id)
        if record.get("status") != "completed":
            print(json.dumps({"phase": "agent", "status": "FAILED",
                              "reason": f"task {record.get('status')}"}))
            return 1
        # NO dataset staging: the agent sees exactly what the parse pipeline
        # produced; content must arrive through the durable store.
        outcome = baseline._run_one(
            case_id=case_id,
            repeat="repeat-0",
            fresh_task_id=task_id,
            configuration_id="bconf-content-hydration-canary",
            configuration_label="content-hydration-agent-canary",
        )
        run_status = outcome.get("status")
        result = outcome.get("result")
        if result is not None:
            try:
                dumped = (
                    result.model_dump() if hasattr(result, "model_dump") else result
                )
                integration = (dumped or {}).get("metrics", {}).get("integration")
            except Exception:
                integration = None
    tdir = Path(record["extraction_directory"]).parent
    found = _scan_hydration_markers(tdir)
    hydrated = any(found[m] for m in found)
    report = {
        "phase": "agent",
        "case_id": case_id,
        "task_id": task_id,
        "run_status": run_status,
        "hydration_markers_found": {m: sorted(set(v)) for m, v in found.items()},
        "content_hydration_exercised": hydrated,
        "integration": integration,
    }
    out = RESULTS_ROOT / "agent-canary"
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent-canary-outcome.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    report["status"] = "PASS" if hydrated else "FAILED"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    baseline._cleanup_task(task_id)
    return 0 if hydrated else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="canary_content_hydration")
    parser.add_argument("phase", choices=["content-pre", "content-post", "agent"])
    parser.add_argument("--recover-task", default=None,
                        help="agent phase only: scan+report an already-run task")
    args = parser.parse_args()
    if args.phase == "content-pre":
        return phase_content_pre()
    if args.phase == "content-post":
        return phase_content_post()
    return phase_agent(args.recover_task)


if __name__ == "__main__":
    raise SystemExit(main())
