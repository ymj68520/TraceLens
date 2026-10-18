"""A1-T trusted-field separation tests (spec §13-§19).

Freezes the boundary introduced by A1-T:

- §13  the model-facing contract (SpecialistResultProposalV1, and the
       schema PydanticAI actually receives from the production builder)
       carries NO runtime-owned field: execution_digest and every count /
       usage / identity-hash fact are structurally absent, and the schema
       forbids additional properties — not merely "optional".
- §14  finalize_specialist_result deterministically enriches from durable
       observations + the captured usage payload; same inputs -> same
       canonical result_hash.
- §15  a raw model/provider payload attempting to smuggle runtime
       metadata (execution_digest, tool_call_count, ...) is rejected by
       the proposal schema, and a model returning the CANONICAL type is
       rejected by the executor's type check.
- §16  semantic fields pass through unchanged; only server-computed
       provenance is added.
- §18  enrichment never legalizes invalid Evidence refs.

S4 snapshot admission, atomicity (§17/§19) and the invalid-evidence
fail-closed paths are enforced unchanged by
``test_evidence_snapshot_admission.py`` (same transaction, same
boundaries — exercised end-to-end on the proposal flow).
"""

import pytest
from pydantic import ValidationError

from httpserver.services.investigation.agent_context import (
    ArtifactFamilyRegistry,
    ContextAssembler,
)
from httpserver.services.investigation.agent_profiles import default_profiles
from httpserver.services.investigation.agent_runtime import ToolObservation
from httpserver.services.investigation.agent_skills import SkillRegistry
from httpserver.services.investigation.agent_specialist_result import (
    SPECIALIST_RESULT_PROPOSAL_VERSION,
    SPECIALIST_RESULT_VERSION,
    AssertionClass,
    ExecutionDigest,
    SpecialistClaimCandidate,
    SpecialistResultContractError,
    SpecialistResultProposalV1,
    SpecialistResultValidator,
    execution_digest_hash,
    finalize_specialist_result,
)

pytestmark = pytest.mark.migration_matrix

TASK = {
    "id": "task-A",
    "scenarios": ["windows"],
    "scenario_databases": {},
}

# every runtime-owned field that must be structurally absent from the
# model-facing contract (§13; audit Q6)
RUNTIME_OWNED_FIELDS = (
    "execution_digest",
    "tool_call_count",
    "observation_count",
    "request_count",
    "input_tokens",
    "output_tokens",
    "model_name",
    "result_hash",
    "context_hash",
    "tool_registry_hash",
    "model_config_hash",
    "created_at",
)

BANNED_PAYLOAD = {
    "proposal_version": SPECIALIST_RESULT_PROPOSAL_VERSION,
    "delegation_id": "del-X",
    "summary": "s",
}


def _build_pack(question_id="q-1", delegation_id="del-X"):
    assembler = ContextAssembler(
        skill_registry=SkillRegistry.with_defaults(),
        family_registry=ArtifactFamilyRegistry.with_defaults(),
        profiles=default_profiles(),
        tool_schema_hash="hash-offline",
    )
    return assembler.build(
        task=TASK,
        run_identity={
            "task_id": "task-A",
            "investigation_id": "inv-A",
            "run_id": "run-A",
        },
        question="unusual logons?",
        source_scope_id="windows",
        question_id=question_id,
        table_lister=lambda _p: frozenset(),
    ).model_copy(update={"delegation_id": delegation_id})


def _good_proposal(delegation_id="del-X", question_id="q-1"):
    return SpecialistResultProposalV1(
        delegation_id=delegation_id,
        question_id=question_id,
        summary="specialist summary",
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1",
                text="logon pattern observed",
                assertion_class=AssertionClass.INFERENCE,
                evidence_refs=("file:C/logon_4624.doc",),
            ),
        ),
        evidence_refs=("file:C/logon_4624.doc",),
        limitations=("scope limited to windows",),
    )


def _observation(delegation_id, index):
    return ToolObservation(
        observation_id=f"obs-{delegation_id}-{index}",
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        delegation_id=delegation_id,
        tool_id="search_evidence",
        summary=f"hit {index}",
        result={"rows": index},
        evidence_refs=("file:C/logon_4624.doc",),
        result_count=1,
        truncated=False,
        created_at="2026-09-29T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# §13 — schema separation
# ---------------------------------------------------------------------------


def test_proposal_schema_has_no_runtime_owned_fields():
    schema = SpecialistResultProposalV1.model_json_schema()
    properties = schema["properties"]
    for field in RUNTIME_OWNED_FIELDS:
        assert field not in properties, (
            f"runtime-owned field {field!r} must be structurally absent "
            "from the model-facing contract"
        )
    assert schema.get("additionalProperties") is False
    # semantic payload and identity bindings stay
    for kept in (
        "proposal_version",
        "delegation_id",
        "question_id",
        "summary",
        "claim_candidates",
        "evidence_refs",
        "limitations",
    ):
        assert kept in properties


def test_proposal_rejects_instance_spoofing_at_construction():
    with pytest.raises(ValidationError) as exc:
        SpecialistResultProposalV1(
            **BANNED_PAYLOAD,
            execution_digest=ExecutionDigest(tool_call_count=999),
            tool_call_count=999,
            observation_count=999,
        )
    messages = str(exc.value)
    assert "execution_digest" in messages
    assert "tool_call_count" in messages


def test_production_builder_exposes_proposal_schema_to_the_model():
    """The schema PydanticAI hands the provider is the proposal schema —
    proven through the real production builder, not just the class."""
    from httpserver.services.investigation.agent_specialist_executor import (
        SpecialistDelegationExecutor,
    )

    from pydantic_ai.models.test import TestModel

    executor = SpecialistDelegationExecutor(
        cpp_backend=None,
        settings=None,
        tool_services=None,
        registry_builder=lambda runtime, observation_sink=None: object(),
    )
    executor._get_model = lambda: TestModel()  # type: ignore[method-assign]
    agent = executor._build_agent(_build_pack(), object())
    assert agent.output_type is SpecialistResultProposalV1
    schema_json = agent.output_json_schema()
    for field in RUNTIME_OWNED_FIELDS:
        assert f'"{field}"' not in schema_json, (
            f"model-visible output schema leaks runtime-owned {field!r}"
        )


# ---------------------------------------------------------------------------
# §14 — deterministic enrichment from durable records
# ---------------------------------------------------------------------------


def _finalize(proposal, observations, usage=None, model_name="offline-model"):
    return finalize_specialist_result(
        proposal,
        delegation_id=proposal.delegation_id,
        model_name=model_name,
        usage_payload=usage,
        run_observations=observations,
    )


def test_enrichment_counts_come_from_durable_observations():
    proposal = _good_proposal()
    observations = [
        _observation("del-X", 1),
        _observation("del-X", 2),
        _observation("del-X", 3),
        # another delegation's observation must NOT count
        _observation("del-Y", 4),
    ]
    result = _finalize(
        proposal,
        observations,
        usage={"requests": 5, "input_tokens": 1000, "output_tokens": 400},
    )
    digest = result.execution_digest
    assert digest.tool_call_count == 3
    assert digest.observation_count == 3
    assert digest.request_count == 5
    assert digest.input_tokens == 1000
    assert digest.output_tokens == 400
    assert digest.model_name == "offline-model"


def test_enrichment_is_deterministic_and_hash_stable():
    proposal = _good_proposal()
    observations = [_observation("del-X", i) for i in range(3)]
    usage = {"requests": 5, "input_tokens": 1000, "output_tokens": 400}
    first = _finalize(proposal, observations, usage)
    second = _finalize(proposal, list(observations), dict(usage))
    assert first == second
    assert first.result_hash() == second.result_hash()
    # different trusted inputs -> different canonical hash
    third = _finalize(proposal, observations[:2], usage)
    assert third.result_hash() != first.result_hash()


def test_enrichment_binds_proposal_to_the_executing_delegation():
    proposal = _good_proposal(delegation_id="del-X")
    with pytest.raises(SpecialistResultContractError):
        finalize_specialist_result(
            proposal,
            delegation_id="del-OTHER",
            model_name="m",
            run_observations=(),
        )


def test_trusted_enrichment_digest_is_deterministic():
    digest = ExecutionDigest(
        model_name="m",
        request_count=2,
        input_tokens=10,
        output_tokens=20,
        tool_call_count=3,
        observation_count=3,
    )
    assert execution_digest_hash(digest) == execution_digest_hash(
        digest.model_copy()
    )


# ---------------------------------------------------------------------------
# §15 — a model cannot spoof runtime metadata
# ---------------------------------------------------------------------------


def test_raw_payload_with_runtime_metadata_is_rejected():
    spoofed = dict(BANNED_PAYLOAD)
    spoofed["execution_digest"] = "fake"
    spoofed["tool_call_count"] = 999
    with pytest.raises(ValidationError):
        SpecialistResultProposalV1.model_validate(spoofed)


async def test_executor_rejects_canonical_type_as_model_output():
    """Even returning the canonical SpecialistResultV1 (with a fake
    digest) fails the executor's proposal type check — the only accepted
    model output shape is the trusted-field-free proposal."""
    from types import SimpleNamespace

    from httpserver.services.investigation.agent_specialist_executor import (
        DispatchStatus,
        SpecialistDelegationExecutor,
    )
    from httpserver.services.investigation.agent_specialist_result import (
        SpecialistResultV1,
    )
    captured: dict = {}

    class _Runtime:
        def list_tool_observations(self, *a, **kw):
            return []

        def get_delegation(self, delegation_id):
            return SimpleNamespace(cancel_requested_at=None)

        def transition_delegation_terminal(self, delegation_id, status, **kw):
            captured["delegation_id"] = delegation_id
            captured["status"] = status
            captured.update(kw)

    envelope = SimpleNamespace(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        delegation_id="del-X",
        question_id="q-1",
        question_text="q",
        based_on_state_revision=None,
        based_on_state_hash=None,
        source_scope_ids=("windows",),
        time_scope=None,
        allowed_tool_ids=frozenset({"search_evidence"}),
        skill_bindings=(),
        profile_id="p",
        profile_version="1",
        context_hash="ctx",
        tool_registry_hash="reg",
        model_config_digest="cfg",
        context_pack=None,
        execution_input_hash=lambda: "in",
    )
    pack = _build_pack(delegation_id="del-X")

    class _FakeRegistry:
        def iter_definitions(self):
            return ()

        def resolve_definition(self, tool_id):
            raise KeyError(tool_id)

        async def execute(self, context, tool_id, args):
            return None

    executor = SpecialistDelegationExecutor(
        cpp_backend=None,
        settings=None,
        tool_services=None,
        registry_builder=lambda runtime, observation_sink=None: _FakeRegistry(),
    )
    executor._policy = SimpleNamespace(
        max_output_retries=1,
        max_provider_retries=0,
        max_model_requests=None,
        max_input_tokens=None,
        max_output_tokens=None,
        max_parallel_delegations=1,
    )
    canonical_output = SpecialistResultV1(
        delegation_id="del-X",
        summary="x",
        execution_digest=ExecutionDigest(tool_call_count=999),
    )

    class _FakeAgent:
        async def run(self, prompt, *, deps, usage_limits=None):
            return SimpleNamespace(
                output=canonical_output,
                usage=lambda: SimpleNamespace(
                    requests=1, input_tokens=10, output_tokens=20
                ),
                response=None,
            )

    executor._build_agent = lambda pack_arg, registry: _FakeAgent()  # type: ignore[method-assign]

    outcome = await executor._execute_envelope(
        envelope, pack, _FakeRegistry(), _Runtime(), "del-X"
    )
    assert outcome.status is DispatchStatus.FAILED
    assert outcome.failure_code == "agent_output_invalid"
    assert captured["status"] == "failed"


# ---------------------------------------------------------------------------
# §16 — semantic preservation
# ---------------------------------------------------------------------------


def test_semantic_fields_pass_through_verbatim():
    proposal = _good_proposal()
    result = _finalize(proposal, [_observation("del-X", 1)])
    assert result.summary == proposal.summary
    assert result.claim_candidates == proposal.claim_candidates
    assert result.evidence_refs == proposal.evidence_refs
    assert result.limitations == proposal.limitations
    assert result.warnings == proposal.warnings
    assert result.follow_up_questions == proposal.follow_up_questions
    assert result.coverage_observations == proposal.coverage_observations
    assert result.result_version == SPECIALIST_RESULT_VERSION
    assert result.delegation_id == proposal.delegation_id
    assert result.question_id == proposal.question_id
    # the ONLY addition is server-computed provenance
    assert result.execution_digest != ExecutionDigest()


def test_canonical_draft_matches_proposal_with_digest_unset():
    draft = _good_proposal().to_canonical_draft()
    assert draft.execution_digest == ExecutionDigest()
    assert draft.result_version == SPECIALIST_RESULT_VERSION


# ---------------------------------------------------------------------------
# §18 — enrichment never legalizes invalid Evidence
# ---------------------------------------------------------------------------


def test_enriched_result_still_fails_closed_on_unknown_evidence():
    proposal = SpecialistResultProposalV1(
        delegation_id="del-X",
        question_id="q-1",
        summary="s",
        evidence_refs=("file:C/never_visible.doc",),
    )
    result = _finalize(proposal, [_observation("del-X", 1)])
    pack = _build_pack(delegation_id="del-X")
    validation = SpecialistResultValidator().validate(pack, result, [])
    assert not validation.valid
    codes = validation.codes
    assert any(
        code.startswith("RESULT_EVIDENCE") for code in codes
    ), codes
    # and the digest enrichment changed nothing about the violation
    draft_validation = SpecialistResultValidator().validate(
        pack, proposal.to_canonical_draft(), []
    )
    assert draft_validation.codes == codes
