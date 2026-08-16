"""Pydantic models for Investigation Evidence Snapshots (Phase C4a).

A Snapshot is the immutable Initial-state of an Evidence frozen at first
capture. ``FileSnapshotPayload`` / ``ClusterSnapshotPayload`` are the typed
payloads stored (deterministically serialized) in ``evidence_snapshots.snapshot_json``.
Missing source fields are NULL -- a Snapshot never generates data (no LLM).
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FileSnapshotPayload(BaseModel):
    """Frozen initial state of a file Evidence (read from files.db at capture)."""

    model_config = ConfigDict(frozen=True)

    evidence_type: Literal["file"] = "file"
    normalized_path: str
    name: Optional[str] = None
    extension: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    size: Optional[int] = None
    md5: Optional[str] = None
    mtime: Optional[int] = None
    ctime: Optional[int] = None
    is_deleted: Optional[int] = None
    # Initial Analysis, frozen as-is (never generated)
    initial_summary: Optional[str] = None
    initial_description: Optional[str] = None
    initial_keywords: Optional[str] = None
    initial_model: Optional[str] = None
    initial_analyzed_at: Optional[int] = None
    scene_type: Optional[str] = None
    scene_priority: Optional[int] = None
    scene_relevant: Optional[int] = None


class ClusterSnapshotPayload(BaseModel):
    """Frozen initial state of a cluster Evidence (recomputed from events.db at capture).

    Initial AI fields are None in C4a: cluster identity is the 2-part
    ``(unix_minute, event_type)``, but cluster LLM analysis is written at 3-part
    granularity (with parent_directory), so a cluster-level AI value cannot be
    determined deterministically -- empty rather than fabricated (S7).
    """

    model_config = ConfigDict(frozen=True)

    evidence_type: Literal["cluster"] = "cluster"
    unix_minute: int
    event_type: str
    cluster_start: Optional[int] = None
    cluster_end: Optional[int] = None
    event_count: Optional[int] = None
    representative_timestamp: Optional[int] = None
    initial_summary: Optional[str] = None
    initial_description: Optional[str] = None
    initial_keywords: Optional[str] = None


SnapshotPayload = Union[FileSnapshotPayload, ClusterSnapshotPayload]


class SnapshotCandidate(BaseModel):
    """Fully-built, immutable snapshot ready to INSERT (constructed outside the
    write transaction)."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    evidence_type: Literal["file", "cluster"]
    captured_at: int
    payload: SnapshotPayload
    # identity / index columns (must satisfy the table CHECK)
    normalized_path: Optional[str] = None
    unix_minute: Optional[int] = None
    event_type: Optional[str] = None


class EvidenceSnapshot(BaseModel):
    """A captured (or re-read) immutable Evidence Snapshot."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    evidence_type: Literal["file", "cluster"]
    captured_at: int
    payload: SnapshotPayload
    # Internal relational key only -- never part of public Evidence Identity
    # and never serialized into HTTP responses (A12). Excluded from model_dump.
    snapshot_id: int = Field(exclude=True)


# ---------------------------------------------------------------------------
# Secondary Analysis (Phase C4b-1)
# ---------------------------------------------------------------------------


class SecondaryAnalysisStatus(str, Enum):
    """Versioned Secondary Analysis lifecycle states.

    State machine (frozen):
        queued       -> running | failed
        running      -> review_pending | failed
        review_pending -> accepted | rejected | invalid
        terminal = {accepted, rejected, invalid, failed}  (zero out-degree;
                   redoing an analysis creates a NEW version row, never mutates)
    """

    queued = "queued"
    running = "running"
    review_pending = "review_pending"
    accepted = "accepted"
    rejected = "rejected"
    invalid = "invalid"
    failed = "failed"


class AnalysisReviewDecision(str, Enum):
    """Explicit analyst decision for a review-pending analysis."""

    accepted = "accepted"
    rejected = "rejected"
    invalid = "invalid"


# Legal transitions keyed by source status. Terminal statuses have zero
# out-degree (absent from this mapping).
SECONDARY_TRANSITIONS: dict[SecondaryAnalysisStatus, frozenset[SecondaryAnalysisStatus]] = {
    SecondaryAnalysisStatus.queued: frozenset(
        {SecondaryAnalysisStatus.running, SecondaryAnalysisStatus.failed}
    ),
    SecondaryAnalysisStatus.running: frozenset(
        {SecondaryAnalysisStatus.review_pending, SecondaryAnalysisStatus.failed}
    ),
    SecondaryAnalysisStatus.review_pending: frozenset(
        {SecondaryAnalysisStatus.accepted, SecondaryAnalysisStatus.rejected, SecondaryAnalysisStatus.invalid}
    ),
}

TERMINAL_SECONDARY_STATUSES: frozenset[SecondaryAnalysisStatus] = frozenset(
    {
        SecondaryAnalysisStatus.accepted,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.invalid,
        SecondaryAnalysisStatus.failed,
    }
)


# ---------------------------------------------------------------------------
# Claims & Grounding (Phase C5a)
# ---------------------------------------------------------------------------


class ClaimType(str, Enum):
    """Claim classification (G6)."""
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class ClaimGroundingStatus(str, Enum):
    """Per-claim grounding status.

    ``grounded`` means all evidence_refs are valid allowed IDs (G8: this does
    NOT mean the evidence semantically proves the claim — only that the refs
    point to real, permitted Evidence).
    """
    GROUNDED = "grounded"
    PARTIALLY_GROUNDED = "partially_grounded"
    UNGROUNDED = "ungrounded"


class AnalysisGroundingStatus(str, Enum):
    """Aggregated analysis-level grounding status.

    ``valid`` = no invalid evidence reference detected (NOT "all conclusions
    are fully proven by evidence"). 0-claim analyses are ``valid``.
    """
    VALID = "valid"
    PARTIALLY_GROUNDED = "partially_grounded"
    INVALID = "invalid"


class RelatedEvidenceEntry(BaseModel):
    """A frozen related-evidence entry in the analysis envelope (C4c/CCTX5).

    ``evidence_key`` is canonical; ``snapshot`` is the DB-trusted
    ``EvidenceSnapshot.model_dump(mode="json")`` (no surrogate ``snapshot_id``).
    """

    model_config = ConfigDict(frozen=True)

    evidence_key: str
    snapshot: dict

    @model_validator(mode="after")
    def _validate_identity(self):
        if self.snapshot.get("evidence_key") != self.evidence_key:
            raise ValueError("related evidence snapshot identity mismatch")
        return self


class AnalysisInputEnvelopeV1(BaseModel):
    """Envelope schema v1 (C4b-1): related_evidence is canonical key strings."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    evidence_snapshot: dict
    analyst_note: Optional[str] = None
    case_context: Optional[str] = None
    related_evidence: tuple[str, ...] = ()
    prompt_version: Optional[str] = None


class AnalysisInputEnvelopeV2(BaseModel):
    """Envelope schema v2 (C4c): related_evidence carries frozen snapshots.

    ``analyst_note`` and ``case_context`` are plain text frozen at create time
    (CCTX1: Note != Evidence != Fact). ``related_evidence`` entries contain
    canonical key + frozen EvidenceSnapshot so the worker never re-reads source.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[2] = 2
    evidence_snapshot: dict
    analyst_note: Optional[str] = None
    case_context: Optional[str] = None
    related_evidence: tuple[RelatedEvidenceEntry, ...] = ()
    prompt_version: Optional[str] = None


AnalysisInputEnvelope = Union[AnalysisInputEnvelopeV1, AnalysisInputEnvelopeV2]


def parse_analysis_input_envelope(raw: Union[str, dict]) -> AnalysisInputEnvelope:
    """Parse an envelope JSON string or dict into the correct typed model.

    Dispatches on ``schema_version``: v1 -> V1 (key strings), v2 -> V2 (frozen
    snapshots). Raises ``ValueError`` for unsupported versions.
    """
    payload = json.loads(raw) if isinstance(raw, str) else raw
    version = payload.get("schema_version")
    if version == 1:
        return AnalysisInputEnvelopeV1.model_validate(payload)
    if version == 2:
        return AnalysisInputEnvelopeV2.model_validate(payload)
    raise ValueError(f"unsupported envelope schema version: {version!r}")


class SecondaryAnalysis(BaseModel):
    """A versioned, immutable Secondary Analysis row (one version = one row).

    A row is only ever created (``queued``) and then advanced through the state
    machine via ``transition``. Terminal rows are immutable at the DB level
    (trigger ``trg_secondary_no_terminal_update``).
    """

    model_config = ConfigDict(frozen=True)

    analysis_id: str
    task_id: str
    evidence_key: str  # canonical
    snapshot_id: int = Field(exclude=True)  # FK -> evidence_snapshots.id (internal, A12)
    version: int
    status: SecondaryAnalysisStatus
    input_hash: str
    input_envelope_json: str
    prompt_version: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    model: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    review_pending_at: Optional[str] = None
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None
    failed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    grounding_status: Optional[AnalysisGroundingStatus] = None


# ---------------------------------------------------------------------------
# Claim models (C5a)
# ---------------------------------------------------------------------------


class ClaimCandidate(BaseModel):
    """Untrusted pre-validation claim from LLM (or test).

    This is the ONLY type ``persist_claims`` accepts — the Repository runs
    GroundingValidator internally (G11) so callers cannot bypass validation
    by constructing ValidatedClaim directly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_type: ClaimType
    claim_text: str = Field(min_length=1, max_length=20_000)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def _validate_ref_lengths(self):
        if any(not isinstance(ref, str) or not 1 <= len(ref) <= 4096 for ref in self.evidence_refs):
            raise ValueError("evidence_refs must contain strings of 1-4096 characters")
        return self


class StructuredAnalysisResponse(BaseModel):
    """Strict structured LLM output for prompt v3 (L1-L3, L8-L10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1, max_length=20_000)
    summary: str = Field(min_length=1, max_length=20_000)
    claims: tuple[ClaimCandidate, ...] = Field(default=(), max_length=100)


class ValidatedClaim(BaseModel):
    """Post-validation claim with adjusted type, grounding, and warnings.

    Produced by ``GroundingValidator.validate``. ``evidence_refs`` contains only
    valid refs (invalid ones moved to ``warnings``). ``claim_type`` may differ
    from the original candidate (FACT → HYPOTHESIS downgrade, G7).
    """

    model_config = ConfigDict(frozen=True)

    claim_type: ClaimType
    claim_text: str
    grounding_status: ClaimGroundingStatus
    evidence_refs: tuple[str, ...] = ()
    warnings: dict = Field(default_factory=dict)


class AnalysisClaim(BaseModel):
    """A persisted Claim row with its evidence refs (read model)."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    analysis_id: str
    claim_index: int
    claim_type: ClaimType
    claim_text: str
    grounding_status: ClaimGroundingStatus
    warnings: Optional[dict] = None
    evidence_refs: tuple[str, ...] = ()
    created_at: str


# ---------------------------------------------------------------------------
# Investigation Event models (Phase C7a)
# ---------------------------------------------------------------------------


class InvestigationEvent(BaseModel):
    """An Investigation-layer event: stable identity + current narrative.

    ``current_version``/``title``/``summary`` are DERIVED from the highest
    version row at read time — there is no materialized pointer. Snapshots of
    this model are point-in-time reads, not mutable references.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str
    task_id: str
    needs_refresh: bool
    current_version: int
    title: str
    summary: Optional[str] = None
    created_at: str
    updated_at: str


class InvestigationEventVersion(BaseModel):
    """One immutable narrative version of an Investigation Event."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    event_id: str
    version: int
    title: str
    summary: Optional[str] = None
    created_at: str
    created_by: Optional[str] = None


class EventEvidenceLink(BaseModel):
    """An explicit, INSERT-only Event→Evidence relation (canonical key)."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    event_id: str
    evidence_key: str
    linked_at: str
    linked_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Event Refresh models (Phase C7c-1)
# ---------------------------------------------------------------------------


class EventRefreshStatus(str, Enum):
    """Event refresh lifecycle: the refresh row IS the job (C4b-2 model)."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class EventRefreshClaimV1(BaseModel):
    """Frozen claim projection consumed by refresh execution (no row IDs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_type: ClaimType
    claim_text: str
    grounding_status: ClaimGroundingStatus
    evidence_refs: tuple[str, ...] = ()
    warnings: Optional[dict] = None


class EventRefreshAcceptedAnalysisV1(BaseModel):
    """The exact accepted analysis frozen at admission (F6).

    No decided_by/decided_at: reviewer identity is not LLM input and must
    not enter the input_hash.  description/summary/grounding_status are
    Optional because legacy v1/v2 accepted analyses may lack them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis_id: str
    version: int
    evidence_key: str
    description: Optional[str] = None
    summary: Optional[str] = None
    grounding_status: Optional[AnalysisGroundingStatus] = None
    claims: tuple[EventRefreshClaimV1, ...] = ()


class EventRefreshLinkV1(BaseModel):
    """One authoritative link with its frozen snapshot and chosen analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str
    snapshot: dict  # canonical EvidenceSnapshot.model_dump() (no snapshot_id)
    accepted_analysis: Optional[EventRefreshAcceptedAnalysisV1] = None


class EventRefreshEnvelopeV1(BaseModel):
    """Self-contained frozen refresh input (C7c-1 historical format)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str
    base_version: int
    base_title: str
    base_summary: Optional[str] = None
    needs_refresh_at_submission: bool
    links: tuple[EventRefreshLinkV1, ...] = ()


class EventRefreshEnvelopeV2(BaseModel):
    """Executable refresh input with an immutable prompt contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2
    prompt_version: str
    event_id: str
    base_version: int
    base_title: str
    base_summary: Optional[str] = None
    needs_refresh_at_submission: bool
    links: tuple[EventRefreshLinkV1, ...] = ()


EventRefreshEnvelope = Union[EventRefreshEnvelopeV1, EventRefreshEnvelopeV2]


def parse_event_refresh_envelope(raw: Union[str, dict]) -> EventRefreshEnvelope:
    """Parse a historical V1 or executable V2 refresh envelope."""
    payload = json.loads(raw) if isinstance(raw, str) else raw
    version = payload.get("schema_version")
    if version == 1:
        return EventRefreshEnvelopeV1.model_validate(payload)
    if version == 2:
        return EventRefreshEnvelopeV2.model_validate(payload)
    raise ValueError(f"unsupported event refresh envelope schema: {version!r}")


class StructuredEventRefreshResponse(BaseModel):
    """Strict title/summary output for an Event narrative refresh."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=20_000)


class EventRefresh(BaseModel):
    """A persisted refresh job row (read model)."""

    model_config = ConfigDict(frozen=True)

    refresh_id: str
    task_id: str
    event_id: str
    base_version: int
    status: EventRefreshStatus
    requested_by: Optional[str] = None
    input_hash: str
    input_envelope_json: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    produced_version: Optional[int] = None
    failed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Investigation Graph overlay read models (Phase C8b)
# ---------------------------------------------------------------------------


class InvestigationGraphNode(BaseModel):
    """One composed graph node: a Base KG entity or an overlay projection.

    ``id`` is deterministic: overlay nodes use the ``event:`` / ``analysis:``
    / ``claim:`` / ``evidence:`` namespaces over persisted IDs; base_kg nodes
    keep the Graphiti Entity uuid untouched (G12).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    label: str
    summary: Optional[str] = None
    source: Literal["base_kg", "investigation"]
    confirmed: Optional[bool] = None
    provenance: Optional[dict] = None


class InvestigationGraphLink(BaseModel):
    """One composed graph edge.

    ``kind`` is the authoritative relation class.  Base KG links carry no
    persisted edge id, so their ``id`` is derived from the
    (source, relation, target) triple the Base query returns.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    target: str
    label: str
    kind: Literal[
        "base_relation",
        "event_evidence",
        "analysis_evidence",
        "analysis_claim",
        "claim_evidence",
    ]
    provenance: Optional[dict] = None


class InvestigationGraphResponse(BaseModel):
    """Derived read-only composition of Base KG + Investigation Overlay.

    ``base_max_nodes`` bounds only the Base KG read; the overlay is never
    truncated (B4).  An empty ``warnings`` tuple means both sources read.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    base_graph_available: bool
    base_max_nodes: int
    nodes: tuple[InvestigationGraphNode, ...] = ()
    links: tuple[InvestigationGraphLink, ...] = ()
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Workbench read models (Phase C9a) -- read-only projections only
# ---------------------------------------------------------------------------

class SelectedAnalysisRef(BaseModel):
    """The one analysis version selected for one evidence (C8b G3/G5 rules).

    ``accepted`` wins over newer pending/rejected; ``review_pending`` only
    appears as the explicit unconfirmed fallback.  This is the same frozen
    selection the Graph overlay uses -- not a new semantics.
    """

    model_config = ConfigDict(frozen=True)

    evidence_key: str
    analysis_id: str
    version: int
    review_state: Literal["accepted", "review_pending"]
    summary: Optional[str] = None


class EvidenceSummary(BaseModel):
    """One evidence row for the Workbench evidence list (read-only)."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    evidence_type: Literal["file", "cluster"]
    captured_at: int
    selected_analysis: Optional[SelectedAnalysisRef] = None


class AnalysisClaimsResponse(BaseModel):
    """The exact historical claims of one exact analysis version (read-only).

    Claims are immutable and never re-derived: this is the persisted
    ``analysis_claims`` row set of the requested ``analysis_id`` only.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    analysis_id: str
    claims: tuple[AnalysisClaim, ...] = ()


# ---------------------------------------------------------------------------
# Report Evidence models (Phase R1) -- frozen explicit Report binding
# ---------------------------------------------------------------------------


class ReportEvidenceStatus(str, Enum):
    """Analyst-decided placement of one evidence inside the Report.

    ``excluded`` is an explicit state, never a DELETE: it records that the
    analyst considered the evidence and then removed it from the report body.
    All three states may transition into each other via explicit updates.
    """

    excluded = "excluded"
    main = "main"
    appendix = "appendix"


class ReportEvidence(BaseModel):
    """One persisted report_evidence row (exact persisted binding).

    ``analysis_id`` is the FROZEN accepted Secondary Analysis the analyst
    explicitly bound at add/rebind time -- never a "latest accepted" pointer.
    The Evidence itself (``task_id`` + ``evidence_key``) is always the real
    report source; the analysis is only an attached interpretation version.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    report_status: ReportEvidenceStatus
    analysis_id: Optional[str] = None
    added_by: str
    created_at: str
    updated_at: str
    updated_by: Optional[str] = None


class BoundAnalysisRef(BaseModel):
    """Exact metadata of the frozen analysis binding (read projection).

    Joined from the immutable ``secondary_analyses`` row of the bound
    ``analysis_id`` at read time; terminal rows never change, so this is a
    stable projection of the frozen binding.
    """

    model_config = ConfigDict(frozen=True)

    analysis_id: str
    version: int
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    summary: Optional[str] = None


class ReportEvidenceItem(BaseModel):
    """One report_evidence row plus its exact bound-analysis read projection.

    ``newer_accepted_available`` is a read-time hint ONLY (an accepted
    analysis exists that is not the frozen binding).  It never changes the
    binding automatically -- rebinding is always an explicit analyst action.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    report_status: ReportEvidenceStatus
    analysis_id: Optional[str] = None
    added_by: str
    created_at: str
    updated_at: str
    updated_by: Optional[str] = None
    bound_analysis: Optional[BoundAnalysisRef] = None
    newer_accepted_available: bool = False
