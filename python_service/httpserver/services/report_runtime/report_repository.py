"""Report-runtime persistence on the existing report artifact store.

Ownership decision (P7A §48, driven by the repository investigation):
outline versions, chapter specs, retrieval plans, and frozen context packs
belong to the **report artifact plane** and therefore live in the existing
``reports.db`` (the R2 report persistence owner), NOT in
``investigation.db``.  Their refs point exactly back at task /
investigation / finalization / evidence / canonical semantics.

Storage is append-only: nothing is ever UPDATEd or DELETEd (§50); an
outline edit creates a new version row (§15); identical deterministic
artifacts replay to the same content-addressed id and are stored once
(§62 idempotency).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .report_admission import ReportRuntimeAdmissionV1
from .report_chapter import ChapterSpecV1
from .report_outline import ReportOutlinePlanV1

REPORT_RUNTIME_SCHEMA_VERSION = 1


class ReportRuntimeRepository:
    """Append-only persistence for P7A planning artifacts in reports.db."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS report_runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS report_runtime_admissions (
                    admission_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    finalization_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                -- Outline versions: append-only; an analyst edit inserts a
                -- new revision row (parent_outline_id), never an UPDATE.
                CREATE TABLE IF NOT EXISTS report_outline_versions (
                    outline_id TEXT NOT NULL,
                    outline_revision INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    finalization_id TEXT NOT NULL,
                    parent_outline_id TEXT,
                    planner_kind TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (outline_id, outline_revision)
                );
                CREATE INDEX IF NOT EXISTS idx_report_outline_task
                    ON report_outline_versions(task_id, investigation_id,
                                               created_at);

                CREATE TABLE IF NOT EXISTS report_chapter_specs (
                    chapter_spec_id TEXT PRIMARY KEY,
                    outline_id TEXT NOT NULL,
                    outline_revision INTEGER NOT NULL,
                    chapter_id TEXT NOT NULL,
                    generation_mode TEXT NOT NULL,
                    context_stage TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    ordering_hint INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_report_chapter_outline
                    ON report_chapter_specs(outline_id, outline_revision,
                                            ordering_hint);

                CREATE TABLE IF NOT EXISTS report_retrieval_plans (
                    retrieval_plan_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    outline_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_retrieval_chapter
                    ON report_retrieval_plans(task_id, outline_id,
                                              chapter_id);

                CREATE TABLE IF NOT EXISTS report_context_packs (
                    context_pack_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    outline_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    generation_mode TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_packs_chapter
                    ON report_context_packs(task_id, outline_id,
                                            chapter_id);

                -- P7B: chapter generation lifecycle.  Insert-only identity
                -- columns (§ frozen-by-trigger discipline mirrors the R2
                -- report_generation_inputs pattern); execution columns move
                -- under the guarded state machine.
                CREATE TABLE IF NOT EXISTS report_chapter_generations (
                    generation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    finalization_id TEXT NOT NULL,
                    outline_id TEXT NOT NULL,
                    outline_revision INTEGER NOT NULL,
                    chapter_id TEXT NOT NULL,
                    chapter_spec_hash TEXT NOT NULL,
                    context_pack_id TEXT NOT NULL,
                    context_pack_hash TEXT NOT NULL,
                    retrieval_plan_id TEXT NOT NULL,
                    admission_id TEXT,
                    generation_mode TEXT NOT NULL CHECK(generation_mode IN
                        ('deterministic', 'evidence_narrative', 'synthesis')),
                    narrative_policy_version TEXT NOT NULL,
                    output_contract_version TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL DEFAULT 1,
                    retry_of_generation_id TEXT,
                    status TEXT NOT NULL DEFAULT 'admitted'
                        CHECK(status IN
                        ('admitted','running','completed','failed')),
                    model TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    failed_at TEXT,
                    failure_code TEXT,
                    failure_summary TEXT,
                    output_json TEXT,
                    output_hash TEXT,
                    digest_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_report_chgen_task
                    ON report_chapter_generations(task_id, outline_id,
                                                  outline_revision);

                -- P7B: assertion ledger + consistency review artifacts.
                CREATE TABLE IF NOT EXISTS report_assertion_ledgers (
                    ledger_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    finalization_id TEXT NOT NULL,
                    outline_id TEXT NOT NULL,
                    outline_revision INTEGER NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS report_consistency_reviews (
                    review_id TEXT PRIMARY KEY,
                    ledger_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                -- Chapter generation guards: identity columns frozen, the
                -- lifecycle is a closed state machine, completed rows are
                -- immutable, failed rows carry explicit reasons.
                CREATE TRIGGER IF NOT EXISTS trg_report_chgen_identity_frozen
                BEFORE UPDATE ON report_chapter_generations
                FOR EACH ROW
                WHEN NEW.task_id IS NOT OLD.task_id
                  OR NEW.investigation_id IS NOT OLD.investigation_id
                  OR NEW.finalization_id IS NOT OLD.finalization_id
                  OR NEW.outline_id IS NOT OLD.outline_id
                  OR NEW.outline_revision IS NOT OLD.outline_revision
                  OR NEW.chapter_id IS NOT OLD.chapter_id
                  OR NEW.chapter_spec_hash IS NOT OLD.chapter_spec_hash
                  OR NEW.context_pack_id IS NOT OLD.context_pack_id
                  OR NEW.context_pack_hash IS NOT OLD.context_pack_hash
                  OR NEW.retrieval_plan_id IS NOT OLD.retrieval_plan_id
                  OR NEW.generation_mode IS NOT OLD.generation_mode
                  OR NEW.input_hash IS NOT OLD.input_hash
                  OR NEW.created_at IS NOT OLD.created_at
                BEGIN
                    SELECT RAISE(ABORT,
                        'report chapter generation identity is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_chgen_no_delete
                BEFORE DELETE ON report_chapter_generations
                BEGIN
                    SELECT RAISE(ABORT,
                        'report chapter generation is never deleted');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_chgen_lifecycle
                BEFORE UPDATE OF status ON report_chapter_generations
                FOR EACH ROW
                WHEN NOT (
                    (OLD.status = 'admitted'
                     AND NEW.status IN ('running', 'failed'))
                    OR (OLD.status = 'running'
                        AND NEW.status IN ('completed', 'failed'))
                    OR OLD.status = NEW.status
                )
                BEGIN
                    SELECT RAISE(ABORT,
                        'invalid report chapter generation transition');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_chgen_completed_invariants
                BEFORE UPDATE OF status ON report_chapter_generations
                FOR EACH ROW
                WHEN NEW.status = 'completed' AND (
                    NEW.output_json IS NULL OR NEW.output_hash IS NULL
                    OR NEW.digest_json IS NULL OR NEW.completed_at IS NULL
                )
                BEGIN
                    SELECT RAISE(ABORT,
                        'completed chapter requires its validated output and digest');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_chgen_failed_invariants
                BEFORE UPDATE OF status ON report_chapter_generations
                FOR EACH ROW
                WHEN NEW.status = 'failed' AND (
                    NEW.output_json IS NOT NULL
                    OR NEW.digest_json IS NOT NULL
                    OR NEW.failed_at IS NULL
                    OR NEW.failure_code IS NULL
                )
                BEGIN
                    SELECT RAISE(ABORT,
                        'failed chapter must not carry output');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_chgen_terminal_immutable
                BEFORE UPDATE ON report_chapter_generations
                FOR EACH ROW
                WHEN OLD.status IN ('completed', 'failed') AND (
                    NEW.status IS NOT OLD.status
                    OR NEW.output_json IS NOT OLD.output_json
                    OR NEW.output_hash IS NOT OLD.output_hash
                    OR NEW.digest_json IS NOT OLD.digest_json
                    OR NEW.completed_at IS NOT OLD.completed_at
                    OR NEW.failed_at IS NOT OLD.failed_at
                    OR NEW.failure_code IS NOT OLD.failure_code
                    OR NEW.failure_summary IS NOT OLD.failure_summary
                    OR NEW.model IS NOT OLD.model
                )
                BEGIN
                    SELECT RAISE(ABORT,
                        'terminal report chapter generation is immutable');
                END;
                """
            )
            # P7B additive migration for P7A-created stores.
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(report_chapter_generations)"
                )
            }
            if "admission_id" not in columns:
                conn.execute(
                    "ALTER TABLE report_chapter_generations "
                    "ADD COLUMN admission_id TEXT"
                )
            conn.commit()
            # ordering_hint ships in the P7A-1 base schema (one store
            # generation; no migration path needed for planning rows).

    # -- admissions ---------------------------------------------------------

    def record_report_runtime_admission(
        self, admission: ReportRuntimeAdmissionV1
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_runtime_admissions
                   (admission_id, task_id, investigation_id, finalization_id,
                    input_hash, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    admission.admission_id,
                    admission.task_id,
                    admission.investigation_id,
                    admission.finalization_id,
                    admission.input_hash,
                    admission.model_dump_json(),
                    admission.created_at,
                ),
            )

    def get_report_runtime_admission(
        self, admission_id: str
    ) -> Optional[ReportRuntimeAdmissionV1]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM report_runtime_admissions "
                "WHERE admission_id = ?",
                (admission_id,),
            ).fetchone()
        return (
            ReportRuntimeAdmissionV1.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def verify_report_runtime_admission(
        self, admission: ReportRuntimeAdmissionV1
    ) -> None:
        """Fail closed if the exact durable admission was altered or lost."""
        stored = self.get_report_runtime_admission(admission.admission_id)
        if stored is None or stored.input_hash != admission.input_hash:
            raise ValueError("report runtime admission is stale or missing")
        if stored.model_dump(mode="json") != admission.model_dump(mode="json"):
            raise ValueError("report runtime admission payload mismatch")

    # -- outline versions ----------------------------------------------------

    def record_outline_version(
        self, plan: ReportOutlinePlanV1
    ) -> None:
        """Insert-only outline persistence; replay of an identical
        semantic outline is a no-op (§62)."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_outline_versions
                   (outline_id, outline_revision, task_id, investigation_id,
                    finalization_id, parent_outline_id, planner_kind,
                    input_hash, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.outline_id,
                    plan.outline_revision,
                    plan.task_id,
                    plan.investigation_id,
                    plan.finalization_id,
                    plan.parent_outline_id,
                    plan.planner_kind,
                    plan.input_hash,
                    plan.model_dump_json(),
                    plan.created_at,
                ),
            )

    def get_outline(
        self, outline_id: str, outline_revision: int = 1
    ) -> Optional[ReportOutlinePlanV1]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM report_outline_versions "
                "WHERE outline_id = ? AND outline_revision = ?",
                (outline_id, outline_revision),
            ).fetchone()
        return (
            ReportOutlinePlanV1.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def list_outlines(
        self, task_id: str, investigation_id: str
    ) -> list[ReportOutlinePlanV1]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM report_outline_versions "
                "WHERE task_id = ? AND investigation_id = ? "
                "ORDER BY created_at, outline_revision",
                (task_id, investigation_id),
            ).fetchall()
        return [
            ReportOutlinePlanV1.model_validate_json(row["payload_json"])
            for row in rows
        ]

    # -- chapter specs --------------------------------------------------------

    def record_chapter_specs(self, specs: tuple[ChapterSpecV1, ...]) -> None:
        with self._connect() as conn:
            for spec in specs:
                conn.execute(
                    """INSERT OR IGNORE INTO report_chapter_specs
                       (chapter_spec_id, outline_id, outline_revision,
                        chapter_id, generation_mode, context_stage,
                        input_hash, payload_json, created_at, ordering_hint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        spec.input_hash,
                        spec.outline_id,
                        spec.outline_revision,
                        spec.chapter_id,
                        spec.generation_mode,
                        spec.context_stage,
                        spec.input_hash,
                        spec.model_dump_json(),
                        spec.created_at,
                        spec.ordering,
                    ),
                )

    def list_chapter_specs(
        self, outline_id: str, outline_revision: int
    ) -> list[ChapterSpecV1]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM report_chapter_specs "
                "WHERE outline_id = ? AND outline_revision = ? "
                "ORDER BY ordering_hint, chapter_spec_id",
                (outline_id, outline_revision),
            ).fetchall()
        return [
            ChapterSpecV1.model_validate_json(row["payload_json"])
            for row in rows
        ]

    # -- retrieval plans / context packs (P7B persist-before-generate) ----

    def record_retrieval_plan(self, plan) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_retrieval_plans
                   (retrieval_plan_id, task_id, investigation_id, outline_id,
                    chapter_id, input_hash, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.retrieval_plan_id,
                    plan.task_id,
                    plan.investigation_id,
                    plan.outline_id,
                    plan.chapter_id,
                    plan.input_hash,
                    plan.model_dump_json(),
                    plan.created_at,
                ),
            )

    def get_retrieval_plan(self, retrieval_plan_id: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM report_retrieval_plans "
                "WHERE retrieval_plan_id = ?",
                (retrieval_plan_id,),
            ).fetchone()
        from .report_retrieval import ReportRetrievalPlanV1

        return (
            ReportRetrievalPlanV1.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def record_context_pack(self, pack) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_context_packs
                   (context_pack_id, task_id, investigation_id, outline_id,
                    chapter_id, generation_mode, input_hash, payload_json,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pack.context_pack_id,
                    pack.task_id,
                    pack.investigation_id,
                    pack.outline_id,
                    pack.chapter_id,
                    pack.generation_mode,
                    pack.input_hash,
                    pack.model_dump_json(),
                    pack.created_at,
                ),
            )

    def get_context_pack(self, context_pack_id: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM report_context_packs "
                "WHERE context_pack_id = ?",
                (context_pack_id,),
            ).fetchone()
        from .report_context_pack import FrozenReportContextPackV1

        return (
            FrozenReportContextPackV1.model_validate_json(row["payload_json"])
            if row
            else None
        )

    # -- chapter generations (P7B lifecycle) -------------------------------

    def record_chapter_generation(
        self,
        *,
        generation_id: str,
        task_id: str,
        investigation_id: str,
        finalization_id: str,
        outline_id: str,
        outline_revision: int,
        chapter_id: str,
        chapter_spec_hash: str,
        context_pack_id: str,
        context_pack_hash: str,
        retrieval_plan_id: str,
        generation_mode: str,
        narrative_policy_version: str,
        output_contract_version: str,
        prompt_version: str,
        input_hash: str,
        attempt_no: int = 1,
        retry_of_generation_id: str | None = None,
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO report_chapter_generations
                   (generation_id, task_id, investigation_id, finalization_id,
                    outline_id, outline_revision, chapter_id,
                    chapter_spec_hash, context_pack_id, context_pack_hash,
                    retrieval_plan_id, generation_mode,
                    narrative_policy_version, output_contract_version,
                    prompt_version, input_hash, attempt_no,
                    retry_of_generation_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, 'admitted', ?)""",
                (
                    generation_id,
                    task_id,
                    investigation_id,
                    finalization_id,
                    outline_id,
                    outline_revision,
                    chapter_id,
                    chapter_spec_hash,
                    context_pack_id,
                    context_pack_hash,
                    retrieval_plan_id,
                    generation_mode,
                    narrative_policy_version,
                    output_contract_version,
                    prompt_version,
                    input_hash,
                    attempt_no,
                    retry_of_generation_id,
                    created_at,
                ),
            )

    def claim_chapter_generation(self, generation_id: str) -> bool:
        """Atomic admitted -> running CAS; the concurrent loser gets False
        and must do nothing (R2 claim pattern)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE report_chapter_generations "
                "SET status = 'running', started_at = ? "
                "WHERE generation_id = ? AND status = 'admitted'",
                (now, generation_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            conn.commit()
        return True

    def fail_chapter_generation(
        self,
        generation_id: str,
        *,
        failure_code: str,
        failure_summary: str,
        model: str | None = None,
    ) -> bool:
        """Terminalize a non-terminal chapter generation (audit only)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE report_chapter_generations "
                "SET status = 'failed', failed_at = ?, failure_code = ?, "
                "failure_summary = ?, model = COALESCE(?, model) "
                "WHERE generation_id = ? AND status IN ('admitted','running')",
                (now, failure_code, failure_summary, model, generation_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            conn.commit()
        return True

    def complete_chapter_generation(
        self,
        generation_id: str,
        *,
        output_json: str,
        output_hash: str,
        digest_json: str,
        model: str | None = None,
    ) -> bool:
        """Atomically persist validated output + digest + terminal state
        (§27): a completed row always carries its output."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE report_chapter_generations "
                "SET status = 'completed', completed_at = ?, output_json = ?, "
                "output_hash = ?, digest_json = ?, model = COALESCE(?, model) "
                "WHERE generation_id = ? AND status = 'running'",
                (now, output_json, output_hash, digest_json, model,
                 generation_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            conn.commit()
        return True

    def get_chapter_generation(self, generation_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM report_chapter_generations "
                "WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_stale_chapter_generations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT generation_id, status FROM report_chapter_generations "
                "WHERE status IN ('admitted', 'running') ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def fail_running_chapter_generations(self) -> int:
        """Restart recovery: running -> failed(runtime_restart).  Admitted
        rows stay dispatchable (§47)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE report_chapter_generations "
                "SET status = 'failed', failed_at = ?, "
                "failure_code = 'runtime_restart', "
                "failure_summary = 'chapter generation interrupted by "
                "service restart' WHERE status = 'running'",
                (now,),
            )
            conn.commit()
        return cursor.rowcount

    # -- ledgers / consistency reviews (P7B) ---------------------------------

    def record_assertion_ledger(self, ledger) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_assertion_ledgers
                   (ledger_id, task_id, investigation_id, finalization_id,
                    outline_id, outline_revision, input_hash, payload_json,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ledger.ledger_id,
                    ledger.task_id,
                    ledger.investigation_id,
                    ledger.finalization_id,
                    ledger.outline_id,
                    ledger.outline_revision,
                    ledger.input_hash,
                    ledger.model_dump_json(),
                    ledger.created_at,
                ),
            )

    def record_consistency_review(self, review) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_consistency_reviews
                   (review_id, ledger_id, task_id, investigation_id,
                    input_hash, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    review.review_id,
                    review.ledger_id,
                    review.task_id,
                    review.investigation_id,
                    review.input_hash,
                    review.model_dump_json(),
                    review.created_at,
                ),
            )


__all__ = ["REPORT_RUNTIME_SCHEMA_VERSION", "ReportRuntimeRepository"]
