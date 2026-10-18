"""P5A §60 failure atomicity tests: proposal / grounding / bundle /
trajectory persistence is all-or-nothing; no dangling half-states."""

import sqlite3

import pytest

from httpserver.services.investigation.agent_claims import ProposedClaimV1
from httpserver.services.investigation.agent_grounding import (
    DeterministicGroundingValidator,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "2" * 8


async def _resolver(task_id, ref):
    return {"source_mtime": 1} if ref == "file:C/a.doc" else None


def _repo(tmp_path):
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
                objective="atomic",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo, db


def _proposal():
    return ProposedClaimV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text="a finding",
        assertion_class=AssertionClass.INFERENCE,
        evidence_refs=("file:C/a.doc",),
        input_hash="",
    )


async def _grounding(proposal):
    return await DeterministicGroundingValidator().validate(
        proposal,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        allowed_evidence_ids=frozenset({"file:C/a.doc"}),
        evidence_resolver=_resolver,
    )


async def test_grounded_unit_persists_all_rows(tmp_path):
    repo, _db = _repo(tmp_path)
    proposal = _proposal()
    grounding = await _grounding(proposal)
    outcome = repo.record_grounded_proposal(
        INVESTIGATION_ID,
        proposal_row=proposal.to_row(),
        grounding_row=grounding.to_row(),
    )
    assert outcome == {
        "proposal_inserted": True,
        "grounding_inserted": True,
        "bundle_inserted": False,
    }
    assert len(repo.list_claim_proposals(INVESTIGATION_ID)) == 1
    assert len(repo.list_grounding_results(INVESTIGATION_ID)) == 1


async def test_bad_grounding_row_rolls_back_proposal(tmp_path):
    repo, _db = _repo(tmp_path)
    proposal = _proposal()
    grounding = await _grounding(proposal)
    bad_row = dict(grounding.to_row())
    bad_row["status"] = "bogus"  # violates the CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_grounded_proposal(
            INVESTIGATION_ID,
            proposal_row=proposal.to_row(),
            grounding_row=bad_row,
        )
    # neither row exists: no dangling proposal without its grounding
    assert repo.list_claim_proposals(INVESTIGATION_ID) == []
    assert repo.list_grounding_results(INVESTIGATION_ID) == []


async def test_bad_proposal_row_rolls_back_grounding(tmp_path):
    repo, _db = _repo(tmp_path)
    proposal = _proposal()
    grounding = await _grounding(proposal)
    bad_proposal = proposal.to_row()
    del bad_proposal["text"]  # structurally invalid row
    with pytest.raises((KeyError, sqlite3.IntegrityError)):
        repo.record_grounded_proposal(
            INVESTIGATION_ID,
            proposal_row=bad_proposal,
            grounding_row=grounding.to_row(),
        )
    assert repo.list_claim_proposals(INVESTIGATION_ID) == []
    assert repo.list_grounding_results(INVESTIGATION_ID) == []


async def test_trajectory_failure_rolls_back_unit(tmp_path):
    repo, _db = _repo(tmp_path)
    proposal = _proposal()
    grounding = await _grounding(proposal)

    original = repo._append_trajectory_with_conn

    def _explode(*args, **kwargs):
        raise RuntimeError("injected trajectory failure")

    repo._append_trajectory_with_conn = _explode
    try:
        with pytest.raises(RuntimeError):
            repo.record_grounded_proposal(
                INVESTIGATION_ID,
                proposal_row=proposal.to_row(),
                grounding_row=grounding.to_row(),
            )
    finally:
        repo._append_trajectory_with_conn = original

    assert repo.list_claim_proposals(INVESTIGATION_ID) == []
    assert repo.list_grounding_results(INVESTIGATION_ID) == []
    kinds = [
        event.event_type.value
        for event in repo.list_trajectory(INVESTIGATION_ID)
    ]
    assert "claim_grounding_recorded" not in kinds


async def test_bundle_failure_rolls_back_whole_unit(tmp_path):
    repo, _db = _repo(tmp_path)
    proposal = _proposal()
    grounding = await _grounding(proposal)
    bad_bundle = {
        "bundle_id": "bundle-x",
        "proposal_id": proposal.proposal_id,
        "grounding_id": grounding.grounding_id,
        "grounding_status": "not-a-status",  # CHECK violation
        "effective_assertion_class": "INFERENCE",
        "claim_text": "t",
        "evidence_items": [],
        "relationship_refs": (),
        "temporal_scope": None,
        "limitations": (),
        "warnings": (),
        "source_question_ids": (),
        "hydration_policy": "digest_first_bounded",
        "input_hash": "h",
    }
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_grounded_proposal(
            INVESTIGATION_ID,
            proposal_row=proposal.to_row(),
            grounding_row=grounding.to_row(),
            bundle_row=bad_bundle,
        )
    assert repo.list_claim_proposals(INVESTIGATION_ID) == []
    assert repo.list_grounding_results(INVESTIGATION_ID) == []
    assert repo.list_support_bundles(INVESTIGATION_ID) == []


async def test_invalid_grounding_cannot_hide_cross_task_evidence(tmp_path):
    """A proposal whose evidence is cross-task grounds as INVALID and its
    grounding row records the integrity failure — never partial credit."""
    repo, _db = _repo(tmp_path)
    proposal = ProposedClaimV1(
        task_id="task-OTHER",  # foreign task binding
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text="cross-task claim",
        assertion_class=AssertionClass.FACT,
        evidence_refs=("file:C/a.doc",),
        input_hash="",
    )
    grounding = await DeterministicGroundingValidator().validate(
        proposal,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        allowed_evidence_ids=frozenset({"file:C/a.doc"}),
        evidence_resolver=_resolver,
    )
    repo.record_grounded_proposal(
        INVESTIGATION_ID,
        proposal_row=proposal.to_row(),
        grounding_row=grounding.to_row(),
    )
    stored = repo.list_grounding_results(INVESTIGATION_ID)
    assert stored[0]["status"] == "invalid"
    assert any(
        item.startswith("grounded means refs are legal")
        for item in stored[0]["limitations"]
    )
