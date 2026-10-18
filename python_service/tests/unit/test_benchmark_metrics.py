"""Deterministic metric engine tests (P8A §90-§97)."""

from __future__ import annotations

import pytest

from httpserver.services.benchmarks.availability import (
    resolve_reachability_record,
)
from httpserver.services.benchmarks.metrics import (
    BenchmarkResultV1,
    METRIC_SPECS,
    FailureLayer,
    assertion_overstatement_rate,
    attribute_missed_critical_evidence,
    causal_overreach_rate,
    correlation_recall,
    critical_evidence_recall,
    duplicate_call_rate,
    false_entity_merge_rate,
    metric_spec,
    premature_closure_rate,
    productive_tool_call_ratio,
    question_disposition_accuracy,
    relevant_evidence_precision,
    structural_hard_gates,
    time_to_first_critical_evidence_ms,
    unjustified_coverage_closure,
    unsupported_fact_rate,
)
from httpserver.services.benchmarks.snapshot import (
    BenchmarkRunSnapshotV1,
    SnapshotToolCallV1,
)
from httpserver.services.benchmarks.truth_manifest import (
    ReachabilityManifestV1,
    TruthManifestV1,
)


def _manifest() -> TruthManifestV1:
    def ev(eid, criticality):
        return {
            "truth_evidence_id": eid,
            "evidence_identity_description": eid,
            "criticality": criticality,
            "parser_expectation": "reachable",
        }

    return TruthManifestV1(
        case_id="c",
        case_version="1",
        critical_evidence=(
            ev("E1", "critical"),
            ev("E2", "critical"),
            ev("E3", "critical"),
        ),
        supporting_evidence=(ev("E4", "supporting"),),
        irrelevant_evidence=(ev("E9", "irrelevant"),),
        expected_questions=(
            {
                "question_id": "q1",
                "text": "answered one",
                "expected_disposition": "answered",
            },
            {
                "question_id": "q2",
                "text": "unresolved one",
                "expected_disposition": "unresolved",
            },
        ),
        confirmed_claims=(
            {
                "claim_id": "c1",
                "proposition": "A file was transferred.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
            },
            {
                "claim_id": "c2",
                "proposition": "Transfer happened on device one.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
            },
        ),
        acceptable_inferences=(),
        unsupported_or_prohibited_overclaims=(
            {
                "claim_id": "x1",
                "proposition": "The user maliciously exfiltrated data.",
                "truth_status": "unsupported",
                "semantic_type": "intent",
            },
        ),
        expected_relations=(
            {
                "relation_id": "r1",
                "subject_entity": "user:a",
                "relation_family": "communicated_with",
                "object_entity": "user:b",
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
            },
            {
                "relation_id": "r2",
                "subject_entity": "user:alice",
                "relation_family": "same_person",
                "object_entity": "user:bob",
                "truth_status": "unsupported",
            },
        ),
        expected_coverage=(
            {
                "dimension_id": "cov1",
                "expected_status": "covered",
                "requires_closure_basis": True,
            },
        ),
    )


def _reachability(manifest, override=None):
    override = override or {}
    records = []
    for item in manifest.all_evidence_items():
        spec = override.get(
            item.truth_evidence_id,
            (True, True, ("key-" + item.truth_evidence_id,)),
        )
        records.append(
            resolve_reachability_record(
                truth_evidence_id=item.truth_evidence_id,
                resolved_evidence_keys=spec[2],
                parser_reachable=spec[0],
                agent_discoverable=spec[1],
                unavailable_reason=spec[3] if len(spec) > 3 else "",
            )
        )
    return ReachabilityManifestV1(case_id="c", records=records)


def _snapshot(**overrides):
    payload = dict(
        run_id="r",
        task_id="task-1",
        investigation_id="inv-1",
        terminal_status="completed",
        discovered_evidence_refs=("key-E1", "key-E2", "key-E9"),
        evidence_first_seen_seq={"key-E1": 2, "key-E2": 5, "key-E9": 9},
        tool_calls=(
            SnapshotToolCallV1(
                seq=1,
                tool_id="search_contacts",
                result_count=1,
                evidence_refs=("key-E1",),
                args_normalized={"query": "a"},
            ),
            SnapshotToolCallV1(
                seq=2,
                tool_id="search_contacts",
                result_count=0,
                args_normalized={"query": "a"},
            ),
        ),
        questions=(
            {"question_id": "q1", "status": "answered"},
            {"question_id": "q2", "status": "unresolved"},
        ),
        coverage=(
            {
                "dimension_id": "cov1",
                "status": "not_applicable",
                "capability_basis": None,
            },
        ),
        findings=(
            {
                "finding_id": "f1",
                "text": "A file was transferred.",
                "assertion_class": "INFERENCE",
                "status": "review_pending",
                "truth_claim_id": "c1",
            },
            {
                "finding_id": "f2",
                "text": "The user maliciously exfiltrated data.",
                "assertion_class": "FACT",
                "status": "review_pending",
                "semantic_type": "intent",
            },
        ),
        correlations=(
            {
                "subject_entity": "user:a",
                "relation_family": "communicated_with",
                "object_entity": "user:b",
            },
            {
                "subject_entity": "user:alice",
                "relation_family": "same_person",
                "object_entity": "user:bob",
            },
        ),
        wall_ms_total=10_000,
    )
    payload.update(overrides)
    return BenchmarkRunSnapshotV1(**payload)


# ---------------------------------------------------------------------------
# §90 evidence metrics
# ---------------------------------------------------------------------------


def test_critical_recall_and_denominators():
    manifest = _manifest()
    reachability = _reachability(
        manifest, {"E3": (False, False, (), "no parser")}
    )
    snapshot = _snapshot()
    recall = critical_evidence_recall(manifest, reachability, snapshot)
    # E3 is parser-unreachable -> excluded from the denominator
    assert recall.denominator == 2
    assert recall.numerator == 2
    assert recall.value == 1.0
    from httpserver.services.benchmarks.availability import (
        compute_availability_summary,
    )

    summary = compute_availability_summary(manifest, reachability)
    assert summary.critical_ground_truth_reachability == pytest.approx(
        2 / 3
    )


def test_irrelevant_discovery_lowers_precision():
    manifest = _manifest()
    reachability = _reachability(manifest)
    snapshot = _snapshot()
    precision = relevant_evidence_precision(manifest, reachability, snapshot)
    # relevant = E1+E2; irrelevant E9 also discovered -> 2/3
    assert precision.value == pytest.approx(2 / 3)


def test_duplicate_representation_counted_once():
    manifest = _manifest()
    reachability = _reachability(manifest)
    snapshot = _snapshot(
        discovered_evidence_refs=(
            "key-E1",
            "key-E1",
            "key-E2",
        ),
    )
    recall = critical_evidence_recall(manifest, reachability, snapshot)
    assert recall.numerator == 2


# ---------------------------------------------------------------------------
# §91 assertion metrics
# ---------------------------------------------------------------------------


def test_unsupported_fact_detected():
    manifest = _manifest()
    snapshot = _snapshot()
    rate = unsupported_fact_rate(manifest, snapshot)
    # the only FACT finding (f2) matches no confirmed claim -> 1.0;
    # f1 is an INFERENCE and never enters this denominator
    assert rate.value == pytest.approx(1.0)
    assert rate.denominator == 1


def test_fact_over_inference_truth_detected():
    manifest = _manifest()
    snapshot = _snapshot(
        findings=(
            {
                "finding_id": "f1",
                "text": "A file was transferred.",
                "assertion_class": "FACT",
                "status": "review_pending",
                "truth_claim_id": "c1",
            },
        ),
    )
    rate = assertion_overstatement_rate(manifest, snapshot)
    assert rate.value == 1.0
    assert rate.numerator == 1


def test_correct_hypothesis_on_indeterminate_not_penalized():
    manifest = _manifest()
    snapshot = _snapshot(
        findings=(
            {
                "finding_id": "f1",
                "text": "A file was transferred.",
                "assertion_class": "HYPOTHESIS",
                "status": "review_pending",
                "truth_claim_id": "c1",
            },
        ),
    )
    rate = assertion_overstatement_rate(manifest, snapshot)
    assert rate.value == 0.0


def test_causal_overreach_detected():
    manifest = _manifest()
    snapshot = _snapshot()
    rate = causal_overreach_rate(manifest, snapshot)
    assert rate.value == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# §92 question / coverage
# ---------------------------------------------------------------------------


def test_question_disposition_correct_answered_and_unresolved():
    manifest = _manifest()
    snapshot = _snapshot()
    accuracy = question_disposition_accuracy(manifest, snapshot)
    assert accuracy.value == 1.0


def test_premature_closure_detected():
    manifest = _manifest()
    snapshot = _snapshot(
        questions=(
            {"question_id": "q1", "status": "answered"},
            {"question_id": "q2", "status": "answered"},
        ),
    )
    rate = premature_closure_rate(manifest, snapshot)
    assert rate.value == 1.0


def test_unjustified_not_applicable_closure():
    manifest = _manifest()
    snapshot = _snapshot()
    rate = unjustified_coverage_closure(manifest, snapshot)
    assert rate.value == 1.0
    justified = _snapshot(
        coverage=(
            {
                "dimension_id": "cov1",
                "status": "not_applicable",
                "capability_basis": "no sms parser in profile",
            },
        ),
    )
    assert unjustified_coverage_closure(manifest, justified).value == 0.0


# ---------------------------------------------------------------------------
# §93 correlation
# ---------------------------------------------------------------------------


def test_correlation_recall_and_false_merge():
    manifest = _manifest()
    snapshot = _snapshot()
    assert correlation_recall(manifest, snapshot).value == 1.0
    merge = false_entity_merge_rate(manifest, snapshot)
    assert merge.value == pytest.approx(1.0)
    clean = _snapshot(
        correlations=(
            {
                "subject_entity": "user:a",
                "relation_family": "communicated_with",
                "object_entity": "user:b",
            },
        ),
    )
    assert false_entity_merge_rate(manifest, clean).status == "unavailable"


# ---------------------------------------------------------------------------
# §95 process metrics
# ---------------------------------------------------------------------------


def test_productive_duplicate_and_zero_yield_distinction():
    manifest = _manifest()
    snapshot = _snapshot()
    # call 1 productive (new evidence), call 2 zero-result (not a failure)
    ratio = productive_tool_call_ratio(snapshot)
    assert ratio.value == pytest.approx(0.5)
    dup = duplicate_call_rate(snapshot)
    # identical tool + args -> the second of the two successful calls
    # duplicates the first -> 1 duplicate / 2 calls
    assert dup.value == pytest.approx(0.5)
    assert dup.numerator == 1


def test_failure_not_counted_as_zero_yield():
    manifest = _manifest()
    snapshot = _snapshot(
        tool_calls=(
            SnapshotToolCallV1(
                seq=1,
                tool_id="search_contacts",
                result_count=0,
                evidence_refs=("key-E1",),
            ),
            SnapshotToolCallV1(
                seq=2,
                tool_id="search_contacts",
                result_count=0,
            ),
        ),
    )
    ratio = productive_tool_call_ratio(snapshot)
    # zero-result is still a successful call (§41); failures would be
    # excluded entirely
    assert ratio.denominator == 2


def test_time_to_first_critical_evidence():
    manifest = _manifest()
    reachability = _reachability(manifest)
    snapshot = _snapshot()
    value = time_to_first_critical_evidence_ms(
        manifest, reachability, snapshot
    )
    assert value.status == "available"
    assert value.value == pytest.approx(10_000 * 2 / 10)


# ---------------------------------------------------------------------------
# §96 failure attribution
# ---------------------------------------------------------------------------


def test_failure_layers_distinguished():
    manifest = _manifest()
    reachability = _reachability(
        manifest,
        {
            "E3": (False, False, (), "no parser"),
            "E2": (True, False, ("key-E2",)),
            "E1": (True, True, ("key-E1",)),
        },
    )
    snapshot = _snapshot(
        discovered_evidence_refs=("key-E4",),
        evidence_first_seen_seq={"key-E4": 1},
    )
    attributions = attribute_missed_critical_evidence(
        manifest, reachability, snapshot
    )
    layers = {
        a.what_failed.split(":")[1].strip(): a.layer
        for a in attributions
    }
    assert layers["E3"] == FailureLayer.PARSER
    assert layers["E2"] == FailureLayer.TOOL_EXPOSURE
    assert layers["E1"] == FailureLayer.RETRIEVAL


def test_grounding_and_verifier_layers_available():
    assert FailureLayer.GROUNDING.value == "GROUNDING"
    assert FailureLayer.SEMANTIC_VERIFICATION.value == (
        "SEMANTIC_VERIFICATION"
    )
    assert FailureLayer.REPORT_WRITER.value == "REPORT_WRITER"


# ---------------------------------------------------------------------------
# §51 hard gates + §50 result
# ---------------------------------------------------------------------------


def test_structural_hard_gates_pass_clean_snapshot():
    snapshot = _snapshot()
    gates = structural_hard_gates(snapshot)
    assert all(gate.passed for gate in gates)


def test_graph_id_evidence_trips_hard_gate():
    snapshot = _snapshot(
        discovered_evidence_refs=("graph:abc", "key-E1"),
    )
    gates = structural_hard_gates(snapshot)
    graph_gate = next(
        g for g in gates if g.gate_id == "no_graph_id_as_evidence"
    )
    assert not graph_gate.passed


def test_agent_terminal_finding_trips_hard_gate():
    snapshot = _snapshot(
        findings=(
            {
                "finding_id": "f1",
                "text": "x",
                "assertion_class": "FACT",
                "status": "accepted",
            },
        ),
    )
    gates = structural_hard_gates(snapshot)
    gate = next(g for g in gates if g.gate_id == "no_agent_accept_reject")
    assert not gate.passed


def test_result_hash_stable_no_aggregate_score():
    manifest = _manifest()
    reachability = _reachability(manifest)
    snapshot = _snapshot()
    result = BenchmarkResultV1(
        run_manifest_id="brun:1",
        run_manifest_hash="r" * 64,
        truth_manifest_id=manifest.manifest_id,
        truth_manifest_hash=manifest.input_hash,
        snapshot_hash=snapshot.snapshot_hash,
        quality_metrics={
            "critical_evidence_recall": critical_evidence_recall(
                manifest, reachability, snapshot
            ).model_dump(mode="json"),
        },
    )
    replay = BenchmarkResultV1(**result.model_dump(mode="json"))
    assert replay.result_hash == result.result_hash
    assert "tracelensscore" not in result.model_dump_json().lower()


def test_missing_data_is_unavailable_not_zero():
    manifest = _manifest()
    snapshot = _snapshot(findings=(), tool_calls=())
    rate = unsupported_fact_rate(manifest, snapshot)
    assert rate.status == "unavailable"
    assert rate.value is None
    ratio = productive_tool_call_ratio(snapshot)
    assert ratio.status == "unavailable"
    specs = {spec.metric_id: spec for spec in METRIC_SPECS}
    assert "parser_reachable" in (
        specs["critical_evidence_recall"].denominator_definition
    )
