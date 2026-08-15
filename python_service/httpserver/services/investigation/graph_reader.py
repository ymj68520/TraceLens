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
    ClaimGroundingStatus,
    ClaimType,
    EventEvidenceLink,
    InvestigationEvent,
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
        try:
            with contextlib.closing(self._connect()) as conn:
                return self._read_with_conn(conn)
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation graph store is unavailable"
            ) from exc

    def _read_with_conn(self, conn: sqlite3.Connection) -> OverlayReadResult:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SUPPORTED_SCHEMA_VERSION:
            # B3: an unsupported store fails closed, never a partial overlay.
            raise EvidenceStoreError(
                "investigation graph store schema is unsupported"
            )

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
