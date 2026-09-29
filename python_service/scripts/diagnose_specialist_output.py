#!/usr/bin/env python3
"""B2-restart diagnosis probe: capture RAW exceptions behind sanitized
`agent_output_invalid` / supervisor failure codes.

Runs ONE fresh benchmark case through the exact driver machinery
(scripts/run_p8b_baseline._run_one) with an observation-only monkeypatch on
``agent_specialist_executor.map_provider_exception``. The wrapper records
the original exception class, provider status code and message to a JSONL
diagnosis log before delegating to the real mapper. No production code is
modified; the patch lives only in this process.

Usage (from python_service/):
    .venv/bin/python scripts/diagnose_specialist_output.py \
        --model-config benchmarks/results/agent-v0/b2-restart/sensenova-6.8-flash-lite.model-config.json \
        --case t2-no-evidence
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
SCRIPTS_DIR = SCRIPT_PATH.parent
for p in (str(PYTHON_SERVICE_ROOT), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = PYTHON_SERVICE_ROOT.parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="diagnose_specialist_output")
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--case", default="t2-no-evidence")
    parser.add_argument(
        "--diag-log",
        default=(
            "benchmarks/results/agent-v0/b2-restart/smoke-deep/"
            "exception-diagnosis.jsonl"
        ),
    )
    args = parser.parse_args(argv)

    diag_path = Path(args.diag_log)
    if not diag_path.is_absolute():
        diag_path = PYTHON_SERVICE_ROOT / diag_path
    diag_path.parent.mkdir(parents=True, exist_ok=True)
    diag_file = diag_path.open("a", encoding="utf-8")

    import run_p8b_baseline as driver
    from httpserver.services.investigation import (
        agent_specialist_executor as executor_module,
    )

    original_mapper = executor_module.map_provider_exception

    def _logging_mapper(exc: Exception):
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "exception_class": type(exc).__name__,
            "module": type(exc).__module__,
            "status_code": getattr(exc, "status_code", None),
            "body": str(getattr(exc, "body", None))[:800],
            "message": str(exc)[:1200],
        }
        diag_file.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )
        diag_file.flush()
        return original_mapper(exc)

    executor_module.map_provider_exception = _logging_mapper

    # Wrap _guard so NO worker exception escapes unlogged (the guard itself
    # swallows exceptions into an outcome without ever logging them).
    _original_guard = executor_module.SpecialistDelegationExecutor._guard

    async def _logging_guard(self, envelope):
        try:
            outcome = await _original_guard(self, envelope)
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": "guard_outcome",
                "delegation_id": envelope.delegation_id[:24],
                "status": str(getattr(outcome, "status", None)),
                "failure_code": getattr(outcome, "failure_code", None),
                "failure_message": str(
                    getattr(outcome, "failure_message", None)
                )[:400],
            }
            diag_file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )
            diag_file.flush()
            return outcome
        except BaseException as exc:  # noqa: BLE001 - diagnose everything
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": "guard_exception",
                "delegation_id": envelope.delegation_id[:24],
                "exception_class": type(exc).__name__,
                "message": str(exc)[:800],
            }
            diag_file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )
            diag_file.flush()
            raise

    executor_module.SpecialistDelegationExecutor._guard = _logging_guard

    # Wrap build_specialist_agent so the pydantic-ai message history of
    # every specialist run is captured: RetryPrompt parts carry the exact
    # validation errors behind "Exceeded maximum output retries".
    from httpserver.services.investigation.agent_tools import (
        pydantic_bridge,
    )

    _original_builder = pydantic_bridge.build_specialist_agent

    def _dump_messages(tag: str, messages) -> None:
        for msg in messages:
            for part in getattr(msg, "parts", []) or []:
                kind = getattr(part, "part_kind", None)
                if kind == "retry-prompt":
                    diag_file.write(
                        json.dumps(
                            {
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "kind": "retry_prompt",
                                "tag": tag,
                                "tool_name": getattr(
                                    part, "tool_name", None
                                ),
                                "content": str(
                                    getattr(part, "content", "")
                                )[:1500],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                elif kind == "text":
                    text = str(getattr(part, "content", ""))
                    diag_file.write(
                        json.dumps(
                            {
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "kind": "model_text",
                                "tag": tag,
                                "length": len(text),
                                "head": text[:600],
                                "tail": text[-600:],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        diag_file.flush()

    def _wrapped_builder(pack, registry, *, model=None, output_type=None,
                         retries=None):
        agent = _original_builder(
            pack,
            registry,
            model=model,
            output_type=output_type,
            retries=retries,
        )
        original_run = agent.run

        async def _instrumented_run(*a, **kw):
            from pydantic_ai import capture_run_messages

            with capture_run_messages() as messages:
                result = await original_run(*a, **kw)
            _dump_messages("specialist", messages)
            return result

        agent.run = _instrumented_run
        return agent

    pydantic_bridge.build_specialist_agent = _wrapped_builder

    model_config = json.loads(
        Path(args.model_config).read_text(encoding="utf-8")
    )
    provision = driver._provision_fresh_task(args.case, "repeat9")
    task_id = provision["task_id"]
    print(f"[diag] task={task_id} staged={len(provision['staged'])}")
    outcome = driver._run_one(
        args.case,
        "repeat9",
        task_id,
        model_config=model_config,
        configuration_id="bconf-b2-restart-diagnosis",
        configuration_label="sensenova-diagnosis-probe",
    )
    status = outcome.get("status")
    print(f"[diag] outcome status: {status}")
    if status == "completed":
        delegs = outcome["snapshot"].delegations or []
        for d in delegs:
            d = d if isinstance(d, dict) else d.model_dump()
            print(
                f"  delegation {d.get('delegation_id', '')[:20]} status="
                f"{d.get('status')} failure={d.get('failure_code')}"
            )
    else:
        failure = outcome.get("failure")
        print(
            "[diag] failure_layer:",
            getattr(failure, "failure_layer", None),
            "| failure_reason:",
            str(getattr(failure, "failure_reason", ""))[:500],
        )
    diag_file.close()
    print(f"[diag] raw exception log -> {diag_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
