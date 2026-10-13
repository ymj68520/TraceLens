"""IntegrationProposalContractDraftV1 (RCA-2A §5) — EXPERIMENTAL, OFFLINE.

Isolation guarantee (RCA-2A §10): this module lives in the benchmarks
tree, OUTSIDE the production ``httpserver`` package. The production agent
factory's import graph never reaches it; it is loaded only by explicit
test/audit imports. It defines no production behaviour.

Design in one sentence: the model keeps EVERY semantic decision it has
today, expressed through ONE uniform update envelope (the entity kind is
inferred from the handle prefix — a bijective, exact mapping, not fuzzy
matching) — and a deterministic resolver translates the proposal into the
CANONICAL ``SupervisorIntegrationDecisionV2`` actions, which then flow
through the UNCHANGED ``resolve_integration_proposal_v2`` binding table,
the UNCHANGED ``IntegrationDecisionValidator``, the UNCHANGED
``StateTransitionPolicy`` and the UNCHANGED ``FinalizationGate``.

Frozen responsibility boundary (A1-S/A1-T/A1-H/v2 contract — unchanged):
    LLM chooses meaning; TraceLens binds identity.
    - the model NEVER emits task/run/state identity (structurally absent);
    - handles pass through VERBATIM to the canonical layer (no fuzzy
      repair, no auto-creation, no relaxed enums: every to_status value
      must be a member of the TARGET KIND's frozen enum, enforced here at
      resolve time — fail-closed before any commit);
    - the resolver never picks dispositions, never fills basis handles.

Status: DRAFT for architecture review. Not wired to any production path.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_integration_v2 import (
    AddFindingReferenceActionV2,
    AddPendingProposalReferenceActionV2,
    ContradictionHandle,
    ContradictionSeverity,
    ContradictionStatus,
    CoverageHandle,
    CoverageStatus,
    CreateContradictionActionV2,
    CreateHypothesisActionV2,
    CreateQuestionActionV2,
    EvidenceHandle,
    EvidenceRelevanceStatus,
    FindingHandle,
    HypothesisHandle,
    HypothesisStatus,
    INTEGRATION_DECISION_VERSION,
    ProposalHandle,
    QuestionDisposition,
    QuestionHandle,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    SupervisorIntegrationDecisionV2,
    UpdateContradictionActionV2,
    UpdateCoverageActionV2,
    UpdateEvidenceRelevanceActionV2,
    UpdateHypothesisActionV2,
    UpdateQuestionActionV2,
)
PROPOSAL_VERSION = "supervisor-integration-proposal:v1"


# ---------------------------------------------------------------------------
# frozen per-kind status vocabularies (EXACTLY the production enums —
# membership is enforced at resolve time; nothing is relaxed)
# ---------------------------------------------------------------------------

_KIND_STATUS_ENUMS = {
    "question": QuestionStatus,
    "evidence": EvidenceRelevanceStatus,
    "hypothesis": HypothesisStatus,
    "contradiction": ContradictionStatus,
    "coverage": CoverageStatus,
}

# bijective handle-prefix -> kind mapping (exact string inspection, never
# fuzzy matching; the binding table still validates existence + kind)
_PREFIX_KIND = (
    ("COV", "coverage"),
    ("Q", "question"),
    ("E", "evidence"),
    ("H", "hypothesis"),
    ("X", "contradiction"),
    ("F", "finding"),
    ("P", "proposal"),
)


def infer_handle_kind(handle: str) -> Optional[str]:
    """Exact prefix -> kind inference. Returns None for unknown prefixes
    (F/P handles are reference-only and cannot be update targets)."""
    text = str(handle or "")
    for prefix, kind in _PREFIX_KIND:
        if text.startswith(prefix):
            return kind
    return None


class ProposalViolation(Exception):
    """Fail-closed proposal-layer violation (raised before any canonical
    decision is assembled; never coerced into a success)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# codes (typed, fail-closed)
P_UNKNOWN_HANDLE_PREFIX = "proposal_unknown_handle_prefix"
P_HANDLE_NOT_UPDATABLE = "proposal_handle_not_updatable"
P_STATUS_NOT_IN_KIND_ENUM = "proposal_status_not_in_kind_enum"
P_DISPOSITION_NOT_IN_ENUM = "proposal_disposition_not_in_enum"
P_FIELD_NOT_VALID_FOR_KIND = "proposal_field_not_valid_for_kind"
P_MISSING_STATUS = "proposal_missing_status"
P_BASIS_HANDLE_NOT_EVIDENCE = "proposal_basis_handle_not_evidence"
P_SOURCE_NOT_IN_ENUM = "proposal_source_not_in_enum"
P_PRIORITY_NOT_IN_ENUM = "proposal_priority_not_in_enum"
P_SEVERITY_NOT_IN_ENUM = "proposal_severity_not_in_enum"


# ---------------------------------------------------------------------------
# proposal actions
# ---------------------------------------------------------------------------


class _ProposalAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UpdateAction(_ProposalAction):
    """ONE uniform semantic update for every updatable entity kind.

    The model chooses: which operand (handle), the new status, and the
    kind-appropriate evidence/justification fields. Question-only fields
    are rejected when the target kind is not question (fail-closed) —
    same authority, smaller surface."""

    action: Literal["update"] = "update"
    target_handle: str
    to_status: str
    disposition: Optional[str] = None          # question only
    basis_handles: Tuple[str, ...] = ()        # evidence handles (Q closure)
    limitations: Tuple[str, ...] = ()          # question only
    investigated_summary: Optional[str] = None  # question only
    blocker: Optional[str] = None              # question only
    superseded_by_handle: Optional[str] = None  # question only
    resolution_basis_handles: Tuple[str, ...] = ()  # contradiction only
    attempted_resolution: Optional[str] = None  # contradiction only
    impact: Optional[str] = None               # contradiction only
    limitation: Optional[str] = None           # coverage only
    capability_basis: Optional[str] = None     # coverage only
    related_question_handles: Tuple[str, ...] = ()  # evidence/coverage only


class CreateQuestionAction(_ProposalAction):
    action: Literal["create_question"] = "create_question"
    text: str
    source: Optional[str] = None    # QuestionSource value (validated)
    priority: Optional[str] = None  # QuestionPriority value (validated)
    parent_question_handle: Optional[str] = None


class CreateHypothesisAction(_ProposalAction):
    action: Literal["create_hypothesis"] = "create_hypothesis"
    text: str
    supporting_handles: Tuple[str, ...] = ()


class CreateContradictionAction(_ProposalAction):
    action: Literal["create_contradiction"] = "create_contradiction"
    severity: str  # ContradictionSeverity value (validated)
    refs_handles: Tuple[str, ...] = ()
    attempted_resolution: Optional[str] = None
    impact: Optional[str] = None
    limitation: Optional[str] = None


class AddFindingReferenceAction(_ProposalAction):
    action: Literal["add_finding_reference"] = "add_finding_reference"
    finding_handle: str


class AddPendingProposalReferenceAction(_ProposalAction):
    action: Literal["add_pending_proposal_reference"] = (
        "add_pending_proposal_reference")
    proposal_handle: str


ProposalAction = Union[
    UpdateAction,
    CreateQuestionAction,
    CreateHypothesisAction,
    CreateContradictionAction,
    AddFindingReferenceAction,
    AddPendingProposalReferenceAction,
]


class SupervisorIntegrationProposalV1(BaseModel):
    """The model-facing proposal: semantic actions only, identity-free
    (task/run/state identity remains structurally absent — injected by
    the frozen context exactly as the canonical v2 path does)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_version: str = PROPOSAL_VERSION
    integration_summary: str = ""
    actions: Tuple[ProposalAction, ...] = ()
    limitations: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# deterministic resolver: proposal -> canonical v2 decision
# ---------------------------------------------------------------------------


def _enum_member(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _require_enum(enum_cls, value, code, label):
    member = _enum_member(enum_cls, value)
    if member is None:
        raise ProposalViolation(
            code,
            f"{label}={value!r} is not a member of {enum_cls.__name__} "
            f"(frozen vocabulary: {[m.value for m in enum_cls]})",
        )
    return member


def _basis_evidence_handles(raw, label):
    out = []
    for handle in raw:
        kind = infer_handle_kind(handle)
        if kind != "evidence":
            raise ProposalViolation(
                P_BASIS_HANDLE_NOT_EVIDENCE,
                f"{label}: {handle!r} is not an evidence handle (basis "
                "operands must be evidence handles)",
            )
        out.append(EvidenceHandle(handle))
    return out or None


def _resolve_update(action: UpdateAction) -> object:
    kind = infer_handle_kind(action.target_handle)
    if kind is None:
        raise ProposalViolation(
            P_UNKNOWN_HANDLE_PREFIX,
            f"target_handle {action.target_handle!r} has no known kind "
            "prefix (F/P handles are reference-only)",
        )
    if not action.to_status:
        raise ProposalViolation(P_MISSING_STATUS, "update requires to_status")

    if kind == "question":
        _reject_foreign_fields(
            action, kind,
            {"resolution_basis_handles", "attempted_resolution", "impact",
             "limitation", "capability_basis", "related_question_handles"})
        status = _require_enum(
            QuestionStatus, action.to_status,
            P_STATUS_NOT_IN_KIND_ENUM, "to_status")
        disposition = None
        if action.disposition is not None:
            disposition = _require_enum(
                QuestionDisposition, action.disposition,
                P_DISPOSITION_NOT_IN_ENUM, "disposition")
        superseded = None
        if action.superseded_by_handle is not None:
            if infer_handle_kind(action.superseded_by_handle) != "question":
                raise ProposalViolation(
                    P_BASIS_HANDLE_NOT_EVIDENCE,
                    "superseded_by_handle must be a question handle")
            superseded = QuestionHandle(action.superseded_by_handle)
        return UpdateQuestionActionV2(
            question_handle=QuestionHandle(action.target_handle),
            to_status=status,
            disposition=disposition,
            basis_handles=_basis_evidence_handles(
                action.basis_handles, "basis_handles"),
            limitations=tuple(action.limitations) or None,
            investigated_summary=action.investigated_summary,
            blocker=action.blocker,
            superseded_by_handle=superseded,
        )

    _reject_foreign_fields(
        action, kind,
        {"disposition", "limitations", "investigated_summary", "blocker",
         "superseded_by_handle"})

    if kind == "evidence":
        status = _require_enum(
            EvidenceRelevanceStatus, action.to_status,
            P_STATUS_NOT_IN_KIND_ENUM, "to_status")
        return UpdateEvidenceRelevanceActionV2(
            evidence_handle=EvidenceHandle(action.target_handle),
            to_status=status,
            related_question_handles=_question_handles(
                action.related_question_handles),
        )
    if kind == "hypothesis":
        status = _require_enum(
            HypothesisStatus, action.to_status,
            P_STATUS_NOT_IN_KIND_ENUM, "to_status")
        return UpdateHypothesisActionV2(
            hypothesis_handle=HypothesisHandle(action.target_handle),
            to_status=status,
        )
    if kind == "contradiction":
        status = _require_enum(
            ContradictionStatus, action.to_status,
            P_STATUS_NOT_IN_KIND_ENUM, "to_status")
        _reject_foreign_fields(
            action, kind,
            {"capability_basis", "related_question_handles"})
        return UpdateContradictionActionV2(
            contradiction_handle=ContradictionHandle(action.target_handle),
            to_status=status,
            resolution_basis_handles=(
                _basis_evidence_handles(
                    action.resolution_basis_handles,
                    "resolution_basis_handles")),
            attempted_resolution=action.attempted_resolution,
            impact=action.impact,
            limitation=action.limitation,
        )
    if kind == "coverage":
        status = _require_enum(
            CoverageStatus, action.to_status,
            P_STATUS_NOT_IN_KIND_ENUM, "to_status")
        return UpdateCoverageActionV2(
            coverage_handle=CoverageHandle(action.target_handle),
            to_status=status,
            basis_handles=_basis_evidence_handles(
                action.basis_handles, "basis_handles"),
            limitation=action.limitation,
            capability_basis=action.capability_basis,
            related_question_handles=_question_handles(
                action.related_question_handles),
        )
    raise ProposalViolation(
        P_HANDLE_NOT_UPDATABLE, f"kind {kind!r} is not updatable")


def _question_handles(raw):
    out = []
    for handle in raw:
        if infer_handle_kind(handle) != "question":
            raise ProposalViolation(
                P_BASIS_HANDLE_NOT_EVIDENCE,
                f"{handle!r} is not a question handle",
            )
        out.append(QuestionHandle(handle))
    return out or None


def _reject_foreign_fields(action: UpdateAction, kind: str, forbidden: set):
    for field in forbidden:
        value = getattr(action, field)
        # "empty default" is absence; an explicitly set foreign field is a
        # violation (fail-closed, no silent drop)
        present = (
            value is not None
            and value != ()
            and value != ""
        )
        if present:
            raise ProposalViolation(
                P_FIELD_NOT_VALID_FOR_KIND,
                f"field {field!r} is not valid for a {kind!r} update",
            )


def _resolve_create_question(action: CreateQuestionAction):
    source = QuestionSource.supervisor_discovery
    if action.source is not None:
        source = _require_enum(
            QuestionSource, action.source, P_SOURCE_NOT_IN_ENUM, "source")
    priority = QuestionPriority.high
    if action.priority is not None:
        priority = _require_enum(
            QuestionPriority, action.priority, P_PRIORITY_NOT_IN_ENUM,
            "priority")
    parent = None
    if action.parent_question_handle is not None:
        if infer_handle_kind(action.parent_question_handle) != "question":
            raise ProposalViolation(
                P_BASIS_HANDLE_NOT_EVIDENCE,
                "parent_question_handle must be a question handle")
        parent = QuestionHandle(action.parent_question_handle)
    return CreateQuestionActionV2(
        text=action.text, source=source, priority=priority,
        parent_question_handle=parent,
    )


def _resolve_create_contradiction(action: CreateContradictionAction):
    severity = _require_enum(
        ContradictionSeverity, action.severity, P_SEVERITY_NOT_IN_ENUM,
        "severity")
    return CreateContradictionActionV2(
        severity=severity,
        refs_handles=_basis_evidence_handles(
            action.refs_handles, "refs_handles") or (),
        attempted_resolution=action.attempted_resolution,
        impact=action.impact,
        limitation=action.limitation,
    )


def resolve_proposal_to_canonical(
    proposal: SupervisorIntegrationProposalV1,
) -> SupervisorIntegrationDecisionV2:
    """Deterministic proposal -> canonical V2 decision. Raises
    ProposalViolation (fail-closed) on any proposal-layer violation; the
    canonical decision then flows through the UNCHANGED
    resolve_integration_proposal_v2 binding/validation path."""
    canonical_actions = []
    for action in proposal.actions:
        if isinstance(action, UpdateAction):
            canonical_actions.append(_resolve_update(action))
        elif isinstance(action, CreateQuestionAction):
            canonical_actions.append(_resolve_create_question(action))
        elif isinstance(action, CreateHypothesisAction):
            canonical_actions.append(CreateHypothesisActionV2(
                text=action.text,
                supporting_handles=_basis_evidence_handles(
                    action.supporting_handles, "supporting_handles") or (),
            ))
        elif isinstance(action, CreateContradictionAction):
            canonical_actions.append(_resolve_create_contradiction(action))
        elif isinstance(action, AddFindingReferenceAction):
            if infer_handle_kind(action.finding_handle) != "finding":
                raise ProposalViolation(
                    P_BASIS_HANDLE_NOT_EVIDENCE,
                    "add_finding_reference requires a finding handle")
            canonical_actions.append(AddFindingReferenceActionV2(
                finding_handle=FindingHandle(action.finding_handle)))
        elif isinstance(action, AddPendingProposalReferenceAction):
            if infer_handle_kind(action.proposal_handle) != "proposal":
                raise ProposalViolation(
                    P_BASIS_HANDLE_NOT_EVIDENCE,
                    "add_pending_proposal_reference requires a proposal "
                    "handle")
            canonical_actions.append(AddPendingProposalReferenceActionV2(
                proposal_handle=ProposalHandle(action.proposal_handle)))
        else:  # pragma: no cover
            raise ProposalViolation(
                "proposal_unknown_action", type(action).__name__)
    return SupervisorIntegrationDecisionV2(
        decision_version=INTEGRATION_DECISION_VERSION,
        actions=tuple(canonical_actions),
        integration_summary=proposal.integration_summary,
        limitations=tuple(proposal.limitations),
        warnings=tuple(proposal.warnings),
    )


__all__ = [
    "P_DISPOSITION_NOT_IN_ENUM",
    "P_FIELD_NOT_VALID_FOR_KIND",
    "P_HANDLE_NOT_UPDATABLE",
    "P_MISSING_STATUS",
    "P_STATUS_NOT_IN_KIND_ENUM",
    "P_UNKNOWN_HANDLE_PREFIX",
    "ProposalViolation",
    "SupervisorIntegrationProposalV1",
    "UpdateAction",
    "PROPOSAL_VERSION",
    "infer_handle_kind",
    "resolve_proposal_to_canonical",
]
