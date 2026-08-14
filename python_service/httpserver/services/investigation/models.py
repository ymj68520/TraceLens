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
