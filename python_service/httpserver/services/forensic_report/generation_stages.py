"""Two report modes within the existing executor; no separate service/jobs."""
from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import re

import logging

from .generation_sources import digest, material
from .generation_structured import _loads_strict
from .generation_prompts import (STAGE_DISCOVERY_SYSTEM_V1, STAGE_COMPARE_SYSTEM_V1,
                                 STAGE_NARRATIVE_SYSTEM_V1, NEUTRAL_IMAGE_PROMPT_V1)
from .generation_prompts import STAGE_DISCOVERY_SYSTEM_V2, STAGE_COMPARE_SYSTEM_V2
from .generation_prompts import (STAGE_DISCOVERY_AGGREGATE_V1,
                                 STAGE_THEME_LOCAL_SYSTEM_V1,
                                 STAGE_THEME_MERGE_SYSTEM_V1,
                                 STAGE_CHAPTER_WRITE_SYSTEM_V1,
                                 STAGE_CHAPTER_HEADING_SYSTEM_V1)
logger = logging.getLogger(__name__)

from .models import (
    DirectionBatch, InvestigationDirection, MaterialSpan, ComparisonSuggestion,
    DirectionComparison, StageAnalysis, StructuredReportResponse, StructuredReportSection,
    StructuredReportCitation, ClassificationQuestion,
)

# Directions per discovery request. The per-request byte budget (REQUEST_CHAR_LIMIT)
# is the hard limit; this is the count cap that keeps one answer tractable. It
# was 3, so a PC.E01 report needed 172 sequential calls for 516 readable
# materials — the single largest share of the 56-minute report stage. Materials
# average ~2.3k prompt characters, so 10 fits the 26k budget with headroom.
BATCH_SIZE = 10
# Cross-batch review covers 8 directions per call; raise it in step with
# BATCH_SIZE so the second pass does not dominate the call count.
CROSS_REVIEW_BATCH = 16
# Concurrent LLM requests inside the report pipeline. The provider pool is
# sized for it (llm_service keeps 256 connections) and .env already sets
# LLM_MAX_CONCURRENCY=32 for the analysis stages; the report pipeline was the
# only caller left fully serial. Batches are independent, so fanning them out
# turns 365 sequential round trips into ~365/limit waves.
DEFAULT_REPORT_CONCURRENCY = 8


def report_concurrency(settings) -> int:
    """Fan-out for report LLM batches, bounded by the shared LLM budget."""
    try:
        value = int(getattr(settings, "llm_max_concurrency", DEFAULT_REPORT_CONCURRENCY))
    except (TypeError, ValueError):
        value = DEFAULT_REPORT_CONCURRENCY
    return max(1, min(value, 32))


async def _gather_bounded(coros, limit: int):
    """Run coroutines concurrently, at most ``limit`` at a time, in order.

    Exceptions are returned in place (like gather(return_exceptions=True)) so a
    rejected batch cannot cancel its siblings; callers inspect each slot.
    """
    semaphore = asyncio.Semaphore(max(1, limit))

    async def guarded(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(guarded(c) for c in coros), return_exceptions=True)

READING_CHARS = 4000
REQUEST_CHAR_LIMIT = 26000
# Narrative shape limits. The prompt asks for 3-6 sections per batch of 400-1200
# characters; the validator enforces a slightly wider window so a compliant
# answer is never rejected, while still refusing the degenerate "one 50-char
# section" that used to pass and let a report grow to 50 chapters.
_MAX_SECTIONS_PER_BATCH = 8
# Heading length the prompt asks for. Over-long labels are shortened rather
# than rejecting the batch; see the validation loop in compose_stage_narrative.
_MAX_HEADING_CHARS = 24
# Floor on a single section. The prompt asks for 400+ characters, but a batch
# covering one narrow artifact can legitimately be shorter, so the floor only
# rejects stubs. 80 characters still rules out the degenerate one-liner that the
# old 50-character floor accepted.
_MIN_SECTION_CHARS = 80
# Total narrative budget across all batches. 50 chapters x ~1000 chars was the
# observed runaway; a readable report stays well under this ceiling.
_MAX_TOTAL_NARRATIVE_CHARS = 30000
# Hard ceiling on rendered chapters, so the final report cannot exceed a
# length a reader can actually work through even when every batch is full.
_MAX_REPORT_CHAPTERS = 20
# Directions per narrative batch. Batching used to be driven only by request
# bytes, which packed 31-36 directions into each of 8 batches on PC.E01: the
# model had to summarize 35 materials inside one 8192-token answer while
# emitting 3-6 sections of 400-1200 characters, and batches 5-8 came back
# malformed. A batch now carries a set a single answer can actually cover.
_MAX_DIRECTIONS_PER_BATCH = 12
# Findings the narrative actually writes up. The full direction list stays in
# stage_analysis (the reader can drill into every material there); the prose
# covers the best-supported subset so the report remains readable.
_MAX_NARRATIVE_DIRECTIONS = 60
# The chapter budget is a hard reading limit: batches past it are not merged
# into the last chapter (that stitched unrelated findings together and produced
# a 7k-character wall) — they are dropped and recorded as a warning.
GENERIC_QUESTIONS = (
    ("g_funds", "材料中的资金活动、金额或业务安排有哪些需要核查的差异与缺口？"),
    ("g_identity", "材料中的人员、账号和设备关系有哪些有依据的线索与未知信息？"),
    ("g_activity", "通讯、网络与位置活动有哪些需要核对的异常、时序或其他解释？"),
    ("g_context", "材料是否可能属于正常业务、培训、示例、虚构或背景资料？"),
)


def stage_questions(envelope):
    values = [ClassificationQuestion(question_id=key, text=text, origin="generic") for key, text in GENERIC_QUESTIONS]
    if envelope.analysis_mode == "case_guided":
        from .generation_classification import classification_questions
        values.extend(classification_questions(envelope.case_description))
    return tuple(values)


def validate_materialized_sources(originals, rendered):
    if len(originals) != len(rendered):
        raise ValueError("BASELINE_MATERIAL_COVERAGE_CHANGED")
    for source, current in zip(originals, rendered):
        if (source.material_id, source.evidence_key, source.source_sha256) != (
            current.material_id, current.evidence_key, current.source_sha256
        ):
            raise ValueError("BASELINE_SOURCE_CHANGED")
        if source.kind != "image" and source != current:
            raise ValueError("BASELINE_TEXT_CHANGED")
        if source.kind == "image" and (current.media_base64 or current.kind not in ("machine_visual", "unavailable")):
            raise ValueError("BASELINE_VISUAL_CONTRACT_CHANGED")


async def materialize_images(envelope, llm):
    if envelope.baseline:
        validate_materialized_sources(envelope.neutral_materials, envelope.baseline.materials)
        return envelope.baseline.materials
    values = []
    for source in envelope.neutral_materials:
        if source.kind != "image":
            values.append(source)
            continue
        try:
            response = await llm.analyze_image(
                image_data=base64.b64decode(source.media_base64, validate=True),
                prompt=NEUTRAL_IMAGE_PROMPT_V1,
            )
            if response.get("success") is False or response.get("error_type"):
                raise ValueError("VISUAL_SOURCE_UNREADABLE")
            text = (response.get("analysis") or {}).get("description") or ""
            if not text.strip():
                raise ValueError("EMPTY_VISUAL_OBSERVATION")
            values.append(material(source.material_id, source.evidence_key, kind="machine_visual",
                text=text, source_hash=source.source_sha256, status="partial",
                limitations=(*source.limitations, "MACHINE_VISUAL_NOT_ORIGINAL_TEXT")))
        except Exception:
            values.append(material(source.material_id, source.evidence_key,
                source_hash=source.source_sha256, limitations=(*source.limitations, "NEUTRAL_VISUAL_FAILED")))
    return tuple(values)


def prompt_material(source, text=None):
    return {"material_id": source.material_id, "source_kind": source.kind,
            "text": source.text[:READING_CHARS] if text is None else text,
            "source_group": source.source_sha256,
            "coverage": source.status, "limitations": source.limitations}


def _prompt_row_size(source) -> int:
    """Serialized size of one material row in a discovery request."""
    return len(json.dumps(prompt_material(source), ensure_ascii=False))


def _pack_batches(materials, *, max_items=None, max_chars=None):
    """Split materials into batches bounded by both item count and prompt size.

    A material's prompt row is dominated by its excerpt, so sizes vary widely.
    Packing by count alone overflows the request budget for a batch of large
    excerpts and wastes it on a batch of tiny files; packing by size alone can
    put 100 tiny files in one request. Bound both.

    A single material larger than the budget still gets its own batch — the
    request guard then rejects it honestly rather than silently shrinking the
    evidence set.
    """
    max_items = BATCH_SIZE if max_items is None else max_items
    max_chars = (REQUEST_CHAR_LIMIT - _REQUEST_OVERHEAD_CHARS if max_chars is None
                 else max_chars)
    batches, current, size = [], [], 0
    for source in materials:
        row_size = _prompt_row_size(source)
        if current and (len(current) >= max_items or size + row_size > max_chars):
            batches.append(current)
            current, size = [], 0
        current.append(source)
        size += row_size
    if current:
        batches.append(current)
    return batches


# Envelope the discovery request adds around the material rows (mode, case
# context, baseline directions, key names). Reserved so a full batch still
# fits REQUEST_CHAR_LIMIT.
_REQUEST_OVERHEAD_CHARS = 2000


def validate_refs(refs, sent, full):
    result = []
    for ref in refs:
        # A material outside the batch (or outside the frozen set) is a
        # contract violation, not an imperfect quote: it cannot be rescued by
        # prefix matching and must fail the batch as before.
        if ref.material_id not in sent or ref.material_id not in full or not ref.quote.strip():
            raise ValueError("DIRECTION_SOURCE_QUOTE_INVALID")
        if ref.quote not in sent[ref.material_id] or ref.quote not in full[ref.material_id].text:
            # The model may have returned a quote longer than the display
            # window whose tail does not match exactly (re-wrapped whitespace,
            # a truncated JSON blob). Retry with the longest prefix that does
            # occur verbatim, so one imperfect quote cannot discard the batch.
            quote = _verbatim_prefix(ref.quote, sent[ref.material_id],
                                     full[ref.material_id].text)
            if quote is None:
                raise ValueError("DIRECTION_SOURCE_QUOTE_INVALID")
        else:
            quote = ref.quote
        start = full[ref.material_id].text.index(quote)
        result.append(MaterialSpan(material_id=ref.material_id, quote=quote,
                                   character_start=start, character_end=start + len(quote),
                                   ambiguous=full[ref.material_id].text.find(quote, start + 1) >= 0))
    return tuple(result)


# Longest quote the report renders; mirrors MaterialQuote's historical cap.
_QUOTE_DISPLAY_CHARS = 300


def _verbatim_prefix(quote, sent_text, full_text):
    """Longest prefix of ``quote`` that appears verbatim in both texts.

    Used only after the exact quote failed: it keeps the evidence binding real
    (the returned string is genuinely in the source) instead of accepting text
    the model paraphrased. Returns None when no usable prefix exists.
    """
    limit = min(len(quote), _QUOTE_DISPLAY_CHARS)
    # Try the display window first, then fall back to shorter boundaries at
    # whitespace so a mid-token cut does not force a much shorter quote.
    candidates = [limit]
    candidates.extend(index for index in range(limit - 1, 0, -1)
                      if quote[index].isspace())
    for end in candidates[:64]:
        candidate = quote[:end].rstrip()
        if (candidate and candidate in sent_text and candidate in full_text):
            return candidate
    return None


def parse_directions(content, sent, full, envelope, allowed_baselines):
    if not isinstance(content, str) or len(content) > 24000:
        raise ValueError("DIRECTION_OUTPUT_BUDGET_EXCEEDED")
    parsed = DirectionBatch.model_validate(_loads_strict(content))
    results = []
    for value in parsed.directions:
        if not set(value.baseline_direction_ids) <= allowed_baselines:
            raise ValueError("DIRECTION_BASELINE_OUTSIDE_SCOPE")
        if value.case_context_quote and value.case_context_quote not in envelope.case_description:
            raise ValueError("DIRECTION_CASE_CONTEXT_QUOTE_INVALID")
        supports = validate_refs(value.supporting_refs, sent, full)
        counters = validate_refs(value.counter_refs, sent, full)
        if value.finding_kind == "observation" and not supports:
            raise ValueError("OBSERVATION_WITHOUT_SOURCE")
        if value.finding_kind == "hypothesis" and not (value.missing_information or value.alternative_explanations):
            raise ValueError("HYPOTHESIS_REQUIRES_LIMITS")
        if not supports and not counters:
            if envelope.analysis_mode != "case_guided" or not value.case_context_quote or value.finding_kind != "hypothesis":
                raise ValueError("DIRECTION_WITHOUT_SOURCE")
            origin = "case_only"
        else:
            origin = "material" if envelope.analysis_mode == "evidence_only" else (
                "reinterpreted" if value.baseline_direction_ids else "new_candidate")
        payload = {**value.model_dump(mode="json"), "supporting_refs": supports, "counter_refs": counters, "origin": origin}
        supporting_ids = {ref.material_id for ref in supports}
        groups = [full[key].source_sha256 for key in supporting_ids]
        if groups and all(groups) and len(set(groups)) < len(groups):
            payload["missing_information"] = (*value.missing_information[:7],
                "引用含相同来源内容，不能据此计作独立佐证，仍需核对材料形成关系。")
        identity = "d_" + digest(value.model_dump(mode="json"))[:24]
        results.append(InvestigationDirection(direction_id=identity, **payload))
    return results


async def discover_directions(envelope, materials, llm, concurrency: int = 1):
    full = {m.material_id: m for m in materials}
    readable = [m for m in materials if m.text and m.status != "unavailable"]
    directions, warnings = {}, []
    baseline = envelope.baseline.directions if envelope.baseline else ()

    async def run(rows, prior=(), summaries=()):
        """One discovery request. Returns its validated directions.

        It does not touch the shared dict: concurrent batches would interleave
        writes and the "at least one batch succeeded" counter would race. The
        caller merges results after all batches settle.
        """
        sent = {r["material_id"]: r["text"] for r in rows}
        request = json.dumps({
            "analysis_mode": envelope.analysis_mode,
            "case_context": envelope.case_description,
            "materials": rows,
            "baseline_directions": [{"direction_id": d.direction_id, "title": d.title,
                                    "description": d.description[:300]} for d in prior],
            "derived_summaries_not_evidence": list(summaries),
        }, ensure_ascii=False)
        if len(request) > REQUEST_CHAR_LIMIT:
            raise ValueError("STAGE_INPUT_BUDGET_EXCEEDED")
        # Aggregated discovery asks the model to group the batch's materials by
        # subject instead of writing one observation per file. That is what
        # turns hundreds of near-duplicate directions into a few dozen
        # substantive ones; the v1 prompt caps a batch at 4 directions and
        # requires a quote per direction, which reads as "one file, one
        # finding" (532 directions for 767 materials on PC.E01, 258 of them
        # quoting exactly one file). Kept behind its own version string so
        # already-admitted generations keep executing their recorded contract.
        if envelope.prompt_version.endswith(":v3"):
            system_prompt = STAGE_DISCOVERY_AGGREGATE_V1
        elif envelope.prompt_version.endswith(":v2"):
            system_prompt = STAGE_DISCOVERY_SYSTEM_V2
        else:
            system_prompt = STAGE_DISCOVERY_SYSTEM_V1
        response = await llm.chat_completion(
            system_prompt, request, max_tokens=4096, temperature=0.0)
        return parse_directions(response.get("content", ""), sent, full, envelope,
                                {d.direction_id for d in prior})

    def merge(values):
        directions.update((d.direction_id, d) for d in values)

    # First pass: one request per material batch, fanned out up to
    # `concurrency`. Batches are independent (each reads only its own
    # materials), so the provider sees `concurrency` requests in flight
    # instead of one at a time.
    jobs, labels = [], []
    # Group by the serialized prompt budget, not by material count alone.
    # Materials differ by ~20x in prompt size (a 4k-character excerpt vs a
    # 39-character config file), so a fixed count of 10 produced requests from
    # 2.4k to 44k characters: 24 of 52 batches exceeded REQUEST_CHAR_LIMIT and
    # were dropped before any LLM call, losing nearly half the evidence.
    for index, chosen in enumerate(_pack_batches(readable)):
        ids = {m.material_id for m in chosen}
        prior = [d for d in baseline if any(r.material_id in ids for r in (*d.supporting_refs, *d.counter_refs))][:4]
        jobs.append(run([prompt_material(m) for m in chosen], prior))
        labels.append(f"DIRECTION_BATCH_REJECTED_{index + 1}")
    successful = 0
    for label, outcome in zip(labels, await _gather_bounded(jobs, concurrency)):
        if isinstance(outcome, BaseException):
            warnings.append(label)
            continue
        merge(outcome)
        successful += 1
    if not successful:
        raise ValueError("NO_VALIDATED_NEUTRAL_ANALYSIS")
    # A bounded cross-batch pass joins literal supports from prior batches.
    # Original findings stay present even if this additional review fails.
    first_pass = list(directions.values())
    if len(readable) > BATCH_SIZE and len(first_pass) > 1:
        jobs, labels = [], []
        for start in range(0, len(first_pass), CROSS_REVIEW_BATCH):
            chosen = first_pass[start:start + CROSS_REVIEW_BATCH]
            snippets = {}
            for d in chosen:
                for ref in (*d.supporting_refs, *d.counter_refs):
                    snippets.setdefault(ref.material_id, []).append(ref.quote)
            rows = [prompt_material(full[key], "\n".join(dict.fromkeys(quotes)))
                    for key, quotes in snippets.items()]
            prior_ids = {key for d in chosen for key in d.baseline_direction_ids}
            jobs.append(run(rows, [d for d in baseline if d.direction_id in prior_ids],
                            [{"title": d.title, "description": d.description[:300]} for d in chosen]))
            labels.append(f"CROSS_MATERIAL_REVIEW_REJECTED_{start // CROSS_REVIEW_BATCH + 1}")
        for label, outcome in zip(labels, await _gather_bounded(jobs, concurrency)):
            if isinstance(outcome, BaseException):
                warnings.append(label)
                continue
            merge(outcome)
    return tuple(directions.values()), tuple(warnings)


async def compare_directions(envelope, materials, llm, current_directions=(),
                             concurrency: int = 1):
    if envelope.baseline is None:
        return (), ()
    full = {m.material_id: m for m in materials}

    async def compare_one(prior):
        """One baseline comparison. Returns (comparison, warning_or_None)."""
        snippets = {}
        prior_sources = {r.material_id for r in (*prior.supporting_refs, *prior.counter_refs)}
        related = [d for d in current_directions if prior.direction_id in d.baseline_direction_ids
                   or any(r.material_id in prior_sources for r in (*d.supporting_refs, *d.counter_refs))]
        refs = [*prior.supporting_refs, *prior.counter_refs,
                *(r for d in related for r in (*d.supporting_refs, *d.counter_refs))]
        for ref in refs:
            source = full.get(ref.material_id)
            if source is None or source.text[ref.character_start:ref.character_end] != ref.quote:
                raise ValueError("BASELINE_QUOTE_CHANGED")
            snippets.setdefault(ref.material_id, []).append(
                source.text[max(0, ref.character_start - 160):ref.character_end + 160])
        sent = {key: "\n".join(dict.fromkeys(values)) for key, values in snippets.items()}
        try:
            request = json.dumps({
                "case_context": envelope.case_description,
                "baseline_direction": prior.model_dump(mode="json"),
                "current_directions_not_evidence": [{"title": d.title, "description": d.description[:300]} for d in related],
                "materials": [prompt_material(full[key], text) for key, text in sent.items()],
            }, ensure_ascii=False)
            if len(request) > REQUEST_CHAR_LIMIT:
                raise ValueError("COMPARISON_INPUT_BUDGET_EXCEEDED")
            response = await llm.chat_completion(STAGE_COMPARE_SYSTEM_V2 if envelope.prompt_version.endswith(":v2") else STAGE_COMPARE_SYSTEM_V1, request, max_tokens=2048, temperature=0.0)
            content = response.get("content", "")
            if not isinstance(content, str) or len(content) > 16000:
                raise ValueError("COMPARISON_OUTPUT_BUDGET_EXCEEDED")
            value = ComparisonSuggestion.model_validate(_loads_strict(content))
            if value.baseline_direction_id != prior.direction_id:
                raise ValueError("COMPARISON_BASELINE_MISMATCH")
            supports = validate_refs(value.supporting_refs, sent, full)
            counters = validate_refs(value.counter_refs, sent, full)
            if value.case_context_quote and value.case_context_quote not in envelope.case_description:
                raise ValueError("COMPARISON_CONTEXT_QUOTE_INVALID")
            if value.status in ("supported", "revised") and not supports:
                raise ValueError("COMPARISON_REQUIRES_SUPPORT")
            if value.status in ("weakened", "contradicted") and not counters:
                raise ValueError("COMPARISON_REQUIRES_COUNTER_SOURCE")
            if value.status == "case_only" and (not value.case_context_quote or supports or counters):
                raise ValueError("CASE_ONLY_COMPARISON_REQUIRES_CONTEXT_ONLY")
            return DirectionComparison(**{
                **value.model_dump(mode="json"), "supporting_refs": supports, "counter_refs": counters,
            }), None
        except (ValueError, KeyError, TypeError):
            return DirectionComparison(baseline_direction_id=prior.direction_id,
                status="insufficient", reason="本轮比较未通过来源校验，不能据此改变首次判断。",
                missing_information=("需要人工核对该方向及其原始材料。",)), \
                f"COMPARISON_REJECTED_{prior.direction_id}"

    # Comparisons are independent (one per baseline direction); fan them out
    # and keep baseline order so the difference section stays deterministic.
    priors = tuple(envelope.baseline.directions)
    comparisons, warnings = [], []
    outcomes = await _gather_bounded([compare_one(p) for p in priors], concurrency)
    for prior, outcome in zip(priors, outcomes):
        if isinstance(outcome, BaseException):
            comparisons.append(DirectionComparison(baseline_direction_id=prior.direction_id,
                status="insufficient", reason="本轮比较未通过来源校验，不能据此改变首次判断。",
                missing_information=("需要人工核对该方向及其原始材料。",)))
            warnings.append(f"COMPARISON_REJECTED_{prior.direction_id}")
            continue
        value, warning = outcome
        comparisons.append(value)
        if warning:
            warnings.append(warning)
    return tuple(comparisons), tuple(warnings)


def stage_citation_name(evidence_key: str) -> str:
    """File name used in narrative text; the reader places citation chips by it."""
    path = evidence_key[5:] if evidence_key.startswith("file:") else evidence_key
    return path.rsplit("/", 1)[-1] if "/" in path else path


# ---------------------------------------------------------------------------
# Theme induction (report shape v3, stages 1-2).
#
# The v2 narrative wrote one chapter per batch of directions. With one
# direction per readable material that produced 21 chapters of per-file
# inventory on PC.E01 — three of them about SVCHOST alone — because nothing
# ever looked at the whole set before writing. These two stages add that
# missing global step: directions are grouped into themes first, and the
# writing stage (stage 3) then writes one chapter per theme.
#
# The model only ever returns direction_id membership. Quotes, evidence keys
# and citation ids are re-attached by the caller from the frozen directions, so
# a hallucinated id is discarded instead of becoming a fabricated citation.
# ---------------------------------------------------------------------------

_THEME_NAME_MAX_CHARS = 20
# A theme is one chapter, so it must stay small enough to write as one. The
# prompt asks for <=25 directions, but the model grouped 218 directions under
# "系统进程与组件执行痕迹" on PC.E01, which then split into 4 parts that each
# concluded "常规系统活动" — the same finding stated four times. Oversized
# themes are split here rather than trusted to the prompt.
_THEME_MAX_DIRECTIONS = 25
# A theme smaller than this cannot carry a chapter; it is a fragment.
_THEME_MIN_DIRECTIONS = 8
# Folding only applies once the grouping is clearly fragmented; a report with a
# handful of genuinely small themes should keep them.
_THEME_FRAGMENT_FOLD_MIN_THEMES = 12
_THEME_COUNT_MAX = 24


def _direction_projection(direction) -> dict:
    """Minimal per-direction row for induction: id, label, kind, short text.

    Quotes and full descriptions stay out: induction only needs to recognize
    what a direction is about, and including quotes tripled the payload.
    """
    return {
        "id": direction.direction_id,
        "title": direction.title[:60],
        "kind": direction.finding_kind,
        "description": direction.description[:120],
    }


def _chunk_directions(directions, limit: int = REQUEST_CHAR_LIMIT):
    """Split directions into induction chunks that fit one request each.

    Sizes are measured from the serialized payload the request actually sends.
    Arithmetic estimates drifted (field order, escaping, separators) and let
    chunks exceed the limit by tens of characters.
    """
    chunks, current, rows, size = [], [], [], 0
    for direction in directions:
        row = _direction_projection(direction)
        candidate = [*rows, row]
        candidate_size = len(_theme_payload(candidate))
        if current and candidate_size > limit:
            chunks.append(current)
            current, rows, size = [], [], 0
            candidate_size = len(_theme_payload([row]))
        current.append(direction)
        rows.append(row)
        size = candidate_size
    if current:
        chunks.append(current)
    return chunks


def _theme_payload(rows) -> str:
    return json.dumps({"directions": rows}, ensure_ascii=False)


def _parse_local_themes(content: str, allowed_ids: set[str]):
    """Parse one induction answer into (themes, unassigned_ids).

    Enforces the contract the prompt states: every id exactly once, no invented
    ids, 1.._THEME_COUNT_MAX themes. Anything the model got wrong is recovered
    rather than failing the whole stage — a missing id becomes unassigned, an
    invented id is dropped, and a duplicate assignment keeps the first theme.
    """
    parsed = _loads_strict(content)
    if not isinstance(parsed, dict):
        raise ValueError("THEME_OUTPUT_INVALID")
    raw_themes = parsed.get("themes")
    raw_unassigned = parsed.get("no_theme") or []
    if not isinstance(raw_themes, list):
        raise ValueError("THEME_OUTPUT_INVALID")
    seen: set[str] = set()
    themes = []
    for entry in raw_themes:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        ids = entry.get("ids")
        if not isinstance(name, str) or not name.strip() or not isinstance(ids, list):
            continue
        name = name.strip()[:_THEME_NAME_MAX_CHARS]
        members = []
        for direction_id in ids:
            if not isinstance(direction_id, str):
                continue
            if direction_id not in allowed_ids:
                continue  # invented id: never becomes a citation
            if direction_id in seen:
                continue  # duplicate assignment: first theme wins
            seen.add(direction_id)
            members.append(direction_id)
        if members:
            themes.append({"name": name, "ids": members})
    unassigned = []
    for direction_id in raw_unassigned:
        if isinstance(direction_id, str) and direction_id in allowed_ids and direction_id not in seen:
            seen.add(direction_id)
            unassigned.append(direction_id)
    # Anything the model silently dropped is still evidence; keep it addressable.
    for direction_id in sorted(allowed_ids - seen):
        unassigned.append(direction_id)
    return themes, unassigned


def _parse_merge_themes(content: str, local_themes):
    """Parse the global merge answer into global themes over local themes.

    Returns ``(global_themes, unmerged_local_indices)`` where each global theme
    is ``{"name": str, "locals": [index, ...]}``.
    """
    parsed = _loads_strict(content)
    if not isinstance(parsed, dict):
        raise ValueError("THEME_MERGE_OUTPUT_INVALID")
    raw_themes = parsed.get("themes")
    if not isinstance(raw_themes, list):
        raise ValueError("THEME_MERGE_OUTPUT_INVALID")
    # (chunk, name) -> local index; names are unique per chunk by construction.
    index_by_key = {(entry["chunk"], entry["name"]): i
                    for i, entry in enumerate(local_themes)}
    used: set[int] = set()
    themes = []
    for entry in raw_themes:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        sources = entry.get("sources")
        if not isinstance(name, str) or not name.strip() or not isinstance(sources, list):
            continue
        name = name.strip()[:_THEME_NAME_MAX_CHARS]
        members = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            try:
                key = (int(source.get("chunk")), str(source.get("name")))
            except (TypeError, ValueError):
                continue
            index = index_by_key.get(key)
            if index is None or index in used:
                continue
            used.add(index)
            members.append(index)
        if members:
            themes.append({"name": name, "locals": members})
    unmerged = [i for i in range(len(local_themes)) if i not in used]
    return themes, unmerged


# Tokens that appear in almost every theme name and therefore say nothing about
# what distinguishes it. Grouping on these would merge unrelated themes.
_THEME_STOPWORDS = frozenset({
    "事件", "记录", "执行", "活动", "材料", "日志", "系统", "组件", "解析",
    "异常", "痕迹", "观察", "预取", "文件", "相关", "信息", "内容", "状态",
    "多次", "集中", "常规", "指向", "显示", "出现", "存在", "报告", "数据",
})


def _theme_tokens(name: str) -> set[str]:
    """Content tokens of a theme name, used to decide whether two belong together.

    Splits on the separators the model uses, keeps ASCII identifiers whole, and
    breaks CJK runs into overlapping 2-character grams: "事件日志时间倒置" and
    "空事件日志" then share 事件/日志, which is what tells us they belong to one
    subject. Generic words are dropped so they cannot merge unrelated themes.
    """
    tokens = set()
    for raw in re.split(r"[\s、，,/|（）()与和及]+", name):
        raw = raw.strip()
        if not raw:
            continue
        for piece in re.findall(r"[A-Za-z0-9_.\-]+|[\u4e00-\u9fff]+", raw):
            lowered = piece.lower()
            if re.fullmatch(r"[a-z0-9_.\-]+", lowered):
                if len(lowered) >= 2 and lowered not in _THEME_STOPWORDS:
                    tokens.add(lowered)
                continue
            # CJK: bigrams plus the whole run when short.
            grams = [lowered] if len(lowered) <= 4 else []
            grams += [lowered[i:i + 2] for i in range(len(lowered) - 1)]
            tokens.update(g for g in grams if g not in _THEME_STOPWORDS)
    return tokens


def _consolidate_themes(themes, warnings):
    """Merge themes whose names share a distinguishing token.

    The merge stage often returns its input unchanged, leaving one theme per
    artifact ("DLLHOST外壳扩展" three times, 38 single-local themes). Those are
    fragments of one subject, not separate chapters. Themes are joined when
    their names share a content token; a theme that shares nothing stays on its
    own so genuinely distinct subjects are not flattened together.
    """
    if len(themes) <= 1:
        return themes
    groups: list[dict] = []       # {"name": str, "tokens": set, "directions": list}
    for theme in themes:
        tokens = _theme_tokens(theme["name"])
        target = None
        for group in groups:
            if tokens & group["tokens"]:
                target = group
                break
        if target is None:
            groups.append({"name": theme["name"], "tokens": set(tokens),
                           "directions": list(theme["directions"])})
            continue
        target["directions"].extend(theme["directions"])
        target["tokens"] |= tokens
        warnings.append(f"THEME_CONSOLIDATED_{theme['name']}")
    return groups


async def induce_themes(directions, llm, *, concurrency: int = 1,
                        split_oversized: bool = True):
    """Group directions into report themes (stages 1-2 of the v3 shape).

    Stage 1 shards the directions by request budget and asks the model to group
    each shard. Stage 2 merges those local themes into one global set, which is
    what prevents the same artifact (SVCHOST: 32 directions spread across
    shards) from becoming several chapters.

    Returns ``(themes, warnings)`` where each theme is
    ``{"name": str, "directions": tuple[InvestigationDirection, ...]}``.
    Raises ValueError only when no usable grouping exists at all.
    """
    directions = tuple(directions)
    if not directions:
        return (), ()
    by_id = {d.direction_id: d for d in directions}
    allowed = set(by_id)
    warnings: list[str] = []
    chunks = _chunk_directions(directions)

    async def group_chunk(index, chunk):
        rows = [_direction_projection(d) for d in chunk]
        payload = _theme_payload(rows)
        chunk_ids = {d.direction_id for d in chunk}
        response = await llm.chat_completion(
            STAGE_THEME_LOCAL_SYSTEM_V1, payload,
            max_tokens=4096, temperature=0.0)
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("THEME_OUTPUT_UNUSABLE")
        return index, _parse_local_themes(content, chunk_ids)

    results = await _gather_bounded(
        [group_chunk(i, c) for i, c in enumerate(chunks)], concurrency)
    local_themes = []          # [{"chunk": int, "name": str, "ids": [...]}]
    unassigned_ids: list[str] = []
    for index, outcome in enumerate(results):
        if isinstance(outcome, BaseException):
            warnings.append(f"THEME_LOCAL_REJECTED_{index + 1}")
            unassigned_ids.extend(d.direction_id for d in chunks[index])
            continue
        _index, (themes, unassigned) = outcome
        for theme in themes:
            local_themes.append({"chunk": index + 1, "name": theme["name"],
                                 "ids": theme["ids"]})
        unassigned_ids.extend(unassigned)

    if not local_themes:
        # Nothing grouped: one fallback theme keeps every direction addressable.
        return ({"name": "材料观察汇总",
                 "directions": tuple(by_id[i] for i in sorted(allowed))},), tuple(warnings)

    if len(chunks) == 1:
        merged_themes = [{"name": t["name"], "locals": [i]}
                         for i, t in enumerate(local_themes)]
        unmerged: list[int] = []
    else:
        merge_payload = json.dumps({"groups": [
            {"chunk": chunk_index,
             "themes": [{"name": t["name"], "size": len(t["ids"])}
                        for t in local_themes if t["chunk"] == chunk_index]}
            for chunk_index in range(1, len(chunks) + 1)
        ]}, ensure_ascii=False)
        try:
            response = await llm.chat_completion(
                STAGE_THEME_MERGE_SYSTEM_V1, merge_payload,
                max_tokens=4096, temperature=0.0)
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("THEME_MERGE_OUTPUT_UNUSABLE")
            merged_themes, unmerged = _parse_merge_themes(content, local_themes)
        except (ValueError, KeyError, TypeError) as exc:
            # The merge is an optimization; local themes are still a valid
            # grouping, so degrade instead of losing the whole induction.
            logger.warning("Theme merge rejected (%s); using local themes", exc)
            warnings.append("THEME_MERGE_REJECTED")
            merged_themes = [{"name": t["name"], "locals": [i]}
                             for i, t in enumerate(local_themes)]
            unmerged = []

    themes = []
    for theme in merged_themes:
        local_indexes = theme["locals"]
        ids = [direction_id for index in local_indexes
               for direction_id in local_themes[index]["ids"]]
        unique_ids = list(dict.fromkeys(ids))
        # A global theme must stay writable as one chapter. When the merge
        # combines local themes past that size, keep the merge but split along
        # the LOCAL theme boundaries instead of slicing the direction list:
        # slicing produced 13 chapters all named "系统组件Prefetch执行记录（n）",
        # while local boundaries carry the distinctions induction already made.
        if len(unique_ids) > _THEME_MAX_DIRECTIONS and len(local_indexes) > 1:
            for index in local_indexes:
                members = tuple(by_id[i] for i in local_themes[index]["ids"] if i in by_id)
                if members:
                    themes.append({"name": local_themes[index]["name"],
                                   "directions": members})
            continue
        members = tuple(by_id[i] for i in unique_ids if i in by_id)
        if members:
            themes.append({"name": theme["name"], "directions": members})
    for index in unmerged:
        members = tuple(by_id[i] for i in local_themes[index]["ids"] if i in by_id)
        if members:
            themes.append({"name": local_themes[index]["name"], "directions": members})
    if unassigned_ids:
        members = tuple(by_id[i] for i in dict.fromkeys(unassigned_ids) if i in by_id)
        if members:
            # Name the bucket after what it actually holds. "未归类材料观察" is
            # an internal bookkeeping label, and it reached a published chapter
            # title verbatim. The lead artifact names the bucket well enough.
            lead = _piece_label("", members)
            name = lead if lead else "未归类材料观察"
            themes.append({"name": name, "directions": members})
            warnings.append(f"THEME_UNASSIGNED_{len(members)}")
    if not themes:
        raise ValueError("NO_VALIDATED_THEME")
    # Consolidate fragments. The merge stage frequently returns the input
    # unchanged (57 "global" themes, 38 of them a single local theme), so the
    # grouping is effectively one theme per object. Rather than dump every
    # fragment into the largest theme — which produced a 100+ direction theme
    # that then split into near-identical chapters — group themes by the object
    # or anomaly their names share. Names that share no keyword with anything
    # else stay as they are only if they carry enough evidence.
    themes = _consolidate_themes(themes, warnings)
    if not split_oversized:
        # Chapter packing balances chapter sizes itself. Splitting here first
        # would turn one theme into "（1/7）…（7/7）" fragments that the packer
        # then scatters across chapters, so every chapter ended up holding a
        # piece of the same few themes and no chapter could be named after one
        # subject. Keep the semantic groups intact and let the packer decide.
        return tuple(themes), tuple(warnings)
    # Split oversized themes deterministically. The prompt asks for small
    # themes, but one 218-direction theme survived it and then produced four
    # near-identical chapters. Splitting here keeps every chapter writable as
    # one unit and gives each part a distinguishing suffix, so the reader sees
    # four labelled sub-topics instead of four copies of the same heading.
    bounded = []
    for theme in themes:
        members = theme["directions"]
        if len(members) <= _THEME_MAX_DIRECTIONS:
            bounded.append(theme)
            continue
        groups = -(-len(members) // _THEME_MAX_DIRECTIONS)  # ceil
        for index in range(groups):
            chunk = members[index * _THEME_MAX_DIRECTIONS:
                            (index + 1) * _THEME_MAX_DIRECTIONS]
            if chunk:
                bounded.append({"name": f"{theme['name']}（{index + 1}/{groups}）",
                                "directions": chunk})
        warnings.append(
            f"THEME_SPLIT_{theme['name']}_{len(members)}")
    return tuple(bounded), tuple(warnings)


# ---------------------------------------------------------------------------
# Chapter packing (report shape v4).
#
# The chapter count has to be a property of the code, not of the model. Asking
# an LLM for "exactly 10 themes" produced 22/17/22/17/21 across five identical
# temperature-0 calls — precise counts are not something it does reliably. So
# induction groups the findings however it likes, and this stage packs those
# groups into a fixed number of chapters deterministically.
#
# LPT (Longest Processing Time first) is the standard makespan heuristic: place
# each group, largest first, into the currently lightest chapter. It keeps every
# group (nothing is dropped), keeps related findings together, and produces a
# balanced chapter size without any model involvement.
# ---------------------------------------------------------------------------

# Narrative chapters the report aims for. Total chapters are this plus the scope
# chapter and the advisory chapter, so 10 -> 12 published chapters.
_TARGET_NARRATIVE_CHAPTERS = 10
# Comparison rows named individually in the difference chapter. The rest are
# reported as a count: a case with 281 comparisons produced 13 chapters / 70k
# characters of near-identical "该方向得到材料支持" text.
_COMPARISON_DETAIL_LIMIT = 12
# Below this many groups the packing cannot fill the target without splitting a
# theme across chapters, so the target shrinks to the number of groups.
_MIN_GROUPS_FOR_FULL_TARGET = 4
# A theme larger than this multiple of the balanced chapter size is split, so
# one huge theme cannot occupy a chapter alone while others carry a fraction.
_THEME_SPLIT_FACTOR = 1.2


# Libraries every Windows process loads. Naming a chapter after one of them says
# nothing about the chapter: a PC.E01 chapter was titled "KERNEL32相关执行"
# because KERNEL32.DLL is the most-cited module across all prefetch records,
# while the chapter actually covered SVCHOST, DLLHOST, RUNTIMEBROKER and more.
_GENERIC_DEPENDENCIES = frozenset({
    "KERNEL32", "NTDLL", "KERNELBASE", "USER32", "GDI32", "ADVAPI32", "RPCRT4",
    "COMBASE", "SECHOST", "BCRYPT", "OLE32", "OLEAUT32", "MSVCP_WIN", "UCRTBASE",
    "CLBCATQ", "SHELL32", "SHCORE", "CRYPT32", "DPAPI", "WININET", "WINHTTP",
    "WS2_32", "IPHLPAPI", "NTASN1", "NCRYPT", "PROFAPI", "CRYPTBASE", "UXTHEME",
    "IMM32", "WIN32U", "GDI32FULL", "MSCTF", "CFGMGR32", "SETUPAPI", "DEVOBJ",
    "RPCSS", "WOW64", "WOW64BASE", "WOW64WIN", "WOW64CPU", "MSVCRT", "SHLWAPI",
    "COMCTL32", "MSI", "WINTRUST", "PSAPI", "VERSION", "IMAGEHLP", "DBGHELP",
})


def _piece_label(theme_name: str, piece, used: set[str] | None = None) -> str:
    """A distinguishing label for one slice of a split theme.

    Takes the executable or artifact name that appears most in this slice and
    is absent from the parent name, so three slices of one 166-direction theme
    get three different labels instead of repeating the parent heading.
    ``used`` carries labels already assigned to sibling slices: when the most
    common name is taken, the next one is used.
    """
    used = used if used is not None else set()
    counts: dict[str, int] = {}
    for direction in piece:
        for match in re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{2,}\.(?:EXE|exe|dll|DLL)",
                                f"{direction.title} {direction.description}"):
            key = match.upper()
            if key.rsplit(".", 1)[0] in _GENERIC_DEPENDENCIES:
                continue
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return theme_name
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for name, _count in ranked:
        stem = name.rsplit(".", 1)[0]
        if stem in theme_name.upper():
            continue
        label = f"{stem}相关执行"
        if label in used:
            continue
        used.add(label)
        return label
    return theme_name


def pack_themes_into_chapters(themes, target: int = _TARGET_NARRATIVE_CHAPTERS):
    """Pack theme groups into at most ``target`` chapter bins.

    Returns ``(chapters, warnings)`` where each chapter is
    ``{"name": str, "themes": [theme, ...]}``. Every theme lands in exactly one
    chapter; the chapter count is ``min(target, len(themes))``.

    A theme far larger than a balanced chapter is split across chapters first.
    Without that, four big themes (34/22/16/15 directions) each occupied a
    chapter alone while the other six chapters carried 13-16 — a 21-direction
    spread that makes one chapter four times another. Splitting at 1.2x the
    ideal brings the spread to 7. The cost is that a split theme's findings can
    appear in two chapters; each part keeps the theme name so the reader can
    still see they belong together.

    Deterministic: the same themes always produce the same chapters, which is
    what makes the chapter count a testable property instead of a model trait.
    """
    groups = [theme for theme in themes if theme["directions"]]
    if not groups:
        return [], ()
    warnings = []
    bins = min(target, len(groups))
    if bins < target:
        warnings.append(f"CHAPTER_TARGET_REDUCED_{bins}_OF_{target}")

    total = sum(len(theme["directions"]) for theme in groups)
    ideal = total / bins
    # Split oversized themes into near-ideal pieces so every chapter can carry
    # a comparable amount of evidence.
    pieces = []
    for theme in groups:
        members = theme["directions"]
        if len(members) <= ideal * _THEME_SPLIT_FACTOR or len(members) < 2:
            pieces.append(theme)
            continue
        count = max(2, round(len(members) / (ideal * _THEME_SPLIT_FACTOR)))
        size = -(-len(members) // count)
        parts = [members[index:index + size]
                 for index in range(0, len(members), size)]
        parts = [part for part in parts if part]
        used_labels: set[str] = set()
        for index, piece in enumerate(parts):
            # Give each piece a distinguishing label. A 166-direction theme
            # split three ways produced three chapters all named after the
            # parent theme, so the reader saw the same heading repeated. The
            # label comes from what that piece actually contains: its most
            # common artifact name, which is what differs between the pieces.
            pieces.append({"name": _piece_label(theme["name"], piece, used_labels),
                           "directions": piece})
        warnings.append(f"THEME_SPLIT_FOR_BALANCE_{theme['name']}_{len(parts)}")

    # Largest first: LPT's bound depends on processing the big items early.
    ordered = sorted(
        range(len(pieces)),
        key=lambda i: (-len(pieces[i]["directions"]), pieces[i]["name"]),
    )
    buckets: list[list[int]] = [[] for _ in range(bins)]
    loads = [0] * bins
    for index in ordered:
        lightest = min(range(bins), key=lambda b: (loads[b], b))
        buckets[lightest].append(index)
        loads[lightest] += len(pieces[index]["directions"])
    chapters = []
    for bucket in buckets:
        if not bucket:
            continue
        members = [pieces[i] for i in bucket]
        # The chapter takes its name from its largest theme; the writer is told
        # the other themes too and may synthesize a broader heading.
        lead = max(members, key=lambda t: (len(t["directions"]), t["name"]))
        chapters.append({"name": lead["name"], "themes": members})
    return chapters, tuple(warnings)


def chapter_directions(chapter):
    """All directions in a chapter, in theme order."""
    return tuple(
        direction
        for theme in chapter["themes"]
        for direction in theme["directions"]
    )


# A chapter longer than this is written in parts that share the chapter title.
# 600-2000 characters is the target body; the ceiling only rejects runaways.
_CHAPTER_MIN_CHARS = 300
_CHAPTER_MAX_CHARS = 4000


def _chapter_write_row(direction, cid) -> dict:
    """One direction as the chapter writer sees it: label, text, quotes."""
    return {
        "title": direction.title,
        "kind": direction.finding_kind,
        "description": direction.description,
        "supporting": [
            {"file": cid.get(ref.material_id, ""), "quote": ref.quote}
            for ref in direction.supporting_refs
        ],
        "counter": [
            {"file": cid.get(ref.material_id, ""), "quote": ref.quote}
            for ref in direction.counter_refs
        ],
        "missing_information": list(direction.missing_information)[:3],
        "alternative_explanations": list(direction.alternative_explanations)[:2],
    }


def _split_chapter_rows(rows, limit: int = REQUEST_CHAR_LIMIT):
    """Split one chapter's rows into write requests that fit the budget."""
    parts, current = [], []
    for row in rows:
        candidate = [*current, row]
        if current and len(json.dumps({"directions": candidate}, ensure_ascii=False)) > limit:
            parts.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


# Phrases a chapter uses when it declares a topic has no evidence. Every
# direction in the chapter was selected because it HAS evidence, so these
# statements contradict the chapter's own contents — a PC.E01 chapter said
# "18 份 Prefetch 记录" and then "未提供任何直接指向该组件的发现".
_NO_EVIDENCE_CLAIM_RE = re.compile(
    r"未提供任何.{0,30}?(?:发现|材料|记录|证据|引文)"
    r"|无法就.{0,30}?作出任何结论"
    r"|(?:本章|本批)(?:材料|方向)?(?:中)?(?:未|没有)(?:包含|提供|出现).{0,20}?(?:发现|记录|材料|证据)"
    r"|(?:未|没有)(?:提供|包含).{0,12}?(?:相关|直接).{0,12}?(?:发现|材料|记录)"
)


def _parse_chapter_section(content: str):
    """Parse one chapter answer into (heading, text), enforcing size limits."""
    parsed = _loads_strict(content)
    if not isinstance(parsed, dict):
        raise ValueError("CHAPTER_SECTION_INVALID")
    heading = parsed.get("heading")
    text = parsed.get("content")
    if not isinstance(text, str):
        raise ValueError("CHAPTER_SECTION_INVALID")
    text = strip_material_ids(text.strip())
    if len(text) < _CHAPTER_MIN_CHARS:
        raise ValueError("CHAPTER_SECTION_TOO_SHORT")
    if _NO_EVIDENCE_CLAIM_RE.search(text):
        # A chapter must not deny its own evidence. Retry rather than publish a
        # self-contradicting chapter.
        raise ValueError("CHAPTER_DENIES_OWN_EVIDENCE")
    if len(text) > _CHAPTER_MAX_CHARS:
        cut = text[:_CHAPTER_MAX_CHARS]
        boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("\n"))
        text = cut[:boundary + 1] if boundary >= _CHAPTER_MIN_CHARS else cut
    heading = strip_material_ids(heading.strip()) if isinstance(heading, str) else ""
    if len(heading) > _MAX_HEADING_CHARS:
        heading = _shorten_heading(heading, _MAX_HEADING_CHARS)
    return heading, text


def _names_generic_dependency(heading: str) -> bool:
    """True when a heading is named after a library every process loads."""
    upper = heading.upper()
    return any(dep in upper for dep in _GENERIC_DEPENDENCIES)


# A heading that ends on one of these is a fragment, not a title: "SVCHOST、WMI"
# names two objects and stops, telling the reader nothing about the chapter.
_HEADING_FRAGMENT_TAILS = ("、", "，", ",", "与", "和", "及", "的", "：", ":", "/")


def _is_heading_fragment(heading: str) -> bool:
    """True when a heading is a bare list of nouns rather than a statement."""
    stripped = heading.strip()
    if not stripped:
        return True
    if stripped.endswith(_HEADING_FRAGMENT_TAILS):
        return True
    # A pure enumeration ("SVCHOST、WMI") has no statement after its separators.
    parts = [p for p in re.split(r"[、，,与和及]", stripped) if p.strip()]
    return len(parts) >= 2 and all(len(p.strip()) <= 12 for p in parts) and \
        not re.search(r"执行|异常|记录|解析|为空|失败|事件|活动|痕迹|重复|缺失|变化", stripped)


async def _chapter_heading(chapter, llm):
    """Name a chapter from its themes; the largest theme is the fallback.

    A single-theme chapter still goes through the namer: the theme name is a
    grouping label ("OfficeHub", "EXPLORER"), which is too terse to be a chapter
    title. Names built from a generic system library ("RPCSS执行…") or left as a
    bare noun list ("SVCHOST、WMI") are rejected and re-derived.
    """
    names = [theme["name"] for theme in chapter["themes"]]
    fallback = _shorten_heading(chapter["name"], _MAX_HEADING_CHARS)
    try:
        response = await llm.chat_completion(
            STAGE_CHAPTER_HEADING_SYSTEM_V1,
            json.dumps({"topics": names}, ensure_ascii=False),
            max_tokens=80, temperature=0.0)
        content = response.get("content")
        if isinstance(content, str) and content.strip():
            heading = content.strip().strip('"“”').split("\n")[0]
            heading = strip_material_ids(heading).strip()
            if len(heading) > _MAX_HEADING_CHARS:
                heading = _shorten_heading(heading, _MAX_HEADING_CHARS)
            if (len(heading) >= 2
                    and not _names_generic_dependency(heading)
                    and not _is_heading_fragment(heading)):
                return heading
            if len(heading) >= 2:
                logger.info("Chapter heading %r unusable; retrying", heading)
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Chapter heading synthesis failed: %s", exc)
    if _names_generic_dependency(fallback) or _is_heading_fragment(fallback):
        # The theme name itself is unusable: fall back to the largest theme
        # that is not, so the chapter still gets a meaningful label.
        for theme in sorted(chapter["themes"],
                            key=lambda t: -len(t["directions"])):
            candidate = _shorten_heading(theme["name"], _MAX_HEADING_CHARS)
            if (not _names_generic_dependency(candidate)
                    and not _is_heading_fragment(candidate)):
                return candidate
    # A bare process name ("RUNTIMEBROKER") is a label, not a title; it tells
    # the reader what the chapter is about only if it says what happened.
    if len(fallback) <= 16 and re.fullmatch(r"[A-Za-z0-9_.\- ]+", fallback):
        return f"{fallback} 执行痕迹"
    return fallback


async def write_chapters(chapters, materials, llm, *, concurrency: int = 1):
    """Write one chapter per packed chapter (report shape v4).

    Returns ``(sections, warnings)`` where each section is
    ``{"heading": str, "content": str, "direction_ids": tuple[str, ...]}``.
    A chapter that does not fit one request is written in parts; every part
    keeps the chapter's heading so the report still has exactly one chapter
    per packed chapter.
    """
    cid = {m.material_id: stage_citation_name(m.evidence_key) for m in materials}
    jobs = []
    for index, chapter in enumerate(chapters):
        directions = chapter_directions(chapter)
        rows = [_chapter_write_row(d, cid) for d in directions]
        parts = _split_chapter_rows(rows)
        cursor = 0
        for part_index, part in enumerate(parts):
            part_ids = tuple(
                d.direction_id for d in directions[cursor:cursor + len(part)])
            cursor += len(part)
            jobs.append({
                "chapter_index": index,
                "part_index": part_index,
                "parts_total": len(parts),
                "topics": [t["name"] for t in chapter["themes"]],
                "rows": part,
                "direction_ids": part_ids,
            })

    async def write_one(job):
        payload = json.dumps({
            "chapter_topics": job["topics"],
            "part": f"{job['part_index'] + 1}/{job['parts_total']}",
            "directions": job["rows"],
        }, ensure_ascii=False)
        response = await llm.chat_completion(
            STAGE_CHAPTER_WRITE_SYSTEM_V1, payload,
            # A chapter body is up to 4000 characters of Chinese prose plus the
            # JSON wrapper. 4096 tokens truncated long chapters mid-string, and
            # the parse error dropped the whole chapter (one run lost 38
            # directions to "Unterminated string").
            max_tokens=8192, temperature=0.0)
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("CHAPTER_SECTION_UNUSABLE")
        try:
            heading, text = _parse_chapter_section(content)
        except ValueError as exc:
            if str(exc) != "CHAPTER_DENIES_OWN_EVIDENCE":
                raise
            # One retry with an explicit reminder: the model declared part of
            # its own input had no evidence. The reminder goes into the system
            # prompt, never appended to the JSON payload — appending broke the
            # payload the retry was supposed to resend.
            retry_prompt = STAGE_CHAPTER_WRITE_SYSTEM_V1 + (
                "\n\n注意：上一版错误地声明本章某个主题没有材料。"
                "本章所有 directions 都有材料支撑，请把全部材料写成同一结论的不同侧面，"
                "不得出现“未提供任何发现”“无法作出结论”这类表述。")
            response = await llm.chat_completion(
                retry_prompt, payload,
                max_tokens=8192, temperature=0.0)
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("CHAPTER_SECTION_UNUSABLE") from None
            heading, text = _parse_chapter_section(content)
        return {**job, "heading": heading, "content": text}

    results = await _gather_bounded([write_one(j) for j in jobs], concurrency)
    warnings = []
    written: dict[int, list[dict]] = {}
    for index, outcome in enumerate(results):
        job = jobs[index]
        if isinstance(outcome, BaseException):
            warnings.append(f"CHAPTER_SECTION_REJECTED_{job['chapter_index'] + 1}")
            logger.warning("Chapter %d part %d rejected: %s",
                           job["chapter_index"] + 1, job["part_index"] + 1, outcome)
            continue
        written.setdefault(job["chapter_index"], []).append(outcome)

    sections = []
    for index in sorted(written):
        parts = sorted(written[index], key=lambda p: p["part_index"])
        chapter = chapters[index]
        # One chapter, one heading: parts of the same chapter must not each
        # invent their own title, or the report gains chapters it does not have.
        heading = await _chapter_heading(chapter, llm)
        body = "\n\n".join(part["content"] for part in parts)
        direction_ids = tuple(
            direction_id for part in parts for direction_id in part["direction_ids"])
        sections.append({"heading": heading, "content": body,
                         "direction_ids": direction_ids})
    return sections, tuple(warnings)


async def _compose_chapter_narrative(envelope, materials, directions, llm, *,
                                     concurrency: int = 1):
    """Chapter-shaped narrative: induce themes, pack to a fixed chapter count, write.

    The chapter count is decided by ``pack_themes_into_chapters`` before any
    writing happens, so it cannot drift with the model's answer. Induction is
    free to return any number of themes; the packer merges them into exactly
    ``_TARGET_NARRATIVE_CHAPTERS`` chapters (or fewer when there are fewer
    themes), keeping every direction.

    Returns ``None`` when induction yields nothing usable so the caller can
    fall back to the batch path or the fragment renderer.
    """
    try:
        themes, theme_warnings = await induce_themes(
            directions, llm, concurrency=concurrency, split_oversized=False)
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Theme induction failed (%s); falling back to batch narrative", exc)
        return None
    if not themes:
        return None
    chapters, pack_warnings = pack_themes_into_chapters(themes)
    if not chapters:
        return None
    sections, write_warnings = await write_chapters(
        chapters, materials, llm, concurrency=concurrency)
    if not sections:
        logger.warning("Chapter writing produced no sections; falling back")
        return None
    for warning in theme_warnings + pack_warnings + write_warnings:
        logger.info("Chapter narrative warning: %s", warning)
    return sections


async def compose_stage_narrative(envelope, materials, directions, comparisons, llm,
                                  concurrency: int = 1, chapter_shaped: bool = True):
    """Weave validated directions into chapter narrative for investigators.

    The LLM may only reorganize already-validated findings; quotes stay in
    the directions (rendered in the stage panel) and section text names the
    source files so the reader places classification-colored citation chips
    inline. Any validation failure returns None — the caller falls back to
    the per-direction fragment rendering.
    """
    if not directions:
        return None
    if chapter_shaped:
        return await _compose_chapter_narrative(
            envelope, materials, directions, llm, concurrency=concurrency)
    # One direction per readable material means a wide scope yields ~500
    # directions, and every one of them became prose: a PC.E01 report reached
    # 228 chapters / 155k characters. The report is a reading document, not a
    # material inventory — the per-material detail stays in the stage panel.
    # Keep the findings that carry the most evidence, in their original order
    # so the narrative still follows the evidence layout.
    if len(directions) > _MAX_NARRATIVE_DIRECTIONS:
        ranked = sorted(
            enumerate(directions),
            key=lambda pair: (
                -len(pair[1].supporting_refs),
                -len(pair[1].counter_refs),
                -len(pair[1].missing_information),
                pair[0],
            ),
        )[:_MAX_NARRATIVE_DIRECTIONS]
        keep = sorted(index for index, _ in ranked)
        directions = tuple(directions[index] for index in keep)
    cid = {m.material_id: stage_citation_name(m.evidence_key) for m in materials}
    name_rows = [{"name": stage_citation_name(m.evidence_key), "kind": m.kind,
                  "coverage": m.status} for m in materials]
    # Aggregate counts only: the full comparison rows render in their own
    # 差异 sections, and the detailed list can overflow the request budget.
    comparison_summary = dict(sorted(
        (status, sum(1 for c in comparisons if c.status == status))
        for status in {c.status for c in comparisons})) if comparisons else []

    def direction_row(d):
        return {
            "kind": d.finding_kind, "origin": d.origin, "title": d.title,
            "description": d.description,
            "supporting": [{"file": cid[r.material_id], "quote": r.quote}
                           for r in d.supporting_refs],
            "counter": [{"file": cid[r.material_id], "quote": r.quote}
                        for r in d.counter_refs],
            "missing_information": list(d.missing_information),
            "alternative_explanations": list(d.alternative_explanations),
        }

    # Wide evidence scopes exceed one request budget; compose in batches and
    # concatenate the chapters, so narrative coverage never silently degrades
    # to fragments just because the task has many directions. Batch on both
    # request bytes and direction count: bytes alone let a batch grow to 36
    # directions, which no single 8192-token answer can summarize into valid
    # sections.
    batches, current, size = [], [], 0
    for d in directions:
        row = direction_row(d)
        length = len(json.dumps(row, ensure_ascii=False))
        if current and (size + length > REQUEST_CHAR_LIMIT
                        or len(current) >= _MAX_DIRECTIONS_PER_BATCH):
            batches.append(current)
            current, size = [], 0
        current.append(row)
        size += length
    if current:
        batches.append(current)

    # The prompt makes each batch emit 3-6 sections, so batch count *drives*
    # chapter count: 507 directions became 43 batches and 228 chapters, a
    # 155k-character report nobody can read. Chapter count is the reader-facing
    # constraint, so a wide run asks each batch for a single chapter instead of
    # shrinking the batches (which only multiplied them). Narrow runs keep the
    # richer 3-6 section contract.
    single_chapter_batches = len(batches) > _MAX_REPORT_CHAPTERS // 3

    sections = []

    async def compose_batch(index, batch):
        """One narrative request. Returns its sections or raises ValueError.

        Split out of the loop so batches can run concurrently: the requests
        are independent (each carries only its own directions), and running
        them serially was most of the report's wall time.
        """
        # name_rows scales with the whole material set (~70 chars/row), so for
        # wide scopes it alone can overflow the request budget; a batch only
        # needs the materials its own directions can name.
        cited_names = {ref["file"] for row in batch
                       for ref in (*row["supporting"], *row["counter"])}
        batch_name_rows = [row for row in name_rows if row["name"] in cited_names]
        request = json.dumps({
            "analysis_mode": envelope.analysis_mode,
            "case_context": envelope.case_description or None,
            "materials": batch_name_rows,
            "part": f"{index + 1}/{len(batches)}",
            "validated_directions": batch,
            "case_comparison_counts": comparison_summary if index == 0 else [],
        }, ensure_ascii=False)
        if len(request) > REQUEST_CHAR_LIMIT * 2:
            raise ValueError("NARRATIVE_REQUEST_TOO_LONG")
        system_prompt = STAGE_NARRATIVE_SYSTEM_V1.replace(
            "__PART__", f"{index + 1}/{len(batches)}")
        if single_chapter_batches:
            # Wide scope: one chapter per batch keeps the report inside a
            # readable chapter count. The skeleton in the base prompt asks
            # for 3-6, so override it explicitly.
            system_prompt = system_prompt.replace(
                "sections为3到6个，按顺序组织为：",
                "sections只输出1个，用一章完整概括本批材料（宽范围报告按批分章）："
            ).replace("单章400到1200字", "单章400到1200字")
        response = await llm.chat_completion(
            system_prompt,
            request, max_tokens=8192, temperature=0.0)
        content = response.get("content")
        if not isinstance(content, str) or len(content) > 60000:
            raise ValueError("NARRATIVE_OUTPUT_UNUSABLE")
        parsed = _loads_strict(content)
        rows = parsed.get("sections") if isinstance(parsed, dict) else None
        # The prompt asks for 3-6 sections per batch and 400-1200 characters
        # each. The validator used to accept 1-8 sections of 50-9000 chars,
        # so a batch could ship one 50-character section and still pass; a
        # PC.E01 report then grew to 50 chapters of near-identical prose.
        # Keep a small tolerance around the prompt's bounds rather than the
        # old open range. A single section is valid only when this run was
        # explicitly told to emit one chapter per batch (wide scopes).
        min_sections = 1 if single_chapter_batches else 2
        if not isinstance(rows, list) or not min_sections <= len(rows) <= _MAX_SECTIONS_PER_BATCH:
            raise ValueError("NARRATIVE_SECTIONS_INVALID")
        # Validate the whole batch before returning. Appending as each row
        # passed meant a batch that failed on its last row had already
        # contributed its earlier sections — the report carried content from
        # batches the log called "rejected".
        batch_sections = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("NARRATIVE_SECTION_INVALID")
            heading, text = row.get("heading"), row.get("content")
            if not isinstance(text, str) or not _MIN_SECTION_CHARS <= len(text) <= 9000:
                raise ValueError("NARRATIVE_SECTION_SIZE")
            heading = strip_material_ids(heading.strip()) if isinstance(heading, str) else ""
            text = strip_material_ids(text.strip())
            if len(text) < _MIN_SECTION_CHARS:
                raise ValueError("NARRATIVE_SECTION_SIZE")
            # An over-long heading is a formatting miss, not a reason to
            # throw away the batch's prose. The prompt asks for <=24
            # characters, but the model routinely writes a full executable
            # name ("BACKGROUNDTASKHOST.EXE执行记录", 26 chars); rejecting
            # on that dropped 4 of the first 6 batches while every section
            # body was perfectly usable. Shorten the label instead — at a
            # word/character boundary, never mid-identifier: a plain slice
            # produced "ELEVATION_SERVICE与EXPLOR".
            if len(heading) > _MAX_HEADING_CHARS:
                heading = _shorten_heading(heading, _MAX_HEADING_CHARS)
            if len(heading) < 2:
                heading = _derived_heading(_SKELETON_HEADINGS[0], text)
            if len(heading) < 2:
                raise ValueError("NARRATIVE_HEADING_UNUSABLE")
            batch_sections.append({"heading": heading, "content": text})
        # The budget is for the whole report, but testing the running total
        # against it made every batch after the first overflow fail forever:
        # once 30k characters were accumulated, no further batch could ever
        # fit, so the remaining evidence produced no prose and the tail of
        # the run was 100% rejections (run 5: 33 of 36 batches). Check the
        # batch on its own; the chapter cap below bounds the final length.
        batch_total = sum(len(s["content"]) for s in batch_sections)
        if batch_total > _MAX_TOTAL_NARRATIVE_CHARS:
            raise ValueError("NARRATIVE_BATCH_TOO_LONG")
        return batch_sections

    # Concurrent fan-out, merged in batch order so the rendered chapter order
    # stays deterministic (batch 1 first) regardless of completion order.
    outcomes = await _gather_bounded(
        [compose_batch(index, batch) for index, batch in enumerate(batches)],
        concurrency)
    for index, outcome in enumerate(outcomes):
        if isinstance(outcome, BaseException):
            # One unusable batch does not sink the rest; a narrative covering
            # the remaining batches still beats falling back to fragments.
            # Log the reason: "rejected" alone made a 33-of-36 failure rate
            # indistinguishable from a single malformed batch.
            logger.warning(
                "Stage narrative batch %d rejected (%s); skipped", index + 1, outcome)
            continue
        sections.extend(outcome)
    return sections or None


# Internal identifiers (m0012, e003) address the prompt's material list; they
# are meaningless to a reader and the prompt forbids them. A PC.E01 run leaked
# 55 of them into published prose because nothing enforced the rule.
_MATERIAL_ID_RE = re.compile(r"(?<![A-Za-z0-9_])m\d{3,4}(?![A-Za-z0-9_])")
# A run of ids joined by enumeration marks ("m003、m004 均指向…") must go as one
# unit: deleting each id separately left the connector behind ("mm均指向…").
# The run absorbs the enumeration mark *after* it, and a leading preposition
# whose only object was the run ("根据 m0001，…" / "见 m001、m002") so the
# sentence keeps its own subject instead of starting with an orphan.
_ID_RUN_RE = re.compile(
    r"(?:(?:根据|依据|参照|按照|结合|基于|如|见)\s*)?"
    r"(?<![A-Za-z0-9_])m\d{3,4}(?:[ \t]*[、,，/和与及][ \t]*m\d{3,4})*"
    r"[ \t]*[、,，]?[ \t]*")
# After an id run is removed, a conjunction with nothing left on its left
# ("根据 与，攻击者") or a doubled separator is a scar, not content.
_DANGLING_CONJUNCTION_RE = re.compile(
    r"(?:根据|依据|参照|按照|结合|如|见)\s*[与和及、,，]\s*")
# A preposition whose only object was the id run ("根据 m0001，…" -> "根据 ，…")
# also loses its purpose; drop the preposition with the ids.
_ORPHANED_LEAD_RE = re.compile(
    r"(?:根据|依据|参照|按照|结合|依据于|基于)\s+(?=[，。；：、])")
_DOUBLED_SEPARATOR_RE = re.compile(r"[、,，]{2,}")
# An empty pair of brackets is left where an id used to sit alone.
_EMPTY_BRACKETS_RE = re.compile(r"[（(]\s*[)）]")


def strip_material_ids(text: str) -> str:
    """Remove prompt-internal material ids from prose the reader will see."""
    if not _MATERIAL_ID_RE.search(text):
        return text
    # Runs first (ids plus their connectors), then any lone id left over.
    cleaned = _ID_RUN_RE.sub("", text)
    cleaned = _MATERIAL_ID_RE.sub("", cleaned)
    # Collapse the spacing/punctuation scars the deletion leaves behind.
    cleaned = _DANGLING_CONJUNCTION_RE.sub("", cleaned)
    cleaned = _ORPHANED_LEAD_RE.sub("", cleaned)
    cleaned = _DOUBLED_SEPARATOR_RE.sub("、", cleaned)
    cleaned = _EMPTY_BRACKETS_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([，。；：、])", r"\1", cleaned)
    return cleaned.strip()


# The four headings the prompt used to prescribe. A batch that repeats one of
# them is re-titled from its own content instead of being numbered.
_SKELETON_HEADINGS = (
    "检材范围与构成", "材料反映的活动与体系",
    "异常与待核线索", "信息缺口与核查建议",
)
_SKELETON_PREFIX_RE = re.compile(
    r"^(?:%s)\s*(?:[（(]\s*\d+\s*[)）])?\s*$" % "|".join(_SKELETON_HEADINGS))


def _shorten_heading(heading: str, limit: int) -> str:
    """Trim an over-long heading without cutting through a word or identifier.

    A plain slice turned "ELEVATION_SERVICE与EXPLORER执行" into
    "ELEVATION_SERVICE与EXPLOR", which reads as a broken token. Prefer the last
    natural boundary (separator, or the ASCII/Chinese script change) that fits;
    fall back to the hard limit only when no boundary exists.
    """
    # A cut inside a bracketed suffix leaves an unclosed "（2" or "（1/3" —
    # a split theme's part marker then reads as broken text. Drop the whole
    # bracket group when it does not fit. Checked against the ORIGINAL string:
    # once sliced to the limit, the closing bracket is already gone.
    open_index = heading.rfind("（")
    if open_index >= 4:
        close_index = heading.find("）", open_index)
        if close_index != -1 and close_index < limit:
            # The whole "（n）" suffix fits: keep it verbatim. Without this the
            # script-change rule below cut at the ASCII→CJK boundary just
            # before "（", silently dropping the part marker that distinguishes
            # split chapters.
            return heading[:limit].rstrip(" 、，, /|：:")
        head = heading[:open_index]
    else:
        head = heading[:limit]
    head = head.rstrip(" 、，, /|：:")
    # Prefer cutting before a conjunction: "DRVINST 与 ELEVATION_SERVICE…"
    # becomes "DRVINST" rather than "DRVINST 与 ELEVATION_SERV".
    for conjunction in (" 与 ", " 和 ", " 及 ", "与", "和", "及"):
        cut = head.rfind(conjunction)
        if cut >= max(4, limit // 3):
            return head[:cut].rstrip(" 、，, /|：:与和及")
    # A boundary just after a separator reads naturally.
    for separator in ("、", "，", ",", " ", "/", "|", "：", ":"):
        cut = head.rfind(separator)
        if cut >= max(4, limit // 2):
            return head[:cut].rstrip("、，, /|：:")
    # Otherwise prefer ending the label at a script change (an ASCII token
    # followed by Chinese text) rather than inside the ASCII identifier.
    for index in range(len(head) - 1, max(4, limit // 2) - 1, -1):
        if head[index].isascii() != head[index - 1].isascii():
            return head[:index].rstrip()
    return head


def _derived_heading(heading: str, content: str) -> str:
    """Replace a generic skeleton heading with a content-derived label.

    Only skeleton headings are touched: a model that followed the prompt and
    wrote a topic heading keeps it verbatim. The label comes from the first
    clause, cut at a natural boundary and trimmed to the 24-character budget
    the prompt sets, so it is reproducible from the frozen text rather than
    invented. A hard 24-character cut is only the last resort: it used to
    produce labels like "default_cloud_config.jso".
    """
    if not _SKELETON_PREFIX_RE.match(heading.strip()):
        return heading
    first = re.split(r"[。；;！!？?\n]", content.strip(), maxsplit=1)[0].strip()
    first = re.sub(r"^(?:从材料内容看|综合现有材料)[，,]?", "", first)
    first = re.sub(r"^材料中(?!心)", "", first)
    # Narrative batches habitually open with a chapter self-reference ("本章围绕
    # 本机账号…"). Kept verbatim it becomes the label "本章围绕本机账号", which
    # reads as a sentence fragment rather than a topic. Drop the lead-in and
    # the verb that introduces the topic, so the label names the subject.
    first = re.sub(
        r"^(?:本章|本节|本文|该章|这一章|此章|本批材料|该批材料|本批|该批)\s*"
        r"(?:围绕|依据|基于|根据|汇总|承接|梳理|说明|介绍|描述|分析|记录|涵盖|涉及|显示|表明)?"
        r"\s*", "", first)
    first = first.strip("，,、 ")
    if len(first) < 4:
        return heading
    # A sentence that opens with a file name ("default_cloud_config.json 与 …")
    # yields a bare-filename label, which tells the reader nothing. Start the
    # label after that opening name instead.
    leading = re.match(r"^([A-Za-z0-9_.\-]+\.(?:json|xml|db|log|txt|ini|dat|evtx|hve|lnk))"
                       r"\s*(?:与|和|、|及|,|，)?\s*", first)
    if leading:
        remainder = first[leading.end():].strip("，,、 ")
        if len(remainder) >= 8:
            first = remainder
    # A bare filename followed directly by its description ("X.json显示…")
    # leaves the same unusable label; strip the name and keep the predicate.
    inline = re.match(r"^([A-Za-z0-9_.\-]+\.(?:json|xml|db|log|txt|ini|dat|evtx|hve|lnk))"
                      r"(?=[\u4e00-\u9fff])", first)
    if inline:
        remainder = first[inline.end():].strip("，,、 ")
        if len(remainder) >= 8:
            first = remainder
    # A preposition followed by a file name ("针对X.json的…") makes the label
    # start with a dangling connective; drop both.
    preposition = re.match(
        r"^(?:针对|关于|根据|依据|结合)\s*"
        r"[A-Za-z0-9_.\-]+\.(?:json|xml|db|log|txt|ini|dat|evtx|hve|lnk)"
        r"\s*(?:的|中|里|与|和|、|,|，)?\s*", first)
    if preposition:
        remainder = first[preposition.end():].strip("，,、 ")
        if len(remainder) >= 8:
            first = remainder
    if len(first) <= 24:
        return first
    # Prefer a clause boundary inside the budget. A bare filename is not a
    # usable label, so a boundary is only accepted when it leaves a real
    # phrase behind; otherwise fall back to the sentence's leading phrase.
    for boundary in ("，", ",", "、", "：", ":"):
        cut = first.rfind(boundary, 0, 24)
        if cut >= 8:
            candidate = first[:cut].strip()
            if not _looks_like_bare_filename(candidate):
                return candidate
    clipped = first[:24]
    # Never stop mid-identifier: back off to the last space when the cut falls
    # inside a token ("话术培训文档 7要素" must not become "…7要素").
    if clipped[-1].isalnum() and len(first) > 24 and (
            first[24].isalnum() or first[24] in "._-"):
        space = clipped.rfind(" ")
        if space >= 8:
            clipped = clipped[:space]
    clipped = clipped.strip()
    if _looks_like_bare_filename(clipped):
        # Give up on this sentence: the next clause usually names the topic.
        tail = re.split(r"[，,；;]", first, maxsplit=1)
        if len(tail) > 1 and len(tail[1].strip()) >= 8:
            return _trim_heading_label(tail[1].strip())
        return heading
    return _trim_heading_label(clipped)


# A label cut mid-identifier ("load_statistics.d", "default_cloud_config.j")
# or ending on a dangling connective ("…包括以") reads as a typo. Repair by
# stepping back to the last complete token/phrase, then give up to the caller.
_DANGLING_TAIL = ("以", "包括", "为", "的", "和", "与", "及", "在", "对")


def _trim_heading_label(text: str) -> str:
    """Drop a dangling identifier/fragment; keep the label readable."""
    original = text.strip("，,、：:；; ")
    text = original
    if re.search(r"[A-Za-z0-9_.\-]\.[A-Za-z]{1,2}$", text):
        # Ends on a filename fragment: drop the whole trailing identifier.
        text = re.sub(r"[A-Za-z0-9_.\-]+$", "", text).strip("，,、：: ")
    for word in _DANGLING_TAIL:
        if text.endswith(word) and len(text) - len(word) >= 6:
            text = text[: -len(word)].strip("，,、：: ")
            break
    # Repair must never turn a usable label into a stub ("针对", "材料观察层面"
    # is still a real phrase, but "针对" alone is not).
    if len(text) < 6:
        return original
    return text


def _looks_like_bare_filename(text: str) -> bool:
    """True when a label is nothing but a file name (no descriptive words)."""
    return bool(re.fullmatch(r"[A-Za-z0-9_.\-]+", text))


def _narrative_citations(text: str, materials) -> tuple[str, ...]:
    """Citation ids of the materials whose file name the section mentions.

    Name matching is a fallback: a chapter that discusses an artifact without
    naming the file gets no citation, and a passing mention attaches one.
    Chapter-shaped sections carry their directions, so ``_direction_citations``
    resolves them exactly instead.
    """
    cited = []
    for index, m in enumerate(materials, 1):
        name = stage_citation_name(m.evidence_key)
        if name and name in text:
            cited.append(f"c{index:03}")
    return tuple(cited)


def _direction_citations(direction_ids, directions_by_id, materials) -> tuple[str, ...]:
    """Citation ids for a chapter, resolved from the directions it was built from.

    Every material a direction quotes is evidence for that chapter, so the set
    is exact and independent of how the prose names files.
    """
    material_ids = set()
    for direction_id in direction_ids:
        direction = directions_by_id.get(direction_id)
        if direction is None:
            continue
        for ref in (*direction.supporting_refs, *direction.counter_refs):
            material_ids.add(ref.material_id)
    order = {m.material_id: index for index, m in enumerate(materials, 1)}
    return tuple(
        f"c{order[mid]:03}"
        for mid in sorted(material_ids, key=lambda x: order.get(x, 10 ** 9))
        if mid in order
    )


def render_stage_report(envelope, materials, directions, comparisons, warnings, narrative=None):
    phase_a = envelope.analysis_mode == "evidence_only"
    directions_by_id = {d.direction_id: d for d in directions}
    warnings = list(warnings)
    citations = tuple(StructuredReportCitation(citation_id=f"c{i:03}", evidence_key=m.evidence_key)
                      for i, m in enumerate(materials, 1))
    cid = {m.material_id: c.citation_id for m, c in zip(materials, citations)}
    available = sum(m.status != "unavailable" and bool(m.text) for m in materials)
    scope = (f"本轮在已入报的 {len(materials)} 份材料范围内研判，可用 {available} 份，"
             f"不可用 {len(materials) - available} 份。只使用冻结的解析片段或明确标记的机器观察，"
             "不代表全镜像或全文穷尽分析。引用位置指向冻结文本字符，不是磁盘偏移。")
    scope += ("未使用案情描述、人工备注、历史 AI 摘要或已接受分析。" if phase_a else
              "本轮复用首次报告的同一批冻结材料，没有新增证据。人工案情仅作为调查语境。")
    # The scope chapter describes the evidence set as a whole; it is a methods
    # note, not a finding. It must not carry citations at all. Attaching the
    # readable set still put 645 ids on a 123-character paragraph — the reader
    # got an evidence list where one chapter claimed almost the whole report.
    # The findings chapters carry the citations that belong to specific claims.
    scope_citation_ids = ()
    sections = [StructuredReportSection(heading="研判范围与方法", content=scope,
                                       citation_ids=scope_citation_ids)]
    if not phase_a:
        sections.append(StructuredReportSection(heading="本次案情（待核语境）", content=envelope.case_description))
    if narrative:
        # A batch may still answer with the generic skeleton even though the
        # prompt asks for topic headings. Repeating "检材范围与构成（2）（3）…"
        # eight times reads as eight reports stapled together, so repeated
        # headings are re-titled from the batch's own first sentence (a
        # deterministic, evidence-derived label). The same applies to any
        # repeated topic label: "材料观察（2）" is still a stapled-report tell,
        # and the second batch has its own content to name it by.
        seen = {}
        dropped_chars = 0
        for row in narrative:
            # Cap the chapter count. The narrative is assembled from one batch
            # per group of directions, so a wide evidence scope produced 50
            # near-identical chapters on PC.E01. Beyond the cap, merge the
            # remaining batches into the last chapter rather than dropping
            # their content outright — but only up to a readable size. The
            # unbounded merge turned that last chapter into a 30,543-character
            # wall of prose (six times any other chapter), which is worse than
            # omitting it: nothing in it can be found again.
            if len(sections) >= _MAX_REPORT_CHAPTERS:
                # The chapter budget is spent. Appending the remaining batches
                # to the last chapter does not preserve them — it destroys both:
                # the appended text has nothing to do with that chapter's topic
                # (a VMware prefetch chapter ended up carrying AppLocker log
                # findings), and the chapter grew to 7k characters of stitched
                # prose. Record the omission in the warnings instead, where the
                # analyst can see exactly what the narrative left out.
                extra = strip_material_ids(row["content"].strip())
                dropped_chars += len(extra)
                continue
            heading = _derived_heading(row["heading"], row["content"])
            # Enforce the heading budget here as well as in compose_batch: the
            # renderer is also fed narratives that did not pass through the
            # composer (stored responses, tests, future callers), and a raw
            # 30-character label reached a published report that way.
            if len(heading) > _MAX_HEADING_CHARS:
                heading = _shorten_heading(heading, _MAX_HEADING_CHARS)
            seen[heading] = seen.get(heading, 0) + 1
            if seen[heading] > 1:
                derived = _derived_heading(_SKELETON_HEADINGS[0], row["content"])
                # Only adopt the derived label when it says something new; a
                # short batch would otherwise fall back to the same heading.
                if derived and derived not in seen:
                    heading = derived
                    seen[heading] = 1
                else:
                    suffix = f"（{seen[heading]}）"
                    heading = _shorten_heading(
                        heading, _MAX_HEADING_CHARS - len(suffix)) + suffix
            # Chapter-shaped sections carry the directions they were written
            # from; resolve citations exactly. The batch path has no such
            # provenance and falls back to matching file names in prose.
            direction_ids = row.get("direction_ids")
            if direction_ids is not None:
                citation_ids = _direction_citations(
                    direction_ids, directions_by_id, materials)
            else:
                citation_ids = _narrative_citations(row["content"], materials)
            sections.append(StructuredReportSection(
                heading=heading, content=row["content"],
                citation_ids=citation_ids))
    else:
        for start in range(0, len(directions), 8):
            chosen = directions[start:start + 8]
            texts, refs = [], []
            for direction in chosen:
                texts.append(("材料观察：" if direction.finding_kind == "observation" else "待核方向：")
                             + direction.title + "\n" + direction.description)
                if direction.origin == "case_only":
                    texts.append("此项仅由案情提出，尚无材料支持。")
                for label, sources in (("支持片段", direction.supporting_refs), ("相反或限制片段", direction.counter_refs)):
                    for ref in sources:
                        texts.append(f"{label}（{cid[ref.material_id]}）：{ref.quote}")
                        refs.append(cid[ref.material_id])
                if direction.missing_information:
                    texts.append("仍缺信息：" + "；".join(direction.missing_information))
                if direction.alternative_explanations:
                    texts.append("其他可能解释：" + "；".join(direction.alternative_explanations))
            sections.append(StructuredReportSection(
                heading=f"{'材料自主发现' if phase_a else '案情对照发现'}（{start // 8 + 1}）",
                content="\n\n".join(texts), citation_ids=tuple(dict.fromkeys(refs))))
    if not directions:
        sections.append(StructuredReportSection(heading="调查方向与限制",
            content="本次可读材料尚未形成有来源支持的调查方向；这不等于不存在相关活动。"))
    if comparisons:
        # Comparisons are a status table over the baseline findings, not prose.
        # Rendering one block per outcome still produced 13 chapters / 70k
        # characters on PC.E01 (281 comparisons, 71% of the report), because
        # each row carried its own multi-sentence reason. Summarize instead:
        # one chapter with the outcome counts, plus the rows that actually
        # change the picture (contradicted / revised / case_only).
        titles = {d.direction_id: d.title for d in envelope.baseline.directions}
        labels = {"supported": "得到支持", "revised": "需要修正", "weakened": "支持减弱",
                  "contradicted": "存在相反材料", "insufficient": "依据不足", "case_only": "仅案情提出"}
        by_status: dict[str, list] = {}
        for comparison in comparisons:
            by_status.setdefault(comparison.status, []).append(comparison)
        total = len(comparisons)
        counts = "、".join(
            f"{labels[status]} {len(by_status[status])} 项"
            for status in labels if by_status.get(status))
        lines = [f"本轮以首次研判的 {total} 项方向为基线逐项对照，结果：{counts}。"]
        # Only outcomes that change the analyst's picture get named; agreement
        # is reported as a count, because listing 200 confirmations tells the
        # reader nothing they did not already know.
        notable = ("contradicted", "revised", "case_only")
        for status in notable:
            chosen = by_status.get(status)
            if not chosen:
                continue
            lines.append(f"\n{labels[status]}（{len(chosen)} 项）：")
            for comparison in chosen[:_COMPARISON_DETAIL_LIMIT]:
                title = titles.get(comparison.baseline_direction_id, "（基线方向）")
                lines.append(f"- {title}：{comparison.reason}")
            remaining = len(chosen) - _COMPARISON_DETAIL_LIMIT
            if remaining > 0:
                lines.append(f"- 另有 {remaining} 项同类差异，详见阶段材料清单。")
        citation_ids = tuple(dict.fromkeys(
            cid[r.material_id] for status in notable
            for c in by_status.get(status, ())
            for r in (*c.supporting_refs, *c.counter_refs)))
        sections.append(StructuredReportSection(
            heading="与首次研判的差异", content="\n".join(lines),
            citation_ids=citation_ids))
    if narrative and dropped_chars:
        warnings.append(f"NARRATIVE_OVERFLOW_DROPPED_{dropped_chars}_CHARS")
    sections.append(StructuredReportSection(heading="人工核查建议",
        content="逐项核对调查方向的支持材料、相反材料和缺失信息。材料记载、机器推断及案情假设分别处理；"
                "没有人工复核的结论不得自动作为已确认事实。" +
                (f"\n本轮有 {len(warnings)} 项分析或覆盖限制，详见本轮材料与差异清单。" if warnings else "")))
    stage = StageAnalysis(
        analysis_mode=envelope.analysis_mode, evidence_scope_hash=envelope.evidence_scope_hash,
        case_description=envelope.case_description,
        case_context_hash=hashlib.sha256(envelope.case_description.encode("utf-8")).hexdigest() if not phase_a else None,
        baseline_report_id=envelope.baseline.report_id if envelope.baseline else None,
        baseline_report_hash=envelope.baseline.report_sha256 if envelope.baseline else None,
        materials=materials, directions=directions, comparisons=comparisons,
        baseline_directions=envelope.baseline.directions if envelope.baseline else (),
        baseline_priorities=envelope.baseline.priorities if envelope.baseline else {},
        warnings=warnings,
    )
    return StructuredReportResponse(title="材料自主研判报告" if phase_a else "案情对照研判报告",
                                    sections=tuple(sections), citations=citations), stage
