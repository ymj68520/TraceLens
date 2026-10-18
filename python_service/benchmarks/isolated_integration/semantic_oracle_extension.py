"""TraceLens Agent v0 — RCA-2A.9a Semantic Oracle Extension V1.

Extends RCA2A9SemanticOracleV1 with closed contract checks:
1. Blind Arm Invariance: arm parameter is strictly non-participating in evaluation logic.
2. Unknown Semantic Support: evidence ID is valid but evidence content is insufficient/inconclusive to judge claim -> INSUFFICIENT_EVIDENCE_TO_JUDGE.
3. Stale Source & Revision Rejection: expected_revision != current_revision or expected_source_hash != current_source_hash -> UNAUTHORIZED_COMMIT / STALE_INTEGRATION_INPUT.
4. Equivalent Acceptable Actions: multiple distinct valid action paths are equally accepted without structural JSON bias.
5. Strict Negative Gate enforcement: unsupported fact promotion, unsupported causality, graph ID masquerading, analyst note as fact, cross-task evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from benchmarks.isolated_integration.semantic_oracle import (
    InformationValue,
    NegativeGateCode,
    OracleEvaluationResult,
    RCA2A9SemanticOracleV1,
    SemanticAdequacy,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_integration import (
    IntegrationDecisionValidator,
)
from httpserver.services.investigation.agent_integration_v2 import (
    AddFindingReferenceActionV2,
    AddPendingProposalReferenceActionV2,
    CreateContradictionActionV2,
    CreateHypothesisActionV2,
    CreateQuestionActionV2,
    SupervisorIntegrationDecisionV2,
    UpdateContradictionActionV2,
    UpdateCoverageActionV2,
    UpdateEvidenceRelevanceActionV2,
    UpdateHypothesisActionV2,
    UpdateQuestionActionV2,
    resolve_integration_proposal_v2,
)
from httpserver.services.investigation.agent_reference_bindings import (
    ReferenceBindingTableV1,
)
from httpserver.services.investigation.agent_transitions import (
    StateTransitionPolicy,
    TransitionBatch,
    TransitionDecisionStatus,
    TransitionPolicyContext,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    CoverageStatus,
    EvidenceRelevanceStatus,
    QuestionDisposition,
    QuestionStatus,
)


class RCA2A9aSemanticOracleExtensionV1(RCA2A9SemanticOracleV1):
    """Versioned extension of Semantic Oracle V1 satisfying all RCA-2A.9a contracts."""

    VERSION = "RCA2A9aSemanticOracleExtensionV1"
    BASE_VERSION = "RCA2A9SemanticOracleV1"

    def evaluate_extended(
        self,
        *,
        scenario_id: str,
        decision_raw: Any,
        table: ReferenceBindingTableV1,
        context: Any,
        state: AgentWorkingStateV1,
        expected_revision: int,
        expected_source_hash: Optional[str] = None,
        runtime: Optional[Any] = None,
        arm: str = "blind",
    ) -> OracleEvaluationResult:
        """Evaluate decision enforcing blind arm invariance, stale source check, and unknown support."""
        # Arm parameter is strictly unobserved in evaluation logic (blind review contract)
        _ = arm

        violations: list[str] = []
        triggered_gates: list[NegativeGateCode] = []

        # -------------------------------------------------------------------
        # Pre-check 1: Staleness & Revision Monotonicity
        # -------------------------------------------------------------------
        current_revision = getattr(context, "state_revision", getattr(state, "revision", 1))
        if expected_revision != current_revision:
            triggered_gates.append(NegativeGateCode.UNAUTHORIZED_COMMIT)
            violations.append(
                f"L3: Expected revision {expected_revision} != current state revision {current_revision} (STALE_INTEGRATION_INPUT)"
            )

        if expected_source_hash is not None:
            current_source_hash = None
            if hasattr(context, "input_hash") and callable(context.input_hash):
                current_source_hash = context.input_hash()
            elif hasattr(context, "source_hash"):
                current_source_hash = context.source_hash
            elif hasattr(context, "context_hash"):
                current_source_hash = context.context_hash

            if current_source_hash is not None and expected_source_hash != current_source_hash:
                triggered_gates.append(NegativeGateCode.UNAUTHORIZED_COMMIT)
                violations.append(
                    f"L3: Stale source hash: expected {expected_source_hash} != current {current_source_hash} (STALE_INTEGRATION_INPUT)"
                )

        # -------------------------------------------------------------------
        # Pre-check 2: Raw negative gates
        # -------------------------------------------------------------------
        self._check_raw_negative_gates(decision_raw, table, triggered_gates, violations)

        # -------------------------------------------------------------------
        # L1: Schema Conformance
        # -------------------------------------------------------------------
        decision = None
        l1_valid = False
        try:
            if isinstance(decision_raw, SupervisorIntegrationDecisionV2):
                decision = decision_raw
                l1_valid = True
            elif isinstance(decision_raw, dict):
                decision = SupervisorIntegrationDecisionV2.model_validate(decision_raw)
                l1_valid = True
            else:
                violations.append(f"L1: Invalid decision type: {type(decision_raw)}")
        except Exception as exc:
            violations.append(f"L1: Pydantic validation error: {exc}")

        if not l1_valid or decision is None:
            return OracleEvaluationResult(
                scenario_id=scenario_id,
                l1_schema_valid=False,
                l2_canonical_valid=False,
                l3_state_integrity=False,
                l4_semantic_adequacy=SemanticAdequacy.SEMANTICALLY_INADEQUATE,
                l5_information_value=InformationValue.DEGRADED,
                triggered_negative_gates=triggered_gates,
                violations=violations,
                verdict="FAIL",
                details={"l1_failure": True},
            )

        # -------------------------------------------------------------------
        # L2: Canonical Resolution & Decision Validation
        # -------------------------------------------------------------------
        l2_valid = False
        resolution = None
        try:
            res, record = resolve_integration_proposal_v2(decision, table, context, state)
            if res is None:
                violations.extend(f"L2: Resolution violation: {v.code.value}" for v in record.violations)
            else:
                validator = IntegrationDecisionValidator(
                    evidence_ref_validator=None,
                    proposal_ref_resolver=(
                        lambda ref: runtime.get_claim_proposal(state.investigation_id, ref) is not None
                        if runtime is not None
                        else True
                    ),
                    finding_ref_resolver=(
                        lambda ref: (
                            lambda finding: finding is not None
                            and finding["status"] in ("review_pending", "accepted")
                        )(runtime.get_investigation_finding(state.investigation_id, ref))
                        if runtime is not None
                        else True
                    ),
                )
                iv = validator.validate(context, res)
                if not iv.valid:
                    violations.extend(f"L2: Validator code: {code}" for code in iv.codes)
                else:
                    l2_valid = True
                    resolution = res
        except Exception as exc:
            violations.append(f"L2: Exception during resolution/validation: {exc}")

        if not l2_valid or resolution is None:
            return OracleEvaluationResult(
                scenario_id=scenario_id,
                l1_schema_valid=True,
                l2_canonical_valid=False,
                l3_state_integrity=False,
                l4_semantic_adequacy=SemanticAdequacy.SEMANTICALLY_INADEQUATE,
                l5_information_value=InformationValue.DEGRADED,
                triggered_negative_gates=triggered_gates,
                violations=violations,
                verdict="FAIL",
                details={"l2_failure": True},
            )

        # -------------------------------------------------------------------
        # L3: State Integrity & StateTransitionPolicy
        # -------------------------------------------------------------------
        l3_valid = False
        policy_result = None
        policy_context = TransitionPolicyContext(
            task_id=state.task_id,
            investigation_id=state.investigation_id,
            agent_run_id=context.run_id if hasattr(context, "run_id") else "run-oracle",
            cycle_phase="integrate",
            plan_decision_id="plan-oracle",
            evidence_ref_resolver=lambda ref: True,
            finding_ref_validator=lambda ref: True,
            active_source_scope_ids=frozenset(["windows"]),
            coverage_dimension_catalog=frozenset(),
        )

        try:
            policy = StateTransitionPolicy()
            policy_result = policy.evaluate_batch(
                state,
                TransitionBatch(transitions=resolution.transition_proposals),
                policy_context,
            )
            if policy_result.status is TransitionDecisionStatus.rejected:
                violations.extend(f"L3: Policy rejection: {v.code}" for v in policy_result.violations)
            else:
                if NegativeGateCode.UNAUTHORIZED_COMMIT not in triggered_gates:
                    l3_valid = True
        except Exception as exc:
            violations.append(f"L3: Transition evaluation exception: {exc}")

        if not l3_valid or policy_result is None:
            return OracleEvaluationResult(
                scenario_id=scenario_id,
                l1_schema_valid=True,
                l2_canonical_valid=True,
                l3_state_integrity=False,
                l4_semantic_adequacy=SemanticAdequacy.SEMANTICALLY_INADEQUATE,
                l5_information_value=InformationValue.DEGRADED,
                triggered_negative_gates=triggered_gates,
                violations=violations,
                verdict="FAIL",
                details={"l3_failure": True},
            )

        # -------------------------------------------------------------------
        # L4 & L5: Scenario Semantics & Unknown Semantic Support
        # -------------------------------------------------------------------
        l4_adequacy, l5_value = self._evaluate_extended_scenario_semantics(
            scenario_id=scenario_id,
            decision=decision,
            resolution=resolution,
            state=state,
            table=table,
            context=context,
            triggered_gates=triggered_gates,
            violations=violations,
        )

        verdict = (
            "PASS"
            if (
                not triggered_gates
                and l4_adequacy
                in (
                    SemanticAdequacy.SEMANTICALLY_ADEQUATE,
                    SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL,
                )
            )
            else "FAIL"
        )

        return OracleEvaluationResult(
            scenario_id=scenario_id,
            l1_schema_valid=True,
            l2_canonical_valid=True,
            l3_state_integrity=True,
            l4_semantic_adequacy=l4_adequacy,
            l5_information_value=l5_value,
            triggered_negative_gates=triggered_gates,
            violations=violations,
            verdict=verdict,
            details={
                "actions_count": len(decision.actions),
                "resolution_actions_total": len(resolution.transition_proposals),
                "new_state_revision": current_revision + 1 if l3_valid else current_revision,
            },
        )

    def _check_raw_negative_gates(
        self,
        decision_raw: Any,
        table: ReferenceBindingTableV1,
        triggered_gates: list[NegativeGateCode],
        violations: list[str],
    ) -> None:
        """Scan raw input for negative gate violations including analyst notes and graph IDs."""
        super()._check_raw_negative_gates(decision_raw, table, triggered_gates, violations)

        raw_str = json.dumps(decision_raw) if isinstance(decision_raw, (dict, list)) else str(decision_raw)

        # Analyst note masquerading as fact check
        if "analyst_note" in raw_str.lower() and (
            "fact" in raw_str.lower() or "proven" in raw_str.lower() or "confirmed" in raw_str.lower()
        ):
            if NegativeGateCode.ANALYST_NOTE_AS_FACT not in triggered_gates:
                triggered_gates.append(NegativeGateCode.ANALYST_NOTE_AS_FACT)
                violations.append("Negative Gate: Analyst note treated as verified fact")

        # Unsupported fact promotion check
        if isinstance(decision_raw, dict):
            actions = decision_raw.get("actions", [])
            for act in actions:
                if act.get("action_type") == "create_hypothesis":
                    text = str(act.get("text", "")).lower()
                    if ("fact:" in text or "proven:" in text or "established fact" in text) and not act.get(
                        "supporting_handles"
                    ):
                        if NegativeGateCode.UNSUPPORTED_FACT_PROMOTION not in triggered_gates:
                            triggered_gates.append(NegativeGateCode.UNSUPPORTED_FACT_PROMOTION)
                            violations.append("Negative Gate: Fact assertion without supporting evidence")

    def _evaluate_extended_scenario_semantics(
        self,
        *,
        scenario_id: str,
        decision: SupervisorIntegrationDecisionV2,
        resolution: Any,
        state: AgentWorkingStateV1,
        table: ReferenceBindingTableV1,
        context: Any,
        triggered_gates: list[NegativeGateCode],
        violations: list[str],
    ) -> tuple[SemanticAdequacy, InformationValue]:
        """Scenario semantics with explicit support for INSUFFICIENT_EVIDENCE_TO_JUDGE."""
        # Check if the decision contains an inconclusive/insufficient evidence assertion
        for act in decision.actions:
            if isinstance(act, (CreateHypothesisActionV2, UpdateHypothesisActionV2)):
                text = act.text.lower()
                if "insufficient evidence" in text or "inconclusive" in text or "cannot be determined" in text:
                    # Grounding identity is valid, but evidence is inconclusive to judge truth
                    return SemanticAdequacy.INSUFFICIENT_EVIDENCE_TO_JUDGE, InformationValue.INFORMATION_NEUTRAL

            if isinstance(act, UpdateQuestionActionV2):
                summary = (act.investigated_summary or "").lower()
                if "insufficient evidence to judge" in summary or "inconclusive" in summary:
                    return SemanticAdequacy.INSUFFICIENT_EVIDENCE_TO_JUDGE, InformationValue.INFORMATION_NEUTRAL

        # Fallback to standard scenario evaluation
        return self._evaluate_scenario_semantics(
            scenario_id=scenario_id,
            decision=decision,
            resolution=resolution,
            state=state,
            table=table,
            context=context,
            triggered_gates=triggered_gates,
            violations=violations,
        )
