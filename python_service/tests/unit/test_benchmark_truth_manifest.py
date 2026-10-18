"""Truth Manifest / availability / case contract tests (P8A §87-§88)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from httpserver.services.benchmarks.availability import (
    AvailabilitySummary,
    compute_availability_summary,
    parser_reachable_critical_ids,
    resolve_reachability_record,
)
from httpserver.services.benchmarks.benchmark_case import (
    BenchmarkCaseV1,
    BenchmarkTier,
    DatasetFileRefV1,
    DatasetManifestV1,
    NegativeCaseFlagsV1,
    verify_dataset_files,
)
from httpserver.services.benchmarks.truth_manifest import (
    AssertionClass,
    ClaimSemanticType,
    EvidenceCriticality,
    ParserExpectation,
    QuestionDispositionExpectation,
    ReachabilityManifestV1,
    ReachabilityStatus,
    TruthClaimV1,
    TruthStatus,
    TruthManifestV1,
)


def _evidence(eid="E1", criticality=EvidenceCriticality.critical):
    return {
        "truth_evidence_id": eid,
        "evidence_identity_description": "SMS from sender 13800 on 2026-01-05 21:04",
        "criticality": criticality,
        "parser_expectation": ParserExpectation.reachable,
        "source_kind": "mmssms_test.db",
        "semantic_role": "transfer_record",
    }


def _manifest(**overrides) -> TruthManifestV1:
    payload = dict(
        case_id="case-demo",
        case_version="1",
        critical_evidence=(_evidence("E1"), _evidence("E2")),
        supporting_evidence=(_evidence("E3", EvidenceCriticality.supporting),),
        irrelevant_evidence=(_evidence("E9", EvidenceCriticality.irrelevant),),
        expected_questions=(
            {
                "question_id": "q1",
                "text": "Was the file transferred?",
                "expected_disposition": QuestionDispositionExpectation.answered,
            },
            {
                "question_id": "q2",
                "text": "Who received the file?",
                "expected_disposition": QuestionDispositionExpectation.unresolved,
            },
        ),
        confirmed_claims=(
            {
                "claim_id": "c-transfer",
                "proposition": "A file was transferred between the two devices.",
                "truth_status": TruthStatus.confirmed,
                "maximum_assertion_class": AssertionClass.FACT,
                "required_evidence_ids": ("E1",),
            },
        ),
        acceptable_inferences=(
            {
                "claim_id": "c-same-device",
                "proposition": "The two accounts were used on one device.",
                "truth_status": TruthStatus.confirmed,
                "maximum_assertion_class": AssertionClass.INFERENCE,
                "required_evidence_ids": ("E1", "E2"),
            },
        ),
        unsupported_or_prohibited_overclaims=(
            {
                "claim_id": "c-intent",
                "proposition": "The transfer was malicious exfiltration.",
                "truth_status": TruthStatus.unsupported,
                "semantic_type": ClaimSemanticType.intent,
            },
        ),
        expected_relations=(
            {
                "relation_id": "r1",
                "subject_entity": "user:a",
                "relation_family": "communicated_with",
                "object_entity": "user:b",
                "truth_status": TruthStatus.confirmed,
                "maximum_assertion_class": AssertionClass.INFERENCE,
                "expected_evidence_ids": ("E1",),
            },
            {
                "relation_id": "r2",
                "subject_entity": "user:alice",
                "relation_family": "same_person",
                "object_entity": "user:bob",
                "truth_status": TruthStatus.unsupported,
            },
        ),
        expected_coverage=(
            {
                "dimension_id": "cov-messages",
                "expected_status": "covered",
                "requires_closure_basis": True,
            },
        ),
        known_ambiguities=("two devices share one Wi-Fi SSID",),
        unavailable_truth=("exact device owner identity",),
    )
    payload.update(overrides)
    return TruthManifestV1(**payload)


# ---------------------------------------------------------------------------
# §87 Truth Manifest tests
# ---------------------------------------------------------------------------


def test_valid_manifest_roundtrip_and_hash_stable():
    manifest = _manifest()
    replay = TruthManifestV1(**manifest.model_dump(mode="json"))
    assert replay.input_hash == manifest.input_hash
    assert replay.manifest_id == manifest.manifest_id
    # canonical ordering: groups and ids are hash-stable regardless of
    # input order
    reordered = TruthManifestV1(
        **{
            **manifest.model_dump(mode="json"),
            "critical_evidence": tuple(
                reversed(manifest.critical_evidence)
            ),
        }
    )
    assert reordered.input_hash == manifest.input_hash


def test_duplicate_truth_evidence_id_rejected():
    with pytest.raises(ValidationError):
        _manifest(supporting_evidence=(_evidence("E1", EvidenceCriticality.supporting),))


def test_item_cannot_be_critical_and_supporting():
    with pytest.raises(ValidationError):
        _manifest(supporting_evidence=(_evidence("E1"),))


def test_duplicate_claim_and_question_ids_rejected():
    with pytest.raises(ValidationError):
        _manifest(
            confirmed_claims=(
                {
                    "claim_id": "c-x",
                    "proposition": "A",
                    "truth_status": TruthStatus.confirmed,
                    "maximum_assertion_class": AssertionClass.FACT,
                },
            ),
            acceptable_inferences=(
                {
                    "claim_id": "c-x",
                    "proposition": "B",
                    "truth_status": TruthStatus.confirmed,
                    "maximum_assertion_class": AssertionClass.INFERENCE,
                },
            ),
        )
    with pytest.raises(ValidationError):
        TruthManifestV1(
            case_id="c",
            case_version="1",
            expected_questions=(
                {
                    "question_id": "q1",
                    "text": "a",
                    "expected_disposition": "answered",
                },
                {
                    "question_id": "q1",
                    "text": "b",
                    "expected_disposition": "unresolved",
                },
            ),
        )


def test_invalid_evidence_criticality_rejected():
    with pytest.raises(ValidationError):
        TruthManifestV1(
            case_id="c",
            case_version="1",
            critical_evidence=(
                {
                    "truth_evidence_id": "E1",
                    "evidence_identity_description": "x",
                    "criticality": "super_critical",
                    "parser_expectation": "reachable",
                },
            ),
        )


def test_unsupported_claim_with_required_evidence_rejected():
    with pytest.raises(ValidationError):
        TruthClaimV1(
            claim_id="c-bad",
            proposition="X",
            truth_status=TruthStatus.unsupported,
            maximum_assertion_class=AssertionClass.FACT,
            required_evidence_ids=("E1",),
        )


def test_confirmed_claim_requires_ceiling():
    with pytest.raises(ValidationError):
        TruthClaimV1(
            claim_id="c-bad",
            proposition="X",
            truth_status=TruthStatus.confirmed,
        )


def test_indeterminate_supported_and_ambiguity_persisted():
    manifest = _manifest(
        confirmed_claims=(),
        acceptable_inferences=(
            {
                "claim_id": "c-ind",
                "proposition": "Unknown whether X occurred.",
                "truth_status": TruthStatus.indeterminate,
            },
        ),
    )
    assert manifest.acceptable_inferences[0].truth_status == (
        TruthStatus.indeterminate
    )
    assert manifest.known_ambiguities == ("two devices share one Wi-Fi SSID",)
    assert manifest.unavailable_truth == ("exact device owner identity",)


def test_claim_unknown_evidence_reference_rejected():
    with pytest.raises(ValidationError):
        _manifest(
            confirmed_claims=(
                {
                    "claim_id": "c-ghost",
                    "proposition": "X",
                    "truth_status": TruthStatus.confirmed,
                    "maximum_assertion_class": AssertionClass.FACT,
                    "required_evidence_ids": ("E-nope",),
                },
            )
        )


# ---------------------------------------------------------------------------
# §8/§10/§11 availability tests
# ---------------------------------------------------------------------------


def _reachability(manifest, mapping):
    records = []
    for item in manifest.all_evidence_items():
        spec = mapping.get(
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
    return ReachabilityManifestV1(
        case_id=manifest.case_id, records=records
    )


def test_ground_truth_but_parser_unavailable_is_parser_limitation():
    manifest = _manifest()
    reachability = _reachability(
        manifest, {"E1": (False, False, (), "no parser for this format")}
    )
    summary = compute_availability_summary(manifest, reachability)
    # ground truth says 2 critical; parser reaches only E2
    assert summary.critical_ground_truth == 2
    assert summary.critical_parser_reachable == 1
    assert summary.critical_ground_truth_reachability == 0.5
    # E1 must NOT count as an agent discovery failure
    assert "E1" not in parser_reachable_critical_ids(manifest, reachability)
    assert parser_reachable_critical_ids(manifest, reachability) == frozenset(
        {"E2"}
    )


def test_parser_reachable_but_tool_not_exposed():
    manifest = _manifest()
    reachability = _reachability(
        manifest, {"E2": (True, False, ("key-E2",))}
    )
    record = next(
        r
        for r in reachability.records
        if r.truth_evidence_id == "E2"
    )
    assert record.status == ReachabilityStatus.tool_not_exposed
    assert record.parser_reachable is True
    assert record.agent_discoverable is False
    # §30 denominator: parser-reachable critical includes it (the agent
    # CAN be blamed for not using a tool that exists); the TOOL_EXPOSURE
    # gap is separately visible in the record status.
    assert "E2" in parser_reachable_critical_ids(manifest, reachability)


def test_discoverable_implies_parser_reachable():
    with pytest.raises(ValidationError):
        resolve_reachability_record(
            truth_evidence_id="E1",
            resolved_evidence_keys=("k",),
            parser_reachable=False,
            agent_discoverable=True,
        )


def test_resolved_requires_keys_and_reason_for_unresolved():
    from httpserver.services.benchmarks.truth_manifest import (
        EvidenceReachabilityRecordV1,
    )

    # the MODEL rejects a "resolved" record without keys...
    with pytest.raises(ValidationError):
        EvidenceReachabilityRecordV1(
            truth_evidence_id="E1",
            resolved_evidence_keys=(),
            parser_reachable=True,
            agent_discoverable=True,
            status=ReachabilityStatus.resolved,
        )
    # ...and the resolver maps keys-less reachable items to unresolved
    # with an explanatory reason rather than a silent resolved row.
    record = resolve_reachability_record(
        truth_evidence_id="E1",
        resolved_evidence_keys=(),
        parser_reachable=True,
        agent_discoverable=True,
    )
    assert record.status == ReachabilityStatus.unresolved
    assert record.unavailable_reason
    record = resolve_reachability_record(
        truth_evidence_id="E1",
        resolved_evidence_keys=(),
        parser_reachable=False,
        agent_discoverable=False,
        unavailable_reason="format unsupported",
    )
    assert record.unavailable_reason == "format unsupported"


def test_summary_counts_supporting_and_irrelevant_separately():
    manifest = _manifest()
    reachability = _reachability(manifest, {})
    summary = compute_availability_summary(manifest, reachability)
    assert summary.supporting_ground_truth == 1
    assert summary.irrelevant_ground_truth == 1
    assert summary.critical_agent_discoverable == 2
    assert isinstance(summary, AvailabilitySummary)


# ---------------------------------------------------------------------------
# §18-§20 benchmark case contract tests
# ---------------------------------------------------------------------------


def _dataset(tmp_path=None):
    return DatasetManifestV1(
        dataset_id="demo-ds",
        files=(
            DatasetFileRefV1(
                logical_id="sms-db",
                relative_path="mmssms_test.db",
                size_bytes=4,
                sha256="a" * 64,
            ),
        ),
    )


def test_case_contract_roundtrip_hash_stable():
    case = BenchmarkCaseV1(
        case_version="1",
        title="Demo transfer case",
        dataset=_dataset(),
        truth_manifest_id="tman:1",
        truth_manifest_hash="h" * 64,
        goal="Determine whether a file was transferred.",
        case_context="Two seized phones.",
        platform_composition=("android", "ios"),
        tier=BenchmarkTier.T1,
        benchmark_tags=("smoke",),
    )
    replay = BenchmarkCaseV1(**case.model_dump(mode="json"))
    assert replay.input_hash == case.input_hash
    assert replay.case_id == case.case_id


def test_case_requires_goal():
    with pytest.raises(ValidationError):
        BenchmarkCaseV1(
            case_version="1",
            title="x",
            dataset=_dataset(),
            truth_manifest_id="tman:1",
            truth_manifest_hash="h" * 64,
            goal="  ",
            tier=BenchmarkTier.T1,
        )


def test_dataset_hash_stable_and_file_hash_enforced():
    ds = _dataset()
    replay = DatasetManifestV1(**ds.model_dump(mode="json"))
    assert replay.dataset_hash == ds.dataset_hash
    with pytest.raises(ValidationError):
        DatasetFileRefV1(
            logical_id="x",
            relative_path="x",
            size_bytes=1,
            sha256="short",
        )


def test_verify_dataset_files_detects_violations(tmp_path):
    ds = DatasetManifestV1(
        dataset_id="d",
        files=(
            DatasetFileRefV1(
                logical_id="a",
                relative_path="a.bin",
                size_bytes=4,
                sha256="b" * 64,
            ),
        ),
    )
    violations = verify_dataset_files(ds, tmp_path)
    assert any("missing file" in v for v in violations)
    (tmp_path / "a.bin").write_bytes(b"abcd")
    violations = verify_dataset_files(ds, tmp_path)
    assert any("sha256 mismatch" in v for v in violations)
    import hashlib

    good = DatasetManifestV1(
        dataset_id="d2",
        files=(
            DatasetFileRefV1(
                logical_id="a",
                relative_path="a.bin",
                size_bytes=4,
                sha256=hashlib.sha256(b"abcd").hexdigest(),
            ),
        ),
    )
    assert verify_dataset_files(good, tmp_path) == []


def test_negative_flags_default_false():
    flags = NegativeCaseFlagsV1()
    assert not flags.same_username_different_person
    assert not flags.misleading_case_context
