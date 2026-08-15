"""SQLite persistence layer for the Investigation Workbench (二次调查分析工作台).

Stores all analyst-driven secondary-investigation state in a dedicated
``investigation.db`` that lives next to the per-task ``files.db``. The initial
pipeline databases (``raw.db`` / ``events.db`` / ``files.db``) are treated as
read-only sources and are never modified from here.

Design rules implemented here (see plan v4):
- Idempotent schema creation with ``PRAGMA user_version`` bookkeeping and
  ``PRAGMA foreign_keys=ON``.
- Explicit FK / CASCADE rules between investigation-owned tables; evidence_key
  is intentionally *not* an FK (it references external files.db/events.db).
- Analysis version allocation is transactional (BEGIN IMMEDIATE + MAX(version)
  + INSERT in one write transaction) so concurrent analyzers cannot collide.
- ``accept_analysis`` runs in one transaction: replaces any previous accepted
  version and enforces grounding rules (invalid analyses can never be
  accepted; partially grounded analyses require explicit acknowledgement).
- ``recover_interrupted_jobs`` converts leftover queued/running analysis
  versions to ``failed`` after a service restart.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .investigation_errors import UnsupportedSchemaVersion, VersionConflict

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3
BOOTSTRAP_VERSION = 2

EVENT_VERSION_QUEUED = "queued"
EVENT_VERSION_RUNNING = "running"
EVENT_VERSION_REVIEW_PENDING = "review_pending"
EVENT_VERSION_ACCEPTED = "accepted"
EVENT_VERSION_REJECTED = "rejected"
EVENT_VERSION_INVALID = "invalid"
EVENT_VERSION_FAILED = "failed"

# Analysis version lifecycle states
ANALYSIS_QUEUED = "queued"
ANALYSIS_RUNNING = "running"
ANALYSIS_REVIEW_PENDING = "review_pending"
ANALYSIS_ACCEPTED = "accepted"
ANALYSIS_REJECTED = "rejected"
ANALYSIS_FAILED = "failed"
ANALYSIS_INVALID = "invalid"

# Grounding states
GROUNDING_VALID = "valid"
GROUNDING_PARTIAL = "partially_grounded"
GROUNDING_INVALID = "invalid"

# Event review states
EVENT_DRAFT = "draft"
EVENT_REVIEW_PENDING = "review_pending"
EVENT_CONFIRMED = "confirmed"
EVENT_REJECTED = "rejected"


def get_investigation_db_path(files_db_path: str) -> Path:
    """Derive the investigation.db path from the task's files.db path.

    New-style task layout: ``data/tasks/<task_id>/files.db``
        -> ``data/tasks/<task_id>/investigation.db``
    Legacy layout: ``<base>_files.db`` -> ``<base>_investigation.db``
    """
    files_path = Path(files_db_path)
    if files_path.name == "files.db":
        return files_path.parent / "investigation.db"
    if files_path.name.endswith("_files.db"):
        return files_path.with_name(
            files_path.name[: -len("_files.db")] + "_investigation.db"
        )
    return files_path.parent / "investigation.db"


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return str(uuid.uuid4())


def _json_string_list(value: Any) -> Optional[List[str]]:
    """Parse an immutable binding list, returning ``None`` on corruption."""
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) or not item for item in parsed
    ):
        return None
    return parsed


def _event_version_inputs_admissible(
    conn: sqlite3.Connection,
    version: sqlite3.Row,
    event: sqlite3.Row,
) -> bool:
    """Validate the complete immutable input binding for an Event Version."""
    if version["task_id"] != event["task_id"] or version["event_id"] != event["id"]:
        return False
    try:
        if int(version["source_revision"]) != int(event["semantic_revision"]):
            return False
    except (TypeError, ValueError):
        return False
    if version["grounding_status"] != GROUNDING_VALID:
        return False

    input_analysis_ids = _json_string_list(version["input_analysis_ids"])
    input_evidence_refs = _json_string_list(version["input_evidence_refs"])
    evidence_refs = _json_string_list(version["evidence_refs"])
    if input_analysis_ids is None or input_evidence_refs is None or evidence_refs is None:
        return False
    allowed_refs = set(input_evidence_refs)
    if not set(evidence_refs).issubset(allowed_refs):
        return False

    allowed_statuses = {ANALYSIS_ACCEPTED}
    if int(version["included_review_pending"] or 0) == 1:
        allowed_statuses.add(ANALYSIS_REVIEW_PENDING)
    for analysis_id in input_analysis_ids:
        analysis = conn.execute(
            "SELECT id, task_id, evidence_key, status FROM evidence_analysis_versions "
            "WHERE id = ? AND task_id = ?",
            (analysis_id, event["task_id"]),
        ).fetchone()
        if analysis is None or analysis["status"] not in allowed_statuses:
            return False
        if analysis["evidence_key"] not in allowed_refs:
            return False
        if analysis["status"] == ANALYSIS_REVIEW_PENDING:
            replacement = conn.execute(
                "SELECT 1 FROM evidence_analysis_versions "
                "WHERE task_id = ? AND evidence_key = ? AND status = ? LIMIT 1",
                (event["task_id"], analysis["evidence_key"], ANALYSIS_ACCEPTED),
            ).fetchone()
            if replacement is not None:
                return False
    return True


def select_effective_event_version(
    conn: sqlite3.Connection, task_id: str, event_id: str
) -> Optional[sqlite3.Row]:
    """Return the one current accepted Event Version, or fail closed.

    This is the sole current-semantic selector. Historical readers must query
    Event Versions by their exact identity instead of using this function.
    """
    event = conn.execute(
        "SELECT * FROM investigation_events WHERE task_id = ? AND id = ?",
        (task_id, event_id),
    ).fetchone()
    if event is None:
        return None
    candidates = conn.execute(
        "SELECT * FROM investigation_event_versions "
        "WHERE task_id = ? AND event_id = ? AND status = ? "
        "ORDER BY version DESC, id DESC",
        (task_id, event_id, EVENT_VERSION_ACCEPTED),
    ).fetchall()
    effective = [
        candidate
        for candidate in candidates
        if _event_version_inputs_admissible(conn, candidate, event)
    ]
    if not effective:
        return None
    if len(effective) > 1:
        return None
    return effective[0]


class InvestigationPersistence:
    """CRUD + schema management for a single task's investigation.db."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ------------------------------------------------------------------
    # connection / schema
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _execute_schema_ddl(self, conn: sqlite3.Connection, script: str) -> None:
        """Execute schema statements without ``executescript`` implicit commits."""
        statement = ""
        for line in script.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                conn.execute(statement)
                statement = ""
        if statement.strip():
            conn.execute(statement)

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection, schema_sql: str) -> None:
        """Upgrade the MVP schema while preserving all existing investigation rows."""
        self._execute_schema_ddl(conn, schema_sql)
        event_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(investigation_events)")
        }
        if "semantic_revision" not in event_columns:
            conn.execute(
                "ALTER TABLE investigation_events "
                "ADD COLUMN semantic_revision INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection, schema_sql: str) -> None:
        """Add immutable Event Claim storage to the Phase 2 schema."""
        self._execute_schema_ddl(conn, schema_sql)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise UnsupportedSchemaVersion(
                    f"investigation database schema {current_version} is newer than supported {SCHEMA_VERSION}"
                )
            conn.execute("BEGIN IMMEDIATE")
            schema_sql = """
                CREATE TABLE IF NOT EXISTS investigation_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,

                    title TEXT NOT NULL,
                    summary TEXT,

                    seed_title TEXT,
                    seed_summary TEXT,

                    start_time INTEGER,
                    end_time INTEGER,
                    evidence_start_time INTEGER,
                    evidence_end_time INTEGER,

                    category TEXT,
                    importance TEXT,

                    source TEXT NOT NULL,
                    -- cluster_seed / llm / analyst / mixed

                    review_status TEXT NOT NULL DEFAULT 'draft',
                    -- draft / review_pending / confirmed / rejected

                    confidence REAL,

                    -- Only used for cluster_seed sourced events; analyst/llm
                    -- events keep this NULL (SQLite allows multiple NULLs).
                    source_cluster_key TEXT,

                    needs_refresh INTEGER NOT NULL DEFAULT 0,
                    semantic_revision INTEGER NOT NULL DEFAULT 0,

                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,

                    UNIQUE(task_id, source_cluster_key)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_events_task
                    ON investigation_events(task_id, start_time);

                CREATE TABLE IF NOT EXISTS investigation_event_evidence (
                    event_id TEXT NOT NULL
                        REFERENCES investigation_events(id) ON DELETE CASCADE,

                    evidence_key TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,

                    role TEXT NOT NULL,
                    -- primary / supporting / context / contradicting

                    relation_type TEXT,
                    source TEXT NOT NULL,
                    -- rule / llm / analyst / cluster_seed

                    relevance REAL,
                    rationale TEXT,

                    created_at INTEGER NOT NULL,

                    PRIMARY KEY (event_id, evidence_key)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_event_evidence_key
                    ON investigation_event_evidence(evidence_key);

                CREATE TABLE IF NOT EXISTS evidence_snapshots (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    evidence_key TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,

                    source_metadata_json TEXT,
                    initial_description TEXT,
                    initial_summary TEXT,

                    source_hash TEXT,
                    source_size INTEGER,
                    source_mtime INTEGER,
                    source_updated_at INTEGER,

                    captured_at INTEGER NOT NULL,

                    UNIQUE(task_id, evidence_key)
                );

                CREATE TABLE IF NOT EXISTS analyst_notes (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,

                    target_type TEXT NOT NULL,
                    -- evidence / investigation_event
                    target_key TEXT NOT NULL,

                    content TEXT NOT NULL,

                    author TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER,

                    UNIQUE(task_id, target_type, target_key)
                );

                CREATE TABLE IF NOT EXISTS evidence_analysis_versions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,

                    evidence_key TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,

                    version INTEGER NOT NULL,

                    analysis_type TEXT NOT NULL,
                    -- analyst_guided

                    analyst_note_id TEXT
                        REFERENCES analyst_notes(id) ON DELETE SET NULL,
                    analyst_note_snapshot TEXT,

                    description TEXT,
                    summary TEXT,

                    status TEXT NOT NULL DEFAULT 'queued',
                    -- queued / running / review_pending / accepted /
                    -- rejected / failed / invalid

                    grounding_status TEXT,
                    -- valid / partially_grounded / invalid
                    grounding_warnings TEXT,

                    error_message TEXT,
                    completed_at INTEGER,

                    model TEXT,
                    prompt_version TEXT,
                    input_hash TEXT,
                    input_evidence_refs TEXT,

                    created_at INTEGER NOT NULL,

                    UNIQUE(task_id, evidence_key, version)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_analysis_evidence
                    ON evidence_analysis_versions(task_id, evidence_key, version DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_one_accepted_analysis
                    ON evidence_analysis_versions(task_id, evidence_key)
                    WHERE status = 'accepted';

                CREATE TABLE IF NOT EXISTS evidence_analysis_claims (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL
                        REFERENCES evidence_analysis_versions(id) ON DELETE CASCADE,

                    claim_text TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    -- fact / inference / hypothesis

                    grounding_status TEXT,
                    -- grounded / partially_grounded / ungrounded
                    origin TEXT,
                    -- evidence_derived / analyst_hypothesis / mixed

                    confidence REAL,

                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_inv_claims_analysis
                    ON evidence_analysis_claims(analysis_id);

                CREATE TABLE IF NOT EXISTS claim_evidence (
                    claim_id TEXT NOT NULL
                        REFERENCES evidence_analysis_claims(id) ON DELETE CASCADE,
                    evidence_key TEXT NOT NULL,

                    relation TEXT NOT NULL,
                    -- supports / contradicts
                    rationale TEXT,

                    PRIMARY KEY (claim_id, evidence_key)
                );

                CREATE TABLE IF NOT EXISTS evidence_analysis_entities (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL
                        REFERENCES evidence_analysis_versions(id) ON DELETE CASCADE,

                    entity_type TEXT NOT NULL,
                    canonical_value TEXT NOT NULL,
                    display_name TEXT,

                    source TEXT NOT NULL DEFAULT 'llm',
                    confidence REAL
                );
                CREATE INDEX IF NOT EXISTS idx_inv_entities_analysis
                    ON evidence_analysis_entities(analysis_id);

                CREATE TABLE IF NOT EXISTS evidence_analysis_relations (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL
                        REFERENCES evidence_analysis_versions(id) ON DELETE CASCADE,

                    source_entity_id TEXT NOT NULL
                        REFERENCES evidence_analysis_entities(id),
                    target_entity_id TEXT NOT NULL
                        REFERENCES evidence_analysis_entities(id),

                    relation_type TEXT NOT NULL,
                    relation_kind TEXT NOT NULL,
                    -- observed / inferred

                    confidence REAL,
                    rationale TEXT,

                    -- Reserved for future per-relation review. The effective
                    -- status is inherited from the owning analysis version.
                    status TEXT NOT NULL DEFAULT 'review_pending'
                );
                CREATE INDEX IF NOT EXISTS idx_inv_relations_analysis
                    ON evidence_analysis_relations(analysis_id);

                CREATE TABLE IF NOT EXISTS investigation_event_versions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_id TEXT NOT NULL REFERENCES investigation_events(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    title TEXT,
                    summary TEXT,
                    model TEXT,
                    prompt_version TEXT,
                    analyst_note_snapshot TEXT,
                    input_analysis_ids TEXT NOT NULL DEFAULT '[]',
                    input_evidence_refs TEXT NOT NULL DEFAULT '[]',
                    input_hash TEXT,
                    source_revision INTEGER NOT NULL,
                    included_review_pending INTEGER NOT NULL DEFAULT 0,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    grounding_status TEXT,
                    grounding_warnings TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    error_message TEXT,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    accepted_at INTEGER,
                    UNIQUE(event_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_event_versions_task_event
                    ON investigation_event_versions(task_id, event_id, version DESC);

                CREATE TABLE IF NOT EXISTS event_claims (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_version_id TEXT NOT NULL
                        REFERENCES investigation_event_versions(id) ON DELETE CASCADE,
                    claim_text TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'review_pending',
                    grounding_status TEXT NOT NULL,
                    grounding_warnings TEXT NOT NULL DEFAULT '[]',
                    origin TEXT,
                    confidence REAL,
                    created_at INTEGER NOT NULL,
                    accepted_at INTEGER,
                    rejected_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_inv_event_claims_version
                    ON event_claims(event_version_id, status);
                CREATE INDEX IF NOT EXISTS idx_inv_event_claims_task_event
                    ON event_claims(task_id, event_id, event_version_id);

                CREATE TABLE IF NOT EXISTS event_claim_evidence (
                    claim_id TEXT NOT NULL
                        REFERENCES event_claims(id) ON DELETE CASCADE,
                    evidence_key TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    rationale TEXT,
                    PRIMARY KEY (claim_id, evidence_key)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_event_claim_evidence_key
                    ON event_claim_evidence(evidence_key);

                CREATE TABLE IF NOT EXISTS report_evidence (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,

                    evidence_key TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,

                    usage TEXT NOT NULL,
                    -- main / appendix
                    role TEXT,
                    -- primary / supporting / context

                    report_note TEXT,

                    -- The accepted analysis version bound at the time the
                    -- evidence was added to the report. NULL means the report
                    -- uses the evidence snapshot / raw evidence directly.
                    analysis_id TEXT,

                    added_by TEXT NOT NULL,
                    -- analyst / ai_recommended
                    analyst_confirmed INTEGER NOT NULL DEFAULT 1,

                    sort_order INTEGER,

                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,

                    UNIQUE(task_id, evidence_key)
                );

                CREATE TABLE IF NOT EXISTS investigation_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            if current_version == 1:
                self._migrate_v1_to_v2(conn, schema_sql)
                self._migrate_v2_to_v3(conn, schema_sql)
            elif current_version == 2:
                self._migrate_v2_to_v3(conn, schema_sql)
            else:
                self._execute_schema_ddl(conn, schema_sql)
            # Accepted Event Versions form an immutable audit history. Older
            # databases created this partial unique index before that rule.
            conn.execute("DROP INDEX IF EXISTS idx_inv_one_accepted_event_version")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    # ------------------------------------------------------------------
    # meta
    # ------------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM investigation_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO investigation_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------------
    # overview
    # ------------------------------------------------------------------
    def overview(self, task_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            event_count = conn.execute(
                "SELECT COUNT(*) c FROM investigation_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()["c"]
            confirmed = conn.execute(
                "SELECT COUNT(*) c FROM investigation_events "
                "WHERE task_id = ? AND review_status = ?",
                (task_id, EVENT_CONFIRMED),
            ).fetchone()["c"]
            analysis_count = conn.execute(
                "SELECT COUNT(*) c FROM evidence_analysis_versions WHERE task_id = ?",
                (task_id,),
            ).fetchone()["c"]
            report_count = conn.execute(
                "SELECT COUNT(*) c FROM report_evidence WHERE task_id = ?",
                (task_id,),
            ).fetchone()["c"]
        bootstrap_version = self.get_meta("bootstrap_version")
        return {
            "task_id": task_id,
            "initialized": bool(bootstrap_version and int(bootstrap_version) >= BOOTSTRAP_VERSION),
            "bootstrap_version": int(bootstrap_version) if bootstrap_version else None,
            "event_count": event_count,
            "confirmed_event_count": confirmed,
            "analysis_count": analysis_count,
            "report_evidence_count": report_count,
        }

    # ------------------------------------------------------------------
    # investigation events
    # ------------------------------------------------------------------
    def upsert_seed_event(
        self,
        task_id: str,
        source_cluster_key: str,
        title: str,
        summary: Optional[str],
        start_time: Optional[int],
        end_time: Optional[int],
        category: Optional[str] = None,
        importance: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> tuple[str, bool]:
        """Idempotently create a cluster-seed event.

        Returns (event_id, created). When the seed already exists the existing
        id is returned and ``created`` is False; seed_title/seed_summary are
        only filled on first insert.
        """
        now = _now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM investigation_events "
                "WHERE task_id = ? AND source_cluster_key = ?",
                (task_id, source_cluster_key),
            ).fetchone()
            if existing:
                return existing["id"], False
            event_id = _new_id()
            conn.execute(
                """INSERT INTO investigation_events
                   (id, task_id, title, summary, seed_title, seed_summary,
                    start_time, end_time, category, importance, source,
                    review_status, confidence, source_cluster_key,
                    needs_refresh, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cluster_seed',
                           'draft', ?, ?, 1, ?, ?)""",
                (
                    event_id, task_id, title, summary, title, summary,
                    start_time, end_time, category, importance,
                    confidence, source_cluster_key, now, now,
                ),
            )
        return event_id, True

    def create_event(
        self,
        task_id: str,
        title: str,
        summary: Optional[str],
        source: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        category: Optional[str] = None,
        importance: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> str:
        """Create an analyst/llm sourced event (source_cluster_key stays NULL)."""
        now = _now()
        event_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO investigation_events
                   (id, task_id, title, summary, start_time, end_time,
                    category, importance, source, review_status, confidence,
                    needs_refresh, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, 1, ?, ?)""",
                (
                    event_id, task_id, title, summary, start_time, end_time,
                    category, importance, source, confidence, now, now,
                ),
            )
        return event_id

    def list_events(
        self,
        task_id: str,
        status: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM investigation_events WHERE task_id = ?"
        params: List[Any] = [task_id]
        if status:
            sql += " AND review_status = ?"
            params.append(status)
        if start_time is not None:
            sql += " AND (start_time IS NULL OR start_time >= ?)"
            params.append(start_time)
        if end_time is not None:
            sql += " AND (end_time IS NULL OR end_time <= ?)"
            params.append(end_time)
        sql += " ORDER BY COALESCE(start_time, evidence_start_time, 0) ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_event(self, task_id: str, event_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM investigation_events WHERE task_id = ? AND id = ?",
                (task_id, event_id),
            ).fetchone()
        return dict(row) if row else None

    def set_event_review_status(
        self, task_id: str, event_id: str, status: str
    ) -> None:
        if status not in (
            EVENT_DRAFT,
            EVENT_REVIEW_PENDING,
            EVENT_CONFIRMED,
            EVENT_REJECTED,
        ):
            raise ValueError(f"invalid event review status: {status}")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE investigation_events SET review_status = ?, updated_at = ? "
                "WHERE task_id = ? AND id = ?",
                (status, _now(), task_id, event_id),
            )
            if cur.rowcount == 0:
                raise KeyError(event_id)

    def update_event_times_from_evidence(
        self,
        task_id: str,
        event_id: str,
        evidence_start: Optional[int],
        evidence_end: Optional[int],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigation_events SET evidence_start_time = ?, "
                "evidence_end_time = ?, updated_at = ? WHERE task_id = ? AND id = ?",
                (evidence_start, evidence_end, _now(), task_id, event_id),
            )

    def mark_events_needing_refresh(self, task_id: str, evidence_key: str) -> int:
        """Flag linked Events and advance their semantic revision atomically."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            event_ids = [
                row["event_id"]
                for row in conn.execute(
                    "SELECT e.event_id FROM investigation_event_evidence e "
                    "JOIN investigation_events ev ON ev.id = e.event_id "
                    "WHERE ev.task_id = ? AND e.evidence_key = ?",
                    (task_id, evidence_key),
                )
            ]
            for event_id in event_ids:
                self._bump_event_revision(conn, task_id, event_id)
            conn.commit()
            return len(event_ids)

    def _bump_event_revision(
        self, conn: sqlite3.Connection, task_id: str, event_id: str
    ) -> None:
        cur = conn.execute(
            "UPDATE investigation_events SET needs_refresh = 1, "
            "semantic_revision = semantic_revision + 1, updated_at = ? "
            "WHERE task_id = ? AND id = ?",
            (_now(), task_id, event_id),
        )
        if not cur.rowcount:
            raise KeyError(event_id)

    @staticmethod
    def _dependent_events_for_analysis(
        conn: sqlite3.Connection, task_id: str, analysis_id: str
    ) -> set[str]:
        """Find only task-local Events linked to or pinning an Analysis ID."""
        event_ids = {
            row["event_id"]
            for row in conn.execute(
                "SELECT e.event_id FROM investigation_event_evidence e "
                "JOIN investigation_events ev ON ev.id = e.event_id "
                "WHERE ev.task_id = ? AND e.evidence_key = "
                "(SELECT evidence_key FROM evidence_analysis_versions "
                "WHERE task_id = ? AND id = ?)",
                (task_id, task_id, analysis_id),
            )
        }
        for row in conn.execute(
            "SELECT event_id, input_analysis_ids FROM investigation_event_versions "
            "WHERE task_id = ?",
            (task_id,),
        ):
            analysis_ids = _json_string_list(row["input_analysis_ids"])
            if analysis_ids is not None and analysis_id in analysis_ids:
                event_ids.add(row["event_id"])
        return event_ids

    def _effective_event_version_in_connection(
        self, conn: sqlite3.Connection, task_id: str, event_id: str
    ) -> Optional[sqlite3.Row]:
        return select_effective_event_version(conn, task_id, event_id)


    # ------------------------------------------------------------------
    # event evidence links
    # ------------------------------------------------------------------
    def link_evidence(
        self,
        task_id: str,
        event_id: str,
        evidence_key: str,
        evidence_type: str,
        role: str,
        source: str,
        relation_type: Optional[str] = None,
        relevance: Optional[float] = None,
        rationale: Optional[str] = None,
    ) -> bool:
        """Link evidence to an event. Returns True if newly inserted."""
        if role not in ("primary", "supporting", "context", "contradicting"):
            raise ValueError(f"invalid evidence role: {role}")
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO investigation_event_evidence
                   (event_id, evidence_key, evidence_type, role, relation_type,
                    source, relevance, rationale, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, evidence_key, evidence_type, role, relation_type,
                    source, relevance, rationale, _now(),
                ),
            )
            return cur.rowcount > 0

    def unlink_evidence(self, event_id: str, evidence_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM investigation_event_evidence "
                "WHERE event_id = ? AND evidence_key = ?",
                (event_id, evidence_key),
            )
            return cur.rowcount > 0

    def list_event_evidence(
        self, event_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_event_evidence WHERE event_id = ? "
                "ORDER BY created_at ASC LIMIT ? OFFSET ?",
                (event_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def event_evidence_counts(self, event_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, COUNT(*) c FROM investigation_event_evidence "
                "WHERE event_id = ? GROUP BY role",
                (event_id,),
            ).fetchall()
        counts = {"primary": 0, "supporting": 0, "context": 0, "contradicting": 0}
        for r in rows:
            counts[r["role"]] = r["c"]
        counts["total"] = sum(counts.values())
        return counts

    def events_for_evidence(self, task_id: str, evidence_key: str) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT e.event_id FROM investigation_event_evidence e "
                "JOIN investigation_events ev ON ev.id = e.event_id "
                "WHERE ev.task_id = ? AND e.evidence_key = ?",
                (task_id, evidence_key),
            ).fetchall()
        return [r["event_id"] for r in rows]

    # ------------------------------------------------------------------
    # evidence snapshots
    # ------------------------------------------------------------------
    def capture_snapshot_if_absent(
        self,
        task_id: str,
        evidence_key: str,
        evidence_type: str,
        metadata: Optional[Dict[str, Any]],
        initial_description: Optional[str],
        initial_summary: Optional[str],
        source_hash: Optional[str] = None,
        source_size: Optional[int] = None,
        source_mtime: Optional[int] = None,
        source_updated_at: Optional[int] = None,
    ) -> bool:
        """Insert the snapshot only when none exists (immutable audit chain)."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO evidence_snapshots
                   (id, task_id, evidence_key, evidence_type,
                    source_metadata_json, initial_description, initial_summary,
                    source_hash, source_size, source_mtime, source_updated_at,
                    captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _new_id(), task_id, evidence_key, evidence_type,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    initial_description, initial_summary,
                    source_hash, source_size, source_mtime, source_updated_at,
                    _now(),
                ),
            )
            return cur.rowcount > 0

    def get_snapshot(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                (task_id, evidence_key),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # analyst notes (current-state, not versioned)
    # ------------------------------------------------------------------
    def upsert_note(
        self,
        task_id: str,
        target_type: str,
        target_key: str,
        content: str,
        author: Optional[str] = None,
    ) -> str:
        now = _now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM analyst_notes WHERE task_id = ? AND target_type = ? "
                "AND target_key = ?",
                (task_id, target_type, target_key),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE analyst_notes SET content = ?, author = ?, updated_at = ? "
                    "WHERE id = ?",
                    (content, author, now, existing["id"]),
                )
                return existing["id"]
            note_id = _new_id()
            conn.execute(
                """INSERT INTO analyst_notes
                   (id, task_id, target_type, target_key, content, author,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (note_id, task_id, target_type, target_key, content, author, now, now),
            )
            return note_id

    def get_note(
        self, task_id: str, target_type: str, target_key: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analyst_notes WHERE task_id = ? AND target_type = ? "
                "AND target_key = ?",
                (task_id, target_type, target_key),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # analysis versions
    # ------------------------------------------------------------------
    def create_analysis_version(
        self,
        task_id: str,
        evidence_key: str,
        evidence_type: str,
        analyst_note_id: Optional[str],
        analyst_note_snapshot: Optional[str],
        model: Optional[str],
        prompt_version: Optional[str],
        input_hash: Optional[str],
        input_evidence_refs: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Allocate the next version and insert it as ``queued``.

        BEGIN IMMEDIATE serializes allocation across concurrent writers so the
        (task_id, evidence_key, version) unique constraint can never collide.
        """
        analysis_id = _new_id()
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS v "
                "FROM evidence_analysis_versions WHERE task_id = ? AND evidence_key = ?",
                (task_id, evidence_key),
            ).fetchone()
            version = int(row["v"])
            conn.execute(
                """INSERT INTO evidence_analysis_versions
                   (id, task_id, evidence_key, evidence_type, version,
                    analysis_type, analyst_note_id, analyst_note_snapshot,
                    status, model, prompt_version, input_hash,
                    input_evidence_refs, created_at)
                   VALUES (?, ?, ?, ?, ?, 'analyst_guided', ?, ?, 'queued',
                           ?, ?, ?, ?, ?)""",
                (
                    analysis_id, task_id, evidence_key, evidence_type, version,
                    analyst_note_id, analyst_note_snapshot, model, prompt_version,
                    input_hash,
                    json.dumps(input_evidence_refs or [], ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
        created = self.get_analysis(analysis_id)
        if created is None:  # pragma: no cover - defensive
            raise RuntimeError(f"created analysis {analysis_id} disappeared")
        return created

    def get_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_analysis_versions WHERE id = ?",
                (analysis_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_analyses(
        self, task_id: str, evidence_key: str
    ) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_analysis_versions "
                "WHERE task_id = ? AND evidence_key = ? ORDER BY version DESC",
                (task_id, evidence_key),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_accepted_analysis(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_analysis_versions WHERE task_id = ? "
                "AND evidence_key = ? AND status = 'accepted' "
                "ORDER BY version DESC LIMIT 1",
                (task_id, evidence_key),
            ).fetchone()
        return dict(row) if row else None

    def get_effective_analysis(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        """Accepted version if any, else the latest completed review_pending."""
        accepted = self.get_accepted_analysis(task_id, evidence_key)
        if accepted:
            return accepted
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_analysis_versions WHERE task_id = ? "
                "AND evidence_key = ? AND status = 'review_pending' "
                "ORDER BY version DESC LIMIT 1",
                (task_id, evidence_key),
            ).fetchone()
        return dict(row) if row else None

    def mark_analysis_running(self, analysis_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE evidence_analysis_versions SET status = 'running' "
                "WHERE id = ? AND status = 'queued'",
                (analysis_id,),
            )

    def complete_analysis(
        self,
        analysis_id: str,
        description: Optional[str],
        summary: Optional[str],
        grounding_status: str,
        grounding_warnings: Optional[List[str]],
        status: str = ANALYSIS_REVIEW_PENDING,
    ) -> None:
        """Mark an analysis finished and persist its results."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE evidence_analysis_versions
                   SET status = ?, description = ?, summary = ?,
                       grounding_status = ?, grounding_warnings = ?,
                       completed_at = ?
                   WHERE id = ?""",
                (
                    status, description, summary, grounding_status,
                    json.dumps(grounding_warnings or [], ensure_ascii=False),
                    _now(), analysis_id,
                ),
            )

    def fail_analysis(self, analysis_id: str, error_message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE evidence_analysis_versions
                   SET status = 'failed', error_message = ?, completed_at = ?
                   WHERE id = ?""",
                (error_message, _now(), analysis_id),
            )

    def recover_interrupted_jobs(self) -> int:
        """Fail analysis versions left in queued/running after a restart."""
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE evidence_analysis_versions
                   SET status = 'failed',
                       error_message = 'Analysis interrupted by service restart',
                       completed_at = ?
                   WHERE status IN ('queued', 'running')""",
                (_now(),),
            )
            if cur.rowcount:
                logger.info(
                    "[Investigation] recovered %d interrupted analysis jobs",
                    cur.rowcount,
                )
            return cur.rowcount

    def accept_analysis(
        self, task_id: str, analysis_id: str, acknowledge_warnings: bool = False
    ) -> None:
        """Accept an analysis version in one transaction.

        - invalid analyses can never be accepted;
        - partially grounded analyses require ``acknowledge_warnings``;
        - any previously accepted version for the same evidence is demoted to
          review_pending in the same transaction.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM evidence_analysis_versions WHERE id = ? AND task_id = ?",
                (analysis_id, task_id),
            ).fetchone()
            if row is None:
                raise KeyError(analysis_id)
            if row["status"] in (ANALYSIS_QUEUED, ANALYSIS_RUNNING):
                raise ValueError("analysis is still running")
            if row["status"] == ANALYSIS_FAILED:
                raise ValueError("failed analysis cannot be accepted")
            if row["status"] == ANALYSIS_INVALID or row["grounding_status"] == GROUNDING_INVALID:
                raise ValueError("invalid analysis cannot be accepted")
            if (
                row["grounding_status"] == GROUNDING_PARTIAL
                and not acknowledge_warnings
            ):
                raise ValueError(
                    "analysis has grounding warnings; acknowledge_warnings required"
                )
            conn.execute(
                "UPDATE evidence_analysis_versions SET status = 'review_pending' "
                "WHERE task_id = ? AND evidence_key = ? AND status = 'accepted'",
                (task_id, row["evidence_key"]),
            )
            conn.execute(
                "UPDATE evidence_analysis_versions SET status = 'accepted', "
                "completed_at = COALESCE(completed_at, ?) WHERE id = ?",
                (_now(), analysis_id),
            )
            dependent_event_ids = self._dependent_events_for_analysis(
                conn, task_id, analysis_id
            )
            for event_id in dependent_event_ids:
                self._bump_event_revision(conn, task_id, event_id)
            conn.commit()

    def reject_analysis(self, task_id: str, analysis_id: str) -> None:
        """Reject an Analysis and invalidate only exact dependent Events."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM evidence_analysis_versions "
                "WHERE id = ? AND task_id = ?",
                (analysis_id, task_id),
            ).fetchone()
            if row is None or row["status"] not in (
                ANALYSIS_REVIEW_PENDING,
                ANALYSIS_ACCEPTED,
            ):
                raise KeyError(analysis_id)
            dependent_event_ids = self._dependent_events_for_analysis(
                conn, task_id, analysis_id
            )
            conn.execute(
                "UPDATE evidence_analysis_versions SET status = 'rejected', "
                "completed_at = COALESCE(completed_at, ?) "
                "WHERE id = ? AND task_id = ?",
                (_now(), analysis_id, task_id),
            )
            for event_id in dependent_event_ids:
                self._bump_event_revision(conn, task_id, event_id)
            conn.commit()

    # ------------------------------------------------------------------
    # claims / claim evidence
    # ------------------------------------------------------------------
    def add_claim(
        self,
        analysis_id: str,
        claim_text: str,
        claim_type: str,
        grounding_status: str,
        origin: str,
        confidence: Optional[float] = None,
    ) -> str:
        claim_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO evidence_analysis_claims
                   (id, analysis_id, claim_text, claim_type, grounding_status,
                    origin, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    claim_id, analysis_id, claim_text, claim_type,
                    grounding_status, origin, confidence, _now(),
                ),
            )
        return claim_id

    def add_claim_evidence(
        self,
        claim_id: str,
        evidence_key: str,
        relation: str,
        rationale: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO claim_evidence
                   (claim_id, evidence_key, relation, rationale)
                   VALUES (?, ?, ?, ?)""",
                (claim_id, evidence_key, relation, rationale),
            )

    def list_claims(self, analysis_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            claims = conn.execute(
                "SELECT * FROM evidence_analysis_claims WHERE analysis_id = ? "
                "ORDER BY created_at ASC",
                (analysis_id,),
            ).fetchall()
            result = []
            for c in claims:
                item = dict(c)
                refs = conn.execute(
                    "SELECT evidence_key, relation, rationale FROM claim_evidence "
                    "WHERE claim_id = ?",
                    (c["id"],),
                ).fetchall()
                item["evidence_refs"] = [dict(r) for r in refs]
                result.append(item)
        return result

    # ------------------------------------------------------------------
    # entities / relations (graph overlay)
    # ------------------------------------------------------------------
    def add_entity(
        self,
        analysis_id: str,
        entity_type: str,
        canonical_value: str,
        display_name: Optional[str] = None,
        source: str = "llm",
        confidence: Optional[float] = None,
    ) -> str:
        entity_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO evidence_analysis_entities
                   (id, analysis_id, entity_type, canonical_value, display_name,
                    source, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entity_id, analysis_id, entity_type, canonical_value,
                    display_name, source, confidence,
                ),
            )
        return entity_id

    def add_relation(
        self,
        analysis_id: str,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        relation_kind: str,
        confidence: Optional[float] = None,
        rationale: Optional[str] = None,
    ) -> str:
        relation_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO evidence_analysis_relations
                   (id, analysis_id, source_entity_id, target_entity_id,
                    relation_type, relation_kind, confidence, rationale, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'review_pending')""",
                (
                    relation_id, analysis_id, source_entity_id, target_entity_id,
                    relation_type, relation_kind, confidence, rationale,
                ),
            )
        return relation_id

    def list_entities(self, analysis_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_analysis_entities WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_relations(self, analysis_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_analysis_relations WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_effective_overlay(
        self, task_id: str, evidence_keys: List[str]
    ) -> Dict[str, Any]:
        """Entities/relations from the effective evidence analysis."""
        entities: List[Dict[str, Any]] = []
        relations: List[Dict[str, Any]] = []
        for key in evidence_keys:
            effective = self.get_effective_analysis(task_id, key)
            if not effective:
                continue
            for e in self.list_entities(effective["id"]):
                e["analysis_status"] = effective["status"]
                entities.append(e)
            for r in self.list_relations(effective["id"]):
                r["analysis_status"] = effective["status"]
                relations.append(r)
        return {"entities": entities, "relations": relations}

    # ------------------------------------------------------------------
    # report evidence
    # ------------------------------------------------------------------
    def set_report_evidence(
        self,
        task_id: str,
        evidence_key: str,
        evidence_type: str,
        usage: str,
        role: Optional[str] = None,
        report_note: Optional[str] = None,
        analysis_id: Optional[str] = None,
        added_by: str = "analyst",
        analyst_confirmed: bool = True,
        sort_order: Optional[int] = None,
    ) -> str:
        """Add or update the report selection for an evidence item."""
        if usage not in ("main", "appendix"):
            raise ValueError(f"invalid report usage: {usage}")
        # Only accepted analyses may be bound to report evidence.
        if analysis_id is not None:
            analysis = self.get_analysis(analysis_id)
            if analysis is None or analysis["task_id"] != task_id:
                raise KeyError(analysis_id)
            if analysis["evidence_key"] != evidence_key or analysis["evidence_type"] != evidence_type:
                raise ValueError("analysis does not belong to report evidence")
            if analysis["status"] != ANALYSIS_ACCEPTED:
                raise ValueError("only accepted analyses can be bound to report evidence")
        now = _now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                (task_id, evidence_key),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE report_evidence SET usage = ?, role = ?, report_note = ?,
                           analysis_id = ?, added_by = ?, analyst_confirmed = ?,
                           sort_order = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        usage, role, report_note, analysis_id, added_by,
                        1 if analyst_confirmed else 0, sort_order, now,
                        existing["id"],
                    ),
                )
                return existing["id"]
            entry_id = _new_id()
            conn.execute(
                """INSERT INTO report_evidence
                   (id, task_id, evidence_key, evidence_type, usage, role,
                    report_note, analysis_id, added_by, analyst_confirmed,
                    sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, task_id, evidence_key, evidence_type, usage, role,
                    report_note, analysis_id, added_by,
                    1 if analyst_confirmed else 0, sort_order, now, now,
                ),
            )
            return entry_id

    def remove_report_evidence(self, task_id: str, evidence_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                (task_id, evidence_key),
            )
            return cur.rowcount > 0

    def get_report_evidence(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM report_evidence WHERE task_id = ? AND evidence_key = ?",
                (task_id, evidence_key),
            ).fetchone()
        return dict(row) if row else None

    def list_report_evidence(self, task_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_evidence WHERE task_id = ? "
                "ORDER BY COALESCE(sort_order, 999999), created_at",
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Phase 2 task-scoped links and semantic event versions
    # ------------------------------------------------------------------
    def get_analysis_for_task(self, task_id: str, analysis_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_analysis_versions WHERE task_id = ? AND id = ?",
                (task_id, analysis_id),
            ).fetchone()
        return dict(row) if row else None

    def event_evidence_for_task(self, task_id: str, event_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT e.* FROM investigation_event_evidence e JOIN investigation_events ev ON ev.id = e.event_id "
                "WHERE ev.task_id = ? AND e.event_id = ? ORDER BY e.created_at LIMIT ? OFFSET ?",
                (task_id, event_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def link_evidence_for_task(self, task_id: str, event_id: str, evidence_key: str, evidence_type: str, role: str, source: str, relation_type: Optional[str] = None, rationale: Optional[str] = None, invalidate: bool = True) -> bool:
        if role not in ("primary", "supporting", "context", "contradicting"):
            raise ValueError(f"invalid evidence role: {role}")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM investigation_events WHERE task_id = ? AND id = ?", (task_id, event_id)).fetchone():
                raise KeyError(event_id)
            cur = conn.execute(
                "INSERT OR IGNORE INTO investigation_event_evidence(event_id, evidence_key, evidence_type, role, relation_type, source, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, evidence_key, evidence_type, role, relation_type, source, rationale, _now()),
            )
            if cur.rowcount and invalidate:
                self._bump_event_revision(conn, task_id, event_id)
            conn.commit()
            return bool(cur.rowcount)

    def unlink_evidence_for_task(self, task_id: str, event_id: str, evidence_key: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM investigation_events WHERE task_id = ? AND id = ?", (task_id, event_id)).fetchone():
                raise KeyError(event_id)
            cur = conn.execute("DELETE FROM investigation_event_evidence WHERE event_id = ? AND evidence_key = ?", (event_id, evidence_key))
            if cur.rowcount:
                self._bump_event_revision(conn, task_id, event_id)
            conn.commit()
            return bool(cur.rowcount)

    def complete_analysis_bundle(self, analysis_id: str, description: Optional[str], summary: Optional[str], grounding_status: str, grounding_warnings: List[str], status: str, model: Optional[str], claims: List[Dict[str, Any]], entities: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM evidence_analysis_versions WHERE id = ?", (analysis_id,)).fetchone()
            if row is None or row["status"] != ANALYSIS_RUNNING:
                raise ValueError("analysis is not running")
            entity_ids: Dict[str, str] = {}
            for claim in claims:
                claim_id = _new_id()
                conn.execute("INSERT INTO evidence_analysis_claims(id, analysis_id, claim_text, claim_type, grounding_status, origin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (claim_id, analysis_id, claim["text"], claim["type"], claim["grounding_status"], claim["origin"], _now()))
                for evidence_key in claim.get("kept_refs", []):
                    conn.execute("INSERT OR IGNORE INTO claim_evidence(claim_id, evidence_key, relation) VALUES (?, ?, 'supports')", (claim_id, evidence_key))
            for entity in entities:
                entity_id = _new_id()
                entity_ids[entity["local_id"]] = entity_id
                conn.execute("INSERT INTO evidence_analysis_entities(id, analysis_id, entity_type, canonical_value, display_name) VALUES (?, ?, ?, ?, ?)", (entity_id, analysis_id, entity["type"], entity["value"], entity["value"]))
            for relation in relations:
                source_id, target_id = entity_ids.get(relation["source"]), entity_ids.get(relation["target"])
                if source_id and target_id:
                    conn.execute("INSERT INTO evidence_analysis_relations(id, analysis_id, source_entity_id, target_entity_id, relation_type, relation_kind) VALUES (?, ?, ?, ?, ?, ?)", (_new_id(), analysis_id, source_id, target_id, relation["type"], relation["kind"]))
            cur = conn.execute("UPDATE evidence_analysis_versions SET status = ?, description = ?, summary = ?, grounding_status = ?, grounding_warnings = ?, model = ?, completed_at = ? WHERE id = ? AND status = 'running'", (status, description, summary, grounding_status, json.dumps(grounding_warnings, ensure_ascii=False), model, _now(), analysis_id))
            if not cur.rowcount:
                raise ValueError("analysis completion conflict")
            conn.commit()

    def create_event_version(self, task_id: str, event_id: str, analyst_note_snapshot: Optional[str], input_analysis_ids: List[str], input_evidence_refs: List[str], input_hash: str, source_revision: int, included_review_pending: bool, prompt_version: str) -> Dict[str, Any]:
        version_id, now = _new_id(), _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM investigation_events WHERE task_id = ? AND id = ?", (task_id, event_id)).fetchone():
                raise KeyError(event_id)
            version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM investigation_event_versions WHERE task_id = ? AND event_id = ?", (task_id, event_id)).fetchone()["v"]
            conn.execute("INSERT INTO investigation_event_versions(id, task_id, event_id, version, analyst_note_snapshot, input_analysis_ids, input_evidence_refs, input_hash, source_revision, included_review_pending, prompt_version, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (version_id, task_id, event_id, version, analyst_note_snapshot, json.dumps(sorted(input_analysis_ids)), json.dumps(sorted(input_evidence_refs)), input_hash, source_revision, int(included_review_pending), prompt_version, EVENT_VERSION_QUEUED, now))
            conn.commit()
        return self.get_event_version(task_id, event_id, version_id)  # type: ignore[return-value]

    def get_event_version(self, task_id: str, event_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM investigation_event_versions WHERE task_id = ? AND event_id = ? AND id = ?", (task_id, event_id, version_id)).fetchone()
        return dict(row) if row else None

    def get_event_version_by_id(self, task_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM investigation_event_versions WHERE task_id = ? AND id = ?", (task_id, version_id)).fetchone()
        return dict(row) if row else None

    def list_event_versions(self, task_id: str, event_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM investigation_event_versions WHERE task_id = ? AND event_id = ? ORDER BY version DESC", (task_id, event_id)).fetchall()
        return [dict(row) for row in rows]

    def mark_event_version_running(self, task_id: str, event_id: str, version_id: str) -> None:
        with self._connect() as conn:
            cur = conn.execute("UPDATE investigation_event_versions SET status = ? WHERE task_id = ? AND event_id = ? AND id = ? AND status = ?", (EVENT_VERSION_RUNNING, task_id, event_id, version_id, EVENT_VERSION_QUEUED))
            if not cur.rowcount:
                raise ValueError("event refresh is not queued")

    def complete_event_version(self, task_id: str, event_id: str, version_id: str, title: str, summary: str, evidence_refs: List[str], grounding_status: str, grounding_warnings: List[str], status: str, model: Optional[str]) -> None:
        with self._connect() as conn:
            cur = conn.execute("UPDATE investigation_event_versions SET title = ?, summary = ?, evidence_refs = ?, grounding_status = ?, grounding_warnings = ?, status = ?, model = ?, completed_at = ? WHERE task_id = ? AND event_id = ? AND id = ? AND status = ?", (title, summary, json.dumps(sorted(evidence_refs)), grounding_status, json.dumps(grounding_warnings, ensure_ascii=False), status, model, _now(), task_id, event_id, version_id, EVENT_VERSION_RUNNING))
            if not cur.rowcount:
                raise ValueError("event refresh completion conflict")

    def complete_event_version_bundle(
        self, task_id: str, event_id: str, version_id: str, title: str,
        summary: str, evidence_refs: List[str], grounding_status: str,
        grounding_warnings: List[str], status: str, model: Optional[str],
        claims: List[Dict[str, Any]],
    ) -> None:
        """Atomically persist an Event Version and its immutable Claim bundle."""
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute(
                "SELECT input_evidence_refs, task_id, event_id FROM investigation_event_versions "
                "WHERE id = ? AND task_id = ? AND event_id = ? AND status = ?",
                (version_id, task_id, event_id, EVENT_VERSION_RUNNING),
            ).fetchone()
            if version is None:
                raise ValueError("event refresh completion conflict")
            allowed_refs = set(json.loads(version["input_evidence_refs"] or "[]"))
            normalized_evidence_refs = list(dict.fromkeys(evidence_refs))
            if any(ref not in allowed_refs for ref in normalized_evidence_refs):
                raise ValueError("event version evidence reference is outside version allowlist")
            for claim in claims:
                claim_id = _new_id()
                kept_refs = list(dict.fromkeys(claim.get("kept_refs", [])))
                relation = claim.get("relation", "supports")
                if relation not in ("supports", "contradicts"):
                    raise ValueError("event claim relation is invalid")
                if any(ref not in allowed_refs for ref in kept_refs):
                    raise ValueError("event claim reference is outside version allowlist")
                conn.execute(
                    "INSERT INTO event_claims(id, task_id, event_id, event_version_id, "
                    "claim_text, claim_type, status, grounding_status, grounding_warnings, "
                    "origin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (claim_id, task_id, event_id, version_id, claim["text"],
                     claim["type"], claim["status"], claim["grounding_status"],
                     json.dumps(claim.get("grounding_warnings", []), ensure_ascii=False),
                     claim.get("origin"), now),
                )
                for evidence_key in kept_refs:
                    conn.execute(
                        "INSERT INTO event_claim_evidence(claim_id, evidence_key, relation) "
                        "VALUES (?, ?, ?)",
                        (claim_id, evidence_key, relation),
                    )
            cur = conn.execute(
                "UPDATE investigation_event_versions SET title = ?, summary = ?, "
                "evidence_refs = ?, grounding_status = ?, grounding_warnings = ?, "
                "status = ?, model = ?, completed_at = ? WHERE id = ? AND task_id = ? "
                "AND event_id = ? AND status = ?",
                (title, summary, json.dumps(sorted(normalized_evidence_refs)), grounding_status,
                 json.dumps(grounding_warnings, ensure_ascii=False), status, model, now,
                 version_id, task_id, event_id, EVENT_VERSION_RUNNING),
            )
            if not cur.rowcount:
                raise ValueError("event refresh completion conflict")
            conn.commit()

    def _event_claims(self, conn: sqlite3.Connection, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        claims = [dict(row) for row in rows]
        for claim in claims:
            refs = conn.execute(
                "SELECT evidence_key, relation, rationale FROM event_claim_evidence "
                "WHERE claim_id = ? ORDER BY evidence_key",
                (claim["id"],),
            ).fetchall()
            claim["evidence_refs"] = [dict(ref) for ref in refs]
        return claims

    def list_event_claims(self, task_id: str, event_id: str, version_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM event_claims WHERE task_id = ? AND event_id = ? "
                "AND event_version_id = ? ORDER BY created_at, id",
                (task_id, event_id, version_id),
            ).fetchall()
            return self._event_claims(conn, rows)

    def effective_event_claims(self, task_id: str, event_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            event = conn.execute(
                "SELECT needs_refresh FROM investigation_events WHERE task_id = ? AND id = ?",
                (task_id, event_id),
            ).fetchone()
            version = select_effective_event_version(conn, task_id, event_id)
            if version is None or event is None or int(event["needs_refresh"] or 0) != 0:
                return []
            rows = conn.execute(
                "SELECT * FROM event_claims WHERE task_id = ? AND event_id = ? "
                "AND event_version_id = ? AND status = 'accepted' ORDER BY created_at, id",
                (task_id, event_id, version["id"]),
            ).fetchall()
            return self._event_claims(conn, rows)

    def _current_effective_event_version_id(
        self, conn: sqlite3.Connection, task_id: str, event_id: str
    ) -> Optional[str]:
        event = conn.execute(
            "SELECT needs_refresh FROM investigation_events WHERE task_id = ? AND id = ?",
            (task_id, event_id),
        ).fetchone()
        if event is None or int(event["needs_refresh"] or 0) != 0:
            return None
        version = select_effective_event_version(conn, task_id, event_id)
        return version["id"] if version else None

    def review_event_claim(
        self, task_id: str, event_id: str, version_id: str, claim_id: str,
        status: str,
    ) -> Dict[str, Any]:
        if status not in (EVENT_VERSION_ACCEPTED, EVENT_VERSION_REJECTED):
            raise ValueError("invalid event claim review status")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._current_effective_event_version_id(conn, task_id, event_id) != version_id:
                raise VersionConflict("event claim version is not current effective")
            claim = conn.execute(
                "SELECT * FROM event_claims WHERE id = ? AND task_id = ? "
                "AND event_id = ? AND event_version_id = ?",
                (claim_id, task_id, event_id, version_id),
            ).fetchone()
            if claim is None:
                raise KeyError(claim_id)
            if claim["status"] != EVENT_VERSION_REVIEW_PENDING:
                raise VersionConflict("event claim is not review pending")
            now = _now()
            cur = conn.execute(
                "UPDATE event_claims SET status = ?, accepted_at = ?, rejected_at = ? "
                "WHERE id = ? AND status = ?",
                (status, now if status == EVENT_VERSION_ACCEPTED else None,
                 now if status == EVENT_VERSION_REJECTED else None, claim_id,
                 EVENT_VERSION_REVIEW_PENDING),
            )
            if not cur.rowcount:
                raise VersionConflict("event claim review conflict")
            conn.commit()
        return next(
            claim for claim in self.list_event_claims(task_id, event_id, version_id)
            if claim["id"] == claim_id
        )

    def fail_event_version(self, task_id: str, event_id: str, version_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE investigation_event_versions SET status = ?, error_message = ?, completed_at = ? WHERE task_id = ? AND event_id = ? AND id = ? AND status IN (?, ?)", (EVENT_VERSION_FAILED, error, _now(), task_id, event_id, version_id, EVENT_VERSION_QUEUED, EVENT_VERSION_RUNNING))

    def accept_event_version(self, task_id: str, event_id: str, version_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute(
                "SELECT * FROM investigation_event_versions "
                "WHERE task_id = ? AND event_id = ? AND id = ?",
                (task_id, event_id, version_id),
            ).fetchone()
            event = conn.execute(
                "SELECT * FROM investigation_events WHERE task_id = ? AND id = ?",
                (task_id, event_id),
            ).fetchone()
            if version is None or event is None:
                raise KeyError(version_id)
            if version["status"] != EVENT_VERSION_REVIEW_PENDING:
                raise VersionConflict("event version is not acceptable")
            if version["source_revision"] != event["semantic_revision"]:
                raise VersionConflict("event version is stale")
            if version["grounding_status"] != GROUNDING_VALID:
                raise VersionConflict("event version is not acceptable")
            input_analysis_ids = _json_string_list(version["input_analysis_ids"])
            if input_analysis_ids is None:
                raise VersionConflict("event version input analysis binding is corrupt")
            allowed_statuses = (
                {ANALYSIS_ACCEPTED, ANALYSIS_REVIEW_PENDING}
                if int(version["included_review_pending"] or 0)
                else {ANALYSIS_ACCEPTED}
            )
            allowed_refs = _json_string_list(version["input_evidence_refs"])
            evidence_refs = _json_string_list(version["evidence_refs"])
            if allowed_refs is None or evidence_refs is None:
                raise VersionConflict("event version evidence binding is corrupt")
            if not set(evidence_refs).issubset(set(allowed_refs)):
                raise VersionConflict("event version evidence reference is outside allowlist")
            for analysis_id in input_analysis_ids:
                analysis = conn.execute(
                    "SELECT evidence_key, status FROM evidence_analysis_versions "
                    "WHERE id = ? AND task_id = ?",
                    (analysis_id, task_id),
                ).fetchone()
                if analysis is None or analysis["status"] not in allowed_statuses:
                    raise VersionConflict("event version input analysis is no longer usable")
                if analysis["evidence_key"] not in set(allowed_refs):
                    raise VersionConflict("event version input analysis is outside allowlist")
                if analysis["status"] == ANALYSIS_REVIEW_PENDING:
                    replacement = conn.execute(
                        "SELECT 1 FROM evidence_analysis_versions WHERE task_id = ? "
                        "AND evidence_key = ? AND status = ? LIMIT 1",
                        (task_id, analysis["evidence_key"], ANALYSIS_ACCEPTED),
                    ).fetchone()
                    if replacement:
                        raise VersionConflict("event version pending input was replaced")
            if not _event_version_inputs_admissible(conn, version, event):
                raise VersionConflict("event version inputs are no longer usable")
            current = select_effective_event_version(conn, task_id, event_id)
            if current is not None and current["id"] != version_id:
                raise VersionConflict("another effective event version already exists")
            conn.execute(
                "UPDATE investigation_event_versions SET status = ?, accepted_at = ? "
                "WHERE task_id = ? AND event_id = ? AND id = ? AND status = ?",
                (EVENT_VERSION_ACCEPTED, _now(), task_id, event_id, version_id,
                 EVENT_VERSION_REVIEW_PENDING),
            )
            if select_effective_event_version(conn, task_id, event_id) is None:
                raise VersionConflict("accepted event version is not effective")
            conn.execute(
                "UPDATE investigation_events SET needs_refresh = 0, updated_at = ? "
                "WHERE task_id = ? AND id = ?",
                (_now(), task_id, event_id),
            )
            conn.commit()
        return self.get_event_version(task_id, event_id, version_id)  # type: ignore[return-value]

    def reject_event_version(self, task_id: str, event_id: str, version_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE investigation_event_versions SET status = ? "
                "WHERE task_id = ? AND event_id = ? AND id = ? AND status = ?",
                (EVENT_VERSION_REJECTED, task_id, event_id, version_id,
                 EVENT_VERSION_REVIEW_PENDING),
            )
            if not cur.rowcount:
                raise KeyError(version_id)
            if select_effective_event_version(conn, task_id, event_id) is None:
                conn.execute(
                    "UPDATE investigation_events SET needs_refresh = 1, updated_at = ? "
                    "WHERE task_id = ? AND id = ?",
                    (_now(), task_id, event_id),
                )
            conn.commit()
        return self.get_event_version(task_id, event_id, version_id)  # type: ignore[return-value]

    def effective_event_version(self, task_id: str, event_id: str) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        with self._connect() as conn:
            accepted = select_effective_event_version(conn, task_id, event_id)
            pending = conn.execute(
                "SELECT * FROM investigation_event_versions WHERE task_id = ? "
                "AND event_id = ? AND status = ? ORDER BY version DESC, id DESC LIMIT 1",
                (task_id, event_id, EVENT_VERSION_REVIEW_PENDING),
            ).fetchone()
        return (dict(accepted) if accepted else None, dict(pending) if pending else None)

    def recover_interrupted_event_versions(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("UPDATE investigation_event_versions SET status = ?, error_message = 'Event refresh interrupted by service restart', completed_at = ? WHERE status IN (?, ?)", (EVENT_VERSION_FAILED, _now(), EVENT_VERSION_QUEUED, EVENT_VERSION_RUNNING))
            return cur.rowcount

    def invalidate_event_semantics(self, task_id: str, event_id: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._bump_event_revision(conn, task_id, event_id)
            conn.commit()

    def upsert_event_note_and_invalidate(
        self, task_id: str, event_id: str, content: str, author: Optional[str] = None
    ) -> Optional[str]:
        """Persist or remove Event context and atomically invalidate its semantic input."""
        content = content or ""
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM investigation_events WHERE task_id = ? AND id = ?",
                (task_id, event_id),
            ).fetchone() is None:
                raise KeyError(event_id)
            existing = conn.execute(
                "SELECT id, content FROM analyst_notes WHERE task_id = ? "
                "AND target_type = 'investigation_event' AND target_key = ?",
                (task_id, event_id),
            ).fetchone()
            note_id = existing["id"] if existing else None
            changed = bool(existing and existing["content"] != content)
            if existing and not content:
                conn.execute("DELETE FROM analyst_notes WHERE id = ?", (note_id,))
            elif existing and changed:
                conn.execute(
                    "UPDATE analyst_notes SET content = ?, author = ?, updated_at = ? WHERE id = ?",
                    (content, author, now, note_id),
                )
            elif not existing and content:
                note_id = _new_id()
                conn.execute(
                    "INSERT INTO analyst_notes(id, task_id, target_type, target_key, content, author, created_at, updated_at) "
                    "VALUES (?, ?, 'investigation_event', ?, ?, ?, ?, ?)",
                    (note_id, task_id, event_id, content, author, now, now),
                )
                changed = True
            if changed:
                self._bump_event_revision(conn, task_id, event_id)
            conn.commit()
        return note_id if content else None
