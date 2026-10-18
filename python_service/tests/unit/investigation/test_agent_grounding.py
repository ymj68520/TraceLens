"""P5A §56/§57 grounding validator + visibility authority tests, §65
explicit pipeline entry, and the §61 Working-State revision invariance."""

import pytest

from httpserver.services.investigation.agent_claims import (
    ProposedClaimV1,
    ProposalNormalizer,
)
from httpserver.services.investigation.agent_grounding import (
    DeterministicGroundingValidator,
    EvidenceRefPolicy,
    GroundingStatus,
    process_specialist_proposals,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
    SpecialistClaimCandidate,
    SpecialistEntityCandidate,
    SpecialistResultV1,
)
from httpserver.services.investigation.agent_tools.visibility import (
    reconstruct_allowed_evidence_ids,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "f" * 8

_VALID_RESOLVABLE = {"file:C/a.doc", "file:C/b.doc",
                     "file:C/iso.img", "cluster:v1:1700000000:login"}


async def _resolver(task_id, evidence_ref):
    if task_id != TASK_ID:
        return None
    return {"source_mtime": 123} if evidence_ref in _VALID_RESOLVABLE else None


def _proposal(
    refs=("file:C/a.doc",),
    assertion=AssertionClass.INFERENCE,
    text="a finding",
    task_id=TASK_ID,
    investigation_id=INVESTIGATION_ID,
) -> ProposedClaimV1:
    return ProposedClaimV1(
        task_id=task_id,
        investigation_id=investigation_id,
        proposal_id="",  # derived
        text=text,
        assertion_class=assertion,
        evidence_refs=refs,
        input_hash="",  # derived
    )


def _validator() -> DeterministicGroundingValidator:
    return DeterministicGroundingValidator()


def _ground(proposal, allowed, task_id=TASK_ID):
    return _validator().validate(
        proposal,
        task_id=task_id,
        investigation_id=proposal.investigation_id,
        allowed_evidence_ids=frozenset(allowed),
        evidence_resolver=_resolver,
    )


async def test_valid_visible_evidence_is_grounded():
    result = await _ground(_proposal(), {"file:C/a.doc"})
    assert result.status is GroundingStatus.GROUNDED
    assert result.valid_evidence_refs == ("file:C/a.doc",)
    assert result.effective_assertion_class is AssertionClass.INFERENCE


async def test_well_formed_but_invisible_is_ungrounded():
    result = await _ground(_proposal(refs=("file:C/b.doc",)), set())
    assert result.status is GroundingStatus.UNGROUNDED
    assert result.invisible_evidence_refs == ("file:C/b.doc",)


async def test_mixed_valid_and_invisible_is_partially_grounded():
    result = await _ground(
        _proposal(refs=("file:C/a.doc", "file:C/b.doc")), {"file:C/a.doc"}
    )
    assert result.status is GroundingStatus.PARTIALLY_GROUNDED
    assert result.valid_evidence_refs == ("file:C/a.doc",)
    assert result.invisible_evidence_refs == ("file:C/b.doc",)


async def test_malformed_key_is_invalid():
    result = await _ground(_proposal(refs=("not-an-evidence-key",)), set())
    assert result.status is GroundingStatus.INVALID
    assert result.invalid_evidence_refs == ("not-an-evidence-key",)


async def test_cross_task_provenance_is_invalid():
    result = await _ground(
        _proposal(task_id="task-OTHER"), {"file:C/a.doc"}
    )
    assert result.status is GroundingStatus.INVALID


async def test_unresolvable_same_task_ref_is_ungrounded():
    result = await _ground(_proposal(refs=("file:C/ghost.doc",)), set())
    assert result.status is GroundingStatus.UNGROUNDED
    assert result.invalid_evidence_refs == ("file:C/ghost.doc",)


async def test_observation_graph_and_llm_text_cannot_masquerade():
    for fake in (
        "obs:abc123",
        "graph:node-9",
        "llm-summary-text",
        "analysis:42",
    ):
        result = await _ground(_proposal(refs=(fake,)), set())
        assert result.status is GroundingStatus.INVALID, fake


async def test_fact_with_zero_valid_refs_downgrades():
    result = await _ground(
        _proposal(assertion=AssertionClass.FACT), set()
    )
    assert result.input_assertion_class is AssertionClass.FACT
    assert result.effective_assertion_class is AssertionClass.HYPOTHESIS
    assert "GROUNDING_FACT_DOWNGRADED_NO_VALID_EVIDENCE" in result.warnings
    assert result.status is GroundingStatus.UNGROUNDED


async def test_overstating_claim_is_still_grounded():
    """P5A grounding performs NO semantic sufficiency: an overreaching
    claim over valid, visible evidence is still grounded."""
    result = await _ground(
        _proposal(
            text="the suspect definitely exfiltrated everything",
            refs=("file:C/a.doc",),
        ),
        {"file:C/a.doc"},
    )
    assert result.status is GroundingStatus.GROUNDED


async def test_grounding_id_deterministic_and_visibility_sensitive():
    proposal = _proposal()
    first = await _ground(proposal, {"file:C/a.doc"})
    second = await _ground(proposal, {"file:C/a.doc"})
    wider = await _ground(proposal, {"file:C/a.doc", "file:C/b.doc"})
    assert first.grounding_id == second.grounding_id
    assert first.grounding_id != wider.grounding_id  # visibility moved it


# ---------------------------------------------------------------------------
# §57 visibility authority from durable provenance
# ---------------------------------------------------------------------------


def _observation(delegation_id, *refs, observation_id="obs-1"):
    from httpserver.services.investigation.agent_runtime import (
        ToolObservation,
    )

    return ToolObservation(
        observation_id=observation_id,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        run_id="run-1",
        delegation_id=delegation_id,
        tool_id="search_evidence",
        summary="s",
        result={},
        evidence_refs=tuple(refs),
        result_count=len(refs),
        truncated=False,
        created_at="2026-09-23T00:00:00+00:00",
    )


def test_contextpack_initial_refs_and_successful_observations_visible():
    allowed = reconstruct_allowed_evidence_ids(
        ("file:C/a.doc",),
        [_observation("dlg-1", "file:C/obs.doc")],
        delegation_id="dlg-1",
    )
    assert allowed == frozenset({"file:C/a.doc", "file:C/obs.doc"})


def test_failed_observation_refs_never_become_visible():
    # a failed tool call is never persisted as an observation, so its refs
    # simply do not exist in the durable record — model that by absence
    allowed = reconstruct_allowed_evidence_ids(
        ("file:C/a.doc",),
        [],  # no observation rows at all
        delegation_id="dlg-1",
    )
    assert "file:C/failed.doc" not in allowed


def test_result_text_and_candidate_text_add_no_visibility():
    """SpecialistResult / CorrelationCandidate text carries no authority:
    only initial refs + observation refs enter the ledger."""
    allowed = reconstruct_allowed_evidence_ids(
        ("file:C/a.doc",),
        [_observation("dlg-1", "file:C/obs.doc")],
        delegation_id="dlg-1",
    )
    assert "file:C/mentioned-in-text.doc" not in allowed


def test_cross_delegation_visibility_not_silently_shared():
    observations = [
        _observation("dlg-1", "file:C/obs1.doc", observation_id="o1"),
        _observation("dlg-2", "file:C/obs2.doc", observation_id="o2"),
    ]
    own = reconstruct_allowed_evidence_ids(
        ("file:C/a.doc",), observations, delegation_id="dlg-1"
    )
    assert "file:C/obs2.doc" not in own
    assert "file:C/obs1.doc" in own


def test_restart_reconstructs_same_visibility(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
        DelegationSpec,
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
                objective="vis",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    run = repo.start_run(INVESTIGATION_ID)
    repo.mark_run_running(run.run_id)
    delegation = repo.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1")]
    )[0]
    scope = repo.record_delegation_evidence_scope(
        INVESTIGATION_ID, delegation.delegation_id,
        initial_evidence_refs=("file:C/a.doc",), input_hash="h1",
    )
    repo.record_tool_observation(
        INVESTIGATION_ID,
        tool_id="search_evidence",
        summary="s",
        result={},
        evidence_refs=("file:C/obs.doc",),
        run_id=run.run_id,
        delegation_id=delegation.delegation_id,
    )

    # restart: same reconstruction from durable rows only
    reopened = AgentRuntimeRepository(InvestigationRepository(db, TASK_ID))
    durable_scope = reopened.get_delegation_evidence_scope(
        delegation.delegation_id
    )
    observations = [
        observation
        for observation in reopened.list_tool_observations(INVESTIGATION_ID)
        if observation.delegation_id == delegation.delegation_id
    ]
    allowed = reconstruct_allowed_evidence_ids(
        durable_scope.initial_evidence_refs,
        observations,
        delegation_id=delegation.delegation_id,
    )
    assert allowed == frozenset({"file:C/a.doc", "file:C/obs.doc"})
    assert scope.initial_evidence_refs == ("file:C/a.doc",)


# ---------------------------------------------------------------------------
# §65 explicit pipeline entry + §61 revision invariance
# ---------------------------------------------------------------------------


def _pipeline_repo(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
        DelegationSpec,
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
                objective="pipe",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    run = repo.start_run(INVESTIGATION_ID)
    repo.mark_run_running(run.run_id)
    delegation = repo.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1")]
    )[0]
    repo.record_delegation_evidence_scope(
        INVESTIGATION_ID, delegation.delegation_id,
        initial_evidence_refs=("file:C/a.doc", "file:C/iso.img"),
        input_hash="h-scope",
    )
    repo.record_tool_observation(
        INVESTIGATION_ID,
        tool_id="search_evidence",
        summary="s",
        result={},
        evidence_refs=("file:C/b.doc",),
        run_id=run.run_id,
        delegation_id=delegation.delegation_id,
    )
    return repo, delegation.delegation_id


def _pipeline_result(delegation_id):
    return SpecialistResultV1(
        delegation_id=delegation_id,
        summary="s",
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1",
                text="suspicious logon observed",
                assertion_class=AssertionClass.INFERENCE,
                evidence_refs=("file:C/a.doc", "file:C/b.doc"),
            ),
        ),
        entity_candidates=(
            SpecialistEntityCandidate(
                candidate_id="e-1",
                raw_value="ab" * 32,
                entity_type_candidate="file_hash",
                evidence_refs=("file:C/iso.img",),
            ),
        ),
    )


async def test_process_specialist_proposals_end_to_end(tmp_path):
    from httpserver.services.investigation.agent_entities import (
        build_occurrences_from_specialist_result,
    )
    from httpserver.services.investigation.agent_identity import IdentityPolicy

    repo, delegation_id = _pipeline_repo(tmp_path)
    result = _pipeline_result(delegation_id)

    report = await process_specialist_proposals(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        results=[result],
        evidence_resolver=_resolver,
    )
    assert report.proposals_recorded == 1
    assert report.grounding_by_status["grounded"] == 1

    stored = repo.list_grounding_results(INVESTIGATION_ID)
    assert len(stored) == 1
    assert stored[0]["status"] == "grounded"
    # visibility = scope initial refs ∪ observation refs
    assert sorted(stored[0]["valid_evidence_refs"]) == [
        "file:C/a.doc", "file:C/b.doc",
    ]
    proposals = repo.list_claim_proposals(INVESTIGATION_ID)
    assert len(proposals) == 1

    # entity occurrence pipeline rides the same durable provenance: the
    # hash candidate's ref is inside the scope, so it verifies
    occurrences = await build_occurrences_from_specialist_result(
        result, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        source_scope_id="img-1", identity_policy=IdentityPolicy(),
        evidence_lookup=_resolver,
        allowed_evidence_ids=frozenset({
            "file:C/a.doc", "file:C/b.doc", "file:C/iso.img",
        }),
    )
    assert len(occurrences.occurrences) == 1

    # replay: idempotent proposals and grounding rows
    replay = await process_specialist_proposals(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        results=[result],
        evidence_resolver=_resolver,
    )
    assert replay.proposals_replayed == 1
    assert len(repo.list_claim_proposals(INVESTIGATION_ID)) == 1
    assert len(repo.list_grounding_results(INVESTIGATION_ID)) == 1

    # §61: P5A persistence never consumes Working State revision
    assert repo.get_working_state_revision(INVESTIGATION_ID, 1) is not None
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is None

    # trajectory: proposals + grounding audited, counts only
    events = repo.list_trajectory(INVESTIGATION_ID)
    kinds = {event.event_type.value for event in events}
    assert "claim_proposals_recorded" in kinds
    assert "claim_grounding_recorded" in kinds
    grounding_events = [
        event for event in events
        if event.event_type.value == "claim_grounding_recorded"
    ]
    assert "text" not in grounding_events[0].payload


async def test_correlation_derived_proposal_uses_explicit_provenance(tmp_path):
    from httpserver.services.investigation.agent_correlation import (
        CorrelationAssertionHint,
        CorrelationCandidateV1,
        CorrelationDerivation,
        CausalStatus,
    )
    from httpserver.services.investigation.agent_claims import (
        claim_from_correlation_candidate,
    )
    from httpserver.services.investigation.agent_entities import (
        EntityOccurrenceV1,
    )

    repo, _delegation_id = _pipeline_repo(tmp_path)

    def _occ(oid, ref):
        return EntityOccurrenceV1(
            occurrence_id=oid, task_id=TASK_ID,
            investigation_id=INVESTIGATION_ID, source_scope_id="s",
            evidence_ref=ref, entity_type="file_hash",
            raw_value="ab" * 32, normalized_value="ab" * 32,
            match_key="hash|sha256|" + "ab" * 32, namespace="hash:sha256",
            role="mention", source_field="t",
        )

    left, right = _occ("o-1", "file:C/a.doc"), _occ("o-2", "file:C/b.doc")
    candidate = CorrelationCandidateV1(
        correlation_id="corr-x",
        relation_family="same_content_hash",
        subject_ref="o-1",
        object_ref="o-2",
        derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
        assertion_hint=CorrelationAssertionHint.INFERENCE,
        evidence_refs=("file:C/a.doc", "file:C/b.doc"),
        support_types=("exact_hash",),
        limitations=(),
        causal_status=CausalStatus.NOT_ASSESSED,
        input_hash="h",
    )
    claim = claim_from_correlation_candidate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        occurrences={"o-1": left, "o-2": right},
    )
    # explicit §33 union provenance: both source occurrence refs
    report = await process_specialist_proposals(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        results=[],
        evidence_resolver=_resolver,
        extra_proposals=[claim],
        extra_proposal_provenance=[
            frozenset({"file:C/a.doc", "file:C/b.doc"})
        ],
    )
    assert report.grounding_by_status["grounded"] == 1
    stored = repo.list_grounding_results(INVESTIGATION_ID)
    assert stored[0]["proposal_id"] == claim.proposal_id
