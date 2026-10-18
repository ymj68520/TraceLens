from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = ROOT / "benchmarks/audits/rca2a7-stepfun-vocabulary-comparison/run_experiment.py"
SPEC = importlib.util.spec_from_file_location("rca2a7_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(runner)


def test_balanced_order_is_amended_and_bounded():
    assert runner.PAIRS == (("C", "T"), ("T", "C"), ("T", "C"), ("C", "T"))
    assert sum(len(pair) for pair in runner.PAIRS) == 8
    assert runner.REQUEST_BUDGET["logical_model_generations_max"] == 16
    assert runner.REQUEST_BUDGET["diagnostic_http_attempts_max"] == 48
    assert runner.REQUEST_BUDGET["preflight_http_attempts_max"] == 9


def test_schema_validation_groups_union_errors_per_payload():
    payload = {
        "actions": [{
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "completed",
        }]
    }
    result = runner._validate_payload(payload)
    assert result["passed"] is False
    assert result["union_cascade_payload"] is True
    assert len(result["error_groups"]) == 1
    assert any(
        error["type"] == "enum"
        for error in result["error_groups"][0]["errors"]
    )


def test_targeted_field_scan_is_payload_level_and_checks_handles():
    payload = {
        "actions": [{
            "action_type": "update_question",
            "handle": "Q1",
            "status": "completed",
            "to_status": "completed",
            "disposition": "no_evidence_found",
            "basis_handles": ["E999"],
        }]
    }
    result = runner._scan_payload(payload, {"Q1", "E1"})
    assert result["to_status_completed"] == 1
    assert result["invalid_disposition"] == 1
    assert result["wrong_action_field_name"] == 1
    assert result["unknown_handle"] == 1
    assert result["fabricated_evidence_like_identifier"] == 1


def test_exclusive_json_refuses_existing_artifact(tmp_path):
    output = tmp_path / "record.json"
    output.write_text("original", encoding="utf-8")
    with pytest.raises(SystemExit, match="OUTPUT_REFUSED_NO_CLOBBER"):
        runner._exclusive_json(output, {"changed": True})
    assert output.read_text(encoding="utf-8") == "original"


def test_retry_accounting_distinguishes_logical_from_http_attempts():
    assert runner.REQUEST_BUDGET["sdk_max_retries"] == 2
    assert runner.REQUEST_BUDGET["sdk_http_attempts_per_logical_request_max"] == 3
    assert runner.REQUEST_BUDGET["diagnostic_http_attempts_max"] == 16 * 3
    assert runner.REQUEST_BUDGET["preflight_http_attempts_max"] == 3 * 3
