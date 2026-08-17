"""InvestigationRepository: task-scoped, immutable Evidence Snapshot + Secondary Analysis persistence.

Invariants (see Phase C4a/C4b-1 plans):
  Snapshot:
    S1 existing snapshot returned without re-reading source
    S2 repository bound to task_id; cross-task capture rejected
    S3 UNIQUE(task_id,evidence_key) + BEGIN IMMEDIATE + ON CONFLICT DO NOTHING
    S4 insert-once / never update (UNIQUE + UPDATE trigger); DELETE only for cleanup
    S6 PRAGMA user_version: 0->v2 init; 1->v2 migrate; v2->validate; >supported or corrupt -> fail closed
    S9 read-time row<->payload identity consistency
  Secondary Analysis (A1-A14):
    A1  bound to canonical evidence_key
    A2  bound to an existing EvidenceSnapshot (DB FK lifecycle enforced, A14)
    A3  version monotonically increasing, starts at 1
    A4  (task_id, evidence_key, version) UNIQUE
    A5  version allocation + queued INSERT same BEGIN IMMEDIATE transaction
    A6  existing versions never overwritten (new analysis = new version row)
    A7  input snapshotted as an envelope
    A8  input_hash reproducible (sha256 over canonical envelope_json)
    A9  accepted/rejected/invalid/failed terminal; history never deleted, never mutated in-place
    A10 SQLite is source of truth (restart-safe)
    A11 input_hash Snapshot content comes from the in-transaction DB trusted row, never caller-supplied
    A12 snapshot_id is internal only -- excluded from model_dump / HTTP responses
    A13 migration DDL + user_version bump in one explicit-execute transaction (NO executescript)
    A14 secondary_analyses.snapshot_id FK REFERENCES evidence_snapshots(id) ON DELETE RESTRICT
        + PRAGMA foreign_keys=ON per connection
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import quote

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.models import ResolvedEvidence
from .acquisition import build_snapshot_candidate, canonical_json
from .grounding import (
    GroundingValidator,
    compute_analysis_grounding,
    derive_allowed_evidence_ids,
)
from .models import (
    SECONDARY_TRANSITIONS,
    TERMINAL_SECONDARY_STATUSES,
    AnalysisClaim,
    AnalysisGroundingStatus,
    AnalysisInputEnvelopeV2,
    AnalysisReviewDecision,
    ClaimCandidate,
    ClaimGroundingStatus,
    ClaimType,
    ClusterSnapshotPayload,
    EventEvidenceLink,
    EventRefresh,
    EventRefreshAcceptedAnalysisV1,
    EventRefreshClaimV1,
    EventRefreshEnvelopeV1,
    EventRefreshEnvelopeV2,
    EventRefreshLinkV1,
    EventRefreshStatus,
    EvidenceSnapshot,
    FileSnapshotPayload,
    InvestigationEvent,
    InvestigationEventVersion,
    RelatedEvidenceEntry,
    ReportEvidence,
    ReportEvidenceStatus,
    SecondaryAnalysis,
    SecondaryAnalysisStatus,
    parse_analysis_input_envelope,
    parse_event_refresh_envelope,
)
from .prompts import EVENT_REFRESH_PROMPT_VERSION, PROMPT_OUTPUT_CONTRACT


class AnalysisReviewConflictError(RuntimeError):
    """The analysis exists but is not currently reviewable."""


class InvestigationEventConflictError(RuntimeError):
    """The investigation event exists but the requested relation conflicts."""


class ReportEvidenceConflictError(RuntimeError):
    """The report_evidence row exists but the requested action conflicts."""


class AnalysisBindingConflictError(RuntimeError):
    """The analysis cannot be bound to this report evidence (wrong evidence
    or not accepted) -- the triple check (R1 §7) failed."""

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = 7

# ---------------------------------------------------------------------------
# DDL: evidence_snapshots (v1, unchanged)
# ---------------------------------------------------------------------------

_CREATE_EVIDENCE_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS evidence_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK(evidence_type IN ('file', 'cluster')),
    normalized_path TEXT,
    unix_minute INTEGER,
    event_type TEXT,
    snapshot_json TEXT NOT NULL,
    captured_at INTEGER NOT NULL,
    UNIQUE(task_id, evidence_key),
    CHECK (
        (evidence_type = 'file'
            AND normalized_path IS NOT NULL
            AND unix_minute IS NULL
            AND event_type IS NULL)
        OR
        (evidence_type = 'cluster'
            AND normalized_path IS NULL
            AND unix_minute IS NOT NULL
            AND event_type IS NOT NULL)
    )
)
"""
_INDEX_PATH_SQL = "CREATE INDEX IF NOT EXISTS idx_evsnap_path ON evidence_snapshots(normalized_path)"
_INDEX_CLUSTER_SQL = "CREATE INDEX IF NOT EXISTS idx_evsnap_cluster ON evidence_snapshots(unix_minute, event_type)"
_INDEX_TASK_SQL = "CREATE INDEX IF NOT EXISTS idx_evsnap_task ON evidence_snapshots(task_id)"
_TRIGGER_EVSNAP_NO_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_evsnap_no_update
BEFORE UPDATE ON evidence_snapshots
BEGIN
    SELECT RAISE(ABORT, 'evidence snapshots are immutable');
END
"""

_REQUIRED_SNAPSHOT_COLUMNS = {
    "id", "task_id", "evidence_key", "evidence_type", "normalized_path",
    "unix_minute", "event_type", "snapshot_json", "captured_at",
}

# ---------------------------------------------------------------------------
# DDL: secondary_analyses (v2 addition)
# ---------------------------------------------------------------------------

_CREATE_SECONDARY_ANALYSES_SQL = """
CREATE TABLE IF NOT EXISTS secondary_analyses (
    analysis_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES evidence_snapshots(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN
        ('queued','running','review_pending','accepted','rejected','invalid','failed')),
    input_hash TEXT NOT NULL,
    input_envelope_json TEXT NOT NULL,
    prompt_version TEXT,
    description TEXT,
    summary TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    review_pending_at TEXT,
    decided_at TEXT,
    decided_by TEXT,
    decision_reason TEXT,
    failed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    grounding_status TEXT CHECK(
        grounding_status IS NULL
        OR grounding_status IN ('valid', 'partially_grounded', 'invalid')
    ),
    UNIQUE(task_id, evidence_key, version)
)
"""
_INDEX_SECONDARY_SCOPE_VERSION_SQL = """
CREATE INDEX IF NOT EXISTS idx_secondary_scope_version
    ON secondary_analyses(task_id, evidence_key, version DESC)
"""
_INDEX_SECONDARY_STATUS_SQL = """
CREATE INDEX IF NOT EXISTS idx_secondary_status
    ON secondary_analyses(task_id, evidence_key, status)
"""
# DB guard 1: a non-terminal row only allows legal status transitions.
_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_secondary_legal_transition
BEFORE UPDATE OF status ON secondary_analyses
WHEN OLD.status NOT IN ('accepted','rejected','invalid','failed')
BEGIN
    SELECT CASE WHEN NOT (
        (OLD.status='queued' AND NEW.status IN ('running','failed'))
        OR (OLD.status='running' AND NEW.status IN ('review_pending','failed'))
        OR (OLD.status='review_pending' AND NEW.status IN ('accepted','rejected','invalid'))
    ) THEN RAISE(ABORT, 'illegal secondary analysis status transition') END;
END
"""
# DB guard 2: a terminal row forbids any UPDATE entirely.
_TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_secondary_no_terminal_update
BEFORE UPDATE ON secondary_analyses
WHEN OLD.status IN ('accepted','rejected','invalid','failed')
BEGIN
    SELECT RAISE(ABORT, 'terminal secondary analysis is immutable');
END
"""
# DB guard 3 (v3): input columns are immutable for ALL states, not just terminal.
# Only output/state columns (status, description, summary, model, lifecycle
# timestamps, decision/error fields) may change via the state machine.
_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_secondary_no_input_update
BEFORE UPDATE ON secondary_analyses
WHEN
       NEW.task_id             IS NOT OLD.task_id
    OR NEW.evidence_key        IS NOT OLD.evidence_key
    OR NEW.snapshot_id         IS NOT OLD.snapshot_id
    OR NEW.version             IS NOT OLD.version
    OR NEW.input_hash          IS NOT OLD.input_hash
    OR NEW.input_envelope_json IS NOT OLD.input_envelope_json
    OR NEW.prompt_version      IS NOT OLD.prompt_version
BEGIN
    SELECT RAISE(ABORT, 'secondary analysis input is immutable');
END
"""

# ---------------------------------------------------------------------------
# DDL: analysis_claims + claim_evidence_refs (v4 addition, C5a)
# ---------------------------------------------------------------------------

_CREATE_ANALYSIS_CLAIMS_SQL = """
CREATE TABLE IF NOT EXISTS analysis_claims (
    claim_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES secondary_analyses(analysis_id) ON DELETE RESTRICT,
    claim_index INTEGER NOT NULL,
    claim_type TEXT NOT NULL CHECK(claim_type IN ('FACT','INFERENCE','HYPOTHESIS')),
    claim_text TEXT NOT NULL,
    grounding_status TEXT NOT NULL CHECK(grounding_status IN
        ('grounded','partially_grounded','ungrounded')),
    warning_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(analysis_id, claim_index)
)
"""
_CREATE_CLAIM_EVIDENCE_REFS_SQL = """
CREATE TABLE IF NOT EXISTS claim_evidence_refs (
    claim_id TEXT NOT NULL REFERENCES analysis_claims(claim_id) ON DELETE CASCADE,
    evidence_key TEXT NOT NULL,
    PRIMARY KEY(claim_id, evidence_key)
)
"""
_INDEX_CLAIMS_ANALYSIS_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_claims_analysis ON analysis_claims(analysis_id)"
)
_INDEX_REFS_CLAIM_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_refs_claim ON claim_evidence_refs(claim_id)"
)
# G14: Claims and evidence refs are DB-level immutable (no UPDATE, no DELETE).
_TRIGGER_CLAIMS_NO_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_claims_no_update
BEFORE UPDATE ON analysis_claims
BEGIN
    SELECT RAISE(ABORT, 'analysis claims are immutable');
END
"""
_TRIGGER_CLAIMS_NO_DELETE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_claims_no_delete
BEFORE DELETE ON analysis_claims
BEGIN
    SELECT RAISE(ABORT, 'analysis claims are immutable');
END
"""
_TRIGGER_CLAIM_REFS_NO_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_claim_refs_no_update
BEFORE UPDATE ON claim_evidence_refs
BEGIN
    SELECT RAISE(ABORT, 'claim evidence refs are immutable');
END
"""
_TRIGGER_CLAIM_REFS_NO_DELETE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_claim_refs_no_delete
BEFORE DELETE ON claim_evidence_refs
BEGIN
    SELECT RAISE(ABORT, 'claim evidence refs are immutable');
END
"""

_REQUIRED_CLAIM_COLUMNS = {
    "claim_id", "analysis_id", "claim_index", "claim_type", "claim_text",
    "grounding_status", "warning_json", "created_at",
}

# ---------------------------------------------------------------------------
# DDL: investigation_events (v5 addition, C7a)
# ---------------------------------------------------------------------------
#
# EV1 Event identity = (task_id, event_id).  Child tables carry task_id and
# composite FKs so task scoping is a DB-level constraint (EV2/EV3), not just a
# repository query convention.  There is NO materialized current_version: the
# current narrative is derived as MAX(version) at read time.  Evidence links
# are INSERT-only (EV4) and must point at a captured snapshot of the SAME task
# (composite FK onto evidence_snapshots(task_id, evidence_key)).

_CREATE_INVESTIGATION_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS investigation_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    needs_refresh INTEGER NOT NULL DEFAULT 0 CHECK(needs_refresh IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, event_id)
)
"""
_CREATE_INVESTIGATION_EVENT_VERSIONS_SQL = """
CREATE TABLE IF NOT EXISTS investigation_event_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT,
    UNIQUE(task_id, event_id, version),
    FOREIGN KEY(task_id, event_id)
        REFERENCES investigation_events(task_id, event_id) ON DELETE RESTRICT
)
"""
_CREATE_INVESTIGATION_EVENT_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS investigation_event_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    linked_by TEXT,
    UNIQUE(task_id, event_id, evidence_key),
    FOREIGN KEY(task_id, event_id)
        REFERENCES investigation_events(task_id, event_id) ON DELETE RESTRICT,
    FOREIGN KEY(task_id, evidence_key)
        REFERENCES evidence_snapshots(task_id, evidence_key) ON DELETE RESTRICT
)
"""
# Reverse lookup (task_id, evidence_key) -> events; the C7b propagation seam.
_INDEX_EVENT_EVIDENCE_KEY_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_inv_event_evidence_key "
    "ON investigation_event_evidence(task_id, evidence_key)"
)
# EV4: narrative versions and evidence links are immutable (INSERT only).
_TRIGGER_EVENT_VERSIONS_NO_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_event_versions_no_update
BEFORE UPDATE ON investigation_event_versions
BEGIN
    SELECT RAISE(ABORT, 'investigation event versions are immutable');
END
"""
_TRIGGER_EVENT_VERSIONS_NO_DELETE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_event_versions_no_delete
BEFORE DELETE ON investigation_event_versions
BEGIN
    SELECT RAISE(ABORT, 'investigation event versions are immutable');
END
"""
_TRIGGER_EVENT_EVIDENCE_NO_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_event_evidence_no_update
BEFORE UPDATE ON investigation_event_evidence
BEGIN
    SELECT RAISE(ABORT, 'investigation event evidence links are immutable');
END
"""
_TRIGGER_EVENT_EVIDENCE_NO_DELETE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_event_evidence_no_delete
BEFORE DELETE ON investigation_event_evidence
BEGIN
    SELECT RAISE(ABORT, 'investigation event evidence links are immutable');
END
"""
# EV5: event identity columns are immutable; needs_refresh/updated_at stay
# writable for C7b (mark dirty) and C7c (record refresh).
_TRIGGER_EVENTS_NO_IDENTITY_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_events_no_identity_update
BEFORE UPDATE ON investigation_events
WHEN new.event_id != OLD.event_id
  OR new.task_id != OLD.task_id
  OR new.created_at != OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'investigation event identity is immutable');
END
"""

_REQUIRED_EVENT_COLUMNS = {
    "event_id", "task_id", "needs_refresh", "created_at", "updated_at",
}
_REQUIRED_EVENT_VERSION_COLUMNS = {
    "id", "task_id", "event_id", "version", "title", "summary",
    "created_at", "created_by",
}
_REQUIRED_EVENT_EVIDENCE_COLUMNS = {
    "id", "task_id", "event_id", "evidence_key", "linked_at", "linked_by",
}

# ---------------------------------------------------------------------------
# DDL: investigation_event_refreshes (v6 addition, C7c-1)
# ---------------------------------------------------------------------------
#
# F9: base_version and (future, C7c-2) produced_version carry composite FKs
# onto investigation_event_versions, locking refresh provenance to exact
# immutable narrative versions at the DB level.  F10: a partial unique index
# enforces at most one non-terminal refresh per event.  F11: requested_by is
# persisted audit metadata (NOT part of the envelope / input_hash).

_CREATE_INVESTIGATION_EVENT_REFRESHES_SQL = """
CREATE TABLE IF NOT EXISTS investigation_event_refreshes (
    refresh_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
    requested_by TEXT,
    input_hash TEXT NOT NULL,
    input_envelope_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    produced_version INTEGER,
    failed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    model TEXT,
    FOREIGN KEY(task_id, event_id)
        REFERENCES investigation_events(task_id, event_id) ON DELETE RESTRICT,
    FOREIGN KEY(task_id, event_id, base_version)
        REFERENCES investigation_event_versions(task_id, event_id, version)
        ON DELETE RESTRICT,
    FOREIGN KEY(task_id, event_id, produced_version)
        REFERENCES investigation_event_versions(task_id, event_id, version)
        ON DELETE RESTRICT
)
"""
_CREATE_INVESTIGATION_EVENT_REFRESHES_V6_SQL = """
CREATE TABLE IF NOT EXISTS investigation_event_refreshes (
    refresh_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
    requested_by TEXT,
    input_hash TEXT NOT NULL,
    input_envelope_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    produced_version INTEGER,
    failed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY(task_id, event_id)
        REFERENCES investigation_events(task_id, event_id) ON DELETE RESTRICT,
    FOREIGN KEY(task_id, event_id, base_version)
        REFERENCES investigation_event_versions(task_id, event_id, version)
        ON DELETE RESTRICT,
    FOREIGN KEY(task_id, event_id, produced_version)
        REFERENCES investigation_event_versions(task_id, event_id, version)
        ON DELETE RESTRICT
)
"""
_INDEX_REFRESH_EVENT_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_inv_refreshs_event "
    "ON investigation_event_refreshes(task_id, event_id)"
)
# F10: at most one queued/running refresh per (task_id, event_id).
_INDEX_REFRESH_ONE_ACTIVE_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_refresh_one_active_per_event
ON investigation_event_refreshes(task_id, event_id)
WHERE status IN ('queued', 'running')
"""
_INDEX_REFRESH_PRODUCED_VERSION_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_refresh_produced_version
ON investigation_event_refreshes(task_id, event_id, produced_version)
WHERE produced_version IS NOT NULL
"""
_TRIGGER_REFRESH_NO_INPUT_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_refresh_no_input_update
BEFORE UPDATE ON investigation_event_refreshes
WHEN new.refresh_id != OLD.refresh_id
  OR new.task_id != OLD.task_id
  OR new.event_id != OLD.event_id
  OR new.base_version != OLD.base_version
  OR new.input_hash != OLD.input_hash
  OR new.input_envelope_json != OLD.input_envelope_json
  OR new.created_at != OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'event refresh input is immutable');
END
"""
_TRIGGER_REFRESH_LEGAL_TRANSITION_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_refresh_legal_transition
BEFORE UPDATE OF status ON investigation_event_refreshes
WHEN (OLD.status = 'queued' AND NEW.status NOT IN ('running', 'failed'))
  OR (OLD.status = 'running' AND NEW.status NOT IN ('completed', 'failed'))
  OR OLD.status IN ('completed', 'failed')
BEGIN
    SELECT RAISE(ABORT, 'illegal event refresh status transition');
END
"""
_TRIGGER_REFRESH_NO_TERMINAL_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_refresh_no_terminal_update
BEFORE UPDATE ON investigation_event_refreshes
WHEN OLD.status IN ('completed', 'failed')
BEGIN
    SELECT RAISE(ABORT, 'terminal event refreshes are immutable');
END
"""
_TRIGGER_REFRESH_STATE_FIELDS_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_refresh_state_fields
BEFORE UPDATE ON investigation_event_refreshes
WHEN
    (NEW.status = 'queued' AND (
        NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL
        OR NEW.produced_version IS NOT NULL OR NEW.failed_at IS NOT NULL
        OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL
    ))
 OR (NEW.status = 'running' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL
        OR NEW.produced_version IS NOT NULL OR NEW.failed_at IS NOT NULL
        OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL
    ))
 OR (NEW.status = 'completed' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NULL
        OR NEW.produced_version IS NULL OR NEW.failed_at IS NOT NULL
        OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL
    ))
 OR (NEW.status = 'failed' AND (
        NEW.failed_at IS NULL OR NEW.error_code IS NULL OR NEW.error_message IS NULL
        OR NEW.completed_at IS NOT NULL OR NEW.produced_version IS NOT NULL
    ))
BEGIN
    SELECT RAISE(ABORT, 'invalid event refresh state fields');
END
"""
_TRIGGER_REFRESH_STATE_FIELDS_INSERT_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_inv_refresh_state_fields_insert
BEFORE INSERT ON investigation_event_refreshes
WHEN
    (NEW.status = 'queued' AND (
        NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL
        OR NEW.produced_version IS NOT NULL OR NEW.failed_at IS NOT NULL
        OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL
    ))
 OR (NEW.status = 'running' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL
        OR NEW.produced_version IS NOT NULL OR NEW.failed_at IS NOT NULL
        OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL
    ))
 OR (NEW.status = 'completed' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NULL
        OR NEW.produced_version IS NULL OR NEW.failed_at IS NOT NULL
        OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL
    ))
 OR (NEW.status = 'failed' AND (
        NEW.failed_at IS NULL OR NEW.error_code IS NULL OR NEW.error_message IS NULL
        OR NEW.completed_at IS NOT NULL OR NEW.produced_version IS NOT NULL
    ))
BEGIN
    SELECT RAISE(ABORT, 'invalid event refresh state fields');
END
"""

_REQUIRED_EVENT_REFRESH_COLUMNS = {
    "refresh_id", "task_id", "event_id", "base_version", "status",
    "requested_by", "input_hash", "input_envelope_json", "created_at",
    "started_at", "completed_at", "produced_version", "failed_at",
    "error_code", "error_message", "model",
}

# ---------------------------------------------------------------------------
# DDL: report_evidence (R1, optional v7 extension)
# ---------------------------------------------------------------------------
#
# R1 semantics frozen at the DB level:
#   - Identity is exactly (task_id, evidence_key) of a CAPTURED snapshot
#     (composite FK; canonical Evidence is always the report source).
#   - analysis_id is an EXPLICIT frozen binding to one accepted Secondary
#     Analysis of the SAME task and the SAME evidence (composite FK backed by
#     idx_secondary_task_analysis).  NULL = Original Evidence only.
#   - report_status is an explicit analyst state; `excluded` is a state, not
#     a DELETE (no-delete trigger) -- the consideration history is kept.
#   - added_by/created_at are immutable audit fields; report_status /
#     analysis_id / updated_at / updated_by change only via explicit
#     analyst actions (add/update report evidence).

_CREATE_REPORT_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS report_evidence (
    task_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    report_status TEXT NOT NULL CHECK(report_status IN ('excluded','main','appendix')),
    analysis_id TEXT NULL,
    added_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (task_id, evidence_key),
    FOREIGN KEY(task_id, evidence_key)
        REFERENCES evidence_snapshots(task_id, evidence_key) ON DELETE RESTRICT,
    FOREIGN KEY(task_id, analysis_id)
        REFERENCES secondary_analyses(task_id, analysis_id) ON DELETE RESTRICT
)
"""
# Parent-side unique index backing the (task_id, analysis_id) composite FK.
_INDEX_SECONDARY_TASK_ANALYSIS_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_secondary_task_analysis
    ON secondary_analyses(task_id, analysis_id)
"""
_TRIGGER_REPORT_EVIDENCE_NO_IDENTITY_UPDATE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_report_evidence_no_identity_update
BEFORE UPDATE ON report_evidence
WHEN NEW.task_id != OLD.task_id
  OR NEW.evidence_key != OLD.evidence_key
  OR NEW.added_by != OLD.added_by
  OR NEW.created_at != OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'report evidence identity is immutable');
END
"""
_TRIGGER_REPORT_EVIDENCE_NO_DELETE_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_report_evidence_no_delete
BEFORE DELETE ON report_evidence
BEGIN
    SELECT RAISE(ABORT, 'report evidence is never deleted; set excluded');
END
"""

_REQUIRED_REPORT_EVIDENCE_COLUMNS = {
    "task_id", "evidence_key", "report_status", "analysis_id", "added_by",
    "created_at", "updated_at", "updated_by",
}

_REQUIRED_SECONDARY_COLUMNS = {
    "analysis_id", "task_id", "evidence_key", "snapshot_id", "version", "status",
    "input_hash", "input_envelope_json", "prompt_version", "description", "summary",
    "model", "created_at", "started_at", "review_pending_at", "decided_at",
    "decided_by", "decision_reason", "failed_at", "error_code", "error_message",
    "grounding_status",
}

# Per-target-status writable fields for transition().  The timestamp field is
# always written on that transition (auto-defaulted to now if not supplied);
# the remaining fields are only written when present in **fields.
_ALLOWED_TRANSITION_FIELDS: dict[SecondaryAnalysisStatus, frozenset[str]] = {
    SecondaryAnalysisStatus.running: frozenset({"started_at"}),
    SecondaryAnalysisStatus.review_pending: frozenset(
        {"review_pending_at", "description", "summary", "model"}
    ),
    SecondaryAnalysisStatus.accepted: frozenset({"decided_at", "decided_by", "decision_reason"}),
    SecondaryAnalysisStatus.rejected: frozenset({"decided_at", "decided_by", "decision_reason"}),
    SecondaryAnalysisStatus.invalid: frozenset({"decided_at", "decided_by", "decision_reason"}),
    SecondaryAnalysisStatus.failed: frozenset({"failed_at", "error_code", "error_message"}),
}

# P1 (C7b): analyst review-terminal decisions may only be recorded through
# review_analysis(), which also propagates needs_refresh to related
# Investigation Events inside the same transaction.
_REVIEW_TERMINAL_STATUSES: frozenset[SecondaryAnalysisStatus] = frozenset(
    {
        SecondaryAnalysisStatus.accepted,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.invalid,
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_analysis_id() -> str:
    return f"sa_{uuid.uuid4().hex}"


def _new_event_id() -> str:
    return f"ie_{uuid.uuid4().hex}"


def _new_refresh_id() -> str:
    return f"er_{uuid.uuid4().hex}"


class InvestigationRepository:
    """SQLite-backed immutable Evidence Snapshot + Secondary Analysis +
    Investigation Event store.

    A single repository owns the full v5 schema for all tables (avoids
    user_version contention / duplicate migration paths).
    """

    def __init__(self, investigation_db_path, task_id: str):
        self.db_path = Path(investigation_db_path)
        self.task_id = task_id
        # D4b: when True, every connection opens SQLite mode=rw so a vanished
        # store is an error instead of a silently recreated file.
        self.existing_only = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @classmethod
    def open_existing(cls, investigation_db_path, task_id: str) -> "InvestigationRepository":
        """Existing-store-only construction for terminal write boundaries (D4b).

        Never creates or heals: no mkdir, no CREATE, no migration, no auxiliary
        object build. The file must already exist and carry the supported
        schema version; anything else fails closed with EvidenceStoreError.
        All subsequent connections use URI mode=rw, so a store deleted after
        this call cannot be recreated by a write.
        """
        path = Path(investigation_db_path)
        if not path.is_file():
            raise EvidenceStoreError("investigation store does not exist")
        repo = cls.__new__(cls)
        repo.db_path = path
        repo.task_id = task_id
        repo.existing_only = True
        uri = f"file:{quote(str(path))}?mode=rw"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=30)) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation store is unavailable"
            ) from exc
        if version != SUPPORTED_SCHEMA_VERSION:
            raise EvidenceStoreError(
                f"unsupported investigation.db schema version: {version} "
                f"(supported: {SUPPORTED_SCHEMA_VERSION})"
            )
        try:
            repo._validate_v7_schema()
        except (sqlite3.DatabaseError, ValueError, EvidenceStoreError) as exc:
            raise EvidenceStoreError("investigation store schema is invalid") from exc
        return repo

    # =====================================================================
    # connection / schema
    # =====================================================================

    def _connect(self) -> sqlite3.Connection:
        if self.existing_only:
            uri = f"file:{quote(str(self.db_path))}?mode=rw"
            conn = sqlite3.connect(uri, uri=True, timeout=30)
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        # A14: enforce FK lifecycle per connection.  Must be issued before any
        # transaction begins (the pragma is a no-op inside a transaction).
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._initialize_v7_atomically()
            self._validate_v7_schema()
        elif version == 1:
            self._migrate_v1_to_v4()
            self._migrate_v4_to_v5()
            self._migrate_v5_to_v6()
            self._migrate_v6_to_v7()
            self._validate_v7_schema()
        elif version == 2:
            self._migrate_v2_to_v4()
            self._migrate_v4_to_v5()
            self._migrate_v5_to_v6()
            self._migrate_v6_to_v7()
            self._validate_v7_schema()
        elif version == 3:
            self._migrate_v3_to_v4()
            self._migrate_v4_to_v5()
            self._migrate_v5_to_v6()
            self._migrate_v6_to_v7()
            self._validate_v7_schema()
        elif version == 4:
            self._migrate_v4_to_v5()
            self._migrate_v5_to_v6()
            self._migrate_v6_to_v7()
            self._validate_v7_schema()
        elif version == 5:
            self._migrate_v5_to_v6()
            self._migrate_v6_to_v7()
            self._validate_v7_schema()
        elif version == 6:
            self._migrate_v6_to_v7()
            self._validate_v7_schema()
        elif version == SUPPORTED_SCHEMA_VERSION:
            self._validate_v7_schema()
            self._ensure_v7_auxiliary_objects()
        else:
            raise EvidenceStoreError(
                f"unsupported investigation.db schema version: {version} "
                f"(supported: {SUPPORTED_SCHEMA_VERSION})"
            )

    def _build_all_secondary_objects(self, conn: sqlite3.Connection) -> None:
        """Create all secondary_analyses + claims tables, indexes, triggers."""
        conn.execute(_CREATE_SECONDARY_ANALYSES_SQL)
        conn.execute(_INDEX_SECONDARY_SCOPE_VERSION_SQL)
        conn.execute(_INDEX_SECONDARY_STATUS_SQL)
        conn.execute(_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL)
        conn.execute(_TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL)
        conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
        # claims (v4)
        conn.execute(_CREATE_ANALYSIS_CLAIMS_SQL)
        conn.execute(_CREATE_CLAIM_EVIDENCE_REFS_SQL)
        conn.execute(_INDEX_CLAIMS_ANALYSIS_SQL)
        conn.execute(_INDEX_REFS_CLAIM_SQL)
        conn.execute(_TRIGGER_CLAIMS_NO_UPDATE_SQL)
        conn.execute(_TRIGGER_CLAIMS_NO_DELETE_SQL)
        conn.execute(_TRIGGER_CLAIM_REFS_NO_UPDATE_SQL)
        conn.execute(_TRIGGER_CLAIM_REFS_NO_DELETE_SQL)

    def _build_all_event_objects(self, conn: sqlite3.Connection) -> None:
        """Create all investigation_events tables, indexes, triggers (v5)."""
        conn.execute(_CREATE_INVESTIGATION_EVENTS_SQL)
        conn.execute(_CREATE_INVESTIGATION_EVENT_VERSIONS_SQL)
        conn.execute(_CREATE_INVESTIGATION_EVENT_EVIDENCE_SQL)
        conn.execute(_INDEX_EVENT_EVIDENCE_KEY_SQL)
        conn.execute(_TRIGGER_EVENT_VERSIONS_NO_UPDATE_SQL)
        conn.execute(_TRIGGER_EVENT_VERSIONS_NO_DELETE_SQL)
        conn.execute(_TRIGGER_EVENT_EVIDENCE_NO_UPDATE_SQL)
        conn.execute(_TRIGGER_EVENT_EVIDENCE_NO_DELETE_SQL)
        conn.execute(_TRIGGER_EVENTS_NO_IDENTITY_UPDATE_SQL)

    def _build_all_refresh_v6_objects(self, conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_INVESTIGATION_EVENT_REFRESHES_V6_SQL)
        conn.execute(_INDEX_REFRESH_EVENT_SQL)
        conn.execute(_INDEX_REFRESH_ONE_ACTIVE_SQL)
        conn.execute(_TRIGGER_REFRESH_NO_INPUT_UPDATE_SQL)
        conn.execute(_TRIGGER_REFRESH_LEGAL_TRANSITION_SQL)
        conn.execute(_TRIGGER_REFRESH_NO_TERMINAL_UPDATE_SQL)

    def _build_all_refresh_objects(self, conn: sqlite3.Connection) -> None:
        """Create all investigation_event_refreshes objects."""
        conn.execute(_CREATE_INVESTIGATION_EVENT_REFRESHES_SQL)
        conn.execute(_INDEX_REFRESH_EVENT_SQL)
        conn.execute(_INDEX_REFRESH_ONE_ACTIVE_SQL)
        conn.execute(_INDEX_REFRESH_PRODUCED_VERSION_SQL)
        conn.execute(_TRIGGER_REFRESH_NO_INPUT_UPDATE_SQL)
        conn.execute(_TRIGGER_REFRESH_LEGAL_TRANSITION_SQL)
        conn.execute(_TRIGGER_REFRESH_NO_TERMINAL_UPDATE_SQL)
        conn.execute(_TRIGGER_REFRESH_STATE_FIELDS_SQL)
        conn.execute(_TRIGGER_REFRESH_STATE_FIELDS_INSERT_SQL)

    def _build_all_report_evidence_objects(self, conn: sqlite3.Connection) -> None:
        """Create the report_evidence table, FK-backing index, and triggers."""
        conn.execute(_INDEX_SECONDARY_TASK_ANALYSIS_SQL)
        conn.execute(_CREATE_REPORT_EVIDENCE_SQL)
        conn.execute(_TRIGGER_REPORT_EVIDENCE_NO_IDENTITY_UPDATE_SQL)
        conn.execute(_TRIGGER_REPORT_EVIDENCE_NO_DELETE_SQL)

    def _initialize_v7_atomically(self) -> None:
        """New database: build everything + version=7 in one tx."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_EVIDENCE_SNAPSHOTS_SQL)
            conn.execute(_INDEX_PATH_SQL)
            conn.execute(_INDEX_CLUSTER_SQL)
            conn.execute(_INDEX_TASK_SQL)
            conn.execute(_TRIGGER_EVSNAP_NO_UPDATE_SQL)
            self._build_all_secondary_objects(conn)
            self._build_all_event_objects(conn)
            self._build_all_refresh_objects(conn)
            self._build_all_report_evidence_objects(conn)
            conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION}")
            conn.commit()

    def _migrate_v1_to_v4(self) -> None:
        """v1 database: add secondary + claims + all triggers → v4 (frozen)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._build_all_secondary_objects(conn)
            conn.execute("PRAGMA user_version = 4")
            conn.commit()

    def _migrate_v2_to_v4(self) -> None:
        """v2 database: add input trigger (v3) + grounding/claims (v4) → v4 (frozen)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(secondary_analyses)")}
            if "grounding_status" not in cols:
                conn.execute("ALTER TABLE secondary_analyses ADD COLUMN grounding_status TEXT")
            conn.execute(_CREATE_ANALYSIS_CLAIMS_SQL)
            conn.execute(_CREATE_CLAIM_EVIDENCE_REFS_SQL)
            conn.execute(_INDEX_CLAIMS_ANALYSIS_SQL)
            conn.execute(_INDEX_REFS_CLAIM_SQL)
            conn.execute(_TRIGGER_CLAIMS_NO_UPDATE_SQL)
            conn.execute(_TRIGGER_CLAIMS_NO_DELETE_SQL)
            conn.execute(_TRIGGER_CLAIM_REFS_NO_UPDATE_SQL)
            conn.execute(_TRIGGER_CLAIM_REFS_NO_DELETE_SQL)
            conn.execute("PRAGMA user_version = 4")
            conn.commit()

    def _migrate_v3_to_v4(self) -> None:
        """v3 database: add grounding_status column + claims tables/triggers → v4 (frozen)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Add grounding_status if not already present (idempotent).
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(secondary_analyses)")}
            if "grounding_status" not in cols:
                conn.execute("ALTER TABLE secondary_analyses ADD COLUMN grounding_status TEXT")
            conn.execute(_CREATE_ANALYSIS_CLAIMS_SQL)
            conn.execute(_CREATE_CLAIM_EVIDENCE_REFS_SQL)
            conn.execute(_INDEX_CLAIMS_ANALYSIS_SQL)
            conn.execute(_INDEX_REFS_CLAIM_SQL)
            conn.execute(_TRIGGER_CLAIMS_NO_UPDATE_SQL)
            conn.execute(_TRIGGER_CLAIMS_NO_DELETE_SQL)
            conn.execute(_TRIGGER_CLAIM_REFS_NO_UPDATE_SQL)
            conn.execute(_TRIGGER_CLAIM_REFS_NO_DELETE_SQL)
            conn.execute("PRAGMA user_version = 4")
            conn.commit()

    def _migrate_v4_to_v5(self) -> None:
        """v4 database: add investigation_events objects → v5 (frozen)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._build_all_event_objects(conn)
            conn.execute("PRAGMA user_version = 5")
            conn.commit()

    def _ensure_v4_auxiliary_objects(self) -> None:
        """Self-heal missing snapshot/secondary indexes and triggers."""
        with self._connect() as conn:
            conn.execute(_INDEX_PATH_SQL)
            conn.execute(_INDEX_CLUSTER_SQL)
            conn.execute(_INDEX_TASK_SQL)
            conn.execute(_TRIGGER_EVSNAP_NO_UPDATE_SQL)
            self._build_all_secondary_objects(conn)
            conn.commit()

    def _ensure_v5_auxiliary_objects(self) -> None:
        """Self-heal snapshot/secondary/event objects (idempotent)."""
        self._ensure_v4_auxiliary_objects()
        with self._connect() as conn:
            self._build_all_event_objects(conn)
            conn.commit()

    def _migrate_v5_to_v6(self) -> None:
        """v5 database: add investigation_event_refreshes objects -> v6."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._build_all_refresh_v6_objects(conn)
            conn.execute("PRAGMA user_version = 6")
            conn.commit()

    def _migrate_v6_to_v7(self) -> None:
        """v6 database: add refresh execution metadata and guards -> v7."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(investigation_event_refreshes)")
            }
            if "model" not in columns:
                conn.execute(
                    "ALTER TABLE investigation_event_refreshes ADD COLUMN model TEXT"
                )
            self._build_all_refresh_objects(conn)
            conn.execute("PRAGMA user_version = 7")
            conn.commit()

    def _ensure_v7_auxiliary_objects(self) -> None:
        """Self-heal v7 refresh indexes/triggers and execution metadata."""
        self._ensure_v5_auxiliary_objects()
        with self._connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(investigation_event_refreshes)")
            }
            if "model" not in columns:
                conn.execute(
                    "ALTER TABLE investigation_event_refreshes ADD COLUMN model TEXT"
                )
            self._build_all_refresh_objects(conn)
            self._build_all_report_evidence_objects(conn)
            conn.commit()

    def _validate_v7_schema(self) -> None:
        with self._connect() as conn:
            self._validate_evidence_snapshots(conn)
            self._validate_secondary_analyses(conn)
            self._validate_claims(conn)
            self._validate_event_tables(conn)
            self._validate_event_refresh_table(conn)
            report_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
            ).fetchone()
            if report_table is not None:
                # A legacy migration chain may have rebuilt secondary_analyses
                # under a surviving report_evidence table, dropping the parent
                # with it. Restore the FK-backing unique index (idempotent and
                # infallible: analysis_id is the PK, so (task_id, analysis_id)
                # is trivially unique). Everything else about the extension
                # stays strictly validated below.
                conn.execute(_INDEX_SECONDARY_TASK_ANALYSIS_SQL)
                self._repair_report_evidence_foreign_keys(conn)
                self._validate_report_evidence_table(conn)

    def _repair_report_evidence_foreign_keys(self, conn: sqlite3.Connection) -> None:
        """Repair SQLite's renamed-parent FK after legacy table-rewrite migrations.

        Older migration tests and real legacy stores may rebuild
        ``secondary_analyses`` with ``ALTER TABLE ... RENAME``. SQLite rewrites
        child FK metadata to the temporary parent name (for example
        ``secondary_analyses_v4``), even after the replacement table is named
        ``secondary_analyses`` again. Rebuild only the small R1 child table so
        its composite FK points at the authoritative current parent while
        preserving every existing Report Evidence row.
        """
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
        ).fetchone()
        if table is None:
            return
        targets = {
            row["table"]
            for row in conn.execute("PRAGMA foreign_key_list(report_evidence)")
            if row["from"] == "analysis_id"
        }
        if targets == {"secondary_analyses"}:
            return
        rows = conn.execute(
            "SELECT task_id, evidence_key, report_status, analysis_id, added_by, "
            "created_at, updated_at, updated_by FROM report_evidence"
        ).fetchall()
        conn.execute("DROP TABLE report_evidence")
        conn.execute(_CREATE_REPORT_EVIDENCE_SQL)
        for row in rows:
            conn.execute(
                "INSERT INTO report_evidence "
                "(task_id, evidence_key, report_status, analysis_id, added_by, "
                "created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
        self._build_all_report_evidence_objects(conn)

    def _validate_evidence_snapshots(self, conn: sqlite3.Connection) -> None:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(evidence_snapshots)")}
        missing = _REQUIRED_SNAPSHOT_COLUMNS - cols
        if missing:
            raise EvidenceStoreError(
                f"evidence_snapshots missing required columns: {sorted(missing)}"
            )
        found_unique = False
        for idx in conn.execute("PRAGMA index_list(evidence_snapshots)"):
            if idx["unique"]:
                idx_name = idx["name"]
                idx_cols = {r["name"] for r in conn.execute(f'PRAGMA index_info("{idx_name}")')}
                if idx_cols == {"task_id", "evidence_key"}:
                    found_unique = True
                    break
        if not found_unique:
            raise EvidenceStoreError("evidence_snapshots missing UNIQUE(task_id, evidence_key)")
        trig = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = 'trg_evsnap_no_update'"
        ).fetchone()
        if trig is None:
            raise EvidenceStoreError("missing trg_evsnap_no_update trigger")

    def _validate_secondary_analyses(self, conn: sqlite3.Connection) -> None:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(secondary_analyses)")}
        missing = _REQUIRED_SECONDARY_COLUMNS - cols
        if missing:
            raise EvidenceStoreError(
                f"secondary_analyses missing required columns: {sorted(missing)}"
            )
        # UNIQUE(task_id, evidence_key, version)
        found_unique = False
        for idx in conn.execute("PRAGMA index_list(secondary_analyses)"):
            if idx["unique"]:
                idx_name = idx["name"]
                idx_cols = {r["name"] for r in conn.execute(f'PRAGMA index_info("{idx_name}")')}
                if idx_cols == {"task_id", "evidence_key", "version"}:
                    found_unique = True
                    break
        if not found_unique:
            raise EvidenceStoreError(
                "secondary_analyses missing UNIQUE(task_id, evidence_key, version)"
            )
        # FK snapshot_id -> evidence_snapshots(id)  (A14)
        fks = conn.execute("PRAGMA foreign_key_list(secondary_analyses)").fetchall()
        found_fk = any(
            fk["table"] == "evidence_snapshots"
            and fk["from"] == "snapshot_id"
            and fk["to"] == "id"
            for fk in fks
        )
        if not found_fk:
            raise EvidenceStoreError(
                "secondary_analyses missing FK(snapshot_id) REFERENCES evidence_snapshots(id)"
            )
        for trig_name in (
            "trg_secondary_legal_transition",
            "trg_secondary_no_terminal_update",
            "trg_secondary_no_input_update",
        ):
            trig = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                [trig_name],
            ).fetchone()
            if trig is None:
                raise EvidenceStoreError(f"missing {trig_name} trigger")

    def _validate_claims(self, conn: sqlite3.Connection) -> None:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_claims)")}
        missing = _REQUIRED_CLAIM_COLUMNS - cols
        if missing:
            raise EvidenceStoreError(
                f"analysis_claims missing required columns: {sorted(missing)}"
            )
        # FK analysis_claims.analysis_id -> secondary_analyses(analysis_id)
        fks = conn.execute("PRAGMA foreign_key_list(analysis_claims)").fetchall()
        found_fk = any(
            fk["table"] == "secondary_analyses"
            and fk["from"] == "analysis_id"
            for fk in fks
        )
        if not found_fk:
            raise EvidenceStoreError(
                "analysis_claims missing FK(analysis_id) REFERENCES secondary_analyses"
            )
        # claim_evidence_refs table exists
        ref_cols = {row["name"] for row in conn.execute("PRAGMA table_info(claim_evidence_refs)")}
        if not {"claim_id", "evidence_key"} <= ref_cols:
            raise EvidenceStoreError("claim_evidence_refs missing required columns")
        for trig_name in (
            "trg_claims_no_update", "trg_claims_no_delete",
            "trg_claim_refs_no_update", "trg_claim_refs_no_delete",
        ):
            trig = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                [trig_name],
            ).fetchone()
            if trig is None:
                raise EvidenceStoreError(f"missing {trig_name} trigger")

    @staticmethod
    def _has_composite_fk(
        conn: sqlite3.Connection,
        table: str,
        parent: str,
        mapping: tuple[tuple[str, str], ...],
        *,
        on_delete: str = "RESTRICT",
    ) -> bool:
        """True iff ``table`` has one composite FK matching (parent, mapping)."""
        groups: dict[int, list[sqlite3.Row]] = {}
        for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
            groups.setdefault(row["id"], []).append(row)
        for rows in groups.values():
            if {r["table"] for r in rows} != {parent}:
                continue
            if {(r["from"], r["to"]) for r in rows} != set(mapping):
                continue
            if {r["on_delete"] for r in rows} != {on_delete}:
                continue
            return True
        return False

    def _validate_event_tables(self, conn: sqlite3.Connection) -> None:
        specs = (
            ("investigation_events", _REQUIRED_EVENT_COLUMNS),
            ("investigation_event_versions", _REQUIRED_EVENT_VERSION_COLUMNS),
            ("investigation_event_evidence", _REQUIRED_EVENT_EVIDENCE_COLUMNS),
        )
        for table, required in specs:
            cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            missing = required - cols
            if missing:
                raise EvidenceStoreError(
                    f"{table} missing required columns: {sorted(missing)}"
                )

        unique_specs = (
            ("investigation_events", ("task_id", "event_id")),
            ("investigation_event_versions", ("task_id", "event_id", "version")),
            ("investigation_event_evidence", ("task_id", "event_id", "evidence_key")),
        )
        for table, columns in unique_specs:
            found = False
            for idx in conn.execute(f"PRAGMA index_list({table})"):
                if not idx["unique"]:
                    continue
                idx_cols = {
                    r["name"]
                    for r in conn.execute(f'PRAGMA index_info("{idx["name"]}")')
                }
                if idx_cols == set(columns):
                    found = True
                    break
            if not found:
                raise EvidenceStoreError(
                    f"{table} missing UNIQUE{columns}"
                )

        event_fk = (("task_id", "task_id"), ("event_id", "event_id"))
        snapshot_fk = (("task_id", "task_id"), ("evidence_key", "evidence_key"))
        if not self._has_composite_fk(
            conn, "investigation_event_versions", "investigation_events", event_fk
        ):
            raise EvidenceStoreError(
                "investigation_event_versions missing composite FK(task_id,event_id) "
                "REFERENCES investigation_events(task_id,event_id)"
            )
        if not self._has_composite_fk(
            conn, "investigation_event_evidence", "investigation_events", event_fk
        ):
            raise EvidenceStoreError(
                "investigation_event_evidence missing composite FK(task_id,event_id) "
                "REFERENCES investigation_events(task_id,event_id)"
            )
        if not self._has_composite_fk(
            conn, "investigation_event_evidence", "evidence_snapshots", snapshot_fk
        ):
            raise EvidenceStoreError(
                "investigation_event_evidence missing composite FK(task_id,evidence_key) "
                "REFERENCES evidence_snapshots(task_id,evidence_key)"
            )

        for trig_name in (
            "trg_inv_events_no_identity_update",
            "trg_inv_event_versions_no_update",
            "trg_inv_event_versions_no_delete",
            "trg_inv_event_evidence_no_update",
            "trg_inv_event_evidence_no_delete",
        ):
            trig = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                [trig_name],
            ).fetchone()
            if trig is None:
                raise EvidenceStoreError(f"missing {trig_name} trigger")

    def _validate_event_refresh_table(self, conn: sqlite3.Connection) -> None:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(investigation_event_refreshes)")
        }
        missing = _REQUIRED_EVENT_REFRESH_COLUMNS - cols
        if missing:
            raise EvidenceStoreError(
                f"investigation_event_refreshes missing required columns: {sorted(missing)}"
            )

        version_fk = (("task_id", "task_id"), ("event_id", "event_id"), ("base_version", "version"))
        produced_fk = (
            ("task_id", "task_id"), ("event_id", "event_id"),
            ("produced_version", "version"),
        )
        fk_specs = (
            ("investigation_events", (("task_id", "task_id"), ("event_id", "event_id"))),
            ("investigation_event_versions", version_fk),
            ("investigation_event_versions", produced_fk),
        )
        for parent, mapping in fk_specs:
            if not self._has_composite_fk(
                conn, "investigation_event_refreshes", parent, mapping
            ):
                raise EvidenceStoreError(
                    "investigation_event_refreshes missing composite FK "
                    f"{tuple(f for f, _ in mapping)} REFERENCES {parent}"
                )

        # F10: partial unique index for one active refresh per event.
        found_active = False
        found_produced = False
        for idx in conn.execute("PRAGMA index_list(investigation_event_refreshes)"):
            if not idx["unique"] or not idx["partial"]:
                continue
            idx_cols = {
                r["name"]
                for r in conn.execute(f'PRAGMA index_info("{idx["name"]}")')
            }
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                [idx["name"]],
            ).fetchone()[0] or ""
            if idx_cols == {"task_id", "event_id"} and "status IN ('queued', 'running')" in sql:
                found_active = True
            if idx_cols == {"task_id", "event_id", "produced_version"} and "produced_version IS NOT NULL" in sql:
                found_produced = True
        if not found_active:
            raise EvidenceStoreError(
                "investigation_event_refreshes missing partial unique index "
                "on (task_id, event_id) for active refreshes"
            )
        if not found_produced:
            raise EvidenceStoreError(
                "investigation_event_refreshes missing produced_version unique index"
            )

        for row in conn.execute(
            "SELECT status, input_envelope_json, model, started_at, completed_at, "
            "produced_version, failed_at, error_code, error_message "
            "FROM investigation_event_refreshes"
        ):
            status = row["status"]
            if status not in {"queued", "running", "completed", "failed"}:
                raise EvidenceStoreError("refresh has unsupported status")
            if status == "queued" and any(row[name] is not None for name in (
                "started_at", "completed_at", "produced_version", "failed_at",
                "error_code", "error_message",
            )):
                raise EvidenceStoreError("queued refresh has terminal state fields")
            if status == "running" and (
                row["started_at"] is None
                or any(row[name] is not None for name in (
                    "completed_at", "produced_version", "failed_at",
                    "error_code", "error_message",
                ))
            ):
                raise EvidenceStoreError("running refresh has invalid state fields")
            if status == "completed":
                if row["started_at"] is None or row["completed_at"] is None or row["produced_version"] is None:
                    raise EvidenceStoreError("completed refresh has incomplete state fields")
                if any(row[name] is not None for name in ("failed_at", "error_code", "error_message")):
                    raise EvidenceStoreError("completed refresh has failure fields")
                try:
                    envelope = parse_event_refresh_envelope(row["input_envelope_json"])
                except (TypeError, ValueError) as exc:
                    raise EvidenceStoreError("completed refresh has invalid envelope") from exc
                if envelope.schema_version == 2 and not row["model"]:
                    raise EvidenceStoreError("completed V2 refresh is missing model")
            if status == "failed" and (
                row["failed_at"] is None or row["error_code"] is None
                or row["error_message"] is None
                or row["completed_at"] is not None or row["produced_version"] is not None
            ):
                raise EvidenceStoreError("failed refresh has invalid state fields")

        for trig_name in (
            "trg_inv_refresh_no_input_update",
            "trg_inv_refresh_legal_transition",
            "trg_inv_refresh_no_terminal_update",
            "trg_inv_refresh_state_fields",
            "trg_inv_refresh_state_fields_insert",
        ):
            trig = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                [trig_name],
            ).fetchone()
            if trig is None:
                raise EvidenceStoreError(f"missing {trig_name} trigger")

    def _validate_report_evidence_table(self, conn: sqlite3.Connection) -> None:
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(report_evidence)")
        }
        missing = _REQUIRED_REPORT_EVIDENCE_COLUMNS - cols
        if missing:
            raise EvidenceStoreError(
                f"report_evidence missing required columns: {sorted(missing)}"
            )

        found_pk = False
        for idx in conn.execute("PRAGMA index_list(report_evidence)"):
            if idx["unique"] and idx["origin"] == "pk":
                idx_cols = {
                    r["name"]
                    for r in conn.execute(f'PRAGMA index_info("{idx["name"]}")')
                }
                if idx_cols == {"task_id", "evidence_key"}:
                    found_pk = True
                    break
        if not found_pk:
            raise EvidenceStoreError(
                "report_evidence missing PRIMARY KEY(task_id, evidence_key)"
            )

        snapshot_fk = (("task_id", "task_id"), ("evidence_key", "evidence_key"))
        analysis_fk = (("task_id", "task_id"), ("analysis_id", "analysis_id"))
        if not self._has_composite_fk(
            conn, "report_evidence", "evidence_snapshots", snapshot_fk
        ):
            raise EvidenceStoreError(
                "report_evidence missing composite FK(task_id,evidence_key) "
                "REFERENCES evidence_snapshots(task_id,evidence_key)"
            )
        if not self._has_composite_fk(
            conn, "report_evidence", "secondary_analyses", analysis_fk
        ):
            raise EvidenceStoreError(
                "report_evidence missing composite FK(task_id,analysis_id) "
                "REFERENCES secondary_analyses(task_id,analysis_id)"
            )
        # The composite FK onto secondary_analyses requires a parent-side
        # UNIQUE(task_id, analysis_id) index to be enforced at all.
        has_backing_index = False
        for idx in conn.execute("PRAGMA index_list(secondary_analyses)"):
            if not idx["unique"]:
                continue
            idx_cols = {
                r["name"]
                for r in conn.execute(f'PRAGMA index_info("{idx["name"]}")')
            }
            if idx_cols == {"task_id", "analysis_id"}:
                has_backing_index = True
                break
        if not has_backing_index:
            raise EvidenceStoreError(
                "secondary_analyses missing UNIQUE(task_id, analysis_id) "
                "backing index for report_evidence FK"
            )

        for trig_name in (
            "trg_report_evidence_no_identity_update",
            "trg_report_evidence_no_delete",
        ):
            trig = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                [trig_name],
            ).fetchone()
            if trig is None:
                raise EvidenceStoreError(f"missing {trig_name} trigger")

    # =====================================================================
    # evidence_snapshots -- read
    # =====================================================================

    def get_snapshot(self, evidence_key: str) -> Optional[EvidenceSnapshot]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def _row_to_snapshot(self, row: sqlite3.Row) -> EvidenceSnapshot:
        evidence_type = row["evidence_type"]
        try:
            data = json.loads(row["snapshot_json"])
        except (ValueError, TypeError) as exc:
            raise EvidenceStoreError(f"snapshot_json is corrupt for id={row['id']}: {exc}") from exc
        if evidence_type == "file":
            payload = FileSnapshotPayload.model_validate(data)
            if payload.normalized_path != row["normalized_path"]:
                raise EvidenceStoreError("snapshot identity mismatch (normalized_path)")
        elif evidence_type == "cluster":
            payload = ClusterSnapshotPayload.model_validate(data)
            if payload.unix_minute != row["unix_minute"] or payload.event_type != row["event_type"]:
                raise EvidenceStoreError("snapshot identity mismatch (cluster)")
        else:
            raise EvidenceStoreError(f"unknown evidence_type in row: {evidence_type!r}")
        return EvidenceSnapshot(
            task_id=row["task_id"],
            evidence_key=row["evidence_key"],
            evidence_type=evidence_type,
            captured_at=row["captured_at"],
            payload=payload,
            snapshot_id=row["id"],  # A12: internal only, excluded from model_dump
        )

    # =====================================================================
    # evidence_snapshots -- capture
    # =====================================================================

    def capture_if_absent(self, resolved: ResolvedEvidence) -> EvidenceSnapshot:
        if resolved.task_id != self.task_id:
            raise ValueError(
                f"resolved evidence belongs to a different task "
                f"({resolved.task_id!r} != repository {self.task_id!r})"
            )

        # S1: existing snapshot wins; do not touch the source DB.
        existing = self.get_snapshot(resolved.evidence_key)
        if existing is not None:
            return existing

        # Build the candidate fully OUTSIDE the write transaction (S5: mode=ro, no LLM).
        try:
            candidate = build_snapshot_candidate(resolved)
        except (EvidenceNotFoundError, EvidenceStoreError):
            # A concurrent winner may have just captured it (and source may have shifted).
            existing = self.get_snapshot(resolved.evidence_key)
            if existing is not None:
                return existing
            raise

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # S3
            conn.execute(
                """
                INSERT INTO evidence_snapshots
                    (task_id, evidence_key, evidence_type, normalized_path,
                     unix_minute, event_type, snapshot_json, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, evidence_key) DO NOTHING
                """,
                (
                    candidate.task_id,
                    candidate.evidence_key,
                    candidate.evidence_type,
                    candidate.normalized_path,
                    candidate.unix_minute,
                    candidate.event_type,
                    canonical_json(candidate.payload),
                    candidate.captured_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, candidate.evidence_key],
            ).fetchone()
            conn.commit()

        return self._row_to_snapshot(row)

    # =====================================================================
    # secondary_analyses -- create (A1-A8, A11)
    # =====================================================================

    def create_analysis(
        self,
        snapshot: EvidenceSnapshot,
        *,
        analyst_note: Optional[str] = None,
        case_context: Optional[str] = None,
        related_evidence: tuple[str, ...] = (),
        prompt_version: Optional[str] = None,
    ) -> SecondaryAnalysis:
        """Create a new ``queued`` Secondary Analysis version for an Evidence.

        The ``snapshot`` argument is used ONLY to locate the DB row
        (``snapshot_id`` / ``task_id`` / ``evidence_key``).  The envelope's
        ``evidence_snapshot`` content is re-read from the DB trusted row inside
        the write transaction -- never from the caller-supplied model (A11).
        """
        if snapshot.task_id != self.task_id:
            raise ValueError(
                f"snapshot belongs to a different task "
                f"({snapshot.task_id!r} != repository {self.task_id!r})"
            )

        analysis_id = _new_analysis_id()
        now = _now_iso()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # A5

            # A2/A11: re-read the trusted snapshot row from DB (not caller's model).
            row = conn.execute(
                "SELECT * FROM evidence_snapshots "
                "WHERE id = ? AND task_id = ? AND evidence_key = ?",
                [snapshot.snapshot_id, self.task_id, snapshot.evidence_key],
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"snapshot not found for (task_id={self.task_id!r}, "
                    f"evidence_key={snapshot.evidence_key!r}, "
                    f"snapshot_id={snapshot.snapshot_id!r})"
                )
            trusted_snapshot = self._row_to_snapshot(row)

            # C4c/CCTX5: re-read each related evidence snapshot from DB (A11).
            related_entries = []
            for rel_key in related_evidence:
                rel_row = conn.execute(
                    "SELECT * FROM evidence_snapshots "
                    "WHERE task_id = ? AND evidence_key = ?",
                    [self.task_id, rel_key],
                ).fetchone()
                if rel_row is None:
                    raise ValueError(
                        f"related evidence snapshot not found: {rel_key!r}"
                    )
                rel_snapshot = self._row_to_snapshot(rel_row)
                related_entries.append(RelatedEvidenceEntry(
                    evidence_key=rel_key,
                    snapshot=rel_snapshot.model_dump(mode="json"),
                ))

            # A7/A8/A11: build V2 envelope from DB-trusted snapshots.
            # model_dump(mode="json") excludes snapshot_id (Field exclude=True, A12).
            envelope = AnalysisInputEnvelopeV2(
                evidence_snapshot=trusted_snapshot.model_dump(mode="json"),
                analyst_note=analyst_note,
                case_context=case_context,
                related_evidence=tuple(related_entries),
                prompt_version=prompt_version,
            )
            envelope_json = canonical_json(envelope)
            input_hash = hashlib.sha256(envelope_json.encode("utf-8")).hexdigest()

            # A3/A4/A5: version allocation + queued INSERT same transaction.
            version_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                "FROM secondary_analyses WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, snapshot.evidence_key],
            ).fetchone()
            version = version_row["next_version"]

            conn.execute(
                """
                INSERT INTO secondary_analyses
                    (analysis_id, task_id, evidence_key, snapshot_id, version, status,
                     input_hash, input_envelope_json, prompt_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    self.task_id,
                    snapshot.evidence_key,
                    snapshot.snapshot_id,
                    version,
                    SecondaryAnalysisStatus.queued.value,
                    input_hash,
                    envelope_json,
                    prompt_version,
                    now,
                ),
            )

            result_row = conn.execute(
                "SELECT * FROM secondary_analyses WHERE analysis_id = ?", [analysis_id]
            ).fetchone()
            conn.commit()

        return self._row_to_analysis(result_row)

    # =====================================================================
    # secondary_analyses -- transition (state machine, A9)
    # =====================================================================

    def _transition_with_conn(
        self,
        conn: sqlite3.Connection,
        analysis_id: str,
        to: SecondaryAnalysisStatus,
        *,
        expected_status: Optional[SecondaryAnalysisStatus] = None,
        **fields,
    ) -> SecondaryAnalysis:
        """Advance one analysis using a caller-owned transaction."""
        allowed = _ALLOWED_TRANSITION_FIELDS.get(to)
        if allowed is None:
            raise ValueError(f"transition to non-targetable status {to.value!r} is not supported")
        unexpected = set(fields) - allowed
        if unexpected:
            raise ValueError(
                f"unexpected fields for transition to {to.value!r}: {sorted(unexpected)} "
                f"(allowed: {sorted(allowed)})"
            )

        row = conn.execute(
            "SELECT status FROM secondary_analyses WHERE task_id = ? AND analysis_id = ?",
            [self.task_id, analysis_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"analysis not found: {analysis_id!r}")

        current = SecondaryAnalysisStatus(row["status"])
        if expected_status is not None and current != expected_status:
            if expected_status == SecondaryAnalysisStatus.review_pending:
                raise AnalysisReviewConflictError(
                    f"analysis is not review_pending (current: {current.value!r})"
                )
            raise ValueError(
                f"concurrent status change for analysis {analysis_id!r} "
                f"(expected status {expected_status.value!r})"
            )
        if current in TERMINAL_SECONDARY_STATUSES:
            if expected_status == SecondaryAnalysisStatus.review_pending:
                raise AnalysisReviewConflictError(
                    f"analysis {analysis_id!r} is terminal ({current.value!r})"
                )
            raise ValueError(
                f"analysis {analysis_id!r} is terminal ({current.value!r}); "
                f"create a new version to redo"
            )
        allowed_targets = SECONDARY_TRANSITIONS.get(current, frozenset())
        if to not in allowed_targets:
            if expected_status == SecondaryAnalysisStatus.review_pending:
                raise AnalysisReviewConflictError(
                    f"illegal review transition {current.value!r} -> {to.value!r}"
                )
            raise ValueError(
                f"illegal transition {current.value!r} -> {to.value!r} "
                f"for analysis {analysis_id!r}"
            )

        now = _now_iso()
        set_clauses: list[str] = ["status = ?"]
        params: list = [to.value]
        timestamp_columns = {
            SecondaryAnalysisStatus.running: "started_at",
            SecondaryAnalysisStatus.review_pending: "review_pending_at",
            SecondaryAnalysisStatus.failed: "failed_at",
        }
        if to in timestamp_columns:
            timestamp_column = timestamp_columns[to]
            set_clauses.append(f"{timestamp_column} = ?")
            params.append(fields.get(timestamp_column, now))
        if to in (
            SecondaryAnalysisStatus.accepted,
            SecondaryAnalysisStatus.rejected,
            SecondaryAnalysisStatus.invalid,
        ):
            set_clauses.append("decided_at = ?")
            params.append(fields.get("decided_at", now))
        for field in (
            "description", "summary", "model", "decided_by", "decision_reason",
            "error_code", "error_message",
        ):
            if field in fields:
                set_clauses.append(f"{field} = ?")
                params.append(fields[field])

        params.extend([self.task_id, analysis_id, current.value])
        cursor = conn.execute(
            f"UPDATE secondary_analyses SET {', '.join(set_clauses)} "
            "WHERE task_id = ? AND analysis_id = ? AND status = ?",
            params,
        )
        if cursor.rowcount != 1:
            if expected_status == SecondaryAnalysisStatus.review_pending:
                raise AnalysisReviewConflictError(
                    f"concurrent review decision for analysis {analysis_id!r}"
                )
            raise EvidenceStoreError(
                f"concurrent status change for analysis {analysis_id!r} "
                f"(expected status {current.value!r})"
            )

        result_row = conn.execute(
            "SELECT * FROM secondary_analyses WHERE task_id = ? AND analysis_id = ?",
            [self.task_id, analysis_id],
        ).fetchone()
        return self._row_to_analysis(result_row)

    def transition(
        self,
        analysis_id: str,
        to: SecondaryAnalysisStatus,
        **fields,
    ) -> SecondaryAnalysis:
        """Advance a Secondary Analysis along the state machine.

        P1: analyst review-terminal decisions (accepted/rejected/invalid) are
        rejected here -- they must go through ``review_analysis()`` so the
        C7b needs_refresh propagation cannot be bypassed.
        """
        if to in _REVIEW_TERMINAL_STATUSES:
            raise ValueError(
                f"review terminal transition to {to.value!r} requires review_analysis()"
            )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            result = self._transition_with_conn(conn, analysis_id, to, **fields)
            conn.commit()
        return result

    def _mark_related_events_dirty(
        self, conn: sqlite3.Connection, evidence_key: str, now: str
    ) -> None:
        """P2/P4/P6: mark events explicitly linked to this evidence dirty.

        Idempotent: rows already dirty keep their updated_at (one bump per
        clean→dirty state change).  P7/P8/P9: touches only needs_refresh and
        updated_at on investigation_events -- never narrative, versions, or
        any source database.
        """
        conn.execute(
            """
            UPDATE investigation_events
            SET needs_refresh = 1, updated_at = ?
            WHERE task_id = ? AND needs_refresh = 0
              AND event_id IN (
                  SELECT event_id FROM investigation_event_evidence
                  WHERE task_id = ? AND evidence_key = ?
              )
            """,
            [now, self.task_id, self.task_id, evidence_key],
        )

    def _mark_event_dirty_if_evidence_accepted(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        evidence_key: str,
        now: str,
    ) -> None:
        """P5: a newly established relation to evidence that already has ANY
        accepted analysis version makes this event's narrative possibly
        stale immediately (conservative: not latest-only)."""
        accepted = conn.execute(
            "SELECT 1 FROM secondary_analyses "
            "WHERE task_id = ? AND evidence_key = ? AND status = ? LIMIT 1",
            [self.task_id, evidence_key, SecondaryAnalysisStatus.accepted.value],
        ).fetchone()
        if accepted is not None:
            conn.execute(
                "UPDATE investigation_events "
                "SET needs_refresh = 1, updated_at = ? "
                "WHERE task_id = ? AND event_id = ? AND needs_refresh = 0",
                [now, self.task_id, event_id],
            )

    def review_analysis(
        self,
        analysis_id: str,
        *,
        decision: AnalysisReviewDecision,
        reviewer: str,
        reason: Optional[str] = None,
    ) -> SecondaryAnalysis:
        """Atomically validate and record one analyst review decision."""
        try:
            target = SecondaryAnalysisStatus(decision.value)
        except (AttributeError, ValueError) as exc:
            raise ValueError("invalid analysis review decision") from exc

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM secondary_analyses "
                "WHERE task_id = ? AND analysis_id = ?",
                [self.task_id, analysis_id],
            ).fetchone()
            if row is None:
                raise EvidenceNotFoundError("analysis not found")

            current = SecondaryAnalysisStatus(row["status"])
            if current != SecondaryAnalysisStatus.review_pending:
                raise AnalysisReviewConflictError(
                    f"analysis is not review_pending (current: {current.value!r})"
                )

            contract = PROMPT_OUTPUT_CONTRACT.get(row["prompt_version"])
            if contract is None:
                raise EvidenceStoreError("analysis has an unknown output contract")
            grounding_status = row["grounding_status"]
            if grounding_status is not None:
                try:
                    AnalysisGroundingStatus(grounding_status)
                except ValueError as exc:
                    raise EvidenceStoreError("analysis has invalid grounding status") from exc
            if contract == "structured_claims_v1":
                if not row["description"] or not row["summary"]:
                    raise EvidenceStoreError(
                        "structured analysis is missing persisted description or summary"
                    )
                if grounding_status is None:
                    raise EvidenceStoreError(
                        "structured analysis is missing persisted grounding status"
                    )
            elif contract != "legacy_text":
                raise EvidenceStoreError("analysis has an unsupported output contract")

            result = self._transition_with_conn(
                conn,
                analysis_id,
                target,
                expected_status=SecondaryAnalysisStatus.review_pending,
                decided_by=reviewer,
                decision_reason=reason,
            )
            # P2/P3: accepted → related Events become possibly-stale in this
            # same transaction (P10: any failure rolls the review back too).
            if decision is AnalysisReviewDecision.accepted:
                self._mark_related_events_dirty(conn, row["evidence_key"], _now_iso())
            conn.commit()
        return result

    # =====================================================================
    # secondary_analyses -- query
    # =====================================================================

    def get_analysis(self, analysis_id: str) -> Optional[SecondaryAnalysis]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM secondary_analyses WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()
        return self._row_to_analysis(row) if row is not None else None

    def list_analyses(
        self,
        evidence_key: str,
        *,
        status: Optional[SecondaryAnalysisStatus] = None,
    ) -> list[SecondaryAnalysis]:
        with self._connect() as conn:
            if status is not None:
                rows = conn.execute(
                    "SELECT * FROM secondary_analyses "
                    "WHERE task_id = ? AND evidence_key = ? AND status = ? "
                    "ORDER BY version DESC",
                    [self.task_id, evidence_key, status.value],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM secondary_analyses "
                    "WHERE task_id = ? AND evidence_key = ? "
                    "ORDER BY version DESC",
                    [self.task_id, evidence_key],
                ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_latest_analysis(self, evidence_key: str) -> Optional[SecondaryAnalysis]:
        """Highest-version analysis of any status (latest != latest_accepted)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM secondary_analyses "
                "WHERE task_id = ? AND evidence_key = ? "
                "ORDER BY version DESC LIMIT 1",
                [self.task_id, evidence_key],
            ).fetchone()
        return self._row_to_analysis(row) if row is not None else None

    def _get_latest_accepted_analysis_with_conn(
        self, conn: sqlite3.Connection, evidence_key: str
    ) -> Optional[SecondaryAnalysis]:
        row = conn.execute(
            "SELECT * FROM secondary_analyses "
            "WHERE task_id = ? AND evidence_key = ? AND status = ? "
            "ORDER BY version DESC LIMIT 1",
            [self.task_id, evidence_key, SecondaryAnalysisStatus.accepted.value],
        ).fetchone()
        return self._row_to_analysis(row) if row is not None else None

    def get_latest_accepted_analysis(self, evidence_key: str) -> Optional[SecondaryAnalysis]:
        """Highest-version analysis with status=accepted."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM secondary_analyses "
                "WHERE task_id = ? AND evidence_key = ? AND status = ? "
                "ORDER BY version DESC LIMIT 1",
                [self.task_id, evidence_key, SecondaryAnalysisStatus.accepted.value],
            ).fetchone()
        return self._row_to_analysis(row) if row is not None else None

    def list_stale_analyses(self) -> list[SecondaryAnalysis]:
        """Return all analyses in a non-terminal state (queued/running).

        Used by restart recovery (E9) to find rows left behind by a crash/kill.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM secondary_analyses "
                "WHERE task_id = ? AND status IN ('queued', 'running') "
                "ORDER BY created_at",
                [self.task_id],
            ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    # =====================================================================
    # secondary_analyses -- row mapping
    # =====================================================================

    # Static so the strict C10 read path (graph_reader) can reuse the exact
    # row mapping without constructing this write-capable repository.
    @staticmethod
    def _row_to_analysis(row: sqlite3.Row) -> SecondaryAnalysis:
        gs = row["grounding_status"]
        return SecondaryAnalysis(
            analysis_id=row["analysis_id"],
            task_id=row["task_id"],
            evidence_key=row["evidence_key"],
            snapshot_id=row["snapshot_id"],
            version=row["version"],
            status=SecondaryAnalysisStatus(row["status"]),
            input_hash=row["input_hash"],
            input_envelope_json=row["input_envelope_json"],
            prompt_version=row["prompt_version"],
            description=row["description"],
            summary=row["summary"],
            model=row["model"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            review_pending_at=row["review_pending_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            decision_reason=row["decision_reason"],
            failed_at=row["failed_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            grounding_status=AnalysisGroundingStatus(gs) if gs else None,
        )

    # =====================================================================
    # analysis_claims -- persist (C5a/C5b: G11-G14)
    # =====================================================================

    def _validate_and_insert_claims(
        self,
        conn: sqlite3.Connection,
        analysis_id: str,
        row: sqlite3.Row,
        candidates: Sequence[ClaimCandidate],
        *,
        now: str,
    ) -> tuple[list, AnalysisGroundingStatus]:
        """Validate candidates from this analysis envelope and insert claims.

        The caller owns the surrounding transaction and precondition checks.
        """
        envelope = parse_analysis_input_envelope(row["input_envelope_json"])
        allowed = derive_allowed_evidence_ids(envelope)
        validated = GroundingValidator(allowed).validate(candidates)
        grounding = compute_analysis_grounding(validated)
        for idx, vc in enumerate(validated):
            claim_id = f"cl_{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO analysis_claims
                    (claim_id, analysis_id, claim_index, claim_type,
                     claim_text, grounding_status, warning_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id, analysis_id, idx, vc.claim_type.value, vc.claim_text,
                    vc.grounding_status.value,
                    json.dumps(vc.warnings, ensure_ascii=False) if vc.warnings else None,
                    now,
                ),
            )
            for ref in vc.evidence_refs:
                conn.execute(
                    "INSERT INTO claim_evidence_refs (claim_id, evidence_key) VALUES (?, ?)",
                    (claim_id, ref),
                )
        return validated, grounding

    def persist_claims(
        self,
        analysis_id: str,
        candidates: Sequence[ClaimCandidate],
    ) -> list[AnalysisClaim]:
        """Persist validated claims for a running analysis (write-once, G11-G14).

        Accepts **untrusted** ClaimCandidates — the GroundingValidator runs
        INSIDE this transaction using the analysis's own frozen envelope, so
        callers can never bypass the evidence-ref trust boundary (G11).

        Preconditions (enforced inside the transaction):
          - analysis exists (else ValueError)
          - status == running (else ValueError, G13)
          - no existing claims (else ValueError, G12 write-once)
        """
        now = _now_iso()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT * FROM secondary_analyses WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()
            if row is None:
                raise ValueError(f"analysis not found: {analysis_id!r}")

            if row["status"] != SecondaryAnalysisStatus.running.value:
                raise ValueError(
                    f"claims require running status (current: {row['status']!r})"
                )

            existing = conn.execute(
                "SELECT COUNT(*) FROM analysis_claims WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()[0]
            if row["grounding_status"] is not None:
                raise ValueError("analysis grounding has already been persisted (write-once)")
            if existing > 0:
                raise EvidenceStoreError("analysis has claims but no grounding status")

            _, grounding = self._validate_and_insert_claims(
                conn, analysis_id, row, candidates, now=now
            )
            conn.execute(
                "UPDATE secondary_analyses SET grounding_status = ? WHERE analysis_id = ?",
                (grounding.value, analysis_id),
            )

            # Re-read persisted claims for the return value.
            claims = self._query_claims(conn, analysis_id)
            conn.commit()

        return claims

    def complete_analysis_for_review(
        self,
        analysis_id: str,
        *,
        description: str,
        summary: str,
        model: str,
        candidates: Sequence[ClaimCandidate],
    ) -> SecondaryAnalysis:
        """Atomically persist structured output, Claims, Grounding, and review state.

        This is the only C5b success path. It never calls public persistence or
        transition methods because those would commit separate transactions.
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM secondary_analyses WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()
            if row is None:
                raise ValueError(f"analysis not found: {analysis_id!r}")
            if row["status"] != SecondaryAnalysisStatus.running.value:
                raise ValueError(
                    f"completion requires running status (current: {row['status']!r})"
                )
            if any(row[name] is not None for name in ("description", "summary", "model", "grounding_status")):
                raise ValueError("analysis already contains persisted result data")
            claim_count = conn.execute(
                "SELECT COUNT(*) FROM analysis_claims WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()[0]
            if claim_count:
                raise ValueError("analysis claims already exist (write-once)")

            _, grounding = self._validate_and_insert_claims(
                conn, analysis_id, row, candidates, now=now
            )
            cursor = conn.execute(
                """
                UPDATE secondary_analyses
                SET description = ?, summary = ?, model = ?,
                    grounding_status = ?, status = 'review_pending',
                    review_pending_at = ?
                WHERE analysis_id = ? AND status = 'running'
                """,
                (description, summary, model, grounding.value, now, analysis_id),
            )
            if cursor.rowcount != 1:
                raise EvidenceStoreError(
                    f"analysis completion status race for {analysis_id!r}"
                )
            result_row = conn.execute(
                "SELECT * FROM secondary_analyses WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()
            result = self._row_to_analysis(result_row)
            conn.commit()
        return result

    # =====================================================================
    # analysis_claims -- read
    # =====================================================================

    def list_claims(self, analysis_id: str) -> list[AnalysisClaim]:
        """Return all claims for an analysis (with evidence refs)."""
        with self._connect() as conn:
            return self._query_claims(conn, analysis_id)

    def _query_claims(self, conn: sqlite3.Connection, analysis_id: str) -> list[AnalysisClaim]:
        rows = conn.execute(
            "SELECT * FROM analysis_claims WHERE analysis_id = ? ORDER BY claim_index",
            [analysis_id],
        ).fetchall()
        result: list[AnalysisClaim] = []
        for row in rows:
            refs = tuple(
                r["evidence_key"]
                for r in conn.execute(
                    "SELECT evidence_key FROM claim_evidence_refs WHERE claim_id = ? ORDER BY evidence_key",
                    [row["claim_id"]],
                ).fetchall()
            )
            warning = None
            if row["warning_json"]:
                try:
                    warning = json.loads(row["warning_json"])
                except (ValueError, TypeError):
                    warning = None
            result.append(AnalysisClaim(
                claim_id=row["claim_id"],
                analysis_id=row["analysis_id"],
                claim_index=row["claim_index"],
                claim_type=ClaimType(row["claim_type"]),
                claim_text=row["claim_text"],
                grounding_status=ClaimGroundingStatus(row["grounding_status"]),
                warnings=warning,
                evidence_refs=refs,
                created_at=row["created_at"],
            ))
        return result

    def get_grounding_summary(self, analysis_id: str) -> Optional[AnalysisGroundingStatus]:
        """Return the analysis-level grounding status.

        Raises KeyError if the analysis does not exist. Returns None if claims
        have not been persisted yet.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT grounding_status FROM secondary_analyses WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()
        if row is None:
            raise KeyError(f"analysis not found: {analysis_id!r}")
        return AnalysisGroundingStatus(row["grounding_status"]) if row["grounding_status"] else None

    # =====================================================================
    # investigation_events (C7a)
    # =====================================================================

    # Current narrative is derived as MAX(version) — no materialized
    # current_version column (single source of truth in the version table).
    _EVENT_READ_SQL = """
        SELECT e.event_id AS event_id, e.task_id AS task_id,
               e.needs_refresh AS needs_refresh,
               e.created_at AS created_at, e.updated_at AS updated_at,
               v.version AS current_version, v.title AS title, v.summary AS summary
        FROM investigation_events e
        JOIN investigation_event_versions v
          ON v.task_id = e.task_id AND v.event_id = e.event_id
         AND v.version = (SELECT MAX(v2.version) FROM investigation_event_versions v2
                          WHERE v2.task_id = e.task_id AND v2.event_id = e.event_id)
        WHERE e.task_id = ?
    """

    def _row_to_event(self, row: sqlite3.Row) -> InvestigationEvent:
        return InvestigationEvent(
            event_id=row["event_id"],
            task_id=row["task_id"],
            needs_refresh=bool(row["needs_refresh"]),
            current_version=row["current_version"],
            title=row["title"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_event(
        self,
        title: str,
        *,
        summary: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> InvestigationEvent:
        """Atomically create one Event + its immutable v1 narrative version."""
        if not title:
            raise ValueError("event title must be a non-empty string")
        event_id = _new_event_id()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO investigation_events "
                "(event_id, task_id, needs_refresh, created_at, updated_at) "
                "VALUES (?, ?, 0, ?, ?)",
                [event_id, self.task_id, now, now],
            )
            conn.execute(
                "INSERT INTO investigation_event_versions "
                "(task_id, event_id, version, title, summary, created_at, created_by) "
                "VALUES (?, ?, 1, ?, ?, ?, ?)",
                [self.task_id, event_id, title, summary, now, created_by],
            )
            row = conn.execute(
                self._EVENT_READ_SQL + " AND e.event_id = ?",
                [self.task_id, event_id],
            ).fetchone()
            conn.commit()
        return self._row_to_event(row)

    def get_event(self, event_id: str) -> Optional[InvestigationEvent]:
        with self._connect() as conn:
            row = conn.execute(
                self._EVENT_READ_SQL + " AND e.event_id = ?",
                [self.task_id, event_id],
            ).fetchone()
        return self._row_to_event(row) if row is not None else None

    def list_events(
        self, *, needs_refresh: Optional[bool] = None
    ) -> list[InvestigationEvent]:
        sql = self._EVENT_READ_SQL
        params: list = [self.task_id]
        if needs_refresh is not None:
            sql += " AND e.needs_refresh = ?"
            params.append(1 if needs_refresh else 0)
        sql += " ORDER BY e.created_at"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def list_event_versions(self, event_id: str) -> list[InvestigationEventVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_event_versions "
                "WHERE task_id = ? AND event_id = ? ORDER BY version",
                [self.task_id, event_id],
            ).fetchall()
        return [
            InvestigationEventVersion(
                task_id=row["task_id"],
                event_id=row["event_id"],
                version=row["version"],
                title=row["title"],
                summary=row["summary"],
                created_at=row["created_at"],
                created_by=row["created_by"],
            )
            for row in rows
        ]

    def link_event_evidence(
        self,
        event_id: str,
        evidence_key: str,
        *,
        linked_by: Optional[str] = None,
    ) -> EventEvidenceLink:
        """INSERT one explicit Event→Evidence relation (write-once per pair).

        Requires the evidence to already be captured in this task (the
        composite FK is the DB-level backstop; this check gives clean
        not-found semantics).
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            event = conn.execute(
                "SELECT 1 FROM investigation_events WHERE task_id = ? AND event_id = ?",
                [self.task_id, event_id],
            ).fetchone()
            if event is None:
                raise EvidenceNotFoundError("investigation event not found")
            existing = conn.execute(
                "SELECT 1 FROM investigation_event_evidence "
                "WHERE task_id = ? AND event_id = ? AND evidence_key = ?",
                [self.task_id, event_id, evidence_key],
            ).fetchone()
            if existing is not None:
                raise InvestigationEventConflictError(
                    "event evidence link already exists"
                )
            snapshot = conn.execute(
                "SELECT 1 FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
            if snapshot is None:
                raise EvidenceNotFoundError(
                    "evidence snapshot not captured for this task"
                )
            conn.execute(
                "INSERT INTO investigation_event_evidence "
                "(task_id, event_id, evidence_key, linked_at, linked_by) "
                "VALUES (?, ?, ?, ?, ?)",
                [self.task_id, event_id, evidence_key, now, linked_by],
            )
            # P5/P10: same transaction as the link INSERT.
            self._mark_event_dirty_if_evidence_accepted(
                conn, event_id, evidence_key, now
            )
            conn.commit()
        return EventEvidenceLink(
            task_id=self.task_id,
            event_id=event_id,
            evidence_key=evidence_key,
            linked_at=now,
            linked_by=linked_by,
        )

    def list_event_evidence(self, event_id: str) -> list[EventEvidenceLink]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_event_evidence "
                "WHERE task_id = ? AND event_id = ? ORDER BY linked_at, evidence_key",
                [self.task_id, event_id],
            ).fetchall()
        return [
            EventEvidenceLink(
                task_id=row["task_id"],
                event_id=row["event_id"],
                evidence_key=row["evidence_key"],
                linked_at=row["linked_at"],
                linked_by=row["linked_by"],
            )
            for row in rows
        ]

    def list_events_for_evidence(self, evidence_key: str) -> list[InvestigationEvent]:
        """Reverse lookup: events explicitly referencing this canonical key.

        The C7b propagation seam (accepted analysis -> affected events) reads
        exactly this mapping; no Timeline heuristics are involved.
        """
        with self._connect() as conn:
            rows = conn.execute(
                self._EVENT_READ_SQL
                + " AND e.event_id IN ("
                "    SELECT event_id FROM investigation_event_evidence"
                "    WHERE task_id = ? AND evidence_key = ?"
                ") ORDER BY e.created_at",
                [self.task_id, self.task_id, evidence_key],
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    # =====================================================================
    # investigation_event_refreshes (C7c-1)
    # =====================================================================

    @staticmethod
    def _row_to_refresh(row: sqlite3.Row) -> EventRefresh:
        return EventRefresh(
            refresh_id=row["refresh_id"],
            task_id=row["task_id"],
            event_id=row["event_id"],
            base_version=row["base_version"],
            status=EventRefreshStatus(row["status"]),
            requested_by=row["requested_by"],
            input_hash=row["input_hash"],
            input_envelope_json=row["input_envelope_json"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            produced_version=row["produced_version"],
            failed_at=row["failed_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            model=row["model"] if "model" in row.keys() else None,
        )

    def create_event_refresh(
        self, event_id: str, *, requested_by: Optional[str] = None
    ) -> EventRefresh:
        """Admit one explicit refresh job with a fully frozen input (F1-F12).

        F8: every envelope read happens on THIS connection inside the single
        BEGIN IMMEDIATE -- no self-opening public reader is called, so the
        frozen input is an admission-time atomic view.
        """
        refresh_id = _new_refresh_id()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            event_row = conn.execute(
                self._EVENT_READ_SQL + " AND e.event_id = ?",
                [self.task_id, event_id],
            ).fetchone()
            if event_row is None:
                raise EvidenceNotFoundError("investigation event not found")

            active = conn.execute(
                "SELECT 1 FROM investigation_event_refreshes "
                "WHERE task_id = ? AND event_id = ? AND status IN ('queued','running')",
                [self.task_id, event_id],
            ).fetchone()
            if active is not None:
                raise InvestigationEventConflictError(
                    "an event refresh is already in progress"
                )

            link_keys = [
                r["evidence_key"]
                for r in conn.execute(
                    "SELECT evidence_key FROM investigation_event_evidence "
                    "WHERE task_id = ? AND event_id = ? ORDER BY evidence_key",
                    [self.task_id, event_id],
                ).fetchall()
            ]

            links: list[EventRefreshLinkV1] = []
            for key in link_keys:
                snap_row = conn.execute(
                    "SELECT * FROM evidence_snapshots "
                    "WHERE task_id = ? AND evidence_key = ?",
                    [self.task_id, key],
                ).fetchone()
                if snap_row is None:  # unreachable: link FK guarantees capture
                    raise EvidenceStoreError(
                        f"linked evidence has no captured snapshot: {key!r}"
                    )
                analysis = self._get_latest_accepted_analysis_with_conn(conn, key)
                accepted: Optional[EventRefreshAcceptedAnalysisV1] = None
                if analysis is not None:
                    claims = self._query_claims(conn, analysis.analysis_id)
                    accepted = EventRefreshAcceptedAnalysisV1(
                        analysis_id=analysis.analysis_id,
                        version=analysis.version,
                        evidence_key=key,
                        description=analysis.description,
                        summary=analysis.summary,
                        grounding_status=analysis.grounding_status,
                        claims=tuple(
                            EventRefreshClaimV1(
                                claim_type=c.claim_type,
                                claim_text=c.claim_text,
                                grounding_status=c.grounding_status,
                                evidence_refs=c.evidence_refs,
                                warnings=c.warnings,
                            )
                            for c in claims
                        ),
                    )
                links.append(EventRefreshLinkV1(
                    evidence_key=key,
                    snapshot=self._row_to_snapshot(snap_row).model_dump(mode="json"),
                    accepted_analysis=accepted,
                ))

            envelope = EventRefreshEnvelopeV2(
                prompt_version=EVENT_REFRESH_PROMPT_VERSION,
                event_id=event_id,
                base_version=event_row["current_version"],
                base_title=event_row["title"],
                base_summary=event_row["summary"],
                needs_refresh_at_submission=bool(event_row["needs_refresh"]),
                links=tuple(links),
            )
            # F3: hash exactly the persisted serialization (serialize once).
            envelope_json = canonical_json(envelope)
            input_hash = hashlib.sha256(envelope_json.encode("utf-8")).hexdigest()

            conn.execute(
                "INSERT INTO investigation_event_refreshes "
                "(refresh_id, task_id, event_id, base_version, status, requested_by, "
                " input_hash, input_envelope_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    refresh_id, self.task_id, event_id,
                    envelope.base_version, EventRefreshStatus.queued.value,
                    requested_by, input_hash, envelope_json, now,
                ],
            )
            row = conn.execute(
                "SELECT * FROM investigation_event_refreshes WHERE refresh_id = ?",
                [refresh_id],
            ).fetchone()
            conn.commit()
        return self._row_to_refresh(row)

    def _accepted_signature_from_envelope(self, envelope) -> tuple[tuple[str, str, int], ...]:
        return tuple(sorted(
            (link.evidence_key, link.accepted_analysis.analysis_id, link.accepted_analysis.version)
            for link in envelope.links
            if link.accepted_analysis is not None
        ))

    def _current_accepted_signature_with_conn(
        self, conn: sqlite3.Connection, event_id: str
    ) -> tuple[tuple[str, str, int], ...]:
        keys = conn.execute(
            "SELECT evidence_key FROM investigation_event_evidence "
            "WHERE task_id = ? AND event_id = ? ORDER BY evidence_key",
            [self.task_id, event_id],
        ).fetchall()
        signature = []
        for row in keys:
            analysis = self._get_latest_accepted_analysis_with_conn(conn, row["evidence_key"])
            if analysis is not None:
                signature.append((row["evidence_key"], analysis.analysis_id, analysis.version))
        return tuple(sorted(signature))

    def _fail_event_refresh_with_conn(
        self,
        conn: sqlite3.Connection,
        refresh_id: str,
        *,
        error_code: str,
        error_message: str,
        model: Optional[str] = None,
        now: Optional[str] = None,
    ) -> Optional[EventRefresh]:
        now = now or _now_iso()
        row = conn.execute(
            "SELECT * FROM investigation_event_refreshes "
            "WHERE task_id = ? AND refresh_id = ?",
            [self.task_id, refresh_id],
        ).fetchone()
        if row is None or row["status"] not in ("queued", "running"):
            return self._row_to_refresh(row) if row is not None else None
        conn.execute(
            "UPDATE investigation_event_refreshes SET status='failed', failed_at=?, "
            "error_code=?, error_message=?, model=COALESCE(?, model) "
            "WHERE task_id=? AND refresh_id=? AND status IN ('queued','running')",
            [now, error_code[:100], error_message[:500], model, self.task_id, refresh_id],
        )
        result = conn.execute(
            "SELECT * FROM investigation_event_refreshes WHERE task_id=? AND refresh_id=?",
            [self.task_id, refresh_id],
        ).fetchone()
        return self._row_to_refresh(result)

    def claim_event_refresh(self, refresh_id: str) -> Optional[EventRefresh]:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id=? AND refresh_id=? AND status='queued'",
                [self.task_id, refresh_id],
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                "UPDATE investigation_event_refreshes SET status='running', started_at=? "
                "WHERE task_id=? AND refresh_id=? AND status='queued'",
                [now, self.task_id, refresh_id],
            )
            result = conn.execute(
                "SELECT * FROM investigation_event_refreshes WHERE task_id=? AND refresh_id=?",
                [self.task_id, refresh_id],
            ).fetchone()
            conn.commit()
        return self._row_to_refresh(result)

    def fail_event_refresh(
        self,
        refresh_id: str,
        *,
        error_code: str,
        error_message: str,
        model: Optional[str] = None,
    ) -> Optional[EventRefresh]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            result = self._fail_event_refresh_with_conn(
                conn, refresh_id, error_code=error_code,
                error_message=error_message, model=model,
            )
            conn.commit()
        return result

    def complete_event_refresh(
        self,
        refresh_id: str,
        *,
        title: str,
        summary: str,
        model: str,
    ) -> EventRefresh:
        now = _now_iso()
        if not model:
            raise ValueError("refresh completion requires model metadata")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            refresh = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id=? AND refresh_id=? AND status='running'",
                [self.task_id, refresh_id],
            ).fetchone()
            if refresh is None:
                raise ValueError("refresh is not running")
            envelope = parse_event_refresh_envelope(refresh["input_envelope_json"])
            if not isinstance(envelope, EventRefreshEnvelopeV2):
                raise ValueError("historical V1 refresh is not executable")
            canonical = canonical_json(envelope)
            if canonical != refresh["input_envelope_json"]:
                raise ValueError("refresh envelope serialization mismatch")
            actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(actual_hash, refresh["input_hash"]):
                raise ValueError("refresh input hash mismatch")
            event_row = conn.execute(
                self._EVENT_READ_SQL + " AND e.event_id = ?",
                [self.task_id, envelope.event_id],
            ).fetchone()
            if event_row is None:
                raise EvidenceNotFoundError("investigation event not found")
            if event_row["current_version"] != envelope.base_version:
                result = self._fail_event_refresh_with_conn(
                    conn, refresh_id, error_code="base_version_changed",
                    error_message="event narrative version changed before completion",
                    model=model, now=now,
                )
                conn.commit()
                return result

            new_version = envelope.base_version + 1
            conn.execute(
                "INSERT INTO investigation_event_versions "
                "(task_id,event_id,version,title,summary,created_at,created_by) "
                "VALUES (?,?,?,?,?,?,NULL)",
                [self.task_id, envelope.event_id, new_version, title, summary, now],
            )
            frozen_signature = self._accepted_signature_from_envelope(envelope)
            current_signature = self._current_accepted_signature_with_conn(conn, envelope.event_id)
            needs_refresh = bool(event_row["needs_refresh"])
            if needs_refresh and envelope.needs_refresh_at_submission and frozen_signature == current_signature:
                next_needs_refresh = 0
            else:
                next_needs_refresh = 1 if needs_refresh else 0
            conn.execute(
                "UPDATE investigation_events SET needs_refresh=?, updated_at=? "
                "WHERE task_id=? AND event_id=?",
                [next_needs_refresh, now, self.task_id, envelope.event_id],
            )
            conn.execute(
                "UPDATE investigation_event_refreshes SET status='completed', completed_at=?, "
                "produced_version=?, model=? WHERE task_id=? AND refresh_id=? AND status='running'",
                [now, new_version, model, self.task_id, refresh_id],
            )
            result = conn.execute(
                "SELECT * FROM investigation_event_refreshes WHERE task_id=? AND refresh_id=?",
                [self.task_id, refresh_id],
            ).fetchone()
            conn.commit()
        return self._row_to_refresh(result)

    def get_event_refresh(self, refresh_id: str) -> Optional[EventRefresh]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id = ? AND refresh_id = ?",
                [self.task_id, refresh_id],
            ).fetchone()
        return self._row_to_refresh(row) if row is not None else None

    def list_event_refreshes(self, event_id: str) -> list[EventRefresh]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id = ? AND event_id = ? ORDER BY created_at",
                [self.task_id, event_id],
            ).fetchall()
        return [self._row_to_refresh(r) for r in rows]

    def list_stale_event_refreshes(self) -> list[EventRefresh]:
        """Non-terminal refresh rows (C7c-2 restart recovery seam)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id = ? AND status IN ('queued','running') "
                "ORDER BY created_at",
                [self.task_id],
            ).fetchall()
        return [self._row_to_refresh(r) for r in rows]

    # =====================================================================
    # report_evidence (Phase R1)
    # =====================================================================

    @staticmethod
    def _row_to_report_evidence(row: sqlite3.Row) -> ReportEvidence:
        return ReportEvidence(
            task_id=row["task_id"],
            evidence_key=row["evidence_key"],
            report_status=ReportEvidenceStatus(row["report_status"]),
            analysis_id=row["analysis_id"],
            added_by=row["added_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
        )

    def _require_bindable_analysis_with_conn(
        self, conn: sqlite3.Connection, evidence_key: str, analysis_id: str
    ) -> None:
        """R1 §7 triple check inside the caller's transaction.

        The bound analysis must belong to THIS task (opaque 404 otherwise --
        another task's analysis must not be probeable), to THIS evidence, and
        be ``accepted``.  The composite FK is the DB-level backstop; this
        check gives clean per-cause errors.
        """
        row = conn.execute(
            "SELECT evidence_key, status FROM secondary_analyses "
            "WHERE task_id = ? AND analysis_id = ?",
            [self.task_id, analysis_id],
        ).fetchone()
        if row is None:
            raise EvidenceNotFoundError("analysis not found")
        if row["evidence_key"] != evidence_key:
            raise AnalysisBindingConflictError(
                "analysis belongs to a different evidence"
            )
        if row["status"] != "accepted":
            raise AnalysisBindingConflictError("analysis is not accepted")

    def add_report_evidence(
        self,
        evidence_key: str,
        *,
        report_status: str,
        analysis_id: Optional[str] = None,
        added_by: str,
    ) -> ReportEvidence:
        """INSERT one explicit Report Evidence row (add includes: main|appendix).

        The evidence must already be captured in this task (canonical Evidence
        is always the report source); ``analysis_id`` is an OPTIONAL frozen
        binding to one accepted analysis of the SAME evidence (R1 §3/§7).
        """
        if report_status not in ("main", "appendix"):
            raise ValueError("report_status must be main or appendix when adding")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # R1 is an optional v7 extension. Existing C10 stores may not
            # have the table; the first explicit Report write creates it in
            # this write transaction. GET paths never call this repository.
            self._build_all_report_evidence_objects(conn)
            snapshot = conn.execute(
                "SELECT 1 FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
            if snapshot is None:
                raise EvidenceNotFoundError(
                    "evidence snapshot not captured for this task"
                )
            existing = conn.execute(
                "SELECT 1 FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
            if existing is not None:
                raise ReportEvidenceConflictError(
                    "report evidence already exists"
                )
            if analysis_id is not None:
                self._require_bindable_analysis_with_conn(
                    conn, evidence_key, analysis_id
                )
            conn.execute(
                "INSERT INTO report_evidence "
                "(task_id, evidence_key, report_status, analysis_id, "
                " added_by, created_at, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    self.task_id, evidence_key, report_status, analysis_id,
                    added_by, now, now, added_by,
                ],
            )
            row = conn.execute(
                "SELECT * FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
            conn.commit()
        return self._row_to_report_evidence(row)

    def update_report_evidence(
        self,
        evidence_key: str,
        *,
        report_status: Optional[str] = None,
        analysis_id: Optional[str] = None,
        bind_analysis: bool = False,
        updated_by: str,
    ) -> ReportEvidence:
        """Explicitly set report_status and/or rebind the frozen analysis.

        ``report_status`` (any of excluded/main/appendix -- all explicit
        analyst transitions are legal) and ``analysis_id`` (triple-checked
        accepted analysis of this evidence) are only written when supplied;
        ``bind_analysis=False`` keeps the current binding untouched (R1 has
        no unbind: clearing a binding is not an analyst action).
        """
        if report_status is not None and report_status not in (
            "excluded", "main", "appendix"
        ):
            raise ValueError("invalid report_status")
        if report_status is None and not bind_analysis:
            raise ValueError("update requires report_status or analysis_id")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
            if row is None:
                raise EvidenceNotFoundError("report evidence not found")
            if bind_analysis and analysis_id is not None:
                self._require_bindable_analysis_with_conn(
                    conn, evidence_key, analysis_id
                )
            next_status = report_status if report_status is not None else row["report_status"]
            next_analysis = analysis_id if bind_analysis else row["analysis_id"]
            conn.execute(
                "UPDATE report_evidence SET report_status=?, analysis_id=?, "
                "updated_at=?, updated_by=? WHERE task_id=? AND evidence_key=?",
                [next_status, next_analysis, now, updated_by,
                 self.task_id, evidence_key],
            )
            updated = conn.execute(
                "SELECT * FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                [self.task_id, evidence_key],
            ).fetchone()
            conn.commit()
        return self._row_to_report_evidence(updated)
