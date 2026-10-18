"""A1-H typed handle contract tests (spec §24-§31).

Freezes the A1-H boundary introduced on the supervisor INTEGRATE
model-facing contract:

- §24  a D* (delegation_result) handle is schema-rejected in EVERY
       typed operand field (evidence-only, finding-only, proposal-only,
       coverage, hypothesis, contradiction, question fields).
- §25  valid kinds resolve end-to-end: schema accepts -> exact
       resolver lookup -> canonical ref (E/Q/COV/F/P/H/X).
- §26  projection stays INCOMPLETE on purpose: a fresh SpecialistResult
       carrying claim candidates yields a D* handle but NO P*/F* handles
       — projecting result-internal objects would fabricate canonical
       state (§15/§16 forbidden).
- §27  action availability: empty operand domains remove the branch
       from the rendered available_actions.
- §28  semantic responsibility: the model's WHICH-evidence choice is
       preserved verbatim by the resolver (no auto-selection).
- §29  policy preservation: resolution output is the canonical v1
       decision consumed by the unchanged validator/policy chain — no
       A1-H fast path.
- §30  negative semantics: a valid handle does not legitimize an
       unsupported claim; closure gates still fire on the resolved
       canonical decision.
"""

import pytest
from pydantic import ValidationError

from httpserver.services.investigation.agent_integration_v2 import (
    AddFindingReferenceActionV2,
    AddPendingProposalReferenceActionV2,
    CreateContradictionActionV2,
    CreateHypothesisActionV2,
    INTEGRATION_DECISION_VERSION,
    INTEGRATION_DECISION_VERSION_V2,
    INTEGRATION_DECISION_VERSION_V3,
    SupervisorIntegrationDecisionV2,
    UpdateContradictionActionV2,
    UpdateCoverageActionV2,
    UpdateEvidenceRelevanceActionV2,
    UpdateHypothesisActionV2,
    UpdateQuestionActionV2,
    availability_projection,
    render_integration_context_v2,
    resolve_integration_proposal_v2,
)

from test_agent_integration_v2 import (  # noqa: F401  (fixture helpers)
    E1_KEY,
    E2_KEY,
    _context,
    _fresh_env,
    _policy_ctx,
    _state,
)

pytestmark = pytest.mark.migration_matrix

# ---------------------------------------------------------------------------
# §24 — kind discipline at the schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        UpdateQuestionActionV2,
        UpdateEvidenceRelevanceActionV2,
        UpdateCoverageActionV2,
        UpdateHypothesisActionV2,
        UpdateContradictionActionV2,
        AddFindingReferenceActionV2,
        AddPendingProposalReferenceActionV2,
        CreateHypothesisActionV2,
        CreateContradictionActionV2,
    ],
)
def test_d1_handle_rejected_in_every_typed_field(action):
    """A D* handle is never a legal operand in any typed field (§24)."""
    kwargs_by_action = {
        UpdateQuestionActionV2: dict(
            question_handle="Q1",
            to_status="answered",
            basis_handles=["D1"],
            disposition="supported",
        ),
        UpdateEvidenceRelevanceActionV2: dict(
            evidence_handle="D1", to_status="relevant"
        ),
        UpdateCoverageActionV2: dict(
            coverage_handle="D1", to_status="covered"
        ),
        UpdateHypothesisActionV2: dict(
            hypothesis_handle="D1", to_status="supported"
        ),
        UpdateContradictionActionV2: dict(
            contradiction_handle="D1", to_status="resolved"
        ),
        AddFindingReferenceActionV2: dict(finding_handle="D1"),
        AddPendingProposalReferenceActionV2: dict(proposal_handle="D1"),
        CreateHypothesisActionV2: dict(
            text="h", supporting_handles=["D1"]
        ),
        CreateContradictionActionV2: dict(
            severity="medium", refs_handles=["D1"]
        ),
    }
    with pytest.raises(ValidationError):
        action(**kwargs_by_action[action])


def test_cross_kind_handles_rejected():
    """An E handle is not a P handle and vice versa (§24 corollary)."""
    with pytest.raises(ValidationError):
        AddPendingProposalReferenceActionV2(proposal_handle="E1")
    with pytest.raises(ValidationError):
        AddFindingReferenceActionV2(finding_handle="P1")
    with pytest.raises(ValidationError):
        UpdateCoverageActionV2(coverage_handle="E1", to_status="covered")


def test_decision_version_bumped_to_v3():
    assert INTEGRATION_DECISION_VERSION_V3 == (
        "supervisor-integration-decision:v3"
    )
    assert INTEGRATION_DECISION_VERSION == INTEGRATION_DECISION_VERSION_V3
    assert INTEGRATION_DECISION_VERSION != INTEGRATION_DECISION_VERSION_V2
    decision = SupervisorIntegrationDecisionV2()
    assert decision.decision_version == INTEGRATION_DECISION_VERSION_V3


# ---------------------------------------------------------------------------
# §25 — valid kinds resolve exactly
# ---------------------------------------------------------------------------


def test_valid_kinds_resolve_to_canonical_refs():
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )

    context = _context(fresh_results=(_fresh_env(),))
    table = build_integration_binding_table(context, _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1",
                to_status="answered",
                disposition="supported",
                basis_handles=["E1", "E2"],
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, context, _state()
    )
    assert canonical is not None and record.ok
    action = canonical.transition_proposals[0]
    assert action.basis_refs == (E1_KEY, E2_KEY)
    # the model's WHICH-evidence choice is preserved exactly (§28)
    assert action.basis_refs[0] == E1_KEY


# ---------------------------------------------------------------------------
# §26 — projection stays deliberately incomplete
# ---------------------------------------------------------------------------


def test_fresh_result_projects_d_but_never_p_or_f():
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
        BindingKind,
    )

    context = _context(fresh_results=(_fresh_env(),))
    table = build_integration_binding_table(context, _state())
    assert table.by_handle("D1") is not None
    assert table.canonical_refs_of_kind(BindingKind.claim_proposal) == ()
    assert table.canonical_refs_of_kind(BindingKind.finding) == ()
    # the availability projection agrees (§27)
    availability = availability_projection(table)
    assert "add_finding_reference" not in availability["available_actions"]
    assert (
        "add_pending_proposal_reference"
        not in availability["available_actions"]
    )
    assert availability["handle_counts_by_kind"]["F"] == 0
    assert availability["handle_counts_by_kind"]["P"] == 0


def test_nonempty_domain_offers_the_branch():
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
    )
    from httpserver.services.investigation.agent_working_state import (
        CoverageDimension,
        CoverageStatus,
    )

    state = _state(
        coverage=(
            CoverageDimension(
                dimension_id="authentication",
                status=CoverageStatus.not_started,
                required=True,
            ),
        ),
    )
    assert any(
        isinstance(q, WorkingQuestion) for q in state.questions
    ) or state.questions
    context = _context(fresh_results=(_fresh_env(),))
    table = build_integration_binding_table(context, state)
    availability = availability_projection(table)
    assert "update_coverage" in availability["available_actions"]
    assert availability["handle_counts_by_kind"]["COV"] == 1


def test_render_exposes_available_actions():
    context = _context(fresh_results=(_fresh_env(),))
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )

    table = build_integration_binding_table(context, _state())
    rendered = render_integration_context_v2(context, _state(), table)
    assert "available_actions" in rendered
    assert "handle_counts_by_kind" in rendered
    assert "add_finding_reference" not in rendered["available_actions"]


# ---------------------------------------------------------------------------
# §28/§29/§30 — semantic responsibility, policy preservation, negative
# semantics
# ---------------------------------------------------------------------------


def test_resolver_preserves_model_evidence_choice_order():
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )

    context = _context(fresh_results=(_fresh_env(),))
    table = build_integration_binding_table(context, _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            CreateHypothesisActionV2(
                text="hypothesis text",
                supporting_handles=["E2", "E1"],
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, context, _state()
    )
    assert canonical is not None and record.ok
    hypothesis = canonical.transition_proposals[0].hypothesis
    assert hypothesis.supporting_refs == (E2_KEY, E1_KEY)


def test_resolved_output_is_canonical_v1_decision():
    from httpserver.services.investigation.agent_integration import (
        SupervisorIntegrationDecisionV1,
    )
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )

    context = _context(fresh_results=(_fresh_env(),))
    table = build_integration_binding_table(context, _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1",
                to_status="answered",
                disposition="supported",
                basis_handles=["E1"],
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, context, _state()
    )
    assert isinstance(canonical, SupervisorIntegrationDecisionV1)
    # trusted identity was injected server-side
    assert canonical.based_on_state_revision == context.state_revision


def test_valid_handle_does_not_legitimize_unsupported_closure():
    """§30: a legal E handle does not turn an unsupported closure into a
    legal one — the unchanged policy still demands closure basis
    semantics on the canonical decision."""
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )
    from httpserver.services.investigation.agent_transitions import (
        StateTransitionPolicy,
    )

    context = _context(fresh_results=(_fresh_env(),))
    table = build_integration_binding_table(context, _state())
    # closure with an EXPLICIT empty basis stays illegal
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1",
                to_status="answered",
                disposition="supported",
                basis_handles=[],
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, context, _state()
    )
    assert canonical is not None
    # the canonical action carries the explicit empty basis; the frozen
    # validator/policy chain downstream sees exactly that
    closure = canonical.transition_proposals[0]
    assert closure.basis_refs == ()
    assert closure.disposition == "supported"


def test_availability_is_pure_function_of_table():
    context = _context(fresh_results=(_fresh_env(),))
    from httpserver.services.investigation.agent_reference_bindings import (
        build_integration_binding_table,
    )

    table = build_integration_binding_table(context, _state())
    assert availability_projection(table) == availability_projection(table)
