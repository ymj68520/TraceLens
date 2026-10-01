"""Per-case deterministic check: calibration dataset ⊆ image bytes.

For each calibration corpus case: provision ONE real task from the
case image (LLM off), then for every dataset_manifest entry:
  1. files.db must contain the row (the parse pipeline discovered it —
     the agent can find it via evidence discovery);
  2. the C++ materialize primitive (raw-DB-gated image reacquisition,
     the production content path) must return bytes whose sha256 equals
     the manifest sha256.

This proves the durable content path can serve every calibration
dataset file WITHOUT any post-parse staging. Tasks are deleted after
the check. Zero model calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.config import Settings  # noqa: E402
from httpserver.services.cpp_backend import CppBackendService  # noqa: E402
from scripts.run_p8b_baseline import CASES_ROOT, IMAGES  # noqa: E402

RESULTS_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "requalification" / "runtime-v3"
)
CPP_BASE = "http://127.0.0.1:8666"


def _http(method: str, url: str, *, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8")
    return json.loads(payload) if payload else {}


def _create(image: Path, case_id: str) -> str:
    return _http("POST", f"{CPP_BASE}/api/tasks", body={
        "image_path": str(image),
        "case_description": (
            f"Runtime V3 requalification dataset-in-image check for {case_id} "
            "(deterministic; no agent run)."
        ),
        "llm_analyze": False,
        "llm_event_analyze": False,
        "priority": "high",
    })["id"]


def _wait(task_id: str, timeout_s: int = 600) -> dict:
    deadline = time.monotonic() + timeout_s
    record = {}
    while time.monotonic() < deadline:
        record = _http("GET", f"{CPP_BASE}/api/tasks/{task_id}")
        if record.get("status") in ("completed", "failed", "cancelled"):
            return record
        time.sleep(3)
    raise TimeoutError(task_id)


def _normalize(path: str) -> str:
    from httpserver.services.investigation_evidence import normalize_forensic_path

    return normalize_forensic_path(path)


async def _check_case(case_id: str) -> dict:
    import sqlite3

    manifest = json.loads(
        (CASES_ROOT / case_id / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    image = IMAGES[case_id]
    task_id = _create(image, case_id)
    record = _wait(task_id)
    out = {
        "case_id": case_id,
        "task_id": task_id,
        "image": str(image),
        "task_status": record.get("status"),
        "files": [],
        "pass": False,
    }
    try:
        if record.get("status") != "completed":
            out["error"] = f"task terminal={record.get('status')}"
            return out
        files_db = record["output_files_db"]
        settings = Settings(_env_file=str(PYTHON_SERVICE_ROOT.parent / ".env"))
        backend = CppBackendService(settings)
        await backend.initialize()
        try:
            conn = sqlite3.connect(files_db)
            rows = {
                _normalize(p)
                for (p,) in conn.execute("SELECT path FROM files").fetchall()
            }
            conn.close()
            all_ok = True
            for ref in manifest["files"]:
                key = _normalize("/" + ref["relative_path"])
                item = {"relative_path": ref["relative_path"], "indexed": key in rows}
                if item["indexed"]:
                    mat = await backend.materialize_file(task_id, key)
                    mpath = (mat or {}).get("materialized_path")
                    if mpath and Path(mpath).is_file():
                        digest = hashlib.sha256(Path(mpath).read_bytes()).hexdigest()
                        item["reacquired_sha256"] = digest
                        item["sha256_matches_manifest"] = digest == ref["sha256"]
                    else:
                        item["reacquired_sha256"] = None
                        item["sha256_matches_manifest"] = False
                else:
                    item["reacquired_sha256"] = None
                    item["sha256_matches_manifest"] = False
                item["ok"] = item["indexed"] and item["sha256_matches_manifest"]
                all_ok = all_ok and item["ok"]
                out["files"].append(item)
            out["pass"] = all_ok
        finally:
            await backend.shutdown()
    finally:
        try:
            _http("DELETE", f"{CPP_BASE}/api/tasks/{task_id}", timeout=60)
        except Exception:
            pass
    return out


def main() -> int:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    corpus = json.loads(
        (PYTHON_SERVICE_ROOT / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json")
        .read_text(encoding="utf-8")
    )
    case_ids = [ref["case_id"] for ref in corpus["calibration_cases"]]
    results = [asyncio.run(_check_case(case_id)) for case_id in case_ids]
    record = {
        "record": "runtime-v3-dataset-in-image-check:v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "cases": results,
        "all_pass": all(r["pass"] for r in results),
    }
    out = RESULTS_ROOT / "dataset-in-image-check.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    for r in results:
        bad = [f for f in r["files"] if not f.get("ok")]
        print(f"{r['case_id']}: {'PASS' if r['pass'] else 'FAIL ' + str(bad)[:160]}")
    print("all_pass =", record["all_pass"])
    return 0 if record["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
