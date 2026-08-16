"""Read-only Investigation Overlay reader for the Graph facade (Phase C8b).

B2: constructing ``InvestigationRepository`` creates directories, migrates,
and self-heals the store, so the Graph GET path must never build one.  This
reader opens investigation.db strictly through a ``mode=ro`` URI plus
``PRAGMA query_only`` and only ever issues SELECTs.

B3: corruption, an unsupported schema version, or any read failure surfaces
as ``EvidenceStoreError`` so the caller fails closed -- an unreadable
authoritative store must never masquerade as "no Investigation findings".
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from ..evidence.exceptions import EvidenceStoreError
from .models import (
    AnalysisClaim,
    BoundAnalysisRef,
    ClaimGroundingStatus,
    ClaimType,
    ClusterSnapshotPayload,
    EventEvidenceLink,
    EventRefresh,
    EvidenceSnapshot,
    EvidenceSummary,
    FileSnapshotPayload,
    InvestigationEvent,
    InvestigationEventVersion,
    ReportEvidenceItem,
    ReportEvidenceStatus,
    SecondaryAnalysis,
    SelectedAnalysisRef,
)
from .repository import InvestigationRepository, SUPPORTED_SCHEMA_VERSION


@dataclass(frozen=True)
class GraphAnalysisSelection:
    """The one analysis version selected for one evidence_key (G5).

    ``review_state`` is ``"accepted"`` when any accepted version exists
    (latest accepted wins, G3) and ``"review_pending"`` only as the explicit
    unconfirmed fallback (G4).  It is deliberately NOT a generic
    "latest effective" abstraction.
    """

    evidence_key: str
    analysis_id: str
    version: int
    review_state: str
    summary: str | None


@dataclass(frozen=True)
class OverlayReadResult:
    """The task-scoped overlay source rows read in one pass."""

    events: tuple[InvestigationEvent, ...] = ()
    event_links: tuple[EventEvidenceLink, ...] = ()
    selections: tuple[GraphAnalysisSelection, ...] = ()
    claims: tuple[AnalysisClaim, ...] = ()
    evidence_types: dict[str, str] = field(default_factory=dict)


# Single source of truth for the current-narrative projection: reuse the
# repository's frozen read SQL instead of duplicating it here.
_EVENT_READ_SQL = InvestigationRepository._EVENT_READ_SQL

# G3/G5 selection: per evidence_key exactly one row -- the latest accepted
# version, or (only when no accepted version exists) the latest
# review_pending version.  Rejected/invalid/failed/queued/running rows never
# participate.  analysis_id DESC only breaks ties between impossible
# same-version rows, keeping the output deterministic.
_ANALYSIS_WINDOW_SQL = """
    SELECT evidence_key, analysis_id, version, status, summary,
           ROW_NUMBER() OVER (
               PARTITION BY evidence_key
               ORDER BY CASE status WHEN 'accepted' THEN 0 ELSE 1 END,
                        version DESC,
                        analysis_id DESC
           ) AS rn
    FROM secondary_analyses
    WHERE task_id = ? AND status IN ('accepted', 'review_pending')
"""

_SELECTED_ANALYSES_SQL = (
    f"SELECT analysis_id FROM ({_ANALYSIS_WINDOW_SQL}) WHERE rn = 1"
)

_SELECTED_ROWS_SQL = (
    "SELECT evidence_key, analysis_id, version, status, summary "
    f"FROM ({_ANALYSIS_WINDOW_SQL}) WHERE rn = 1 "
    "ORDER BY evidence_key"
)

# Claims/refs carry no task_id column; task scoping flows exclusively through
# the selected-analyses subquery above.
_SELECTED_CLAIMS_SQL = f"""
    SELECT c.claim_id, c.analysis_id, c.claim_index, c.claim_type,
           c.claim_text, c.grounding_status, c.warning_json, c.created_at
    FROM analysis_claims c
    WHERE c.analysis_id IN ({_SELECTED_ANALYSES_SQL})
    ORDER BY c.analysis_id, c.claim_index
"""

_SELECTED_CLAIM_REFS_SQL = f"""
    SELECT r.claim_id, r.evidence_key
    FROM claim_evidence_refs r
    JOIN analysis_claims c ON c.claim_id = r.claim_id
    WHERE c.analysis_id IN ({_SELECTED_ANALYSES_SQL})
    ORDER BY r.claim_id, r.evidence_key
"""


class InvestigationGraphReader:
    """Task-scoped, strictly read-only projection of overlay source rows."""

    def __init__(self, investigation_db_path, task_id: str):
        self._db_path = Path(investigation_db_path)
        self._task_id = task_id

    def _connect(self) -> sqlite3.Connection:
        # mode=ro refuses to create or write the file; query_only is
        # belt-and-braces on top of it.  The path is server-trusted, but is
        # still URI-quoted so '?'/'#' in a directory name cannot alter the URI.
        uri = f"file:{quote(str(self._db_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def read(self) -> OverlayReadResult:
        return self._run(self._read_with_conn)

    def list_evidence(self) -> list[EvidenceSummary]:
        """Every captured evidence of the task plus its C8b selection state."""
        return self._run(self._list_evidence_with_conn)

    def latest_snapshot(self, evidence_key: str) -> EvidenceSnapshot | None:
        """The single captured snapshot of one evidence (UNIQUE(task_id,
        evidence_key)), or ``None`` when this evidence was never captured."""
        return self._run(lambda conn: self._latest_snapshot_with_conn(conn, evidence_key))

    def claims_for_analysis(self, analysis_id: str) -> tuple[AnalysisClaim, ...] | None:
        """Exact persisted claims of one analysis, or ``None`` when the
        analysis_id does not belong to this task."""
        return self._run(lambda conn: self._claims_with_conn(conn, analysis_id))

    # -- Strict Workbench reads (C10 §14/E13) ------------------------------
    # These projections exist so the events/analyses GET services never
    # construct InvestigationRepository: its constructor mkdir/migrates/
    # self-heals (and initializes a fresh store when the file is absent),
    # which no GET may do. All methods here open mode=ro + query_only and
    # fail closed on any non-v7 store.

    def list_events(self, *, needs_refresh: bool | None = None) -> list[InvestigationEvent]:
        def read(conn: sqlite3.Connection) -> list[InvestigationEvent]:
            sql = _EVENT_READ_SQL
            params: list = [self._task_id]
            if needs_refresh is not None:
                sql += " AND e.needs_refresh = ?"
                params.append(1 if needs_refresh else 0)
            sql += " ORDER BY e.created_at"
            return [self._row_to_event(r) for r in conn.execute(sql, params)]

        return self._run(read)

    def get_event(self, event_id: str) -> InvestigationEvent | None:
        def read(conn: sqlite3.Connection) -> InvestigationEvent | None:
            row = conn.execute(
                _EVENT_READ_SQL + " AND e.event_id = ?",
                [self._task_id, event_id],
            ).fetchone()
            return self._row_to_event(row) if row is not None else None

        return self._run(read)

    def list_event_versions(
        self, event_id: str
    ) -> list[InvestigationEventVersion]:
        def read(conn: sqlite3.Connection) -> list[InvestigationEventVersion]:
            rows = conn.execute(
                "SELECT * FROM investigation_event_versions "
                "WHERE task_id = ? AND event_id = ? ORDER BY version",
                [self._task_id, event_id],
            ).fetchall()
            return [
                InvestigationEventVersion(
                    task_id=r["task_id"],
                    event_id=r["event_id"],
                    version=r["version"],
                    title=r["title"],
                    summary=r["summary"],
                    created_at=r["created_at"],
                    created_by=r["created_by"],
                )
                for r in rows
            ]

        return self._run(read)

    def list_event_evidence(self, event_id: str) -> list[EventEvidenceLink]:
        def read(conn: sqlite3.Connection) -> list[EventEvidenceLink]:
            rows = conn.execute(
                "SELECT * FROM investigation_event_evidence "
                "WHERE task_id = ? AND event_id = ? ORDER BY linked_at, evidence_key",
                [self._task_id, event_id],
            ).fetchall()
            return [
                EventEvidenceLink(
                    task_id=r["task_id"],
                    event_id=r["event_id"],
                    evidence_key=r["evidence_key"],
                    linked_at=r["linked_at"],
                    linked_by=r["linked_by"],
                )
                for r in rows
            ]

        return self._run(read)

    def get_event_refresh(self, refresh_id: str) -> EventRefresh | None:
        def read(conn: sqlite3.Connection) -> EventRefresh | None:
            row = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id = ? AND refresh_id = ?",
                [self._task_id, refresh_id],
            ).fetchone()
            return (
                InvestigationRepository._row_to_refresh(row)
                if row is not None
                else None
            )

        return self._run(read)

    def list_event_refreshes(self, event_id: str) -> list[EventRefresh]:
        def read(conn: sqlite3.Connection) -> list[EventRefresh]:
            rows = conn.execute(
                "SELECT * FROM investigation_event_refreshes "
                "WHERE task_id = ? AND event_id = ? ORDER BY created_at",
                [self._task_id, event_id],
            ).fetchall()
            return [InvestigationRepository._row_to_refresh(r) for r in rows]

        return self._run(read)

    def get_analysis(self, analysis_id: str) -> SecondaryAnalysis | None:
        """Exact analysis of THIS task, or ``None`` (task-scoped by design)."""

        def read(conn: sqlite3.Connection) -> SecondaryAnalysis | None:
            row = conn.execute(
                "SELECT * FROM secondary_analyses "
                "WHERE task_id = ? AND analysis_id = ?",
                [self._task_id, analysis_id],
            ).fetchone()
            return (
                InvestigationRepository._row_to_analysis(row)
                if row is not None
                else None
            )

        return self._run(read)

    def list_analyses(self, evidence_key: str) -> list[SecondaryAnalysis]:
        def read(conn: sqlite3.Connection) -> list[SecondaryAnalysis]:
            rows = conn.execute(
                "SELECT * FROM secondary_analyses "
                "WHERE task_id = ? AND evidence_key = ? ORDER BY version DESC",
                [self._task_id, evidence_key],
            ).fetchall()
            return [InvestigationRepository._row_to_analysis(r) for r in rows]

        return self._run(read)

    # -- Report Evidence reads (Phase R1) ------------------------------------
    # Exact frozen bindings only: the bound analysis is joined from the
    # immutable secondary_analyses row of the PERSISTED analysis_id -- never
    # get_latest_accepted_analysis.  newer_accepted_available is a read-time
    # hint (an accepted version exists that is not the frozen binding); it
    # never changes the binding and rebinding stays an explicit PUT.

    _REPORT_EVIDENCE_SELECT_SQL = """
        SELECT re.task_id, re.evidence_key, re.report_status, re.analysis_id,
               re.added_by, re.created_at, re.updated_at, re.updated_by,
               sa.version AS bound_version,
               sa.decided_by AS bound_decided_by,
               sa.decided_at AS bound_decided_at,
               sa.summary AS bound_summary,
               (SELECT MAX(sa2.version) FROM secondary_analyses sa2
                WHERE sa2.task_id = re.task_id
                  AND sa2.evidence_key = re.evidence_key
                  AND sa2.status = 'accepted') AS max_accepted_version
        FROM report_evidence re
        LEFT JOIN secondary_analyses sa
            ON sa.task_id = re.task_id AND sa.analysis_id = re.analysis_id
        WHERE re.task_id = ?
    """

    def list_report_evidence(self) -> list[ReportEvidenceItem]:
        def read(conn: sqlite3.Connection) -> list[ReportEvidenceItem]:
            if not self._report_evidence_table_exists(conn):
                return []
            rows = conn.execute(
                self._REPORT_EVIDENCE_SELECT_SQL + " ORDER BY re.evidence_key",
                [self._task_id],
            ).fetchall()
            return [self._row_to_report_item(r) for r in rows]

        return self._run(read)

    def get_report_evidence(self, evidence_key: str) -> ReportEvidenceItem | None:
        def read(conn: sqlite3.Connection) -> ReportEvidenceItem | None:
            if not self._report_evidence_table_exists(conn):
                return None
            row = conn.execute(
                self._REPORT_EVIDENCE_SELECT_SQL + " AND re.evidence_key = ?",
                [self._task_id, evidence_key],
            ).fetchone()
            return self._row_to_report_item(row) if row is not None else None

        return self._run(read)

    @staticmethod
    def _report_evidence_table_exists(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
        ).fetchone() is not None

    @staticmethod
    def _row_to_report_item(row: sqlite3.Row) -> ReportEvidenceItem:
        bound = None
        if row["analysis_id"] is not None:
            bound = BoundAnalysisRef(
                analysis_id=row["analysis_id"],
                version=row["bound_version"],
                decided_by=row["bound_decided_by"],
                decided_at=row["bound_decided_at"],
                summary=row["bound_summary"],
            )
        max_accepted = row["max_accepted_version"]
        newer_available = max_accepted is not None and (
            row["bound_version"] is None or max_accepted > row["bound_version"]
        )
        return ReportEvidenceItem(
            task_id=row["task_id"],
            evidence_key=row["evidence_key"],
            report_status=ReportEvidenceStatus(row["report_status"]),
            analysis_id=row["analysis_id"],
            added_by=row["added_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            bound_analysis=bound,
            newer_accepted_available=newer_available,
        )

    def _run(self, read_fn):
        try:
            with contextlib.closing(self._connect()) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version != SUPPORTED_SCHEMA_VERSION:
                    # B3: an unsupported store fails closed, never partial data.
                    raise EvidenceStoreError(
                        "investigation graph store schema is unsupported"
                    )
                return read_fn(conn)
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation graph store is unavailable"
            ) from exc

    def _read_with_conn(self, conn: sqlite3.Connection) -> OverlayReadResult:
        events = tuple(
            self._row_to_event(row)
            for row in conn.execute(
                _EVENT_READ_SQL + " ORDER BY e.event_id", [self._task_id]
            )
        )
        event_links = tuple(
            EventEvidenceLink(
                task_id=row["task_id"],
                event_id=row["event_id"],
                evidence_key=row["evidence_key"],
                linked_at=row["linked_at"],
                linked_by=row["linked_by"],
            )
            for row in conn.execute(
                "SELECT task_id, event_id, evidence_key, linked_at, linked_by "
                "FROM investigation_event_evidence WHERE task_id = ? "
                "ORDER BY event_id, evidence_key, linked_at",
                [self._task_id],
            )
        )
        selections = tuple(
            GraphAnalysisSelection(
                evidence_key=row["evidence_key"],
                analysis_id=row["analysis_id"],
                version=row["version"],
                review_state=(
                    "accepted"
                    if row["status"] == "accepted"
                    else "review_pending"
                ),
                summary=row["summary"],
            )
            for row in conn.execute(_SELECTED_ROWS_SQL, [self._task_id])
        )

        refs: dict[str, list[str]] = {}
        for row in conn.execute(_SELECTED_CLAIM_REFS_SQL, [self._task_id]):
            refs.setdefault(row["claim_id"], []).append(row["evidence_key"])
        claims = tuple(
            self._row_to_claim(row, tuple(refs.get(row["claim_id"], ())))
            for row in conn.execute(_SELECTED_CLAIMS_SQL, [self._task_id])
        )

        evidence_types = {
            row["evidence_key"]: row["evidence_type"]
            for row in conn.execute(
                "SELECT evidence_key, evidence_type FROM evidence_snapshots "
                "WHERE task_id = ?",
                [self._task_id],
            )
        }
        return OverlayReadResult(
            events=events,
            event_links=event_links,
            selections=selections,
            claims=claims,
            evidence_types=evidence_types,
        )

    # -- Workbench read projections (C9a) ------------------------------------

    def _list_evidence_with_conn(
        self, conn: sqlite3.Connection
    ) -> list[EvidenceSummary]:
        selections = {
            row["evidence_key"]: SelectedAnalysisRef(
                evidence_key=row["evidence_key"],
                analysis_id=row["analysis_id"],
                version=row["version"],
                review_state=(
                    "accepted"
                    if row["status"] == "accepted"
                    else "review_pending"
                ),
                summary=row["summary"],
            )
            for row in conn.execute(_SELECTED_ROWS_SQL, [self._task_id])
        }
        return [
            EvidenceSummary(
                task_id=self._task_id,
                evidence_key=row["evidence_key"],
                evidence_type=row["evidence_type"],
                captured_at=row["captured_at"],
                selected_analysis=selections.get(row["evidence_key"]),
            )
            for row in conn.execute(
                "SELECT evidence_key, evidence_type, captured_at "
                "FROM evidence_snapshots WHERE task_id = ? "
                "ORDER BY evidence_key",
                [self._task_id],
            )
        ]

    def _latest_snapshot_with_conn(
        self, conn: sqlite3.Connection, evidence_key: str
    ) -> EvidenceSnapshot | None:
        # evidence_snapshots enforces UNIQUE(task_id, evidence_key): there is
        # at most one row, so id DESC only keeps the statement deterministic.
        row = conn.execute(
            "SELECT id, task_id, evidence_key, evidence_type, snapshot_json, "
            "captured_at FROM evidence_snapshots "
            "WHERE task_id = ? AND evidence_key = ? ORDER BY id DESC LIMIT 1",
            [self._task_id, evidence_key],
        ).fetchone()
        if row is None:
            return None
        evidence_type = row["evidence_type"]
        try:
            data = json.loads(row["snapshot_json"])
        except (ValueError, TypeError) as exc:
            raise EvidenceStoreError(
                f"snapshot_json is corrupt for id={row['id']}: {exc}"
            ) from exc
        if evidence_type == "file":
            payload = FileSnapshotPayload.model_validate(data)
        elif evidence_type == "cluster":
            payload = ClusterSnapshotPayload.model_validate(data)
        else:  # pragma: no cover - guarded by the table CHECK
            raise EvidenceStoreError(
                f"unknown evidence_type {evidence_type!r} for id={row['id']}"
            )
        return EvidenceSnapshot(
            task_id=row["task_id"],
            evidence_key=row["evidence_key"],
            evidence_type=evidence_type,
            captured_at=row["captured_at"],
            payload=payload,
            snapshot_id=row["id"],
        )

    def _claims_with_conn(
        self, conn: sqlite3.Connection, analysis_id: str
    ) -> tuple[AnalysisClaim, ...] | None:
        owned = conn.execute(
            "SELECT 1 FROM secondary_analyses WHERE task_id = ? AND analysis_id = ?",
            [self._task_id, analysis_id],
        ).fetchone()
        if owned is None:
            return None
        refs: dict[str, list[str]] = {}
        for row in conn.execute(
            "SELECT r.claim_id, r.evidence_key FROM claim_evidence_refs r "
            "JOIN analysis_claims c ON c.claim_id = r.claim_id "
            "WHERE c.analysis_id = ? ORDER BY r.claim_id, r.evidence_key",
            [analysis_id],
        ):
            refs.setdefault(row["claim_id"], []).append(row["evidence_key"])
        return tuple(
            self._row_to_claim(row, tuple(refs.get(row["claim_id"], ())))
            for row in conn.execute(
                "SELECT claim_id, analysis_id, claim_index, claim_type, "
                "claim_text, grounding_status, warning_json, created_at "
                "FROM analysis_claims WHERE analysis_id = ? ORDER BY claim_index",
                [analysis_id],
            )
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> InvestigationEvent:
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

    @staticmethod
    def _row_to_claim(row: sqlite3.Row, evidence_refs: tuple[str, ...]) -> AnalysisClaim:
        warning = None
        if row["warning_json"]:
            try:
                warning = json.loads(row["warning_json"])
            except (ValueError, TypeError):
                warning = None
        return AnalysisClaim(
            claim_id=row["claim_id"],
            analysis_id=row["analysis_id"],
            claim_index=row["claim_index"],
            claim_type=ClaimType(row["claim_type"]),
            claim_text=row["claim_text"],
            grounding_status=ClaimGroundingStatus(row["grounding_status"]),
            warnings=warning,
            evidence_refs=evidence_refs,
            created_at=row["created_at"],
        )


__all__ = [
    "GraphAnalysisSelection",
    "InvestigationGraphReader",
    "OverlayReadResult",
]
