"""Chapter Writer (P7B §9-§10, §22, §26) + deterministic chapter renderer
(§23).

The Writer has TOOLS = 0: it receives only the frozen
``ChapterGenerationInputV1`` (spec + pack + policy + output contract) and
calls the LLM once per attempt with a versioned prompt.  No registry, no
graph, no resolver, no DB, no HTTP retrieval — structurally, the input
model cannot carry them.

``DeterministicChapterRenderer`` (§22/§23) produces the SAME
``ChapterDraftV1`` contract with NO LLM for deterministic-mode chapters
(inventory / methodology / appendix / limitations / overview), so every
chapter shares the downstream validation / ledger pipeline.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from .canonical import digest_text
from .report_chapter_draft import (
    ChapterDraftV1,
    ReportAssertionV1,
    WriterMetadataV1,
)
from .report_chapter_generation import ChapterGenerationInputV1
from .report_context_pack import FrozenReportContextPackV1

CHAPTER_WRITER_PROMPT_VERSION = "chapter-writer:starter:v1"


class WriterOutputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_writer_prompts(
    generation_input: ChapterGenerationInputV1,
    context_pack: FrozenReportContextPackV1,
) -> tuple[str, str]:
    """Versioned system + user prompt.  The user prompt embeds ONLY pack
    content (digests/structured fields/excerpts) — never a live lookup."""
    system_prompt = (
        "你是取证报告章节撰写器。工具数量为零：你只能使用输入中冻结的"
        "ChapterSpec、ReportContextPack、NarrativePolicy 与输出契约。\n"
        "硬规则：\n"
        "1. 不得提升断言强度（FACT>INFERENCE>HYPOTHESIS；只能保留或降低）。\n"
        "2. 只能引用 pack 中 accepted semantic basis；direct evidence 只能"
        "陈述其直接记录的事实。\n"
        "3. citation_refs 只能是 pack.allowed_citation_refs 的子集，且必须是"
        "该断言 evidence_refs 的子集。\n"
        "4. 禁止引用任何 graph id / finding id / analysis id / event id 作为"
        "citation。\n"
        "5. 禁止编造 actor intent、causality、timeline connection 或新结论。\n"
        "6. limitations 必须保留可见。\n"
        "输出必须是严格 JSON：ChapterDraftV1（chapter_id、statements[]、"
        "chapter_limitations[]、writer_metadata）。每条 statement 是一个"
        "ReportAssertionV1（text、assertion_class、basis_type、basis_refs、"
        "evidence_refs、citation_refs）。不要输出整段无结构 Markdown。"
    )
    pack_projection = {
        "chapter_id": context_pack.chapter_id,
        "generation_mode": context_pack.generation_mode,
        "anchor_evidence": [
            {
                "evidence_ref": item.evidence_ref,
                "digest": item.evidence_digest,
                "hydration_depth": item.hydration_depth,
                "excerpt": item.bounded_excerpt,
                "direct_fact_only": item.direct_fact_only,
            }
            for item in context_pack.anchor_evidence
        ],
        "supporting_evidence": [
            {"evidence_ref": item.evidence_ref, "digest": item.evidence_digest}
            for item in context_pack.supporting_evidence
        ],
        "retrieved_context_evidence": [
            {"evidence_ref": item.evidence_ref, "digest": item.evidence_digest}
            for item in context_pack.retrieved_context_evidence
        ],
        "accepted_semantic_basis": [
            {
                "basis_ref": basis.basis_ref,
                "basis_type": basis.basis_type,
                "assertion_class": basis.assertion_class,
                "text_digest": basis.text_digest,
                "evidence_refs": list(basis.evidence_refs),
            }
            for basis in context_pack.accepted_semantic_basis
        ],
        "allowed_citation_refs": list(context_pack.allowed_citation_refs),
        "limitations": list(context_pack.limitations),
        "required_question_dispositions": dict(
            context_pack.required_question_dispositions
        ),
        "narrative_policy": generation_input.narrative_policy.model_dump(
            mode="json"
        ),
        "generation_mode": generation_input.generation_mode,
        "output_contract": generation_input.output_contract_version,
    }
    from .canonical import canonical_dumps

    user_prompt = (
        "以下是你唯一可用的章节输入（冻结 ReportContextPack 投影）：\n"
        + canonical_dumps(pack_projection)
        + "\n\n请输出 ChapterDraftV1 结构。"
    )
    return system_prompt, user_prompt


class ChapterWriter:
    """Tools = 0 constrained Writer (§9).  ``llm_chat`` is the shared LLM
    entrypoint (same provider/model config as the R2 report chain — no
    second REPORT_MODEL_* namespace, §10)."""

    tools = 0  # static/runtime marker asserted by boundary tests

    def __init__(
        self,
        llm_chat: Callable[[str, str], Awaitable[dict]],
        *,
        max_output_retries: int = 2,
    ):
        self._llm_chat = llm_chat
        self._max_output_retries = max_output_retries

    async def write(
        self,
        generation_input: ChapterGenerationInputV1,
        context_pack: FrozenReportContextPackV1,
    ) -> ChapterDraftV1:
        system_prompt, user_prompt = build_writer_prompts(
            generation_input, context_pack
        )
        attempt = 0
        last_error: Optional[WriterOutputError] = None
        while attempt <= self._max_output_retries:
            attempt += 1
            result = await self._llm_chat(system_prompt, user_prompt)
            content = result.get("content", "")
            model = result.get("model", "")
            try:
                draft = parse_writer_output(
                    content,
                    generation_input=generation_input,
                    context_pack=context_pack,
                    model=model,
                )
            except WriterOutputError as exc:
                last_error = exc
                # §26: structured-output retry only for parse/shape errors;
                # semantic ceiling violations are NOT retried blindly
                if exc.code in (
                    "ceiling_violated",
                    "citation_invalid",
                    "evidence_invalid",
                ):
                    raise
                continue
            return draft
        raise last_error or WriterOutputError(
            "writer_output_invalid", "writer produced no valid draft"
        )


def parse_writer_output(
    content: str,
    *,
    generation_input: ChapterGenerationInputV1,
    context_pack: FrozenReportContextPackV1,
    model: str = "",
) -> ChapterDraftV1:
    """Parse + shape-normalize the Writer JSON (format-only normalization,
    §25 — no semantic repair)."""
    import json

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise WriterOutputError(
            "writer_output_unparseable", "writer output is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise WriterOutputError(
            "writer_output_shape", "writer output must be a JSON object"
        )
    try:
        draft = ChapterDraftV1.model_validate(
            {
                **payload,
                "chapter_id": generation_input.chapter_id,
                "writer_metadata": {
                    "model": model,
                    "prompt_version": generation_input.prompt_version,
                    "narrative_policy_version": (
                        generation_input.narrative_policy.policy_version
                    ),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        )
    except Exception as exc:
        raise WriterOutputError(
            "writer_output_invalid", f"draft failed schema validation: {exc}"
        ) from exc
    return draft


# ---------------------------------------------------------------------------
# Deterministic chapter renderer (§22/§23)
# ---------------------------------------------------------------------------


class DeterministicChapterRenderer:
    """LLM-free chapter generation for deterministic-mode chapters.

    Produces the same ``ChapterDraftV1`` contract from the frozen pack:
    one assertion per evidence item (digest-level facts), limitations
    carried through verbatim.
    """

    version = "deterministic-chapter-renderer:v1"

    def render(
        self,
        generation_input: ChapterGenerationInputV1,
        context_pack: FrozenReportContextPackV1,
    ) -> ChapterDraftV1:
        if generation_input.generation_mode != "deterministic":
            raise ValueError(
                "deterministic renderer requires generation_mode="
                f"'deterministic', got {generation_input.generation_mode!r}"
            )
        statements: list[ReportAssertionV1] = []
        semantic_basis = {
            basis.basis_ref: basis
            for basis in context_pack.accepted_semantic_basis
        }
        for item in context_pack.anchor_evidence:
            statements.append(
                ReportAssertionV1(
                    text=(
                        f"证据 {item.evidence_ref} 已纳入报告范围"
                        f"（{item.source_kind}，digest "
                        f"{item.evidence_digest[:12]}）。"
                    ),
                    assertion_class="FACT",
                    basis_type="direct_evidence",
                    basis_refs=(),
                    evidence_refs=(item.evidence_ref,),
                    citation_refs=(item.evidence_ref,),
                )
            )
        for basis in context_pack.accepted_semantic_basis:
            statements.append(
                ReportAssertionV1(
                    text=(
                        f"已接受语义依据 {basis.basis_ref}（"
                        f"{basis.assertion_class}，digest "
                        f"{basis.text_digest[:12]}）纳入本章。"
                    ),
                    assertion_class=basis.assertion_class,
                    basis_type="accepted_finding"
                    if basis.basis_type == "finding"
                    else "accepted_event"
                    if basis.basis_type == "event"
                    else "accepted_analysis",
                    basis_refs=(basis.basis_ref,),
                    evidence_refs=tuple(
                        ref
                        for ref in basis.evidence_refs
                        if ref in set(context_pack.allowed_citation_refs)
                    )[:1],
                    citation_refs=(
                        tuple(
                            ref
                            for ref in basis.evidence_refs
                            if ref
                            in set(context_pack.allowed_citation_refs)
                        )[:1]
                    ),
                )
            )
        if not statements:
            statements.append(
                ReportAssertionV1(
                    text="本章无可呈现的确定性内容。",
                    assertion_class="LIMITATION",
                    basis_type="direct_evidence",
                    evidence_refs=(),
                    citation_refs=(),
                )
            )
        draft = ChapterDraftV1(
            chapter_id=generation_input.chapter_id,
            statements=tuple(statements),
            chapter_limitations=tuple(context_pack.limitations),
            writer_metadata=WriterMetadataV1(
                model="deterministic_renderer",
                prompt_version=generation_input.prompt_version,
                narrative_policy_version=(
                    generation_input.narrative_policy.policy_version
                ),
                generated_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
        return draft.with_identities(generation_input.input_hash)


__all__ = [
    "CHAPTER_WRITER_PROMPT_VERSION",
    "ChapterWriter",
    "DeterministicChapterRenderer",
    "WriterOutputError",
    "build_writer_prompts",
    "parse_writer_output",
]
