"""Deterministic AttentionBuilder / AttentionPolicy (P2).

The AttentionSet is a pure projection of the current typed Working State plus
delegation runtime state — never canonical DB truth, never persisted as a
table.  Same state (+ same config + same runtime view) yields the same set
and the same ``attention_hash``.

Frozen contract (architecture §18, P2 §20-§24):
  - priority bands P0 CONTROL .. P5 EXPLORATORY; no numeric importance score
  - only ``blocks`` question relations propagate effective priority;
    ``supports`` / ``explores`` never do
  - intrinsic question priority and effective attention band are separate
    concepts
  - deterministic coalescing only (explicit related ids / verification
    target); no embedding or LLM similarity
  - P5 requires at least one real basis ref; ref-less exploratory leads never
    enter the set
  - calibration-sensitive numbers (window size, exploration allowance, P1
    internal ordering) come from ``AttentionPolicyConfig`` — never hardcoded
    architecture constants.  ``build_full_set`` always returns the complete
    deterministic projection; ``build_window`` is a separate policy step and
    keeps P4/P5 when no config constrains them.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .agent_working_state import (
    AgentWorkingStateV1,
    ContradictionSeverity,
    ContradictionStatus,
    CoverageStatus,
    QuestionPriority,
    QuestionRelationType,
    QuestionStatus,
    VerificationStatus,
    ATTENTION_POLICY_VERSION,
)


class AttentionBand(str, Enum):
    p0_control = "p0_control"                          # P0 CONTROL
    p1_correctness_blocker = "p1_correctness_blocker"  # P1 CORRECTNESS BLOCKER
    p2_investigation_obligation = "p2_investigation_obligation"
    p3_active_progress = "p3_active_progress"
    p4_supporting_opportunistic = "p4_supporting_opportunistic"
    p5_exploratory = "p5_exploratory"


_BAND_ORDER = {
    AttentionBand.p0_control: 0,
    AttentionBand.p1_correctness_blocker: 1,
    AttentionBand.p2_investigation_obligation: 2,
    AttentionBand.p3_active_progress: 3,
    AttentionBand.p4_supporting_opportunistic: 4,
    AttentionBand.p5_exploratory: 5,
}

_INTRINSIC_BAND = {
    QuestionPriority.required: AttentionBand.p2_investigation_obligation,
    QuestionPriority.high: AttentionBand.p3_active_progress,
    QuestionPriority.normal: AttentionBand.p4_supporting_opportunistic,
    QuestionPriority.exploratory: AttentionBand.p5_exploratory,
}

_OPEN_QUESTION_STATUSES = {
    QuestionStatus.open,
    QuestionStatus.in_progress,
    QuestionStatus.deferred,
}


class AttentionEligibility(str, Enum):
    eligible = "eligible"
    blocked = "blocked"
    suppressed = "suppressed"


class AttentionActionType(str, Enum):
    """Investigation-level action families only — never Tool/Skill names
    (those belong to P3/P4)."""

    delegate_source = "delegate_source"
    delegate_correlation = "delegate_correlation"
    request_verification = "request_verification"
    direct_read = "direct_read"
    create_question = "create_question"
    request_finalize = "request_finalize"


class AttentionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str
    band: AttentionBand
    intrinsic_priority: Optional[QuestionPriority] = None
    eligibility: AttentionEligibility = AttentionEligibility.eligible
    blocked_by: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    title: str = ""
    related_question_ids: tuple[str, ...] = ()
    related_coverage_refs: tuple[str, ...] = ()
    related_verification_ids: tuple[str, ...] = ()
    related_contradiction_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    eligible_action_types: tuple[AttentionActionType, ...] = ()


class AttentionSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    investigation_id: str
    state_revision: Optional[int]
    policy_version: str
    items: tuple[AttentionItem, ...]
    attention_hash: str


class DelegationRuntimeView(BaseModel):
    """Deterministic delegation runtime facts supplied by the orchestrator
    (queued/running delegation question refs, whether a run is active)."""

    model_config = ConfigDict(frozen=True)

    run_active: bool = False
    in_flight_question_refs: tuple[str, ...] = ()


class AttentionPolicyConfig(BaseModel):
    """Calibration surface — nothing here is an architecture constant."""

    model_config = ConfigDict(frozen=True)

    window_size: Optional[int] = None
    exploration_allowance: Optional[int] = None
    suppress_exploratory_when_budget_exhausted: bool = True


_QUESTION_ACTIONS = (
    AttentionActionType.delegate_source,
    AttentionActionType.delegate_correlation,
    AttentionActionType.request_verification,
    AttentionActionType.direct_read,
    AttentionActionType.create_question,
)
_COVERAGE_ACTIONS = (
    AttentionActionType.delegate_source,
    AttentionActionType.direct_read,
)
_DIRECTIVE_ACTIONS = (
    AttentionActionType.create_question,
    AttentionActionType.delegate_source,
)
_CONTRADICTION_ACTIONS = (
    AttentionActionType.delegate_correlation,
    AttentionActionType.request_verification,
)
_VERIFICATION_ACTIONS = (
    AttentionActionType.delegate_source,
    AttentionActionType.direct_read,
)


def _effective_bands(state: AgentWorkingStateV1) -> dict[str, AttentionBand]:
    """Intrinsic band per question + transitive ``blocks``-only propagation.

    Cycles are cut deterministically (first visit wins in sorted question id
    order); ``supports`` / ``explores`` never propagate.
    """
    bands = {
        q.question_id: _INTRINSIC_BAND[q.priority]
        for q in state.questions
        if q.status in _OPEN_QUESTION_STATUSES
    }
    blockers: dict[str, set[str]] = {}
    for question in state.questions:
        for relation in question.relations:
            if relation.relation_type != QuestionRelationType.blocks:
                continue
            # ``question`` blocks ``relation.question_id``
            blockers.setdefault(relation.question_id, set()).add(question.question_id)

    # relax from targets to sources along blocks edges, deterministically
    for _ in range(len(state.questions) + 1):
        changed = False
        for target in sorted(blockers):
            if target not in bands:
                continue
            for source in sorted(blockers[target]):
                if source in bands and _BAND_ORDER[bands[source]] > _BAND_ORDER[bands[target]]:
                    bands[source] = bands[target]
                    changed = True
        if not changed:
            break
    return bands


class AttentionBuilder:
    """Builds the deterministic AttentionSet projection."""

    def __init__(self, *, policy_version: str = ATTENTION_POLICY_VERSION):
        self.policy_version = policy_version

    # ------------------------------------------------------------------

    def build_full_set(
        self,
        state: AgentWorkingStateV1,
        *,
        state_revision: Optional[int],
        runtime: DelegationRuntimeView = DelegationRuntimeView(),
        config: Optional[AttentionPolicyConfig] = None,
    ) -> AttentionSet:
        config = config or AttentionPolicyConfig()
        items: list[AttentionItem] = []
        items.extend(self._directive_items(state))
        question_items = self._question_items(state, runtime, config)
        verification_items = self._verification_items(state)
        # deterministic verification coalescing: a blocking verification on a
        # question that already has an item raises that item to P1 and is
        # recorded in its related_verification_ids (the standalone blocker
        # item stays visible for audit).
        for vid, item_id, target in (
            (f"verification:{v.verification_id}", f"question:{v.target_ref}", v.target_ref)
            for v in state.pending_verifications
            if v.required and v.blocking
            and v.status in (VerificationStatus.pending, VerificationStatus.failed)
        ):
            question_item = question_items.get(target)
            if question_item is not None:
                updated_related = tuple(dict.fromkeys(
                    question_item.related_verification_ids + (vid.split(":", 1)[1],)
                ))
                question_items[target] = question_item.model_copy(update={
                    "related_verification_ids": updated_related,
                    "band": AttentionBand.p1_correctness_blocker,
                })
        items.extend(verification_items)
        items.extend(self._contradiction_items(state))
        items.extend(question_items.values())
        items.extend(self._coverage_items(state, question_items))
        items.sort(key=lambda item: (_BAND_ORDER[item.band], item.item_id))
        attention_set = AttentionSet(
            investigation_id=state.investigation_id,
            state_revision=state_revision,
            policy_version=self.policy_version,
            items=tuple(items),
            attention_hash=_attention_hash(items),
        )
        return attention_set

    def build_window(
        self,
        full_set: AttentionSet,
        config: Optional[AttentionPolicyConfig] = None,
    ) -> AttentionSet:
        """Separate windowing policy step.

        Without a config (or window_size) the full projection is returned
        unchanged — P4/P5 are never cut arbitrarily.
        """
        config = config or AttentionPolicyConfig()
        if config.window_size is None and config.exploration_allowance is None:
            return full_set
        kept: list[AttentionItem] = []
        p4: list[AttentionItem] = []
        p5: list[AttentionItem] = []
        for item in full_set.items:
            if item.band in (
                AttentionBand.p0_control,
                AttentionBand.p1_correctness_blocker,
                AttentionBand.p2_investigation_obligation,
                AttentionBand.p3_active_progress,
            ):
                kept.append(item)
            elif item.band == AttentionBand.p4_supporting_opportunistic:
                p4.append(item)
            else:
                p5.append(item)
        if config.window_size is not None:
            budget = max(config.window_size - len(kept), 0)
        else:
            budget = None
        if budget is None:
            kept.extend(p4)
        else:
            kept.extend(p4[:budget])
        if config.exploration_allowance is not None:
            kept.extend(p5[: config.exploration_allowance])
        else:
            kept.extend(p5)
        kept.sort(key=lambda item: (_BAND_ORDER[item.band], item.item_id))
        return AttentionSet(
            investigation_id=full_set.investigation_id,
            state_revision=full_set.state_revision,
            policy_version=full_set.policy_version,
            items=tuple(kept),
            attention_hash=_attention_hash(kept),
        )

    # ------------------------------------------------------------------

    def _directive_items(self, state: AgentWorkingStateV1) -> list[AttentionItem]:
        items = []
        for directive in state.directive_refs:
            if directive.applied:
                continue
            items.append(AttentionItem(
                item_id=f"directive:{directive.directive_ref}",
                band=AttentionBand.p0_control,
                reason_codes=("UNAPPLIED_USER_DIRECTIVE",),
                title=directive.directive_ref,
                eligible_action_types=_DIRECTIVE_ACTIONS,
            ))
        return items

    def _verification_items(self, state: AgentWorkingStateV1) -> list[AttentionItem]:
        items = []
        for verification in state.pending_verifications:
            blocking_now = (
                verification.required
                and verification.blocking
                and verification.status
                in (VerificationStatus.pending, VerificationStatus.failed,
                    VerificationStatus.unavailable)
            )
            if not blocking_now:
                continue
            # F1 §7: a provider/runtime failure on a still-mandatory
            # verification stays a P1 blocker (unavailable), never a
            # silent demotion to evidence-unavailability
            reason = (
                "BLOCKING_MANDATORY_VERIFICATION_PENDING"
                if verification.status == VerificationStatus.pending
                else "MANDATORY_VERIFICATION_UNAVAILABLE"
                if verification.status == VerificationStatus.unavailable
                else "MANDATORY_VERIFICATION_FAILED"
            )
            items.append(AttentionItem(
                item_id=f"verification:{verification.verification_id}",
                band=AttentionBand.p1_correctness_blocker,
                reason_codes=(reason,),
                title=verification.target_ref,
                related_question_ids=(
                    (verification.target_ref,)
                    if state.question(verification.target_ref) is not None
                    else ()
                ),
                evidence_refs=(),
                eligible_action_types=_VERIFICATION_ACTIONS,
            ))
        return items

    def _contradiction_items(self, state: AgentWorkingStateV1) -> list[AttentionItem]:
        items = []
        for contradiction in state.contradictions:
            if contradiction.status != ContradictionStatus.open:
                continue
            band = (
                AttentionBand.p1_correctness_blocker
                if contradiction.severity == ContradictionSeverity.critical
                else (
                    AttentionBand.p3_active_progress
                    if contradiction.severity == ContradictionSeverity.material
                    else AttentionBand.p4_supporting_opportunistic
                )
            )
            items.append(AttentionItem(
                item_id=f"contradiction:{contradiction.contradiction_id}",
                band=band,
                reason_codes=("OPEN_CONTRADICTION",),
                title=contradiction.contradiction_id,
                related_contradiction_ids=(contradiction.contradiction_id,),
                evidence_refs=tuple(contradiction.refs),
                eligible_action_types=_CONTRADICTION_ACTIONS,
            ))
        return items

    def _question_items(
        self,
        state: AgentWorkingStateV1,
        runtime: DelegationRuntimeView,
        config: AttentionPolicyConfig,
    ) -> dict[str, AttentionItem]:
        bands = _effective_bands(state)
        blockers_by_target: dict[str, set[str]] = {}
        for question in state.questions:
            for relation in question.relations:
                if relation.relation_type != QuestionRelationType.blocks:
                    continue
                blockers_by_target.setdefault(relation.question_id, set()).add(
                    question.question_id
                )
        items: dict[str, AttentionItem] = {}
        for question in sorted(state.questions, key=lambda q: q.question_id):
            if question.status not in _OPEN_QUESTION_STATUSES:
                continue  # terminal obligations produce no attention item
            band = bands.get(question.question_id, _INTRINSIC_BAND[question.priority])
            evidence_refs = tuple(
                item.evidence_key
                for item in state.evidence_working_set
                if question.question_id in item.related_question_ids
            )
            if question.priority == QuestionPriority.exploratory:
                # P5 must be evidence-backed: a ref-less exploratory lead
                # (no basis refs and no linked working-set evidence) never
                # enters attention.
                if not question.basis_refs and not evidence_refs:
                    continue
            open_blockers = sorted(
                blocker
                for blocker in blockers_by_target.get(question.question_id, ())
                if state.question(blocker) is not None
                and state.question(blocker).status in _OPEN_QUESTION_STATUSES
            )
            eligibility = AttentionEligibility.eligible
            reason_codes: list[str] = []
            actions = _QUESTION_ACTIONS
            if open_blockers:
                eligibility = AttentionEligibility.blocked
                reason_codes.append("BLOCKED_BY_OPEN_QUESTION")
                actions = (AttentionActionType.create_question,)
            if (
                question.priority == QuestionPriority.exploratory
                and config.suppress_exploratory_when_budget_exhausted
                and state.budget_state.exhausted
            ):
                eligibility = AttentionEligibility.suppressed
                reason_codes.append("SUPPRESSED_BUDGET_EXHAUSTED")
            if question.question_id in runtime.in_flight_question_refs:
                reason_codes.append("DELEGATION_IN_FLIGHT")
            evidence_refs = tuple(
                item.evidence_key
                for item in state.evidence_working_set
                if question.question_id in item.related_question_ids
            )
            items[question.question_id] = AttentionItem(
                item_id=f"question:{question.question_id}",
                band=band,
                intrinsic_priority=question.priority,
                eligibility=eligibility,
                blocked_by=tuple(open_blockers),
                reason_codes=tuple(reason_codes),
                title=question.text,
                related_question_ids=(question.question_id,),
                evidence_refs=evidence_refs,
                eligible_action_types=actions,
            )
        return items

    def _coverage_items(
        self,
        state: AgentWorkingStateV1,
        question_items: dict[str, AttentionItem],
    ):
        items = []
        for dimension in sorted(state.coverage, key=lambda c: c.dimension_id):
            if dimension.status in COVERAGE_TERMINAL_OR_NA:
                continue
            band = (
                AttentionBand.p2_investigation_obligation
                if dimension.required
                else AttentionBand.p4_supporting_opportunistic
            )
            linked = [
                qid
                for qid in dimension.related_question_ids
                if qid in question_items
            ]
            if linked:
                # deterministic coalescing: merge into the primary question
                # item(s); a coverage row never becomes a separate item when
                # an explicit question link exists.
                continue
            items.append(AttentionItem(
                item_id=f"coverage:{dimension.dimension_id}",
                band=band,
                reason_codes=("COVERAGE_GAP",),
                title=dimension.dimension_id,
                related_coverage_refs=(dimension.dimension_id,),
                related_question_ids=tuple(dimension.related_question_ids),
                eligible_action_types=_COVERAGE_ACTIONS,
            ))
        return items


# terminal coverage statuses produce no attention item
COVERAGE_TERMINAL_OR_NA = set(CoverageStatus) - {
    CoverageStatus.not_started,
    CoverageStatus.in_progress,
}


def _attention_hash(items: tuple[AttentionItem, ...]) -> str:
    payload = json.dumps(
        [item.model_dump(mode="json") for item in items],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
