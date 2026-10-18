"""RCA-2A.2d evidence collector (extends the 2A.2c collector).

Reads the durable AgentRun state EXACTLY as the CLI left it, then runs
the production recovery primitive to demonstrate non-interference, then
deletes the benchmark task through the normal lifecycle API.

Ids are taken from snapshot.json, falling back to failure.json's
run_manifest.benchmark_run_id (the sqlite-failure scenario produces no
snapshot).

Usage: collect_evidence.py <real_task_id> <results_dir> <out_json>
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

PYTHON_SERVICE_ROOT = "/home/ymj68520/projects/TraceLens/python_service"
if PYTHON_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, PYTHON_SERVICE_ROOT)

SERVICE = "http://127.0.0.1:8666"
_MAX_STR = 400


def _trunc(value, depth=0):
    if isinstance(value, str):
        return value[:_MAX_STR]
    if isinstance(value, dict):
        return {
            k: _trunc(v, depth + 1)
            for k, v in value.items()
            if k not in ("result", "result_json", "raw_model_proposal_v2")
            or depth < 3
        }
    if isinstance(value, (list, tuple)):
        return [_trunc(v, depth + 1) for v in value[:40]]
    return value


def _get_task(task_id: str) -> dict:
    page = 1
    while True:
        with urllib.request.urlopen(
            f"{SERVICE}/api/tasks?page={page}&page_size=100", timeout=30
        ) as r:
            data = json.loads(r.read().decode("utf-8"))
        tasks = data.get("tasks") or data.get("data") or []
        for task in tasks:
            if task.get("id") == task_id:
                return task
        if len(tasks) < 100:
            break
        page += 1
    raise RuntimeError(f"task not found via list API: {task_id!r}")


def _ids(results_dir: Path) -> tuple[str, str]:
    snapshot = results_dir / "snapshot.json"
    if snapshot.is_file():
        snap = json.loads(snapshot.read_text())
        return snap["task_id"], snap["investigation_id"]
    failure = results_dir / "failure.json"
    record = json.loads(failure.read_text())
    brun = record["run_manifest"]["benchmark_run_id"]
    return f"bench-{brun}", f"inv-{brun}"


def _delete_task(task_id: str) -> bool:
    req = urllib.request.Request(
        f"{SERVICE}/api/tasks/{task_id}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def main() -> int:
    real_task_id, results_dir, out_path = (
        sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    )
    alias_task_id, investigation_id = _ids(results_dir)

    from httpserver.services.investigation.paths import (
        investigation_db_path_for_task,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )

    task = _get_task(real_task_id)
    db_path = investigation_db_path_for_task(task)
    repo = InvestigationRepository.open_existing(db_path, alias_task_id)
    runtime = AgentRuntimeRepository(repo)

    def snapshot():
        state = {"db_path": str(db_path), "investigations": [], "runs": [],
                 "delegations": [], "trajectory_events": [],
                 "finalizations": []}
        for inv in runtime.list_investigations():
            state["investigations"].append({
                "investigation_id": inv.investigation_id,
                "status": inv.status.value,
                "pause_reason": (
                    inv.pause_reason.value if inv.pause_reason else None),
            })
            for run in runtime.list_runs(inv.investigation_id):
                state["runs"].append({
                    "run_id": run.run_id,
                    "status": run.status.value,
                    "stop_reason": (
                        run.stop_reason.value if run.stop_reason else None),
                    "error_code": run.error_code,
                    "error_message": (run.error_message or "")[:200] or None,
                })
            for event in runtime.list_trajectory(inv.investigation_id):
                state["trajectory_events"].append({
                    "seq": event.seq,
                    "event_type": event.event_type.value,
                    "run_id": event.run_id,
                    "payload": _trunc(event.payload or {}),
                })
            for run in runtime.list_runs(inv.investigation_id):
                for d in runtime.list_delegations(run.run_id):
                    state["delegations"].append({
                        "delegation_id": d.delegation_id,
                        "question_ref": d.question_ref,
                        "status": d.status.value,
                        "failure_code": d.failure_code,
                        "integrated_at": d.integrated_at,
                    })
            record = runtime.get_finalization(inv.investigation_id)
            if record is not None:
                state["finalizations"].append({
                    "finalization_id": record.finalization_id,
                    "completion_mode": record.completion_mode,
                    "run_id": record.run_id,
                })
        return state

    before = snapshot()
    summary = runtime.recover_interrupted_agent_runtime()
    after = snapshot()

    settlement_artifact = results_dir / "settlement.json"
    result = {
        "real_task_id": real_task_id,
        "alias_task_id": alias_task_id,
        "recovery_summary": summary,
        "settlement_artifact": (
            json.loads(settlement_artifact.read_text())
            if settlement_artifact.is_file() else None
        ),
        "at_cli_exit": before,
        "after_production_recovery": after,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    deleted = _delete_task(real_task_id)
    print(json.dumps({
        "out": out_path,
        "recovery": summary,
        "task_deleted": deleted,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
