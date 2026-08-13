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
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.models import ResolvedEvidence
from .acquisition import build_snapshot_candidate, canonical_json
from .models import (
    SECONDARY_TRANSITIONS,
    TERMINAL_SECONDARY_STATUSES,
    AnalysisInputEnvelopeV2,
    ClusterSnapshotPayload,
    EvidenceSnapshot,
    FileSnapshotPayload,
    RelatedEvidenceEntry,
    SecondaryAnalysis,
    SecondaryAnalysisStatus,
)

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = 3

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

_REQUIRED_SECONDARY_COLUMNS = {
    "analysis_id", "task_id", "evidence_key", "snapshot_id", "version", "status",
    "input_hash", "input_envelope_json", "prompt_version", "description", "summary",
    "model", "created_at", "started_at", "review_pending_at", "decided_at",
    "decided_by", "decision_reason", "failed_at", "error_code", "error_message",
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_analysis_id() -> str:
    return f"sa_{uuid.uuid4().hex}"


class InvestigationRepository:
    """SQLite-backed immutable Evidence Snapshot + Secondary Analysis store.

    A single repository owns the full v3 schema for both tables (avoids
    user_version contention / duplicate migration paths).
    """

    def __init__(self, investigation_db_path, task_id: str):
        self.db_path = Path(investigation_db_path)
        self.task_id = task_id
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # =====================================================================
    # connection / schema
    # =====================================================================

    def _connect(self) -> sqlite3.Connection:
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
            self._initialize_v3_atomically()
            self._validate_v3_schema()
        elif version == 1:
            self._migrate_v1_to_v3()
            self._validate_v3_schema()
        elif version == 2:
            self._migrate_v2_to_v3()
            self._validate_v3_schema()
        elif version == SUPPORTED_SCHEMA_VERSION:
            # Validate core schema FIRST (columns/UNIQUE/trigger/FK); a corrupt
            # store must fail closed before building auxiliary objects.
            self._validate_v3_schema()
            self._ensure_v3_auxiliary_objects()
        else:
            raise EvidenceStoreError(
                f"unsupported investigation.db schema version: {version} "
                f"(supported: {SUPPORTED_SCHEMA_VERSION})"
            )

    def _initialize_v3_atomically(self) -> None:
        """New database: build both tables + all objects + version=3 in one tx."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # evidence_snapshots (v1 table)
            conn.execute(_CREATE_EVIDENCE_SNAPSHOTS_SQL)
            conn.execute(_INDEX_PATH_SQL)
            conn.execute(_INDEX_CLUSTER_SQL)
            conn.execute(_INDEX_TASK_SQL)
            conn.execute(_TRIGGER_EVSNAP_NO_UPDATE_SQL)
            # secondary_analyses (v2 table + v3 input immutability trigger)
            conn.execute(_CREATE_SECONDARY_ANALYSES_SQL)
            conn.execute(_INDEX_SECONDARY_SCOPE_VERSION_SQL)
            conn.execute(_INDEX_SECONDARY_STATUS_SQL)
            conn.execute(_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL)
            conn.execute(_TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL)
            conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
            conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION}")
            conn.commit()

    def _migrate_v1_to_v3(self) -> None:
        """v1 database: add secondary_analyses with all triggers + bump to v3.

        Equivalent to v1->v2->v3 in one atomic step.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_SECONDARY_ANALYSES_SQL)
            conn.execute(_INDEX_SECONDARY_SCOPE_VERSION_SQL)
            conn.execute(_INDEX_SECONDARY_STATUS_SQL)
            conn.execute(_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL)
            conn.execute(_TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL)
            conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
            conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION}")
            conn.commit()

    def _migrate_v2_to_v3(self) -> None:
        """v2 database: add input immutability trigger + bump to v3 (CCTX6).

        Uses explicit ``conn.execute()`` per statement -- ``executescript()`` is
        FORBIDDEN because it implicitly COMMITs pending transactions, breaking
        migration atomicity.  Any exception rolls back; user_version stays 2.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
            conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION}")
            conn.commit()

    def _ensure_v3_auxiliary_objects(self) -> None:
        """Self-heal missing indexes/triggers only (idempotent CREATE IF NOT EXISTS)."""
        with self._connect() as conn:
            conn.execute(_INDEX_PATH_SQL)
            conn.execute(_INDEX_CLUSTER_SQL)
            conn.execute(_INDEX_TASK_SQL)
            conn.execute(_TRIGGER_EVSNAP_NO_UPDATE_SQL)
            conn.execute(_INDEX_SECONDARY_SCOPE_VERSION_SQL)
            conn.execute(_INDEX_SECONDARY_STATUS_SQL)
            conn.execute(_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL)
            conn.execute(_TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL)
            conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
            conn.commit()

    def _validate_v3_schema(self) -> None:
        with self._connect() as conn:
            self._validate_evidence_snapshots(conn)
            self._validate_secondary_analyses(conn)

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

    def transition(
        self,
        analysis_id: str,
        to: SecondaryAnalysisStatus,
        **fields,
    ) -> SecondaryAnalysis:
        """Advance a Secondary Analysis along the state machine.

        Only fields allowed for the target status are accepted (per-target
        validation); unexpected fields raise ``ValueError`` and leave the DB
        untouched.  The expected-status ``WHERE`` clause is the primary
        concurrency guard; the two DB triggers are backstops.
        """
        allowed = _ALLOWED_TRANSITION_FIELDS.get(to)
        if allowed is None:
            raise ValueError(f"transition to non-targetable status {to.value!r} is not supported")
        unexpected = set(fields) - allowed
        if unexpected:
            raise ValueError(
                f"unexpected fields for transition to {to.value!r}: {sorted(unexpected)} "
                f"(allowed: {sorted(allowed)})"
            )

        now = _now_iso()
        set_clauses: list[str] = ["status = ?"]
        params: list = [to.value]
        # Timestamp field is always written on this transition (auto -> now).
        _ts_col = {
            SecondaryAnalysisStatus.running: "started_at",
            SecondaryAnalysisStatus.review_pending: "review_pending_at",
            SecondaryAnalysisStatus.failed: "failed_at",
        }
        if to in _ts_col:
            ts_col = _ts_col[to]
            set_clauses.append(f"{ts_col} = ?")
            params.append(fields.get(ts_col, now))
        if to in (
            SecondaryAnalysisStatus.accepted,
            SecondaryAnalysisStatus.rejected,
            SecondaryAnalysisStatus.invalid,
        ):
            set_clauses.append("decided_at = ?")
            params.append(fields.get("decided_at", now))
        # Optional content fields -- only written when present.
        for f in ("description", "summary", "model", "decided_by", "decision_reason",
                  "error_code", "error_message"):
            if f in fields:
                set_clauses.append(f"{f} = ?")
                params.append(fields[f])

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM secondary_analyses WHERE analysis_id = ?",
                [analysis_id],
            ).fetchone()
            if row is None:
                raise ValueError(f"analysis not found: {analysis_id!r}")

            current = SecondaryAnalysisStatus(row["status"])
            if current in TERMINAL_SECONDARY_STATUSES:
                raise ValueError(
                    f"analysis {analysis_id!r} is terminal ({current.value!r}); "
                    f"create a new version to redo"
                )
            allowed_targets = SECONDARY_TRANSITIONS.get(current, frozenset())
            if to not in allowed_targets:
                raise ValueError(
                    f"illegal transition {current.value!r} -> {to.value!r} "
                    f"for analysis {analysis_id!r}"
                )

            params.extend([analysis_id, current.value])
            cursor = conn.execute(
                f"UPDATE secondary_analyses SET {', '.join(set_clauses)} "
                f"WHERE analysis_id = ? AND status = ?",
                params,
            )
            if cursor.rowcount == 0:
                raise EvidenceStoreError(
                    f"concurrent status change for analysis {analysis_id!r} "
                    f"(expected status {current.value!r})"
                )

            result_row = conn.execute(
                "SELECT * FROM secondary_analyses WHERE analysis_id = ?", [analysis_id]
            ).fetchone()
            conn.commit()

        return self._row_to_analysis(result_row)

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

    def _row_to_analysis(self, row: sqlite3.Row) -> SecondaryAnalysis:
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
        )
