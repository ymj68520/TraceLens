"""Frozen Report generation admission (Phase R2b).

Assembles the R2 LLM-generation input from R1 Report Evidence bindings:
exact immutable Evidence Snapshots plus, when the analyst explicitly bound
one, the exact accepted Secondary Analysis with its persisted Claims and
refs. The result is a typed, deterministic envelope serialized exactly once
to canonical JSON and hashed (SHA-256); the hash is frozen on the durable
admission row in ``reports.db``.

R2b boundaries: no LLM call, no narrative generation, no executor, and no
public HTTP route -- a route without an executor would strand user-visible
never-running generations, so R2c enables admission and scheduling together.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..investigation.acquisition import canonical_json
from ..investigation.models import (
    AnalysisGroundingStatus,
    ClaimGroundingStatus,
    ClaimType,
    ClusterSnapshotPayload,
    FileSnapshotPayload,
    ReportEvidenceStatus,
)
from ..investigation.paths import investigation_db_path_for_task
from ..investigation.repository import SUPPORTED_SCHEMA_VERSION
from .models import (
    EnvelopeBoundAnalysisReviewV1,
    EnvelopeBoundAnalysisV1,
    EnvelopeClaimV1,
    EnvelopeEvidenceItemV1,
    EnvelopeSnapshotV1,
    ReportGenerationEnvelopeV1,
    ReportGenerationInput,
)
from .repository import ReportRepository

# Prompt version identity only (R2b): the version string is frozen into the
# envelope hash now so R2c's executor prompt can never invalidate an admitted
# input_hash contract. The prompt itself is R2c scope.
REPORT_GENERATION_PROMPT_VERSION = "final-report:v1"


class ReportGenerationInputError(RuntimeError):
    """Admission rejected before any generation row exists.

    ``code`` is a stable machine code (``no_report_evidence`` /
    ``invalid_report_evidence_binding``); HTTP mapping is deliberately left
    to the R2c route.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ReportGenerationInputBuilder:
    """Strictly read-only assembly of one frozen envelope in one read txn.

    Mirrors InvestigationGraphReader's discipline (mode=ro URI + query_only
    + fail-closed on a non-v7 store) but keeps its own narrow projections so
    the graph reader does not grow into a catch-all. The whole envelope is
    read inside ONE explicit read transaction on ONE connection, so an
    analyst rebind committed mid-assembly can never yield a mixed-epoch
    input: the read snapshot is internally self-consistent.
    """

    def __init__(self, investigation_db_path, task_id: str):
        self._db_path = Path(investigation_db_path)
        self._task_id = task_id

    def assemble(
        self, prompt_version: str = REPORT_GENERATION_PROMPT_VERSION
    ) -> ReportGenerationEnvelopeV1:
        try:
            with contextlib.closing(self._connect()) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version != SUPPORTED_SCHEMA_VERSION:
                    raise EvidenceStoreError(
                        "investigation store schema is unsupported"
                    )
                conn.execute("BEGIN")
                try:
                    return self._assemble_with_conn(conn, prompt_version)
                finally:
                    conn.execute("ROLLBACK")
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError("investigation store is unavailable") from exc

    def _connect(self) -> sqlite3.Connection:
        # mode=ro refuses to create or write; query_only is belt-and-braces.
        uri = f"file:{quote(str(self._db_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def _assemble_with_conn(
        self, conn: sqlite3.Connection, prompt_version: str
    ) -> ReportGenerationEnvelopeV1:
        main: list[EnvelopeEvidenceItemV1] = []
        appendix: list[EnvelopeEvidenceItemV1] = []
        if self._report_evidence_table_exists(conn):
            rows = conn.execute(
                "SELECT evidence_key, report_status, analysis_id "
                "FROM report_evidence WHERE task_id = ? ORDER BY evidence_key",
                [self._task_id],
            ).fetchall()
            for row in rows:
                status = ReportEvidenceStatus(row["report_status"])
                if status is ReportEvidenceStatus.excluded:
                    # Excluded is an audit state, never generation input.
                    continue
                item = self._item_with_conn(conn, row)
                if status is ReportEvidenceStatus.main:
                    main.append(item)
                else:
                    appendix.append(item)
        return ReportGenerationEnvelopeV1(
            prompt_version=prompt_version,
            task_id=self._task_id,
            main_evidence=tuple(main),
            appendix_evidence=tuple(appendix),
            allowed_report_evidence_ids=tuple(
                sorted({item.evidence_key for item in (*main, *appendix)})
            ),
        )

    def _item_with_conn(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> EnvelopeEvidenceItemV1:
        evidence_key = row["evidence_key"]
        snapshot = self._snapshot_with_conn(conn, self._task_id, evidence_key)
        if snapshot is None:
            raise ReportGenerationInputError(
                "invalid_report_evidence_binding",
                "report evidence snapshot is missing",
            )
        bound = None
        analysis_id = row["analysis_id"]
        if analysis_id is not None:
            bound = self._bound_analysis_with_conn(conn, evidence_key, analysis_id)
        return EnvelopeEvidenceItemV1(
            evidence_key=evidence_key,
            report_status=ReportEvidenceStatus(row["report_status"]),
            snapshot=snapshot,
            bound_analysis=bound,
        )

    def _bound_analysis_with_conn(
        self, conn: sqlite3.Connection, evidence_key: str, analysis_id: str
    ) -> EnvelopeBoundAnalysisV1:
        # Admission re-validates the persisted binding even though the R1
        # write path already triple-checked it: report generation is a new
        # trust boundary and must fail closed on any stale or tampered row,
        # never repair or rebind it.
        row = conn.execute(
            "SELECT analysis_id, evidence_key, version, status, description, "
            "summary, model, grounding_status, decided_by, decided_at, "
            "decision_reason FROM secondary_analyses "
            "WHERE task_id = ? AND analysis_id = ?",
            [self._task_id, analysis_id],
        ).fetchone()
        if row is None:
            raise ReportGenerationInputError(
                "invalid_report_evidence_binding", "bound analysis is missing"
            )
        if row["evidence_key"] != evidence_key:
            raise ReportGenerationInputError(
                "invalid_report_evidence_binding",
                "bound analysis belongs to a different evidence",
            )
        if row["status"] != "accepted":
            raise ReportGenerationInputError(
                "invalid_report_evidence_binding", "bound analysis is not accepted"
            )
        return EnvelopeBoundAnalysisV1(
            analysis_id=row["analysis_id"],
            version=row["version"],
            description=row["description"],
            summary=row["summary"],
            model=row["model"],
            grounding_status=(
                AnalysisGroundingStatus(row["grounding_status"])
                if row["grounding_status"] is not None
                else None
            ),
            review=EnvelopeBoundAnalysisReviewV1(
                decided_by=row["decided_by"],
                decided_at=row["decided_at"],
                decision_reason=row["decision_reason"],
            ),
            claims=self._claims_with_conn(conn, analysis_id),
        )

    def _claims_with_conn(
        self, conn: sqlite3.Connection, analysis_id: str
    ) -> tuple[EnvelopeClaimV1, ...]:
        refs: dict[str, list[str]] = {}
        for ref in conn.execute(
            "SELECT r.claim_id, r.evidence_key FROM claim_evidence_refs r "
            "JOIN analysis_claims c ON c.claim_id = r.claim_id "
            "WHERE c.analysis_id = ? ORDER BY r.claim_id, r.evidence_key",
            [analysis_id],
        ):
            refs.setdefault(ref["claim_id"], []).append(ref["evidence_key"])
        claims = [
            self._claim_with_conn(row, tuple(sorted(refs.get(row["claim_id"], ()))))
            for row in conn.execute(
                "SELECT claim_id, claim_index, claim_type, claim_text, "
                "grounding_status, warning_json, created_at "
                "FROM analysis_claims WHERE analysis_id = ?",
                [analysis_id],
            )
        ]
        claims.sort(key=lambda claim: claim.claim_id)
        return tuple(claims)

    @staticmethod
    def _claim_with_conn(row: sqlite3.Row, evidence_refs: tuple[str, ...]) -> EnvelopeClaimV1:
        warnings = None
        if row["warning_json"]:
            try:
                warnings = json.loads(row["warning_json"])
            except (ValueError, TypeError):
                warnings = None
        return EnvelopeClaimV1(
            claim_id=row["claim_id"],
            claim_index=row["claim_index"],
            claim_type=ClaimType(row["claim_type"]),
            claim_text=row["claim_text"],
            grounding_status=ClaimGroundingStatus(row["grounding_status"]),
            warnings=warnings,
            evidence_refs=evidence_refs,
            created_at=row["created_at"],
        )

    @staticmethod
    def _snapshot_with_conn(
        conn: sqlite3.Connection, task_id: str, evidence_key: str
    ) -> EnvelopeSnapshotV1 | None:
        # evidence_snapshots enforces UNIQUE(task_id, evidence_key): there is
        # at most one row, so id DESC only keeps the statement deterministic.
        row = conn.execute(
            "SELECT task_id, evidence_key, evidence_type, snapshot_json, "
            "captured_at FROM evidence_snapshots "
            "WHERE task_id = ? AND evidence_key = ? ORDER BY id DESC LIMIT 1",
            [task_id, evidence_key],
        ).fetchone()
        if row is None:
            return None
        evidence_type = row["evidence_type"]
        try:
            data = json.loads(row["snapshot_json"])
        except (ValueError, TypeError) as exc:
            raise EvidenceStoreError(
                "report evidence snapshot payload is corrupt"
            ) from exc
        if evidence_type == "file":
            payload = FileSnapshotPayload.model_validate(data)
        elif evidence_type == "cluster":
            payload = ClusterSnapshotPayload.model_validate(data)
        else:  # pragma: no cover - guarded by the table CHECK
            raise EvidenceStoreError("report evidence snapshot type is unknown")
        return EnvelopeSnapshotV1(
            task_id=row["task_id"],
            evidence_key=row["evidence_key"],
            evidence_type=evidence_type,
            captured_at=row["captured_at"],
            payload=payload,
        )

    @staticmethod
    def _report_evidence_table_exists(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
        ).fetchone() is not None


class ReportGenerationAdmissionService:
    """Admit one frozen report generation from a task's Report Evidence.

    Trust boundary: the task lookup comes from the C++ backend (trusted
    server-side paths only); the investigation store path is derived from
    it, never accepted from the client. The whole envelope is assembled from
    one read transaction before the immutable admission row is persisted, so
    later analyst changes (rebind, exclude, new evidence) can never alter an
    admitted input. R2b deliberately exposes no HTTP route.
    """

    def __init__(self, cpp_backend, repository: ReportRepository):
        self._cpp_backend = cpp_backend
        self._repository = repository

    async def admit(
        self,
        task_id: str,
        *,
        requested_by: str,
        prompt_version: str = REPORT_GENERATION_PROMPT_VERSION,
    ) -> ReportGenerationInput:
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        try:
            db_path = investigation_db_path_for_task(task)
        except EvidenceStoreError:
            raise ReportGenerationInputError(
                "no_report_evidence", "task has no report evidence"
            ) from None
        if not db_path.exists():
            raise ReportGenerationInputError(
                "no_report_evidence", "task has no report evidence"
            )
        builder = ReportGenerationInputBuilder(db_path, task_id)
        envelope = await asyncio.to_thread(builder.assemble, prompt_version)
        if not envelope.main_evidence and not envelope.appendix_evidence:
            raise ReportGenerationInputError(
                "no_report_evidence", "task has no report evidence"
            )
        envelope_json = canonical_json(envelope)
        input_hash = hashlib.sha256(envelope_json.encode("utf-8")).hexdigest()
        try:
            return await asyncio.to_thread(
                self._repository.create_generation_input,
                task_id,
                requested_by=requested_by,
                input_schema_version=envelope.schema_version,
                prompt_version=prompt_version,
                input_envelope_json=envelope_json,
                input_hash=input_hash,
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "report generation store is unavailable"
            ) from exc


__all__ = [
    "REPORT_GENERATION_PROMPT_VERSION",
    "ReportGenerationAdmissionService",
    "ReportGenerationInputBuilder",
    "ReportGenerationInputError",
]
