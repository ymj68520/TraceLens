"""P5B §62 CorrelationAgent tests: bounded input, causality boundary,
allowlist-only refs, proposal-not-canonical, explicit failures."""

import pytest

from httpserver.services.investigation.agent_claims import ProposedClaimV1
from httpserver.services.investigation.agent_correlation import (
    CausalStatus,
    CorrelationCandidateV1,
    CorrelationDerivation,
)
from httpserver.services.investigation.agent_correlation_agent import (
    CorrelationAgent,
    CorrelationContextPackV1,
    CorrelationOutputViolationCode,
    CorrelationProposalV1,
    proposal_to_claim,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "5" * 8


def _candidate(correlation_id="corr-1", family="same_content_hash"):
    return CorrelationCandidateV1(
        correlation_id=correlation_id,
        relation_family=family,
        subject_ref="o-1",
        object_ref="o-2",
        derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
        assertion_hint="inference",
        evidence_refs=("file:C/1.iso", "file:D/2.iso"),
        support_types=("exact_hash",),
        limitations=(),
        causal_status=CausalStatus.NOT_ASSESSED,
        input_hash="h",
    )


def _context(**overrides) -> CorrelationContextPackV1:
    fields = dict(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        question="did the same usb device move data between hosts?",
        correlation_candidates=(_candidate(),),
        occurrence_digests=(
            {
                "occurrence_id": "o-1",
                "entity_type": "file_hash",
                "normalized_value": "ab" * 32,
                "namespace": "hash:sha256",
            },
            {
                "occurrence_id": "o-2",
                "entity_type": "file_hash",
                "normalized_value": "ab" * 32,
                "namespace": "hash:sha256",
            },
        ),
        evidence_allowlist=("file:C/1.iso", "file:D/2.iso"),
        limitations=("bounded candidates only",),
    )
    fields.update(overrides)
    return CorrelationContextPackV1(**fields)


def _proposal(context, **overrides) -> CorrelationProposalV1:
    fields = dict(
        proposal_id="corr-1",
        subject_ref="o-1",
        object_ref="o-2",
        relation_family="same_content_hash",
        assertion_class=AssertionClass.INFERENCE,
        evidence_refs=("file:C/1.iso", "file:D/2.iso"),
        semantic_interpretation="both images contain identical content",
        input_hash=context.context_hash,
    )
    fields.update(overrides)
    return CorrelationProposalV1(**fields)


def test_context_is_bounded_and_deterministic():
    first = _context()
    second = _context()
    assert first.context_hash == second.context_hash
    # bounded: only the supplied candidates and digests exist in the pack
    assert len(first.correlation_candidates) == 1
    assert first.allowed_tool_ids == ()  # tools=none by default
    assert not hasattr(first, "graph") and not hasattr(first, "all_evidence")


async def test_agent_binds_runtime_facts_and_accepts_compliant_output():
    context = _context()
    agent = CorrelationAgent(model_name="test-model")
    proposal = await agent.run(
        context, candidate=_candidate(),
        model_output={
            "proposal_id": "corr-1",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "same_content_hash",
            "assertion_class": "INFERENCE",
            "evidence_refs": ["file:C/1.iso", "file:D/2.iso"],
            "semantic_interpretation": "identical digest across hosts",
            "causal_status": "not_assessed",
        },
    )
    assert isinstance(proposal, CorrelationProposalV1)
    assert proposal.task_id == TASK_ID
    assert proposal.context_hash == context.context_hash
    assert proposal.model == "test-model"
    assert proposal.proposal_version == "correlation-proposal:v1"


async def test_unknown_evidence_ref_rejected():
    context = _context()
    agent = CorrelationAgent()
    outcome = await agent.run(
        context, candidate=_candidate(),
        model_output={
            "proposal_id": "corr-1",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "same_content_hash",
            "assertion_class": "INFERENCE",
            "evidence_refs": ["file:C/never-exposed.iso"],
            "semantic_interpretation": "x",
        },
    )
    assert outcome.failure_code == "output_invalid"
    assert "CORRELATION_EVIDENCE_REF_OUTSIDE_ALLOWLIST" in outcome.detail


async def test_temporal_relation_cannot_become_confirmed_causal():
    context = _context(
        correlation_candidates=(
            _candidate(correlation_id="corr-t", family="temporal_overlap"),
        ),
    )
    agent = CorrelationAgent()
    outcome = await agent.run(
        context,
        candidate=_candidate(correlation_id="corr-t", family="temporal_overlap"),
        model_output={
            "proposal_id": "corr-t",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "temporal_overlap",
            "assertion_class": "INFERENCE",
            "evidence_refs": ["file:C/1.iso"],
            "semantic_interpretation": "events near in time imply transfer",
            "causal_status": "causal_hypothesis",
        },
    )
    assert outcome.failure_code == "output_invalid"
    assert "CORRELATION_TEMPORAL_CAUSAL_FORBIDDEN" in outcome.detail


async def test_causal_hypothesis_requires_hypothesis_class():
    context = _context()
    agent = CorrelationAgent()
    outcome = await agent.run(
        context, candidate=_candidate(),
        model_output={
            "proposal_id": "corr-1",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "same_content_hash",
            "assertion_class": "INFERENCE",
            "evidence_refs": ["file:C/1.iso"],
            "semantic_interpretation": "maybe copied between devices",
            "causal_status": "causal_hypothesis",
        },
    )
    assert outcome.failure_code == "output_invalid"
    assert "CORRELATION_CAUSAL_REQUIRES_HYPOTHESIS" in outcome.detail
    # with HYPOTHESIS class it is the sanctioned shape
    ok = await agent.run(
        context, candidate=_candidate(),
        model_output={
            "proposal_id": "corr-1",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "same_content_hash",
            "assertion_class": "HYPOTHESIS",
            "evidence_refs": ["file:C/1.iso"],
            "semantic_interpretation": "maybe copied between devices",
            "causal_status": "causal_hypothesis",
        },
    )
    assert isinstance(ok, CorrelationProposalV1)
    assert ok.causal_status is CausalStatus.CAUSAL_HYPOTHESIS


async def test_candidate_mismatch_and_invalid_text_fail_closed():
    context = _context()
    agent = CorrelationAgent()
    outcome = await agent.run(
        context, candidate=_candidate(),
        model_output={
            "proposal_id": "corr-unknown",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "same_content_hash",
            "assertion_class": "INFERENCE",
            "evidence_refs": [],
            "semantic_interpretation": "x",
        },
    )
    assert "CORRELATION_CANDIDATE_MISMATCH" in outcome.detail
    outcome = await agent.run(
        context, candidate=_candidate(),
        model_output={
            "proposal_id": "corr-1",
            "subject_ref": "o-1",
            "object_ref": "o-2",
            "relation_family": "same_content_hash",
            "assertion_class": "INFERENCE",
            "evidence_refs": [],
            "semantic_interpretation": "   ",
        },
    )
    assert "CORRELATION_TEXT_INVALID" in outcome.detail


async def test_correlation_result_remains_proposal(tmp_path):
    """The output never touches canonical state: no repo write path exists
    in the module; the only downstream entry is proposal_to_claim, which
    produces another non-canonical ProposedClaimV1."""
    import httpserver.services.investigation.agent_correlation_agent as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "commit_working_state" not in source
    assert "AgentRuntimeRepository" not in source
    assert "record_" not in source

    proposal = _proposal(_context())
    claim = proposal_to_claim(
        proposal, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    assert isinstance(claim, ProposedClaimV1)
    assert claim.text == proposal.semantic_interpretation
    assert claim.assertion_class is proposal.assertion_class
    assert claim.proposal_id.startswith("prop:")
    assert claim.relationship_refs == (proposal.proposal_id,)


async def test_provider_failure_is_explicit():
    class ExplodingModel:
        pass

    agent = CorrelationAgent(model=ExplodingModel())

    async def _explode(*args, **kwargs):
        raise RuntimeError("connection reset")

    agent._build_agent = lambda: type(
        "A", (), {"run": staticmethod(_explode)}
    )()
    context = _context()
    outcome = await agent.run(
        context, candidate=_candidate(),
        model_output=None,
    )
    from httpserver.services.investigation.agent_correlation_agent import (
        CorrelationAgentFailure,
    )

    assert isinstance(outcome, CorrelationAgentFailure)
    assert outcome.failure_code == "agent_internal_failure"
    assert "connection reset" in outcome.detail
