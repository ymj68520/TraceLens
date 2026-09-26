"""Chapter generation contracts (P7B §6-§8).

``ChapterGenerationInputV1`` is the ENTIRE Writer universe: ChapterSpec +
FrozenReportContextPack + NarrativePolicy + OutputContract (§87 hard
boundary).  It structurally cannot carry a repository handle, DB path,
graph client, tool registry, or any live-state callback — those shapes
are not expressible in the frozen model.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .canonical import sha256_hex

CHAPTER_GENERATION_INPUT_VERSION = "chapter-generation-input:v1"
CHAPTER_OUTPUT_CONTRACT_VERSION = "chapter-draft:v1"

CHAPTER_GENERATION_ID_PREFIX = "rgen:"


class NarrativePolicyV1(BaseModel):
    """Versioned narrative policy (P7B §11).

    Prose-level rules are starter/versioned policy, never claimed as
    permanent architecture; the structural prohibitions below are the
    frozen ones the validators enforce.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = "report-narrative-policy:starter:v1"

    no_assertion_strength_increase: Literal[True] = True
    accepted_semantic_basis_only: Literal[True] = True
    direct_evidence_direct_fact_only: Literal[True] = True
    limitations_must_remain_visible: Literal[True] = True
    review_pending_semantic_text_forbidden: Literal[True] = True
    citation_placement_required: Literal[True] = True

    # starter prose rules (P8 calibration; informational for prompts)
    uncertainty_wording_required: bool = True
    no_invented_actor_intent: Literal[True] = True
    no_invented_causality: Literal[True] = True
    no_invented_timeline_connection: Literal[True] = True
    no_hidden_new_conclusion: Literal[True] = True

    notes: str = ""

    @property
    def policy_hash(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


def build_starter_narrative_policy() -> NarrativePolicyV1:
    return NarrativePolicyV1(
        notes=(
            "starter policy: exact prose rules are versioned and may be "
            "recalibrated in a later policy version"
        )
    )


class ChapterGenerationInputV1(BaseModel):
    """Frozen Writer input (§8): the four-artifact bundle plus exact
    identity bindings.  ``input_hash`` covers every semantic field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_version: str = CHAPTER_GENERATION_INPUT_VERSION

    generation_id: str

    task_id: str
    investigation_id: str
    finalization_id: str
    finalization_record_hash: str

    outline_id: str
    outline_revision: int
    chapter_id: str
    chapter_spec_hash: str

    context_pack_id: str
    context_pack_hash: str
    retrieval_plan_id: str

    generation_mode: str
    narrative_policy: NarrativePolicyV1
    output_contract_version: str = CHAPTER_OUTPUT_CONTRACT_VERSION
    prompt_version: str

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("input_version", CHAPTER_GENERATION_INPUT_VERSION)
        data.setdefault(
            "output_contract_version", CHAPTER_OUTPUT_CONTRACT_VERSION
        )
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("input_hash", "generation_id")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("generation_id"):
            data["generation_id"] = (
                CHAPTER_GENERATION_ID_PREFIX + digest[:24]
            )
        return data


def new_chapter_generation_input(
    *,
    context_pack,
    chapter_spec,
    narrative_policy: NarrativePolicyV1,
    prompt_version: str,
) -> ChapterGenerationInputV1:
    """Assemble the frozen Writer input from a persisted pack + spec."""
    return ChapterGenerationInputV1(
        task_id=context_pack.task_id,
        investigation_id=context_pack.investigation_id,
        finalization_id=context_pack.finalization_id,
        finalization_record_hash=context_pack.finalization_record_hash,
        outline_id=context_pack.outline_id,
        outline_revision=context_pack.outline_revision,
        chapter_id=chapter_spec.chapter_id,
        chapter_spec_hash=chapter_spec.input_hash,
        context_pack_id=context_pack.context_pack_id,
        context_pack_hash=context_pack.input_hash,
        retrieval_plan_id=context_pack.retrieval_plan_id,
        generation_mode=chapter_spec.generation_mode,
        narrative_policy=narrative_policy,
        prompt_version=prompt_version,
    )


class ChapterDispatchError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def commit_report_chapter_dispatch(
    repository,
    *,
    context_pack,
    chapter_spec,
    retrieval_plan,
    narrative_policy: NarrativePolicyV1,
    prompt_version: str,
) -> ChapterGenerationInputV1:
    """§5/§6 persist-before-generate, in ONE transaction:

    verify admission-relevant identity -> INSERT/verify exact
    RetrievalPlan -> INSERT/verify exact ContextPack -> INSERT chapter
    generation admission -> COMMIT.  Any failure raises and leaves NO
    chapter generation row (fail-closed); the Writer is only ever
    admitted against a persisted pack.
    """
    import sqlite3
    from datetime import datetime, timezone

    pack = context_pack
    spec = chapter_spec
    # identity cross-checks before any write
    if pack.chapter_id != spec.chapter_id:
        raise ChapterDispatchError(
            "identity_mismatch",
            "context pack and chapter spec belong to different chapters",
        )
    if pack.outline_id != spec.outline_id or (
        pack.outline_revision != spec.outline_revision
    ):
        raise ChapterDispatchError(
            "identity_mismatch",
            "context pack and chapter spec belong to different outlines",
        )
    if retrieval_plan.chapter_id != spec.chapter_id or (
        retrieval_plan.input_hash != pack.retrieval_plan_hash
    ):
        raise ChapterDispatchError(
            "identity_mismatch",
            "retrieval plan does not match the pack's frozen plan hash",
        )

    generated_input = new_chapter_generation_input(
        context_pack=pack,
        chapter_spec=spec,
        narrative_policy=narrative_policy,
        prompt_version=prompt_version,
    )
    now = datetime.now(timezone.utc).isoformat()
    try:
        with repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO report_retrieval_plans
                       (retrieval_plan_id, task_id, investigation_id,
                        outline_id, chapter_id, input_hash, payload_json,
                        created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        retrieval_plan.retrieval_plan_id,
                        retrieval_plan.task_id,
                        retrieval_plan.investigation_id,
                        retrieval_plan.outline_id,
                        retrieval_plan.chapter_id,
                        retrieval_plan.input_hash,
                        retrieval_plan.model_dump_json(),
                        retrieval_plan.created_at,
                    ),
                )
                stored_plan = conn.execute(
                    "SELECT input_hash FROM report_retrieval_plans "
                    "WHERE retrieval_plan_id = ?",
                    (retrieval_plan.retrieval_plan_id,),
                ).fetchone()
                if stored_plan is None or (
                    stored_plan["input_hash"] != retrieval_plan.input_hash
                ):
                    raise ChapterDispatchError(
                        "plan_conflict",
                        "a different retrieval plan already occupies this id",
                    )
                conn.execute(
                    """INSERT OR IGNORE INTO report_context_packs
                       (context_pack_id, task_id, investigation_id,
                        outline_id, chapter_id, generation_mode, input_hash,
                        payload_json, created_at)
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
                stored_pack = conn.execute(
                    "SELECT input_hash FROM report_context_packs "
                    "WHERE context_pack_id = ?",
                    (pack.context_pack_id,),
                ).fetchone()
                if stored_pack is None or (
                    stored_pack["input_hash"] != pack.input_hash
                ):
                    raise ChapterDispatchError(
                        "pack_conflict",
                        "a different context pack already occupies this id",
                    )
                conn.execute(
                    """INSERT OR IGNORE INTO report_chapter_generations
                       (generation_id, task_id, investigation_id,
                        finalization_id, outline_id, outline_revision,
                        chapter_id, chapter_spec_hash, context_pack_id,
                        context_pack_hash, retrieval_plan_id,
                        generation_mode, narrative_policy_version,
                        output_contract_version, prompt_version, input_hash,
                        attempt_no, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               ?, 1, 'admitted', ?)""",
                    (
                        generated_input.generation_id,
                        pack.task_id,
                        pack.investigation_id,
                        pack.finalization_id,
                        pack.outline_id,
                        pack.outline_revision,
                        spec.chapter_id,
                        spec.input_hash,
                        pack.context_pack_id,
                        pack.input_hash,
                        retrieval_plan.retrieval_plan_id,
                        spec.generation_mode,
                        narrative_policy.policy_version,
                        CHAPTER_OUTPUT_CONTRACT_VERSION,
                        prompt_version,
                        generated_input.input_hash,
                        now,
                    ),
                )
                existing_generation = conn.execute(
                    "SELECT input_hash FROM report_chapter_generations "
                    "WHERE generation_id = ?",
                    (generated_input.generation_id,),
                ).fetchone()
                if (
                    existing_generation is None
                    or existing_generation["input_hash"]
                    != generated_input.input_hash
                ):
                    raise ChapterDispatchError(
                        "generation_conflict",
                        "a different generation already occupies this id",
                    )
                conn.commit()
            except ChapterDispatchError:
                conn.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise ChapterDispatchError(
                    "dispatch_conflict", f"chapter dispatch conflict: {exc}"
                ) from exc
    except sqlite3.DatabaseError as exc:
        raise ChapterDispatchError(
            "store_unavailable", "report runtime store is unavailable"
        ) from exc
    return generated_input


__all__ = [
    "CHAPTER_GENERATION_INPUT_VERSION",
    "CHAPTER_OUTPUT_CONTRACT_VERSION",
    "ChapterDispatchError",
    "ChapterGenerationInputV1",
    "NarrativePolicyV1",
    "build_starter_narrative_policy",
    "commit_report_chapter_dispatch",
    "new_chapter_generation_input",
]
