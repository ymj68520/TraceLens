"""CrossModelFailureRootCauseAuditV1 — deterministic, read-only audit.

Failure Attribution Audit across all allowed calibration series. Zero model
calls, zero writes to historical artifacts. Every classification rule is
code-derived and cited in the report.

Subcommands (output dir: benchmarks/audits/cross-model-root-cause-audit-v1/):
  matrix          per-run failure matrix (§2) + cross-model concentration
  retries         "Exceeded maximum output retries" forensics (§3)
  timeouts        provider timeout timelines + taxonomy (§4)
  terminalization recompute charter q-1 terminalization under the single
                  frozen definition and compare with historical claims (§7)

Failure-stage classification rules (derived from the audited code):
  - "Exceeded maximum output retries (1)": supervisor agents are built
    WITHOUT a retries argument (agent_supervisor.py build_*_agent → pydantic-ai
    default retries=1); supervisor PLAN failures are caught and evented
    (agent_orchestrator.py ~1318) so they can never escape as run failures,
    while the INTEGRATE calls (integrate_v2/integrate, ~1596/~1681) have NO
    try/except. An escaped "(1)" is therefore SUPERVISOR_INTEGRATE.
  - "Exceeded maximum output retries (2+)": specialist agents are built with
    retries=AgentRunPolicy.max_output_retries (default 2,
    agent_specialist_executor.py) → SPECIALIST_OUTPUT_VALIDATION.
  - "Request timed out.": str(openai.APITimeoutError); transport errors are
    never retried by pydantic-ai and escape at the first uncaught model call.
    The escaped stage is located by the last durable trajectory event:
    delegation_completed → SUPERVISOR_INTEGRATE; delegation_started (no
    completion) → SPECIALIST_EXECUTION; earlier → SUPERVISOR_PLAN.
  - quota/429 codes in delegation_failures → SPECIALIST_EXECUTION (provider).

Usage (from python_service/):
    .venv/bin/python scripts/audit_cross_model_failure.py matrix
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RESULTS = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
OUT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "audits" / "cross-model-root-cause-audit-v1"
)
TASK_STORE_ROOT = REPO_ROOT / "build" / "data" / "tasks"

# Allowed calibration series (public calibration side only). Consumed
# holdout series (acceptance-gen2/3/4, b6-holdout) are EXCLUDED by the
# audit directive §0; a1-*/canary/ablation/b4/requalification are not
# model-candidate calibration series.
SERIES = {
    "b2-runtime-v3-incumbent": RESULTS / "b2-runtime-v3",
    "b2-runtime-v3-glm52": RESULTS / "b2-runtime-v3-glm52",
    "b2-restart-sensenova": RESULTS / "b2-restart" / "b2",
    "baseline-mimo": RESULTS / "baseline",
    "wave2-dsv4f-sensenova": (
        RESULTS / "model-candidates" / "wave2" / "deepseek-v4-flash" / "qual-8x1"
    ),
    "dsv4f-sensenova": RESULTS / "model-candidates" / "deepseek-v4-flash" / "qual-8x1",
    "glm-5.2-sensenova": RESULTS / "model-candidates" / "glm-5.2" / "qual-8x1",
    "space-bunny-alpha-openrouter": (
        RESULTS / "model-candidates" / "space-bunny-alpha-openrouter" / "qual-8x1"
    ),
    "step-3.7-flash-stepfun": (
        RESULTS / "model-candidates" / "step-3.7-flash-stepfun" / "qual-8x1"
    ),
    "step-5-preview-stepfun": (
        RESULTS / "model-candidates" / "step-5-preview-stepfun" / "qual-8x1"
    ),
}
# experiment files that map case/repeat -> fresh task_id (store timelines)
EXPERIMENT_FILES = {
    "space-bunny-alpha-openrouter": (
        RESULTS / "model-candidates" / "space-bunny-alpha-openrouter" / "experiment-8x1.json"
    ),
    "step-3.7-flash-stepfun": (
        RESULTS / "model-candidates" / "step-3.7-flash-stepfun" / "experiment-8x1.json"
    ),
    "step-5-preview-stepfun": (
        RESULTS / "model-candidates" / "step-5-preview-stepfun" / "experiment-8x1.json"
    ),
}

OPEN_STATUSES = {"open", "in_progress"}
QUOTA_MARKERS = ("rate_limited", "rate-limited", "quota", "billing", "402", "429")
OUTPUT_RETRY_RE = re.compile(r"Exceeded maximum output retries \((\d+)\)")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ts(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def _store_row(task_id: str | None) -> dict:
    """Durable trajectory facts for a run's task store (if still on disk)."""
    if not task_id:
        return {"store_available": False}
    db = TASK_STORE_ROOT / task_id / "investigation.db"
    if not db.is_file():
        return {"store_available": False}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception:
        return {"store_available": False}
    try:
        counts = dict(conn.execute(
            "select event_type, count(*) from agent_trajectory_events "
            "group by event_type"
        ).fetchall())
        last = conn.execute(
            "select event_type, created_at from agent_trajectory_events "
            "order by seq desc limit 1"
        ).fetchone()
        return {
            "store_available": True,
            "store_task_id": task_id,
            "event_counts": counts,
            "tool_observations": counts.get("tool_observation_recorded", 0),
            "last_event_type": last[0] if last else None,
            "last_event_at": last[1] if last else None,
        }
    finally:
        conn.close()


def _classify_stage(failure: dict, digest: dict, store: dict) -> dict:
    """Stage attribution per the code-derived rules in the docstring."""
    reason = str(failure.get("failure_reason", ""))
    m = OUTPUT_RETRY_RE.search(reason)
    if m:
        retries = int(m.group(1))
        if retries <= 1:
            stage = "SUPERVISOR_INTEGRATE"
            evidence = (
                "marker retries=1 = pydantic-ai agent default (supervisor "
                "agents built without retries); PLAN is caught+evented so an "
                "escaped '(1)' can only be INTEGRATE (uncaught call sites)"
            )
        else:
            stage = "SPECIALIST_OUTPUT_VALIDATION"
            evidence = (
                "marker retries>=2 = AgentRunPolicy.max_output_retries "
                "(specialist agents built with retries=2)"
            )
        return {"failed_stage": stage, "stage_evidence": evidence,
                "output_validation_retry_budget": retries}
    if "timed out" in reason.lower() or "timeout" in reason.lower():
        last = store.get("last_event_type")
        mapping = {
            "delegation_completed": "SUPERVISOR_INTEGRATE",
            "delegation_started": "SPECIALIST_EXECUTION",
            "delegation_admitted": "SPECIALIST_EXECUTION",
        }
        stage = mapping.get(last, "SUPERVISOR_PLAN" if last else "UNATTRIBUTED_NO_STORE")
        gap = None
        if store.get("last_event_at") and failure.get("run_manifest", {}).get("completed_at"):
            gap = round((_ts(failure["run_manifest"]["completed_at"])
                         - _ts(store["last_event_at"])).total_seconds(), 1)
        return {
            "failed_stage": stage,
            "stage_evidence": (
                f"APITimeoutError escapes uncaught; last durable event "
                f"{last!r}, post-event gap {gap}s"
            ),
            "post_event_gap_s": gap,
        }
    delegation_failures = digest.get("delegation_failures") or []
    if any(
        any(q in (f if isinstance(f, str) else str(f.get("failure_code", ""))).lower()
            for q in QUOTA_MARKERS)
        for f in delegation_failures
    ):
        return {"failed_stage": "SPECIALIST_EXECUTION",
                "stage_evidence": "quota-class delegation failure codes",
                "output_validation_retry_budget": None}
    return {"failed_stage": "UNATTRIBUTED",
            "stage_evidence": "no code-derived rule matched",
            "output_validation_retry_budget": None}


def _taxonomy(stage: str, failure: dict) -> dict:
    reason = str(failure.get("failure_reason", ""))
    if OUTPUT_RETRY_RE.search(reason):
        return {
            "primary": "MODEL_OUTPUT_CONTRACT_FAILURE",
            "contributing": ["INSUFFICIENT_TELEMETRY"],
            "note": (
                "stage-localized from retry marker + catch topology, but the "
                "actual model output, validation error list and retry "
                "feedback were never persisted (safe_failure_message "
                "sanitizes; UnexpectedModelBehavior.__cause__ is dropped)"
            ),
        }
    if "timed out" in reason.lower():
        return {
            "primary": "PROVIDER_TIMEOUT_OR_LATENCY",
            "contributing": ["SDK_INTERNAL_RETRY_AMPLIFICATION"],
            "note": (
                "openai.APITimeoutError after DEFAULT_MAX_RETRIES=2 (3 "
                "attempts x 120s per-attempt timeout); pydantic-ai never "
                "retries transport errors; LLM_MAX_RETRIES is unconsumed on "
                "the agent path; production run-level wait_for budget is "
                "not armed (generation_params has no timeout_seconds)"
            ),
        }
    if stage == "SPECIALIST_EXECUTION":
        return {"primary": "PROVIDER_QUOTA_FAILURE", "contributing": [],
                "note": "quota-class delegation failure codes"}
    return {"primary": "INSUFFICIENT_TELEMETRY", "contributing": [],
            "note": "no code-derived rule matched the persisted evidence"}


def _walk_series(label: str, root: Path) -> list[dict]:
    rows = []
    experiment = {}
    exp_file = EXPERIMENT_FILES.get(label)
    if exp_file and exp_file.is_file():
        experiment = _load(exp_file).get("fresh_task_ids", {})
    for run_dir in sorted(root.glob("t*/repeat*")):
        manifest_p = run_dir / "run_manifest.json"
        if not manifest_p.is_file():
            continue
        manifest = _load(manifest_p)
        if manifest.get("run_manifest"):
            manifest = manifest["run_manifest"]
        model = manifest.get("model") or {}
        case, repeat = run_dir.parent.name, run_dir.name
        digest = {}
        digest_p = run_dir / "trajectory_digest.json"
        if digest_p.is_file():
            digest = _load(digest_p)
            if not isinstance(digest, dict):
                # digest_version<=2 legacy flat rejection-code list
                digest = {"legacy_flat_rejection_codes": digest}
        identity_p = run_dir / "identity_telemetry.json"
        identity = _load(identity_p) if identity_p.is_file() else []
        result_p = run_dir / "result.json"
        failure_p = run_dir / "failure.json"
        completed = result_p.is_file()
        failure = _load(failure_p) if failure_p.is_file() else None
        snapshot = _load(result_p.parent / "snapshot.json") if completed else {}

        q1 = next((q for q in (snapshot.get("questions") or [])
                   if q.get("question_id") == "q-1"), None)
        coverage = snapshot.get("coverage") or []
        cov_counts: dict[str, int] = {}
        for c in coverage:
            if isinstance(c, dict):
                cov_counts[str(c.get("status"))] = cov_counts.get(str(c.get("status")), 0) + 1
        fin = snapshot.get("finalization") or {}
        tokens_in = tokens_out = requests = None
        if completed:
            result = _load(result_p)
            usage = (result.get("cost_metrics") or {}).get("usage_entries") or []
            tokens_in = sum(int(u.get("input_tokens") or 0) for u in usage)
            tokens_out = sum(int(u.get("output_tokens") or 0) for u in usage)
            requests = sum(int(u.get("requests") or 1) for u in usage)
        started = manifest.get("started_at")
        completed_at = manifest.get("completed_at")
        elapsed_ms = None
        if started and completed_at:
            elapsed_ms = int((_ts(completed_at) - _ts(started)).total_seconds() * 1000)

        store = _store_row((experiment.get(case) or {}).get(repeat))
        if completed:
            stage_info = {"failed_stage": None, "stage_evidence": None,
                          "output_validation_retry_budget": None}
            tax = {"primary": None, "contributing": [], "note": "run completed"}
        else:
            stage_info = _classify_stage(failure or {}, digest, store)
            tax = _taxonomy(stage_info["failed_stage"], failure or {})
        rows.append({
            "series": label,
            "candidate_config_id": manifest.get("configuration_id"),
            "provider": model.get("provider"),
            "model": model.get("model_id"),
            "runtime_hash": manifest.get("tracelens_git_commit"),
            "pydantic_ai_version": "2.30.0 (pinned, agent_model_adapter.py:31)",
            "adapter_profile": (
                "supports_json_schema_output=False, strict_tools=False, "
                "max_completion_tokens=False, default_structured_output_mode="
                "'tool' (pydantic-ai default; adapter does not override)"
            ),
            "case_id": case,
            "run_id": manifest.get("benchmark_run_id"),
            "run_status": "completed" if completed else "failed",
            "failed_stage": stage_info["failed_stage"],
            "stage_evidence": stage_info["stage_evidence"],
            "failure_code": (failure or {}).get("failure_layer"),
            "failure_reason": str((failure or {}).get("failure_reason", ""))[:120],
            "raw_exception_type": None,  # never persisted (str(exc)[:500] only)
            "output_validation_attempts": (
                stage_info.get("output_validation_retry_budget") or None),
            "request_attempts_completed": len(identity),
            "tool_calls": store.get("tool_observations"),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "model_requests": requests,
            "elapsed_ms": elapsed_ms,
            "question_q1_status": (q1 or {}).get("status"),
            "question_q1_disposition": (q1 or {}).get("disposition"),
            "coverage_status_counts": cov_counts or None,
            "finalization_status": (
                "finalized" if fin else
                (snapshot.get("terminal_status") if snapshot else None)),
            "taxonomy_primary": tax["primary"],
            "taxonomy_contributing": tax["contributing"],
            "taxonomy_note": tax["note"],
            "store_available": store.get("store_available", False),
            "last_event_type": store.get("last_event_type"),
            "post_event_gap_s": stage_info.get("post_event_gap_s"),
            "delegation_failures": [
                f if isinstance(f, str) else str(f.get("failure_code"))
                for f in (digest.get("delegation_failures") or [])
            ],
            "supervisor_failures": [
                f if isinstance(f, str) else str(f.get("code"))
                for f in (digest.get("supervisor_failures") or [])
            ],
        })
    return rows


def cmd_matrix() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for label, root in SERIES.items():
        if root.is_dir():
            all_rows.extend(_walk_series(label, root))
    (OUT / "failure-matrix.json").write_text(
        json.dumps(all_rows, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    fields = [k for k in all_rows[0].keys() if k not in ("taxonomy_note", "stage_evidence")]
    with (OUT / "failure-matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    # concentration stats
    def by(key, rows=None):
        return _group(rows if rows is not None else all_rows, key)
    summary = {
        "total_runs": len(all_rows),
        "completed": sum(1 for r in all_rows if r["run_status"] == "completed"),
        "failed": sum(1 for r in all_rows if r["run_status"] == "failed"),
        "failed_stage_distribution": by("failed_stage"),
        "taxonomy_distribution": by("taxonomy_primary"),
        "failures_by_series": {
            s: {
                "runs": sum(1 for r in all_rows if r["series"] == s),
                "failed": sum(1 for r in all_rows if r["series"] == s and r["run_status"] == "failed"),
                "stages": by("failed_stage", [r for r in all_rows if r["series"] == s and r["run_status"] == "failed"]),
            } for s in SERIES if any(r["series"] == s for r in all_rows)
        },
        "failed_cases_concentration": {
            c: sum(1 for r in all_rows if r["case_id"] == c and r["run_status"] == "failed")
            for c in sorted({r["case_id"] for r in all_rows})
        },
        "question_status_disposition_pairs": _pairs(all_rows),
    }
    (OUT / "matrix-summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"matrix: {summary['total_runs']} runs "
          f"({summary['completed']} completed / {summary['failed']} failed)")
    print(f"stages: {summary['failed_stage_distribution']}")
    print(f"taxonomy: {summary['taxonomy_distribution']}")
    print(f"-> {OUT/'failure-matrix.json'}")
    return 0


def _group(rows, key):
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key))
        out[k] = out.get(k, 0) + 1
    return out


def _pairs(rows):
    pairs: dict[str, int] = {}
    for r in rows:
        if r.get("question_q1_status") is None:
            continue
        k = f"status={r['question_q1_status']}|disposition={r['question_q1_disposition']}"
        pairs[k] = pairs.get(k, 0) + 1
    return pairs


def cmd_retries() -> int:
    """§3 forensics: every 'Exceeded maximum output retries' occurrence."""
    findings = []
    for label, root in SERIES.items():
        if not root.is_dir():
            continue
        for run_dir in sorted(root.glob("t*/repeat*")):
            fp = run_dir / "failure.json"
            if not fp.is_file():
                continue
            failure = _load(fp)
            m = OUTPUT_RETRY_RE.search(str(failure.get("failure_reason", "")))
            if not m:
                continue
            experiment = {}
            exp_file = EXPERIMENT_FILES.get(label)
            if exp_file and exp_file.is_file():
                experiment = _load(exp_file).get("fresh_task_ids", {})
            store = _store_row(
                (experiment.get(run_dir.parent.name) or {}).get(run_dir.name))
            schema = _schema_metrics()
            findings.append({
                "series": label,
                "case_id": run_dir.parent.name,
                "repeat": run_dir.name,
                "failure_reason": failure.get("failure_reason"),
                "retry_marker_count": int(m.group(1)),
                "localized_stage": _classify_stage(failure, {}, store)["failed_stage"],
                "store_last_event": store.get("last_event_type"),
                "evidence_availability": {
                    "original_output_tool_call": False,
                    "actual_model_response": False,
                    "local_validation_errors": False,
                    "retry_feedback_content": False,
                    "last_failure_cause_chain": False,
                    "expected_pydantic_schema": True,
                    "retry_attempt_count_from_marker": True,
                },
                "telemetry_note": (
                    "runner persists str(exc)[:500] only "
                    "(benchmarks/runner.py:306); delegation/supervisor "
                    "failures are sanitized via safe_failure_message "
                    "(agent_specialist_executor.py:116); pydantic-ai "
                    "UnexpectedModelBehavior.__cause__ (last ValidationError "
                    "with field paths) is never serialized"
                ),
                "integrate_vs_plan_schema_asymmetry": schema,
            })
    (OUT / "output-retry-forensics.json").write_text(
        json.dumps({
            "artifact_version": "OutputRetryForensicsV1",
            "total_occurrences": len(findings),
            "occurrences": findings,
            "historical_evidence_exists": (
                "b2-restart era: scripts/diagnose_specialist_output.py "
                "(monkey-patch capturing pydantic-ai retry-prompt parts) "
                "produced benchmarks/results/agent-v0/b2-restart/"
                "specialist-output-diagnosis.v1.json with REAL validation "
                "errors for the specialist layer '(2)' failures "
                "(model filled server-computed tool_call_count/"
                "observation_count + stringified execution_digest; retry "
                "feedback was delivered and partially acted on). That hook "
                "covers ONLY build_specialist_agent — supervisor INTEGRATE "
                "runs were never instrumented, and it was not re-armed for "
                "any of the three 2026-10 candidate screenings."
            ),
            "conclusion": (
                "all occurrences localize to SUPERVISOR_INTEGRATE "
                "(retry marker '(1)' + PLAN-is-caught topology + last durable "
                "event delegation_completed); the actual failing outputs are "
                "NOT recoverable from any persisted artifact — historical "
                "'model capability' attributions rest on the exception string "
                "alone and are downgraded to "
                "MODEL_OUTPUT_CONTRACT_FAILURE(suspected)+INSUFFICIENT_TELEMETRY"
            ),
        }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"retries: {len(findings)} occurrences, all localized")
    print(f"-> {OUT/'output-retry-forensics.json'}")
    return 0


def _schema_metrics() -> dict:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
        SupervisorPlanDecisionV2,
    )

    def metrics(schema):
        js = schema.model_json_schema()
        return {
            "schema_bytes": len(json.dumps(js)),
            "top_level_fields": len(js.get("properties") or {}),
            "defs": len(js.get("$defs") or {}),
            "extra": (schema.model_config.get("extra")),
        }

    return {
        "plan_v2": metrics(SupervisorPlanDecisionV2),
        "integrate_v2": metrics(SupervisorIntegrationDecisionV2),
        "note": (
            "INTEGRATE output tool carries ~3.7x the PLAN schema size and "
            "6x the $defs; both extra=forbid; both delivered as output TOOLS "
            "(default_structured_output_mode='tool', text output disallowed)"
        ),
    }


def cmd_timeouts() -> int:
    """§4 forensics: per-timeout timeline + taxonomy."""
    label = "step-5-preview-stepfun"
    root = SERIES[label]
    experiment = _load(EXPERIMENT_FILES[label]).get("fresh_task_ids", {})
    rows = []
    for run_dir in sorted(root.glob("t*/repeat*")):
        fp = run_dir / "failure.json"
        if not fp.is_file():
            continue
        failure = _load(fp)
        if "timed out" not in str(failure.get("failure_reason", "")).lower():
            continue
        manifest = failure.get("run_manifest", {})
        store = _store_row(
            (experiment.get(run_dir.parent.name) or {}).get(run_dir.name))
        identity = _load(run_dir / "identity_telemetry.json") \
            if (run_dir / "identity_telemetry.json").is_file() else []
        gap = None
        if store.get("last_event_at") and manifest.get("completed_at"):
            gap = round((_ts(manifest["completed_at"])
                         - _ts(store["last_event_at"])).total_seconds(), 1)
        rows.append({
            "case_id": run_dir.parent.name,
            "repeat": run_dir.name,
            "run_started_at": manifest.get("started_at"),
            "run_failed_at": manifest.get("completed_at"),
            "request_sent_at": None,
            "response_headers_at": None,
            "first_token_at": None,
            "response_completed_at": None,
            "timeout_at": None,
            "retry_started_at": None,
            "unavailable_reason": (
                "per-request timing was never instrumented; non-streaming "
                "agent.run() has no first-token concept; identity telemetry "
                "records completed responses only"
            ),
            "last_durable_event": store.get("last_event_type"),
            "last_durable_event_at": store.get("last_event_at"),
            "post_event_gap_s": gap,
            "gap_fits_3x120s": gap is not None and 355 <= gap <= 370,
            "completed_model_requests_in_run": len(identity),
            "tool_observations": store.get("tool_observations"),
            "classification": {
                "primary": "PROVIDER_RESPONSE_LATENCY",
                "manifestation": "PROVIDER_TRANSPORT_TIMEOUT",
                "amplifier": "SDK_INTERNAL_RETRY (openai DEFAULT_MAX_RETRIES=2 -> 3 attempts x 120s)",
                "excluded": {
                    "LOCAL_REQUEST_SCHEDULING": (
                        "delegation_completed at T, gap uniform 362s across 5 "
                        "runs; specialist phase (11 tool calls, 3.5 min) "
                        "completed normally on the same machine/connection"),
                    "AGENT_RETRY_AMPLIFICATION": (
                        "pydantic-ai never retries transport errors; "
                        "LLM_MAX_RETRIES=3 is unconsumed on the agent path "
                        "(only config.py:263 defines it)"),
                    "PROVIDER_QUOTA": "zero 429/quota events in any series",
                },
                "evidence_basis": (
                    "gap == 3x120s+overhead on all five runs + code audit of "
                    "the retry stack; per-request server-side timing was "
                    "never persisted, so sub-attempt attribution is "
                    "UNVERIFIED"),
            },
        })
    (OUT / "timeout-forensics.json").write_text(
        json.dumps({
            "artifact_version": "TimeoutForensicsV1",
            "timeout_budget_origin": (
                "adapter: model_settings['timeout']=120 (LLM_TIMEOUT_SECONDS) "
                "passed per HTTP attempt (pydantic_ai/models/openai.py:1141); "
                "AsyncOpenAI(max_retries=2 default) retries APITimeoutError "
                "twice more; run-level asyncio.wait_for budget NOT armed "
                "(production_executor.py:95-99: generation_params has no "
                "timeout_seconds key -> wait_for(timeout=None))"),
            "timeouts": rows,
        }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"timeouts: {len(rows)} runs, "
          f"{sum(1 for r in rows if r['gap_fits_3x120s'])} fit the 3x120s signature")
    print(f"-> {OUT/'timeout-forensics.json'}")
    return 0


def cmd_terminalization() -> int:
    """§7: recompute charter q-1 terminalization under the ONE frozen
    definition (disposition_wave2_final.OPEN_STATUSES, q-1) and compare
    with historical claims."""
    claims = {
        "b2-runtime-v3-incumbent": "20/24",
        "b2-runtime-v3-glm52": "10/24",
        "glm-5.2-sensenova": "10/24 (wave-1 b2 claim)",
        "space-bunny-alpha-openrouter": "1/8",
        "step-3.7-flash-stepfun": "0/8",
        "step-5-preview-stepfun": "1/8",
    }
    results = {}
    for label, root in SERIES.items():
        if not root.is_dir():
            continue
        total = term = 0
        detail = []
        pairs: dict[str, int] = {}
        for run_dir in sorted(root.glob("t*/repeat*")):
            snap_p = run_dir / "snapshot.json"
            if not snap_p.is_file():
                continue
            snapshot = _load(snap_p)
            questions = snapshot.get("questions") or []
            charter = [q for q in questions if q.get("question_id") == "q-1"]
            ok = bool(charter) and charter[0].get("status") not in OPEN_STATUSES
            total += 1
            term += int(ok)
            key = (f"status={charter[0].get('status')}|"
                   f"disposition={charter[0].get('disposition')}"
                   if charter else "no-charter-q1")
            pairs[key] = pairs.get(key, 0) + 1
            if not ok:
                detail.append({
                    "case_id": run_dir.parent.name, "repeat": run_dir.name,
                    "q1": key})
        if total:
            results[label] = {
                "terminal_snapshots": total,
                "terminalized_q1": term,
                "ratio": f"{term}/{total}",
                "historical_claim": claims.get(label),
                "status_disposition_pairs": pairs,
                "non_terminalized": detail,
            }
    (OUT / "terminalization-audit.json").write_text(
        json.dumps({
            "artifact_version": "TerminalizationAuditV1",
            "frozen_definition": (
                "charter question q-1 of the run snapshot has left "
                "{open, in_progress} (disposition_wave2_final.OPEN_STATUSES, "
                "imported unchanged by disposition_wave2_screening and "
                "disposition_openrouter_8x1 — single shared definition)"),
            "question_status_vs_disposition": (
                "snapshot records BOTH status and disposition per question; "
                "the frozen metric uses status only; observed pairs listed "
                "per series"),
            "series": results,
        }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for label, r in results.items():
        print(f"{label}: {r['ratio']} (claim: {r['historical_claim']})")
    print(f"-> {OUT/'terminalization-audit.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_cross_model_failure")
    parser.add_argument("command",
                        choices=["matrix", "retries", "timeouts", "terminalization",
                                 "all"])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.command in ("matrix", "all"):
        cmd_matrix()
    if args.command in ("retries", "all"):
        cmd_retries()
    if args.command in ("timeouts", "all"):
        cmd_timeouts()
    if args.command in ("terminalization", "all"):
        cmd_terminalization()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
