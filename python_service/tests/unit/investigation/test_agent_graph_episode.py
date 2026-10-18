"""P6A §58 ForensicGraphEpisode tests: only-admitted freezing, canonical
hashing, immutability, micro-batch provenance, backend neutrality."""

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionDecisionV1,
    GraphAdmissionPolicy,
)
from httpserver.services.investigation.agent_graph_candidate import (
    GraphCandidateBuilder,
)
from httpserver.services.investigation.agent_graph_episode import (
    ForensicGraphEpisodeV1,
    freeze_episode,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "3" * 8

_BUILDER = GraphCandidateBuilder()
_POLICY = GraphAdmissionPolicy()


def _evidence_candidate(refs=("file:C/1.iso", "file:D/2.iso"),
                        summary="identical sha256 payload"):
    return _BUILDER.candidate_from_evidence_context(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        summary=summary,
        evidence_refs=refs,
    )


def _decision(candidate,
              decision=GraphAdmissionDecision.ADMIT) -> GraphAdmissionDecisionV1:
    raw = _POLICY.evaluate(candidate)
    if raw.decision is decision:
        return raw
    # synthesize a variant with the same binding shape for negative tests
    return raw.model_copy(update={"decision": decision})


def _decide_all(candidates, decision=GraphAdmissionDecision.ADMIT):
    return {
        candidate.candidate_id: _decision(candidate, decision)
        for candidate in candidates
    }


def _freeze(candidates, decisions, **overrides):
    kwargs = dict(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        source_revision=7,
        source_state_hash="s-hash",
        policy_version=_POLICY.policy_version,
        policy_hash=_POLICY.policy_hash(),
    )
    kwargs.update(overrides)
    return freeze_episode(candidates, decisions, **kwargs)


def test_only_admitted_candidates_can_freeze():
    candidate = _evidence_candidate()
    decisions = _decide_all([candidate], decision=GraphAdmissionDecision.DEFER)
    with pytest.raises(ValueError):
        _freeze([candidate], decisions)
    decisions = _decide_all(
        [candidate], decision=GraphAdmissionDecision.NOT_ADMITTED
    )
    with pytest.raises(ValueError):
        _freeze([candidate], decisions)
    # missing decision entirely
    with pytest.raises(ValueError):
        _freeze([candidate], {})


def test_candidate_set_ordering_is_hash_canonical():
    a = _evidence_candidate(refs=("file:C/1.iso",), summary="unit A")
    b = _evidence_candidate(refs=("file:D/2.iso",), summary="unit B")
    forward = _freeze([a, b], _decide_all([a, b]))
    backward = _freeze([b, a], _decide_all([a, b]))
    assert forward.episode_id == backward.episode_id
    assert forward.input_hash == backward.input_hash
    assert [u.unit_id for u in forward.semantic_units] == sorted(
        u.unit_id for u in forward.semantic_units
    )


def test_review_status_change_changes_episode_hash():
    pending = _finding_candidate(status="review_pending")
    accepted = _finding_candidate(status="accepted")
    first = _freeze([pending], _decide_all([pending]))
    second = _freeze([accepted], _decide_all([accepted]))
    assert first.input_hash != second.input_hash


def test_evidence_provenance_change_changes_hash():
    a = _evidence_candidate(refs=("file:C/1.iso",))
    b = _evidence_candidate(refs=("file:C/changed.iso",))
    episode_a = _freeze([a], _decide_all([a]))
    episode_b = _freeze([b], _decide_all([b]))
    assert episode_a.input_hash != episode_b.input_hash


def _finding_candidate(status):
    return _BUILDER.candidate_from_finding(
        {
            "finding_id": f"finding:{status}",
            "status": status,
            "evidence_refs": ("file:C/a.doc",),
            "semantic_verification_id": "sver-1",
            "text": "finding text",
            "limitations": (),
        },
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
    )


def test_micro_batch_preserves_assertion_evidence_map():
    a = _evidence_candidate(refs=("file:C/1.iso",), summary="unit A")
    b = _evidence_candidate(refs=("file:D/2.iso",), summary="unit B")
    episode = _freeze([a, b], _decide_all([a, b]))
    assert len(episode.semantic_units) == 2
    units = {unit.unit_id: unit for unit in episode.semantic_units}
    assert units[a.candidate_id].evidence_refs == ("file:C/1.iso",)
    assert units[b.candidate_id].evidence_refs == ("file:D/2.iso",)
    # provenance manifest maps every unit back to its admission decision
    manifest_ids = {
        item["unit_id"]: item["admission_decision_id"]
        for item in episode.provenance_manifest
    }
    assert manifest_ids[a.candidate_id] == (
        _decide_all([a])[a.candidate_id].decision_id
    )


def test_episode_carries_no_backend_binding():
    fields = set(ForensicGraphEpisodeV1.model_fields)
    backend_fields = {
        name for name in fields
        if any(token in name for token in
               ("graphiti", "neo4j", "cypher", "db_path", "backend",
                "callback", "repository"))
    }
    assert backend_fields == set()


def test_episode_persistence_idempotent(tmp_path):
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
                objective="ep",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    candidate = _evidence_candidate()
    episode = _freeze([candidate], _decide_all([candidate]))
    first = repo.record_graph_episodes(
        INVESTIGATION_ID, [episode.to_row()]
    )
    assert first["inserted_count"] == 1
    second = repo.record_graph_episodes(
        INVESTIGATION_ID, [episode.to_row()]
    )
    assert second["inserted_count"] == 0
    stored = repo.get_graph_episode(INVESTIGATION_ID, episode.episode_id)
    assert stored["input_hash"] == episode.input_hash
    assert stored["semantic_units"][0]["unit_id"] == candidate.candidate_id
