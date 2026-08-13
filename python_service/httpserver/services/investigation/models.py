"""Pydantic models for Investigation Evidence Snapshots (Phase C4a).

A Snapshot is the immutable Initial-state of an Evidence frozen at first
capture. ``FileSnapshotPayload`` / ``ClusterSnapshotPayload`` are the typed
payloads stored (deterministically serialized) in ``evidence_snapshots.snapshot_json``.
Missing source fields are NULL -- a Snapshot never generates data (no LLM).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


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


class AnalysisInputEnvelope(BaseModel):
    """Content-addressed input envelope for a Secondary Analysis (A7/A8/A11).

    ``evidence_snapshot`` is the DB-trusted Snapshot's ``model_dump(mode="json")``
    (with no surrogate ``snapshot_id``) -- re-read inside the write transaction,
    never caller-supplied. The envelope is deterministically serialized and
    SHA-256 hashed so the same logical input yields the same ``input_hash``.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    evidence_snapshot: dict
    analyst_note: Optional[str] = None
    case_context: Optional[str] = None
    related_evidence: tuple[str, ...] = ()
    prompt_version: Optional[str] = None


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
