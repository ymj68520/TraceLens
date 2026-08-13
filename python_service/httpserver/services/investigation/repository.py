"""InvestigationRepository: task-scoped, immutable Evidence Snapshot persistence.

Invariants (see Phase C4a plan):
  S1 existing snapshot returned without re-reading source
  S2 repository bound to task_id; cross-task capture rejected
  S3 UNIQUE(task_id,evidence_key) + BEGIN IMMEDIATE + ON CONFLICT DO NOTHING
  S4 insert-once / never update (UNIQUE + UPDATE trigger); DELETE only for cleanup
  S6 PRAGMA user_version: 0->atomic v1; v1->ensure+validate; >supported or corrupt -> fail closed
  S9 read-time row<->payload identity consistency
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.models import ResolvedEvidence
from .acquisition import build_snapshot_candidate, canonical_json
from .models import ClusterSnapshotPayload, EvidenceSnapshot, FileSnapshotPayload

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = 1

_CREATE_TABLE_SQL = """
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
_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_evsnap_no_update
BEFORE UPDATE ON evidence_snapshots
BEGIN
    SELECT RAISE(ABORT, 'evidence snapshots are immutable');
END
"""

_REQUIRED_COLUMNS = {
    "id", "task_id", "evidence_key", "evidence_type", "normalized_path",
    "unix_minute", "event_type", "snapshot_json", "captured_at",
}


class InvestigationRepository:
    """SQLite-backed immutable Evidence Snapshot store, bound to one task."""

    def __init__(self, investigation_db_path, task_id: str):
        self.db_path = Path(investigation_db_path)
        self.task_id = task_id
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ---- connection / schema ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._initialize_v1_atomically()
            self._validate_v1_schema()
        elif version == SUPPORTED_SCHEMA_VERSION:
            # Validate core schema FIRST (columns/UNIQUE/trigger); a corrupt v1
            # store must fail closed here, before building indexes that assume
            # the columns exist.
            self._validate_v1_schema()
            self._ensure_v1_auxiliary_objects()
        else:
            raise EvidenceStoreError(
                f"unsupported investigation.db schema version: {version} "
                f"(supported: {SUPPORTED_SCHEMA_VERSION})"
            )

    def _initialize_v1_atomically(self) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_INDEX_PATH_SQL)
            conn.execute(_INDEX_CLUSTER_SQL)
            conn.execute(_INDEX_TASK_SQL)
            conn.execute(_TRIGGER_SQL)
            conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION}")
            conn.commit()

    def _ensure_v1_auxiliary_objects(self) -> None:
        # Self-heal missing indexes/trigger only (table + UNIQUE + CHECK come from v0 init).
        with self._connect() as conn:
            conn.execute(_INDEX_PATH_SQL)
            conn.execute(_INDEX_CLUSTER_SQL)
            conn.execute(_INDEX_TASK_SQL)
            conn.execute(_TRIGGER_SQL)
            conn.commit()

    def _validate_v1_schema(self) -> None:
        with self._connect() as conn:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(evidence_snapshots)")}
            missing = _REQUIRED_COLUMNS - cols
            if missing:
                raise EvidenceStoreError(
                    f"evidence_snapshots missing required columns: {sorted(missing)}"
                )
            # UNIQUE(task_id, evidence_key) present?
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

    # ---- read ----

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
        )

    # ---- capture ----

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
