"""B7/B8 final acceptance artifact tests (§74/§76/§77, §91/§94)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from httpserver.services.benchmarks.acceptance import (
    AcceptanceDisposition,
)
from httpserver.services.benchmarks.final_report import (
    BenchmarkAcceptanceReportV1,
    ExternalValidationItemV1,
    KnownLimitationsV1,
    ModelSupportEntryV1,
    ModelSupportTier,
    SupportedResourceEnvelopeV1,
)


def _report(**kw):
    payload = dict(
        git_baseline="f13ffd89",
        corpus_id="bcorpus:1",
        corpus_hash="c" * 64,
        hard_gate_results=(
            {"gate_id": "no_cross_task_evidence_leak", "passed": True},
            {"gate_id": "no_graph_id_as_evidence", "passed": True},
        ),
        disposition=AcceptanceDisposition.PASS.value,
    )
    payload.update(kw)
    return BenchmarkAcceptanceReportV1(**payload)


def test_report_content_addressed_and_score_free():
    report = _report()
    replay = BenchmarkAcceptanceReportV1(**report.model_dump(mode="json"))
    assert replay.report_hash == report.report_hash
    dumped = report.model_dump_json().lower()
    assert "score" not in dumped  # §73: no aggregate score anywhere


def test_disposition_must_be_exact():
    with pytest.raises(ValidationError):
        _report(disposition="looks good")


def test_blocking_external_validation_forbids_pass():
    with pytest.raises(ValidationError):
        _report(
            limitations=KnownLimitationsV1(
                external_validations=(
                    ExternalValidationItemV1(
                        item="Graphiti external backend",
                        reason="not reachable from this environment",
                        blocking=True,
                    ),
                )
            ),
        )


def test_pass_with_limitations_allowed_for_non_blocking_gaps():
    report = _report(
        disposition=AcceptanceDisposition.PASS_WITH_LIMITATIONS.value,
        limitations=KnownLimitationsV1(
            external_validations=(
                ExternalValidationItemV1(
                    item="T4 large-case acceptance",
                    reason="no suitable forensic image available",
                    blocking=False,
                ),
            )
        ),
    )
    assert report.disposition == "PASS_WITH_LIMITATIONS"


def test_hard_gate_failure_visible_in_summary():
    report = _report(
        hard_gate_results=(
            {"gate_id": "no_agent_accept_reject", "passed": False},
        ),
        disposition=AcceptanceDisposition.FAIL.value,
        disposition_reason="structural zero-tolerance gate violation",
    )
    summary = report.human_summary()
    assert "FAIL" in summary
    assert "no_agent_accept_reject" in summary


def test_model_support_tiers_recorded_not_generalized():
    report = _report(
        model_support=(
            ModelSupportEntryV1(
                provider="deepseek",
                model_id="deepseek-flash",
                tier=ModelSupportTier.validated,
            ),
            ModelSupportEntryV1(
                provider="any-openai-compatible",
                model_id="*",
                tier=ModelSupportTier.provisional,
            ),
        ),
    )
    summary = report.human_summary()
    assert "deepseek/deepseek-flash: validated" in summary
    assert "provisional" in summary


def test_resource_envelope_records_not_promotes():
    envelope = SupportedResourceEnvelopeV1(
        ram_recommended_gb=16.0,
        measured_on="dev host 32GB — context only, NOT a requirement",
    )
    assert envelope.gpu_required is False
    assert "NOT a requirement" in envelope.measured_on


def test_report_summary_consistent_with_machine_data():
    report = _report(
        limitations=KnownLimitationsV1(
            items=("per-observation durations unavailable",)
        ),
    )
    summary = report.human_summary()
    assert "1 recorded" in summary
