"""P5A §54 deterministic correlation tests."""

import pytest

from httpserver.services.investigation.agent_correlation import (
    CausalStatus,
    CorrelationBounds,
    CorrelationCandidateV1,
    DeterministicCorrelationEngine,
)
from httpserver.services.investigation.agent_entities import (
    EntityOccurrenceV1,
    EntityTemporalRef,
    derive_occurrence_id,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "c" * 8

_RULE_PRIORITY = {
    "same_content_hash": 0,
    "normalized_identifier_match": 1,
    "composite_account_match": 2,
    "url_domain_structure": 3,
    "structured_co_occurrence": 4,
    "temporal_overlap": 5,
}


def _occ(
    entity_type,
    raw,
    normalized,
    match_key,
    namespace,
    ref,
    *,
    start=None,
    end=None,
    auto=False,
):
    occurrence_id = derive_occurrence_id(
        task_id=TASK_ID,
        evidence_ref=ref,
        entity_type=entity_type,
        source_field="t",
        raw_value=raw,
        normalized_value=normalized,
        role="mention",
    )
    return EntityOccurrenceV1(
        occurrence_id=occurrence_id,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        source_scope_id="scope-1",
        evidence_ref=ref,
        entity_type=entity_type,
        raw_value=raw,
        normalized_value=normalized,
        match_key=match_key,
        namespace=namespace,
        role="mention",
        temporal=(
            EntityTemporalRef(kind="evidence_mtime", start=start, end=end)
            if start is not None else None
        ),
        source_field="t",
        provenance={
            "auto_link_allowed": auto,
            "identity_class": (
                "strong_identifier" if auto else "scoped_identifier"
            ),
        },
    )


def _hash(ref, value="ab" * 32, **kwargs):
    return _occ(
        "file_hash", value, value.lower(), f"hash|sha256|{value.lower()}",
        "hash:sha256", ref, auto=True, **kwargs,
    )


def test_exact_hash_match_candidate():
    engine = DeterministicCorrelationEngine()
    candidates = engine.generate([_hash("file:C/1.iso"), _hash("file:D/2.iso")])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.relation_family == "same_content_hash"
    assert candidate.derivation.value == "deterministic_match"
    assert candidate.assertion_hint.value == "inference"
    assert candidate.evidence_refs == ("file:C/1.iso", "file:D/2.iso")
    assert "no transfer/copy action is asserted" in candidate.limitations[0]


def test_normalized_identifier_match():
    email_a = _occ(
        "email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
        "file:C/a.eml",
    )
    email_b = _occ(
        "email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
        "file:C/b.eml",
    )
    candidates = DeterministicCorrelationEngine().generate([email_a, email_b])
    assert len(candidates) == 1
    assert candidates[0].relation_family == "normalized_identifier_match"


def test_composite_account_match():
    account_a = _occ(
        "user_account", "CORP\\john", "corp\\john",
        "account|corp/john", "account:composite", "file:C/1.log",
    )
    account_b = _occ(
        "user_account", "corp\\john", "corp\\john",
        "account|corp/john", "account:composite", "file:C/2.log",
    )
    candidates = DeterministicCorrelationEngine().generate(
        [account_a, account_b]
    )
    assert len(candidates) == 1
    assert candidates[0].relation_family == "composite_account_match"
    assert "not a proof of the same natural person" in (
        candidates[0].limitations[0]
    )


def test_url_domain_structural_relation():
    domain = _occ(
        "domain", "evil.example", "evil.example", "domain|evil.example",
        "domain:global", "file:C/dns.log",
    )
    url = _occ(
        "url", "http://evil.example/x", "http://evil.example/x",
        "url|http://evil.example/x", "url:global", "file:C/props.csv",
    )
    candidates = DeterministicCorrelationEngine().generate([domain, url])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.relation_family == "url_domain_structure"
    assert {candidate.subject_ref, candidate.object_ref} == {
        domain.occurrence_id, url.occurrence_id,
    }


def test_structured_co_occurrence_is_artifact_explicit_observed():
    email = _occ(
        "email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
        "file:C/doc.txt",
    )
    phone = _occ(
        "phone", "+1555010", "+1555010", "phone|+1555010", "phone:global",
        "file:C/doc.txt",
    )
    candidates = DeterministicCorrelationEngine().generate([email, phone])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.relation_family == "structured_co_occurrence"
    assert candidate.derivation.value == "artifact_explicit"
    assert candidate.assertion_hint.value == "observed"


def test_temporal_overlap_candidate_is_never_causal():
    left = _hash("file:C/1.iso", start=1_700_000_000, end=1_700_000_100)
    right = _hash("file:D/2.iso", value="cd" * 32,
                  start=1_700_000_120, end=1_700_000_200)
    email = _occ(
        "email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
        "file:C/a.eml", start=1_700_000_000, end=1_700_000_050,
    )
    candidates = DeterministicCorrelationEngine(
        bounds=CorrelationBounds(temporal_window_seconds=600),
    ).generate([left, right, email])
    temporal = [
        candidate for candidate in candidates
        if candidate.relation_family == "temporal_overlap"
    ]
    assert temporal, "expected bounded temporal overlap candidates"
    for candidate in temporal:
        assert candidate.causal_status is CausalStatus.NOT_ASSESSED
        assert candidate.assertion_hint.value == "hypothesis"
        assert "never causal" in candidate.limitations[0]
        assert candidate.temporal_relation.window_seconds == 600
    # every candidate in the engine obeys the §20 assertion boundary
    allowed_causal = {"not_assessed", "non_causal", "causal_hypothesis"}
    assert all(
        candidate.causal_status.value in allowed_causal
        for candidate in candidates
    )


def test_temporal_beyond_window_generates_no_candidate():
    left = _hash("file:C/1.iso", start=1_700_000_000, end=1_700_000_100)
    right = _occ(
        "email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
        "file:C/a.eml", start=1_700_100_000, end=1_700_100_050,
    )
    candidates = DeterministicCorrelationEngine(
        bounds=CorrelationBounds(temporal_window_seconds=600),
    ).generate([left, right])
    assert all(
        candidate.relation_family != "temporal_overlap"
        for candidate in candidates
    )


def test_candidate_ordering_deterministic_under_input_shuffle():
    occurrences = [
        _hash("file:C/1.iso"),
        _hash("file:D/2.iso"),
        _occ("email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
             "file:C/a.eml"),
        _occ("email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
             "file:C/b.eml"),
        _occ("domain", "evil.example", "evil.example",
             "domain|evil.example", "domain:global", "file:C/dns.log"),
        _occ("url", "http://evil.example/x", "http://evil.example/x",
             "url|http://evil.example/x", "url:global", "file:C/props.csv"),
    ]
    engine = DeterministicCorrelationEngine()
    forward = engine.generate(occurrences)
    backward = engine.generate(list(reversed(occurrences)))
    assert forward == backward
    # ordering is rule priority first, correlation_id second
    assert [candidate.correlation_id for candidate in forward] == [
        candidate.correlation_id
        for candidate in sorted(
            forward,
            key=lambda item: (
                _RULE_PRIORITY[item.relation_family], item.correlation_id
            ),
        )
    ]


def test_max_candidate_bound_respected():
    occurrences = [
        _hash(f"file:C/{index}.iso") for index in range(10)
    ]
    engine = DeterministicCorrelationEngine(
        bounds=CorrelationBounds(max_candidates=5)
    )
    candidates = engine.generate(occurrences)
    assert len(candidates) == 5


def test_weak_identifiers_never_bucket_into_identifier_matches():
    same_ip = [
        _occ("ip", "10.0.0.1", "10.0.0.1", "ip|10.0.0.1", "ip:network", ref)
        for ref in ("file:C/a.log", "file:C/b.log")
    ]
    bare_users = [
        _occ("user_account", "administrator", "administrator",
             "account|-/administrator", "account:bare", ref)
        for ref in ("file:C/a.log", "file:C/b.log")
    ]
    candidates = DeterministicCorrelationEngine().generate(
        same_ip + bare_users
    )
    # only the intra-evidence co-occurrence pairs remain; no identifier
    # buckets were formed from weak namespaces
    assert all(
        candidate.relation_family == "structured_co_occurrence"
        for candidate in candidates
    )


def test_cross_investigation_input_rejected():
    stray = _occ(
        "email", "a@x.com", "a@x.com", "email|a@x.com", "email:global",
        "file:C/a.eml",
    )
    stray = stray.model_copy(
        update={"investigation_id": "inv-" + "d" * 8}
    )
    normal = _occ(
        "email", "b@x.com", "b@x.com", "email|b@x.com", "email:global",
        "file:C/b.eml",
    )
    with pytest.raises(ValueError):
        DeterministicCorrelationEngine().generate([stray, normal])


def test_candidate_persistence_idempotent_and_roundtrip(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    db = tmp_path / "investigation.db"
    repo = AgentRuntimeRepository(InvestigationRepository(db, TASK_ID))
    repo.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
                objective="corr",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )

    engine = DeterministicCorrelationEngine()
    candidates = engine.generate(
        [_hash("file:C/1.iso"), _hash("file:D/2.iso")]
    )
    rows = [candidate.to_row() for candidate in candidates]
    first = repo.record_correlation_candidates(INVESTIGATION_ID, rows)
    assert first["inserted_count"] == 1
    second = repo.record_correlation_candidates(INVESTIGATION_ID, rows)
    assert second["inserted_count"] == 0
    assert second["duplicate_count"] == 1

    persisted = repo.list_correlation_candidates(INVESTIGATION_ID)
    restored = [CorrelationCandidateV1.from_row(row) for row in persisted]
    assert tuple(restored) == candidates

    events = repo.list_trajectory(INVESTIGATION_ID)
    recorded = [
        event for event in events
        if event.event_type.value == "correlation_candidates_recorded"
    ]
    assert len(recorded) == 2
    assert recorded[0].payload["inserted_count"] == 1
    assert "relation_family" not in recorded[0].payload
