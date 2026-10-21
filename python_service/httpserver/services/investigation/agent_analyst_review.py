"""Agent Analyst Review & Investigation Integration Service (RCA-2A.20).

Provides the authoritative human analyst review boundary for TraceLens Agent v0.
Guarantees:
  1. Human-only review authority: agent pipelines only create review_pending candidates.
  2. Immutability & Epistemic Type Preservation: HYPOTHESIS never becomes FACT.
  3. Evidence Provenance Verification: Every evidence reference must canonically resolve.
  4. Durable, Append-Only Review History: Enforced by SQLite triggers.
  5. Concurrency & Idempotency: Atomic SQLite claims, exact replays return 200, conflicts 409.
  6. Downstream Separation: 0 auto-finalizations, 0 auto report evidence admissions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.resolver import EvidenceResolver
from .agent_findings import (
    INVESTIGATION_FINDING_VERSION,
    FindingReviewService,
    InvestigationFindingV1,
    REVIEW_ACCEPTED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
)
from .agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    canonical_state_json,
)
from .agent_specialist_result import AssertionClass
from .agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    working_state_from_json,
)
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository

logger = logging.getLogger(__name__)

REVIEW_SERVICE_VERSION = "agent-analyst-review:v1"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReviewConflictError(Exception):
    """Raised on stale candidate, revision mismatch, concurrent claim, or idempotent conflict."""


class EvidenceProvenanceError(Exception):
    """Raised when evidence references fail canonical task-scoped resolution."""


class FactPromotionBlockedError(Exception):
    """Raised when an ungrounded or hypothesis assertion attempts unauthorized promotion to FACT."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class ReviewDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReviewCandidateProjection(BaseModel):
    """Normalized, read-only projection of a review-pending or reviewed candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    target_type: str  # "finding" | "hypothesis"
    target_id: str
    claim_type: str  # "FACT" | "INFERENCE" | "HYPOTHESIS"
    content: str
    evidence_refs: tuple[str, ...]
    source_revision: int
    source_integration_id: Optional[str] = None
    grounding_status: str  # "grounded" | "ungrounded"
    review_status: str  # "review_pending" | "accepted" | "rejected"
    candidate_hash: str
    created_at: str
    reviewed_at: Optional[str] = None
    reviewer: Optional[str] = None
    review_note: Optional[str] = None


class ReviewDecisionRequest(BaseModel):
    """Explicit mutation command submitted by an analyst."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    investigation_id: Optional[str] = None
    review_target_id: str = Field(min_length=1)
    expected_source_revision: int = Field(ge=1)
    expected_candidate_hash: str = Field(min_length=1)
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    note: Optional[str] = Field(default=None, max_length=4000)
    requested_assertion_class: Optional[str] = Field(default=None, max_length=64)


class ReviewDecisionOutcome(BaseModel):
    """Auditable result of an explicit analyst review action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_id: str
    request_id: str
    task_id: str
    investigation_id: str
    target_id: str
    target_type: str
    decision: str
    status: str
    accepted_finding_id: Optional[str]
    epistemic_type: str
    candidate_hash: str
    reviewed_at: str
    reviewer: str
    note: Optional[str] = None


class ReviewHistoryItem(BaseModel):
    """Append-only review history row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_id: str
    task_id: str
    investigation_id: str
    finding_id: str
    decision: str
    reviewer: str
    note: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Hash Helper
# ---------------------------------------------------------------------------


def compute_candidate_hash(
    target_type: str,
    target_id: str,
    claim_type: str,
    text: str,
    evidence_refs: Sequence[str],
) -> str:
    """Canonical content hash for candidate snapshot verification."""
    payload = {
        "target_type": str(target_type),
        "target_id": str(target_id),
        "claim_type": str(claim_type),
        "text": str(text),
        "evidence_refs": sorted(str(r) for r in evidence_refs),
    }
    return hashlib.sha256(canonical_state_json(payload).encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# AgentAnalystReviewService
# ---------------------------------------------------------------------------


class AgentAnalystReviewService:
    """Application service for Agent Analyst Review and Investigation Integration."""

    def __init__(self, cpp_backend, settings=None):
        self._cpp_backend = cpp_backend
        self._settings = settings
        self._finding_review_service = FindingReviewService()

    async def _resolve_task_and_db(
        self, task_id: str, *, allow_missing_db: bool = False
    ) -> tuple[dict[str, Any], Path]:
        """Resolves task and validates database path fail-closed."""
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError(f"task not found: {task_id}")
        if not task.get("output_files_db") and not task.get("output_events_db"):
            raise EvidenceNotFoundError(f"task not found: {task_id}")
        db_path = investigation_db_path_for_task(task)
        if not db_path.exists() and not allow_missing_db:
            raise EvidenceNotFoundError(f"investigation database not found for task {task_id}")
        return task, db_path

    def _open_runtime(self, db_path: Path, task_id: str) -> AgentRuntimeRepository:
        repo = InvestigationRepository(db_path, task_id)
        return AgentRuntimeRepository(repo)

    def _ensure_review_tables(self, conn: sqlite3.Connection) -> None:
        """Ensure review execution idempotency tracking table exists."""
        sql = """
        CREATE TABLE IF NOT EXISTS agent_review_executions (
            execution_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            investigation_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            review_target_id TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('claimed','completed','failed','conflict')),
            review_outcome_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, request_id)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_review_executions_active
        ON agent_review_executions(task_id) WHERE status IN ('claimed');
        """
        conn.executescript(sql)

    # -----------------------------------------------------------------------
    # Query API (Strictly Read-Only: 0 LLM calls, 0 writes, 0 mutations)
    # -----------------------------------------------------------------------

    async def list_candidates(
        self, task_id: str, investigation_id: Optional[str] = None
    ) -> list[ReviewCandidateProjection]:
        """Read all review candidates from SQLite."""
        _, db_path = await self._resolve_task_and_db(task_id, allow_missing_db=True)
        if not db_path.exists():
            return []
        return await asyncio.to_thread(
            self._sync_list_candidates, db_path, task_id, investigation_id
        )

    def _sync_list_candidates(
        self, db_path: Path, task_id: str, investigation_id: Optional[str]
    ) -> list[ReviewCandidateProjection]:
        runtime = self._open_runtime(db_path, task_id)
        inv_id = investigation_id
        if not inv_id:
            invs = runtime.list_investigations()
            if not invs:
                return []
            inv_id = invs[0].investigation_id

        latest = runtime.get_latest_working_state(inv_id)
        source_rev = latest.revision if latest else 1

        candidates: list[ReviewCandidateProjection] = []
        seen_target_ids: set[str] = set()

        # 1. Existing investigation_findings rows
        with runtime._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM investigation_findings WHERE task_id = ? AND investigation_id = ? ORDER BY finding_row_id ASC",
                [task_id, inv_id],
            ).fetchall()
            for r in rows:
                f_id = r["finding_id"]
                seen_target_ids.add(f_id)
                ev_refs = []
                if r["evidence_refs_json"]:
                    try:
                        ev_refs = json.loads(r["evidence_refs_json"]).get("refs", [])
                    except Exception:
                        pass
                c_hash = compute_candidate_hash(
                    "finding", f_id, r["assertion_class"], r["text"], ev_refs
                )
                candidates.append(
                    ReviewCandidateProjection(
                        candidate_id=f_id,
                        target_type="finding",
                        target_id=f_id,
                        claim_type=r["assertion_class"],
                        content=r["text"],
                        evidence_refs=tuple(ev_refs),
                        source_revision=source_rev,
                        source_integration_id=r["disposition_id"],
                        grounding_status="grounded" if r["grounding_id"] else "ungrounded",
                        review_status=r["status"],
                        candidate_hash=c_hash,
                        created_at=r["created_at"],
                        reviewed_at=r["reviewed_at"],
                        reviewer=r["reviewer"],
                        review_note=r["review_note"],
                    )
                )

        # 2. AgentWorkingStateV1 Hypotheses (if not already represented in findings)
        if latest and latest.state:
            state = working_state_from_json(task_id, inv_id, latest.state)
            for h in state.hypotheses:
                h_target_id = h.hypothesis_id
                hyp_finding_id = f"finding:hyp_{h_target_id}"
                if h_target_id in seen_target_ids or hyp_finding_id in seen_target_ids:
                    continue
                ev_refs = list(h.supporting_refs)
                c_hash = compute_candidate_hash(
                    "hypothesis", h_target_id, "HYPOTHESIS", h.text, ev_refs
                )
                candidates.append(
                    ReviewCandidateProjection(
                        candidate_id=h_target_id,
                        target_type="hypothesis",
                        target_id=h_target_id,
                        claim_type="HYPOTHESIS",
                        content=h.text,
                        evidence_refs=tuple(ev_refs),
                        source_revision=source_rev,
                        source_integration_id=None,
                        grounding_status="grounded" if ev_refs else "ungrounded",
                        review_status="review_pending",
                        candidate_hash=c_hash,
                        created_at=latest.created_at,
                    )
                )

        return candidates

    async def get_candidate(
        self, task_id: str, candidate_id: str, investigation_id: Optional[str] = None
    ) -> ReviewCandidateProjection:
        """Retrieve a specific candidate by id."""
        candidates = await self.list_candidates(task_id, investigation_id)
        for c in candidates:
            if c.candidate_id == candidate_id or c.target_id == candidate_id:
                return c
        raise EvidenceNotFoundError(f"review candidate not found: {candidate_id}")

    async def get_history(
        self,
        task_id: str,
        candidate_id: Optional[str] = None,
        investigation_id: Optional[str] = None,
    ) -> list[ReviewHistoryItem]:
        """Query append-only review history."""
        _, db_path = await self._resolve_task_and_db(task_id, allow_missing_db=True)
        if not db_path.exists():
            return []
        return await asyncio.to_thread(
            self._sync_get_history, db_path, task_id, candidate_id, investigation_id
        )

    def _sync_get_history(
        self,
        db_path: Path,
        task_id: str,
        candidate_id: Optional[str],
        investigation_id: Optional[str],
    ) -> list[ReviewHistoryItem]:
        runtime = self._open_runtime(db_path, task_id)
        inv_id = investigation_id
        if not inv_id:
            invs = runtime.list_investigations()
            if not invs:
                return []
            inv_id = invs[0].investigation_id

        with runtime._connect() as conn:
            conn.row_factory = sqlite3.Row
            if candidate_id:
                target_finding_id = candidate_id
                if not target_finding_id.startswith("finding:"):
                    target_finding_id = f"finding:hyp_{candidate_id}"
                rows = conn.execute(
                    "SELECT * FROM investigation_finding_reviews WHERE task_id = ? AND investigation_id = ? AND (finding_id = ? OR finding_id = ?) ORDER BY review_row_id ASC",
                    [task_id, inv_id, candidate_id, target_finding_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM investigation_finding_reviews WHERE task_id = ? AND investigation_id = ? ORDER BY review_row_id ASC",
                    [task_id, inv_id],
                ).fetchall()

            return [
                ReviewHistoryItem(
                    review_id=r["review_id"],
                    task_id=r["task_id"],
                    investigation_id=r["investigation_id"],
                    finding_id=r["finding_id"],
                    decision=r["decision"],
                    reviewer=r["reviewer"],
                    note=r["note"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # -----------------------------------------------------------------------
    # Explicit Review Mutation API
    # -----------------------------------------------------------------------

    async def submit_review(
        self, task_id: str, request: ReviewDecisionRequest
    ) -> ReviewDecisionOutcome:
        """Record one explicit analyst decision for a review candidate."""
        task, db_path = await self._resolve_task_and_db(task_id)
        runtime = self._open_runtime(db_path, task_id)

        inv_id = request.investigation_id
        if not inv_id:
            invs = runtime.list_investigations()
            if not invs:
                raise EvidenceNotFoundError(f"no investigation found for task {task_id}")
            inv_id = invs[0].investigation_id

        if request.task_id and request.task_id != task_id:
            raise ReviewConflictError(
                f"task_id mismatch: url task_id {task_id!r} != request task_id {request.task_id!r}"
            )

        # 1. Fetch current candidate (read-only pre-flight)
        candidate = await self.get_candidate(task_id, request.review_target_id, inv_id)

        # 2. Candidate hash & revision staleness verification
        if candidate.candidate_hash != request.expected_candidate_hash:
            raise ReviewConflictError(
                f"stale candidate: hash mismatch (expected {request.expected_candidate_hash}, got {candidate.candidate_hash})"
            )
        if candidate.source_revision != request.expected_source_revision:
            raise ReviewConflictError(
                f"working state revision mismatch (expected {request.expected_source_revision}, got {candidate.source_revision})"
            )

        if request.decision == ReviewDecision.ACCEPTED:
            # 3. Grounding & Evidence Provenance Verification
            resolver = EvidenceResolver(self._cpp_backend)
            for ref in candidate.evidence_refs:
                if not ref or ref.startswith("analyst_note:") or ref.startswith("summary:") or ref.startswith("note:"):
                    raise EvidenceProvenanceError(
                        f"invalid evidence reference: analyst note/summary cannot be evidence ({ref!r})"
                    )
                try:
                    await resolver.resolve_evidence(task_id, ref)
                except Exception as exc:
                    raise EvidenceProvenanceError(
                        f"evidence reference {ref!r} could not be resolved in task scope: {exc}"
                    ) from exc

            # 4. Epistemic Type Preservation: HYPOTHESIS must NEVER become FACT
            if (
                request.requested_assertion_class
                and request.requested_assertion_class.upper() == "FACT"
                and candidate.claim_type != "FACT"
            ):
                raise FactPromotionBlockedError(
                    "cannot promote HYPOTHESIS or INFERENCE to FACT: epistemic types are immutable"
                )

            if candidate.claim_type == "FACT":
                if not candidate.evidence_refs or candidate.grounding_status == "ungrounded":
                    raise FactPromotionBlockedError(
                        "unsupported FACT promotion: FACT claims require grounded evidence"
                    )
                target_assertion_class = AssertionClass.FACT
            elif candidate.claim_type == "HYPOTHESIS":
                target_assertion_class = AssertionClass.HYPOTHESIS
            elif candidate.claim_type == "INFERENCE":
                target_assertion_class = AssertionClass.INFERENCE
            else:
                target_assertion_class = AssertionClass(candidate.claim_type)
        else:
            # Rejection preserves existing assertion class
            try:
                target_assertion_class = AssertionClass(candidate.claim_type)
            except Exception:
                target_assertion_class = AssertionClass.HYPOTHESIS

        # 5. Atomic Execution & Idempotency Locking
        return await asyncio.to_thread(
            self._sync_submit_review,
            db_path,
            task_id,
            inv_id,
            request,
            candidate,
            target_assertion_class,
        )

    def _sync_submit_review(
        self,
        db_path: Path,
        task_id: str,
        inv_id: str,
        request: ReviewDecisionRequest,
        candidate: ReviewCandidateProjection,
        target_assertion_class: AssertionClass,
    ) -> ReviewDecisionOutcome:
        runtime = self._open_runtime(db_path, task_id)

        fingerprint = hashlib.sha256(
            canonical_state_json({
                "task_id": task_id,
                "investigation_id": inv_id,
                "review_target_id": request.review_target_id,
                "expected_source_revision": request.expected_source_revision,
                "expected_candidate_hash": request.expected_candidate_hash,
                "decision": request.decision.value,
                "reviewer": request.reviewer.strip(),
                "note": request.note,
                "requested_assertion_class": request.requested_assertion_class,
            }).encode("utf-8")
        ).hexdigest()

        with runtime._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_review_tables(conn)

            # Idempotency Check
            existing = conn.execute(
                "SELECT * FROM agent_review_executions WHERE task_id = ? AND request_id = ?",
                [task_id, request.request_id],
            ).fetchone()
            if existing is not None:
                if (
                    existing["input_fingerprint"] == fingerprint
                    and existing["status"] == "completed"
                ):
                    cached_dict = json.loads(existing["review_outcome_json"])
                    conn.commit()
                    return ReviewDecisionOutcome(**cached_dict)
                if existing["status"] == "claimed":
                    conn.rollback()
                    raise ReviewConflictError(
                        f"review execution already in progress for request_id {request.request_id!r}"
                    )
                conn.rollback()
                raise ReviewConflictError(
                    f"request_id {request.request_id!r} already used with different parameters"
                )

            # Insert execution claim
            exec_id = f"rexec_{hashlib.sha256(f'{task_id}:{request.request_id}'.encode()).hexdigest()[:16]}"
            now = _now_iso()
            conn.execute(
                "INSERT INTO agent_review_executions "
                "(execution_id, task_id, investigation_id, request_id, review_target_id, "
                " input_fingerprint, decision, reviewer, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'claimed', ?, ?)",
                [
                    exec_id,
                    task_id,
                    inv_id,
                    request.request_id,
                    request.review_target_id,
                    fingerprint,
                    request.decision.value,
                    request.reviewer.strip(),
                    now,
                    now,
                ],
            )

            # Determine / create target finding in SQLite
            target_finding_id = candidate.target_id
            if candidate.target_type == "hypothesis":
                target_finding_id = f"finding:hyp_{candidate.target_id}"
                # Ensure finding row exists as review_pending
                f_row = conn.execute(
                    "SELECT status FROM investigation_findings WHERE task_id = ? AND investigation_id = ? AND finding_id = ?",
                    [task_id, inv_id, target_finding_id],
                ).fetchone()
                if f_row is None:
                    conn.execute(
                        "INSERT INTO investigation_findings "
                        "(finding_id, task_id, investigation_id, proposal_id, disposition_id, "
                        " text, assertion_class, evidence_refs_json, relationship_refs_json, "
                        " temporal_scope_json, grounding_id, limitations_json, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'review_pending', ?)",
                        [
                            target_finding_id,
                            task_id,
                            inv_id,
                            f"prop_{candidate.target_id}",
                            f"disp_{candidate.target_id}",
                            candidate.content,
                            target_assertion_class.value,
                            canonical_state_json({"refs": list(candidate.evidence_refs)}),
                            canonical_state_json({"refs": []}),
                            None,
                            f"grnd_{candidate.target_id}",
                            canonical_state_json({"limitations": []}),
                            now,
                        ],
                    )

            # Check finding is review_pending
            f_row = conn.execute(
                "SELECT status FROM investigation_findings WHERE task_id = ? AND investigation_id = ? AND finding_id = ?",
                [task_id, inv_id, target_finding_id],
            ).fetchone()
            if f_row is None:
                conn.rollback()
                raise EvidenceNotFoundError(f"target finding {target_finding_id!r} not found")
            if f_row["status"] != "review_pending":
                conn.rollback()
                raise ReviewConflictError(
                    f"finding {target_finding_id!r} is not review_pending (current: {f_row['status']!r})"
                )

            # Write review history row and update finding
            review_id = f"freview:{hashlib.sha256(f'{task_id}:{target_finding_id}:{request.request_id}'.encode()).hexdigest()[:20]}"
            conn.execute(
                "INSERT INTO investigation_finding_reviews "
                "(review_id, task_id, investigation_id, finding_id, decision, reviewer, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    review_id,
                    task_id,
                    inv_id,
                    target_finding_id,
                    request.decision.value,
                    request.reviewer.strip(),
                    request.note,
                    now,
                ],
            )
            conn.execute(
                "UPDATE investigation_findings "
                "SET status = ?, reviewed_at = ?, reviewer = ?, review_note = ?, review_id = ? "
                "WHERE finding_id = ?",
                [
                    request.decision.value,
                    now,
                    request.reviewer.strip(),
                    request.note,
                    review_id,
                    target_finding_id,
                ],
            )

            # Append trajectory audit event
            evt_id = f"trj_rev_{review_id[-12:]}"
            conn.execute(
                "INSERT INTO agent_trajectory_events "
                "(event_id, task_id, investigation_id, seq, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_trajectory_events WHERE investigation_id = ?), ?, ?, ?)",
                [
                    evt_id,
                    task_id,
                    inv_id,
                    inv_id,
                    AgentTrajectoryEventType.final_semantic_review_recorded.value,
                    canonical_state_json({
                        "review_id": review_id,
                        "request_id": request.request_id,
                        "finding_id": target_finding_id,
                        "decision": request.decision.value,
                        "reviewer": request.reviewer.strip(),
                        "epistemic_type": target_assertion_class.value,
                        "target_type": candidate.target_type,
                    }),
                    now,
                ],
            )

            outcome = ReviewDecisionOutcome(
                review_id=review_id,
                request_id=request.request_id,
                task_id=task_id,
                investigation_id=inv_id,
                target_id=candidate.target_id,
                target_type=candidate.target_type,
                decision=request.decision.value,
                status=request.decision.value,
                accepted_finding_id=target_finding_id if request.decision == ReviewDecision.ACCEPTED else None,
                epistemic_type=target_assertion_class.value,
                candidate_hash=candidate.candidate_hash,
                reviewed_at=now,
                reviewer=request.reviewer.strip(),
                note=request.note,
            )

            conn.execute(
                "UPDATE agent_review_executions SET status = 'completed', review_outcome_json = ?, updated_at = ? WHERE execution_id = ?",
                [outcome.model_dump_json(), _now_iso(), exec_id],
            )
            conn.commit()
            return outcome


__all__ = [
    "AgentAnalystReviewService",
    "EvidenceProvenanceError",
    "FactPromotionBlockedError",
    "ReviewCandidateProjection",
    "ReviewConflictError",
    "ReviewDecision",
    "ReviewDecisionOutcome",
    "ReviewDecisionRequest",
    "ReviewHistoryItem",
    "compute_candidate_hash",
]
