"""Report runtime orchestrator for agent-aware reports (P7B §46-§50).

Deterministic per-chapter execution over persisted artifacts:

    execute_chapter_generation(generation_id):
        load persisted generation row -> load EXACT persisted pack/plan
        -> claim (admitted -> running CAS) -> deterministic renderer OR
        tools=0 Writer -> §24 validation (fail-closed, no silent repair)
        -> atomic completion (validated output + hash + digest + terminal
        state in one transaction)

Restart recovery (§47): running -> failed(runtime_restart); admitted
rows stay dispatchable; initialize performs NO model generation (§48).
Failure isolation (§50): one failed chapter leaves completed chapters
immutable and the report unpublished.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

from .canonical import sha256_hex
from .report_chapter_draft import ChapterDraftV1
from .report_chapter_generation import ChapterGenerationInputV1
from .report_chapter_validation import (
    ChapterValidationError,
    validate_chapter_draft,
)
from .report_chapter_writer import (
    ChapterWriter,
    WriterOutputError,
    DeterministicChapterRenderer,
)
from .report_context_pack import FrozenReportContextPackV1
from .report_ledger import build_chapter_digest

logger = logging.getLogger(__name__)

CHAPTER_EXECUTION_VERSION = "chapter-execution:v1"


class ChapterExecutionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _policy_from_row(row: dict):
    """Reconstruct the persisted narrative policy by version.

    Only the starter policy exists in P7B; unknown versions fail closed
    (a hash built from a different policy would mismatch anyway).
    """
    from .report_chapter_generation import build_starter_narrative_policy

    policy = build_starter_narrative_policy()
    if row["narrative_policy_version"] != policy.policy_version:
        raise ChapterExecutionError(
            "narrative_policy_unknown",
            f"unknown narrative policy version: "
            f"{row['narrative_policy_version']!r}",
        )
    return policy


class ChapterGenerationExecutor:
    """Executes admitted chapter generations against persisted packs."""

    version = CHAPTER_EXECUTION_VERSION

    def __init__(
        self,
        *,
        repository: Any,
        llm_chat: Optional[Callable[[str, str], Awaitable[dict]]] = None,
        max_output_retries: int = 2,
    ):
        self._repository = repository
        self._writer = (
            ChapterWriter(llm_chat, max_output_retries=max_output_retries)
            if llm_chat is not None
            else None
        )
        self._renderer = DeterministicChapterRenderer()

    def initialize(self) -> dict:
        """§47/§48: restart recovery only — no model generation."""
        failed = self._repository.fail_running_chapter_generations()
        return {"running_failed": failed}

    def _verify_admission(self, row: dict) -> None:
        admission_id = row.get("admission_id")
        if not admission_id:
            return
        admission = self._repository.get_report_runtime_admission(admission_id)
        if admission is None:
            raise ChapterExecutionError(
                "admission_missing", "report runtime admission is missing"
            )
        self._repository.verify_report_runtime_admission(admission)

    async def execute_chapter_generation(
        self, generation_id: str
    ) -> dict:
        row = self._repository.get_chapter_generation(generation_id)
        if row is None:
            raise ChapterExecutionError(
                "generation_not_found", f"unknown generation: {generation_id}"
            )
        if row["status"] == "completed":
            raise ChapterExecutionError(
                "generation_completed", "chapter generation already completed"
            )
        if row["status"] == "failed":
            raise ChapterExecutionError(
                "generation_failed",
                "chapter generation already failed; dispatch a new attempt",
            )
        self._verify_admission(row)
        # §46/§E3: the Writer input is reconstructed from persisted bytes
        pack = self._repository.get_context_pack(row["context_pack_id"])
        if pack is None:
            raise ChapterExecutionError(
                "pack_missing",
                f"context pack not persisted: {row['context_pack_id']}",
            )
        if pack.input_hash != row["context_pack_hash"]:
            raise ChapterExecutionError(
                "pack_hash_mismatch",
                "persisted pack hash differs from the admitted generation",
            )
        generation_input = ChapterGenerationInputV1(
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            finalization_id=row["finalization_id"],
            finalization_record_hash=pack.finalization_record_hash,
            outline_id=row["outline_id"],
            outline_revision=row["outline_revision"],
            chapter_id=row["chapter_id"],
            chapter_spec_hash=row["chapter_spec_hash"],
            context_pack_id=row["context_pack_id"],
            context_pack_hash=row["context_pack_hash"],
            retrieval_plan_id=row["retrieval_plan_id"],
            generation_mode=row["generation_mode"],
            narrative_policy=_policy_from_row(row),
            output_contract_version=row["output_contract_version"],
            prompt_version=row["prompt_version"],
        )
        if generation_input.input_hash != row["input_hash"]:
            raise ChapterExecutionError(
                "input_hash_mismatch",
                "reconstructed generation input hash differs from admission",
            )

        if not self._repository.claim_chapter_generation(generation_id):
            return {"outcome": "already_claimed"}

        try:
            if row["generation_mode"] == "deterministic":
                draft = self._renderer.render(generation_input, pack)
            else:
                if self._writer is None:
                    self._verify_admission(row)
                    self._repository.fail_chapter_generation(
                        generation_id,
                        failure_code="llm_unavailable",
                        failure_summary="LLM service is not initialized",
                    )
                    return {"outcome": "failed", "code": "llm_unavailable"}
                try:
                    draft = await self._writer.write(generation_input, pack)
                except WriterOutputError as exc:
                    self._verify_admission(row)
                    self._repository.fail_chapter_generation(
                        generation_id,
                        failure_code=exc.code,
                        failure_summary=str(exc),
                    )
                    return {"outcome": "failed", "code": exc.code}
            # §24 validation — one failure invalidates the whole chapter
            try:
                validated = validate_chapter_draft(
                    draft, generation_input, pack
                )
            except ChapterValidationError as exc:
                self._verify_admission(row)
                self._repository.fail_chapter_generation(
                    generation_id,
                    failure_code=exc.code,
                    failure_summary=str(exc),
                )
                return {"outcome": "failed", "code": exc.code}
            digest = build_chapter_digest(
                validated,
                generation_id=generation_id,
                context_pack_hash=pack.input_hash,
            )
            output_payload = {
                **validated.model_dump(mode="json"),
                "draft_hash": validated.draft_hash(),
            }
            output_json = json.dumps(output_payload, ensure_ascii=False)
            self._verify_admission(row)
            completed = self._repository.complete_chapter_generation(
                generation_id,
                output_json=output_json,
                output_hash=validated.draft_hash(),
                digest_json=digest.model_dump_json(),
                model=validated.writer_metadata.model or None,
            )
            if not completed:
                raise ChapterExecutionError(
                    "completion_conflict",
                    "chapter generation left the running state",
                )
            return {
                "outcome": "completed",
                "chapter_id": row["chapter_id"],
                "output_hash": validated.draft_hash(),
                "digest_id": digest.digest_id,
            }
        except ChapterExecutionError:
            raise
        except Exception as exc:
            logger.exception(
                "Chapter generation execution failed: %s", generation_id
            )
            self._verify_admission(row)
            self._repository.fail_chapter_generation(
                generation_id,
                failure_code="execution_error",
                failure_summary=str(exc)[:500],
            )
            return {"outcome": "failed", "code": "execution_error"}

    def list_completed(self, outline_id: str, outline_revision: int) -> list[dict]:
        with self._repository._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_chapter_generations "
                "WHERE outline_id = ? AND outline_revision = ? "
                "AND status = 'completed' ORDER BY chapter_id",
                (outline_id, outline_revision),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_failed(self, outline_id: str, outline_revision: int) -> list[dict]:
        with self._repository._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_chapter_generations "
                "WHERE outline_id = ? AND outline_revision = ? "
                "AND status = 'failed' ORDER BY chapter_id",
                (outline_id, outline_revision),
            ).fetchall()
        return [dict(row) for row in rows]


def retry_chapter_generation(
    repository: Any,
    failed_generation_id: str,
    *,
    narrative_policy_version: str,
    prompt_version: str,
) -> str:
    """§50: a retry is a NEW attempt row; the failed attempt is kept."""
    row = repository.get_chapter_generation(failed_generation_id)
    if row is None:
        raise ChapterExecutionError(
            "generation_not_found", f"unknown generation: {failed_generation_id}"
        )
    if row["status"] != "failed":
        raise ChapterExecutionError(
            "retry_denied", "only failed generations can be retried"
        )
    from datetime import datetime, timezone

    import uuid

    new_id = "rgen_" + uuid.uuid4().hex
    with repository._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        attempt_row = conn.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_attempt "
            "FROM report_chapter_generations WHERE chapter_id = ? "
            "AND outline_id = ? AND outline_revision = ?",
            (row["chapter_id"], row["outline_id"], row["outline_revision"]),
        ).fetchone()
        conn.execute(
            """INSERT INTO report_chapter_generations
               (generation_id, task_id, investigation_id, finalization_id,
                outline_id, outline_revision, chapter_id, chapter_spec_hash,
                context_pack_id, context_pack_hash, retrieval_plan_id,
                generation_mode, narrative_policy_version,
                output_contract_version, prompt_version, input_hash,
                attempt_no, retry_of_generation_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, 'admitted', ?)""",
            (
                new_id,
                row["task_id"],
                row["investigation_id"],
                row["finalization_id"],
                row["outline_id"],
                row["outline_revision"],
                row["chapter_id"],
                row["chapter_spec_hash"],
                row["context_pack_id"],
                row["context_pack_hash"],
                row["retrieval_plan_id"],
                row["generation_mode"],
                narrative_policy_version,
                row["output_contract_version"],
                prompt_version,
                row["input_hash"],
                attempt_row["next_attempt"],
                failed_generation_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    return new_id


__all__ = [
    "CHAPTER_EXECUTION_VERSION",
    "ChapterExecutionError",
    "ChapterGenerationExecutor",
    "retry_chapter_generation",
]
