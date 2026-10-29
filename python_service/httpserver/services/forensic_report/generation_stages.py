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
                                 STAGE_CHAPTER_HEADING_SYSTEM_V1,
                                 STAGE_CHAPTER_SUMMARY_SYSTEM_V1,
                                 STAGE_RECALL_SUMMARY_SYSTEM_V1,
                                 STAGE_RECALL_CONTRIBUTION_SYSTEM_V1,
                                 STAGE_EVIDENCE_THREAD_SYSTEM_V1,
                                 STAGE_CASE_OVERVIEW_SYSTEM_V1)
logger = logging.getLogger(__name__)

from .models import (
    DirectionBatch, InvestigationDirection, MaterialSpan, ComparisonSuggestion,
    DirectionComparison, StageAnalysis, StructuredReportResponse, StructuredReportSection,
    StructuredReportCitation, ClassificationQuestion,
    EvidenceRecallRow, EvidenceRecallTable, EvidenceThreadRow, EvidenceThreadTable,
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
    """Fan-out for report LLM batches, bounded by the shared LLM budget.

    Capped well below LLM_MAX_CONCURRENCY: the report pipeline issues hundreds
    of large requests back to back, and the gateway answers that sustained rate
    with 429 windows even though the same concurrency succeeds in a short burst
    (measured: 32 concurrent 14k-character requests all returned 200, while a
    full generation hit a 33-second 429 window after ~490 calls). More
    parallelism does not shorten the report — those seconds are spent waiting
    out the limiter — so keep the sustained rate modest.
    """
    try:
        value = int(getattr(settings, "llm_max_concurrency", DEFAULT_REPORT_CONCURRENCY))
    except (TypeError, ValueError):
        value = DEFAULT_REPORT_CONCURRENCY
    return max(1, min(value, DEFAULT_REPORT_CONCURRENCY))


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
# Bounded path tail in prompt projections: enough to name the enclosing
# software/directory, short enough that installed AppX paths do not dominate
# the request budget (they can exceed 200 characters each).
_PROMPT_PATH_MAX = 160
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
    """One material as the discovery model sees it.

    ``path`` is included and is NOT optional. Quasar's config file contains only
    ``<Hosts>192.168.10.30:4782;</Hosts>`` and ``<Tag>Office04</Tag>`` — nothing
    that says what program wrote it. Its location
    ``/Users/admin/Desktop/控制端/Quasar v1.4.1/Profiles/Default.xml`` is the only
    place the case semantics exist, so a projection without it produces
    "a config with a remote host" instead of "the Quasar RAT client config".
    Measured on PC.E01: 83 of 911 materials carry case semantics only in the
    path; adding it costs ~101 characters per material (+5.6% prompt size).
    """
    return {"material_id": source.material_id, "source_kind": source.kind,
            # Path is a locator, not a fact: the discovery prompt forbids
            # treating a directory name as evidence of what happened.
            "path": stage_citation_key_path(source.evidence_key),
            "text": source.text[:READING_CHARS] if text is None else text,
            "source_group": source.source_sha256,
            "coverage": source.status, "limitations": source.limitations}


def stage_citation_key_path(evidence_key: str) -> str:
    """The human-readable location of an evidence key, bounded for prompts."""
    path = evidence_key[5:] if evidence_key.startswith("file:") else evidence_key
    # Long installed paths (AppX packages with version + hash + locale) would
    # otherwise add hundreds of characters for no extra signal: the tail is
    # what names the object, the head is boilerplate.
    if len(path) > _PROMPT_PATH_MAX:
        path = "…" + path[-_PROMPT_PATH_MAX:]
    return path


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
# prompt asks for <=30 directions, but the model grouped 218 directions under
# "系统进程与组件执行痕迹" on PC.E01, which then split into 4 parts that each
# concluded "常规系统活动" — the same finding stated four times. Oversized
# themes are split here rather than trusted to the prompt.
#
# Raised from 25 to 30 with the object-level regrouping: object themes are
# naturally smaller, and the old cap forced distinct case objects to be folded
# back together (a 46-material PrivaZer install bundle swallowed Quasar's two
# directions, and the chapter took the largest theme's name).
_THEME_MAX_DIRECTIONS = 30
# A theme smaller than this cannot carry a chapter; it is a fragment.
# Lowered from 8 because an object-level theme is legitimately small: one
# suspect program with 3-6 observations is exactly what a reader wants.
_THEME_MIN_DIRECTIONS = 3
# Folding only applies once the grouping is clearly fragmented; a report with a
# handful of genuinely small themes should keep them.
_THEME_FRAGMENT_FOLD_MIN_THEMES = 12
_THEME_COUNT_MAX = 24


def _direction_projection(direction, paths=None) -> dict:
    """Minimal per-direction row for induction: id, label, kind, short text.

    Quotes and full descriptions stay out: induction only needs to recognize
    what a direction is about, and including quotes tripled the payload.
    ``paths`` adds the directories a direction's evidence lives in, which is
    what lets induction group by case OBJECT (Quasar 控制端, PrivaZer 安装包)
    instead of by material type (all Prefetch, all evtx).
    """
    row = {
        "id": direction.direction_id,
        "title": direction.title[:60],
        "kind": direction.finding_kind,
        "description": direction.description[:120],
    }
    if paths:
        where = []
        for ref in (*direction.supporting_refs, *direction.counter_refs):
            path = paths.get(ref.material_id)
            if path and path not in where:
                where.append(path)
        if where:
            row["where"] = [w[-100:] for w in where[:3]]
    return row


def _chunk_directions(directions, limit: int = REQUEST_CHAR_LIMIT, paths=None):
    """Split directions into induction chunks that fit one request each.

    Sizes are measured from the serialized payload the request actually sends.
    Arithmetic estimates drifted (field order, escaping, separators) and let
    chunks exceed the limit by tens of characters.
    """
    chunks, current, rows, size = [], [], [], 0
    for direction in directions:
        row = _direction_projection(direction, paths)
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
                        split_oversized: bool = True, paths=None):
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
    chunks = _chunk_directions(directions, paths=paths)

    async def group_chunk(index, chunk):
        rows = [_direction_projection(d, paths) for d in chunk]
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

# Directions that report the ABSENCE of content rather than a finding: an empty
# event log, a failed parse, an empty XML/JSON object, a license file, a memory
# dump with no strings. On PC.E01 they were 109 of 339 directions — a third of
# the evidence — and size-balanced packing spread them across every chapter, so
# the chapters carrying real findings were diluted until a Quasar RAT
# configuration existed only in the citation list and never in the prose.
# Pooling them keeps every direction reported while confining the material
# limits to one honest chapter.
_NO_FINDING_RE = re.compile(
    r"解析(?:结果)?为空|解析失败|为空|空\s*XML|空\s*JSON|空哈希|空占位|无实质"
    r"|未提取到|无显著|无法形成|无法就|未显示异常|无可用"
    r"|(?:开源)?许可证|第三方组件声明|同源重复|重复副本|重复材料"
    r"|解析器(?:格式|限制)|格式识别限制|手段限制"
)
_NO_FINDING_THEME_NAME = "材料解析限制与空记录"
# Subjects a case is actually about. A direction naming one of these is not
# "one observation among two hundred" — it is the finding the report exists to
# deliver. On PC.E01 the only Quasar direction (a RAT client config with
# 192.168.10.30:4782, Mutex and AddStartup) was packed into a chapter titled
# "Edge与PrivaZer触发Defender", where no reader would ever find it. Themes
# carrying such a direction get their own chapter, ahead of the bulk.
_CASE_CRITICAL_RE = re.compile(
    # Malware families and tool names: unambiguous on their own.
    r"quasar|njrat|darkcomet|gh0st|remcos|asyncrat|xworm|cobalt\s*strike"
    r"|meterpreter|mimikatz|beacon"
    # Behavioural language that only a malicious reading uses. "网络能力"
    # (network capability) and "提权" (privilege escalation) appear in benign
    # driver descriptions too, so they are excluded; "远控/木马/后门" and a
    # control-end/server-config pair are not.
    r"|远控|木马|后门程序|恶意程序|恶意代码|勒索软件|窃密"
    r"|控制端|受控端|服务端配置|客户端配置|监听端口"
    r"|外联地址|回连|反弹\s*shell|C2\s*服务器|C&C",
    re.IGNORECASE)
_CRITICAL_THEME_NAME = "重点可疑对象"
# Inferences are what an investigator reads first: they state what the evidence
# may mean. They are few (5 of 339 on PC.E01), so size-balanced packing always
# tucked them behind bulk observations, and the one Quasar inference lost the
# chapter name to a larger, less specific theme. One dedicated chapter makes the
# inferences the report's analytic core instead of a footnote.
_HYPOTHESIS_THEME_NAME = "待验证推断与可疑关联"
# Specific subjects handed to the heading namer alongside the theme names. A
# chapter named only after its themes becomes "MATERIAL相关执行异常研判" even
# when it also holds a named RAT configuration; the concrete subjects let the
# namer title the chapter after what is actually in it.
_MAX_HEADING_SUBJECTS = 4


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


def _is_no_finding(direction) -> bool:
    """True when a direction reports missing content instead of a finding."""
    return bool(_NO_FINDING_RE.search(f"{direction.title} {direction.description}"))


def _is_case_critical(direction) -> bool:
    """True when a direction names a subject the case is actually about.

    Malware, remote-control configuration, exfiltration channels. These are few
    and decisive; they must not be averaged into a chapter of browser prefetch
    observations.

    A direction that mentions a malicious tool only to DISCLAIM a link is not
    case-critical. One PC.E01 chapter was titled "Quasar远控等重点样本研判"
    while its prose said the samples showed no link to Quasar at all: the
    direction read "未显示与前述Quasar配置…的直接关联", and a bare keyword
    match promoted it. The negation has to be checked before the keyword.
    """
    text = f"{direction.title} {direction.description}"
    if _CASE_CRITICAL_NEGATION_RE.search(text):
        return False
    return bool(_CASE_CRITICAL_RE.search(text))


# Phrases that turn a malware mention into its opposite: "未显示与 Quasar 配置
# 的直接关联", "与远控无关", "不能据此认定存在远控". Chinese puts the negated
# predicate after the object, so both orders must be covered: a keyword followed
# by "…无直接关联" is the common one ("未显示与前述Quasar配置的直接关联").
_CASE_CRITICAL_NEGATION_RE = re.compile(
    r"(?:远控|木马|后门|恶意|控制端|外联|Quasar|NjRat|DarkComet|Gh0st|Remcos)"
    r"[^。；]{0,30}?(?:无关|无涉|无直接关联|没有关联|不存在关联|未发现关联"
    r"|未显示[^。；]{0,20}?关联|无证据|未被证实|不能认定|不足以认定)"
    r"|(?:未|没有|无|不|非)[^。；]{0,24}?"
    r"(?:关联|关系|指向|证据|迹象|发现|显示|表明|认定|属于|构成)"
    r"[^。；]{0,16}?"
    r"(?:远控|木马|后门|恶意|控制端|外联|Quasar)",
    re.IGNORECASE)


def _split_case_critical(themes):
    """Pull case-critical observations into one dedicated theme.

    Returns ``(critical_theme, remaining_themes)``. The critical theme keeps its
    own chapter so the RAT configuration is a heading a reader can find, rather
    than a paragraph inside "Edge与PrivaZer触发Defender".

    Only OBSERVATIONS move: a critical hypothesis already belongs to the
    inference tier, which has its own chapter.
    """
    critical, remaining = [], []
    for theme in themes:
        rest = []
        for direction in theme["directions"]:
            if (direction.finding_kind != "hypothesis"
                    and not _is_no_finding(direction)
                    and _is_case_critical(direction)):
                critical.append(direction)
            else:
                rest.append(direction)
        if rest:
            remaining.append({"name": theme["name"], "directions": tuple(rest)})
    if not critical:
        return None, themes
    return {"name": _CRITICAL_THEME_NAME, "directions": tuple(critical)}, remaining


def _subject_key(direction) -> str:
    """A coarse identity for what a direction is about.

    Used to keep two readings of the same object (one observation, one
    hypothesis) in the same tier instead of splitting them across chapters.
    The title carries the object and is stable across the two readings; the
    description is free prose and names different parameters each time, so
    reading it would give the twins different keys. Normalized to lowercase and
    stripped of the finding vocabulary induction appends. Empty when the title
    names no specific object.
    """
    tokens = set()
    for match in _SUBJECT_TOKEN_RE.findall(direction.title):
        stem = match.rsplit(".", 1)[0].lower()
        if not stem or stem.upper() in _SUBJECT_STOPWORDS:
            continue
        if stem.upper() in _GENERIC_DEPENDENCIES:
            continue
        if _subject_rank(match) != 0:
            continue
        tokens.add(stem)
    # One specific name identifies the object; requiring all of them fails
    # whenever one reading rephrases its title.
    return min(tokens) if tokens else ""


def _split_no_finding_and_hypotheses(themes):
    """Separate the two tiers that must not compete with bulk observations.

    Returns ``(pooled, hypotheses, findings, warnings)``:

    * ``pooled`` — one theme holding every direction that reports absent
      content, or ``None`` when there are none.
    * ``hypotheses`` — one theme holding every ``hypothesis`` direction, or
      ``None``.
    * ``findings`` — the remaining themes, with pooled/hypothesis directions
      removed from them.

    A theme that loses all of its directions disappears; one that keeps some
    is returned with the remainder.

    An observation is moved with its hypothesis twin. The pipeline emits both
    readings of the same object under the SAME title ("Quasar类远控配置与监听
    配置并存" once as an observation, once as a hypothesis); splitting them put
    the RAT configuration in two chapters, and the heading then named neither
    after it. The move is keyed on the exact normalized title, so the seven
    ordinary PrivaZer observations — same subject, different findings — stay in
    the findings tier where they belong.
    """
    warnings = []
    pooled, hypotheses, findings = [], [], []
    inferred_titles = {
        _subject_key(d)
        for theme in themes for d in theme["directions"]
        if d.finding_kind == "hypothesis" and not _is_no_finding(d)
    }
    inferred_titles.discard("")
    for theme in themes:
        observations, inferences = [], []
        for direction in theme["directions"]:
            if _is_no_finding(direction):
                pooled.append(direction)
            elif direction.finding_kind == "hypothesis":
                inferences.append(direction)
            elif _subject_key(direction) and _subject_key(direction) in inferred_titles:
                # The observation twin of a hypothesis: same object, same title.
                # The explicit non-empty test matters: two hypothesis titles name
                # no specific token and key to "", which would match every
                # subject-less observation and drag 238 of them into the tier.
                inferences.append(direction)
            else:
                observations.append(direction)
        hypotheses.extend(inferences)
        if observations:
            findings.append({"name": theme["name"], "directions": tuple(observations)})
    if pooled:
        warnings.append(f"NO_FINDING_POOLED_{len(pooled)}")
    if hypotheses:
        warnings.append(f"HYPOTHESES_SEPARATED_{len(hypotheses)}")
    return (
        {"name": _NO_FINDING_THEME_NAME, "directions": tuple(pooled)} if pooled else None,
        {"name": _HYPOTHESIS_THEME_NAME, "directions": tuple(hypotheses)} if hypotheses else None,
        findings,
        warnings,
    )


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
    pooled, hypotheses, groups, tier_warnings = _split_no_finding_and_hypotheses(groups)
    warnings.extend(tier_warnings)
    if not groups and len((pooled, hypotheses)) == 0:
        return [], ()
    # A tier that survives is a chapter in its own right, so it takes one bin
    # before the findings compete for the rest. Both tiers are optional: a case
    # whose materials are all readable has neither. They never consume the whole
    # budget: at least one bin is left for the findings, otherwise a report of
    # nothing but parse failures would be a wall of limitations.
    critical, groups = _split_case_critical(groups)
    if critical is not None:
        warnings.append(f"CASE_CRITICAL_ISOLATED_{len(critical['directions'])}")
    reserved = [tier for tier in (hypotheses, critical, pooled) if tier is not None]
    if not groups:
        # Only pooled/hypothesis/critical directions exist; they are the report.
        chapters = [{"name": tier["name"], "themes": [tier]} for tier in reserved]
        # Keep the analytic tiers first: inferences, then the critical objects.
        order = {tier["name"]: i for i, tier in
                 enumerate(t for t in (hypotheses, critical, pooled) if t is not None)}
        chapters.sort(key=lambda c: order[c["name"]])
        return chapters, tuple(warnings)
    # Never let the tiers take the whole budget: at least one bin is left for
    # the findings, otherwise a report of nothing but parse failures would be a
    # wall of limitations with no findings at all.
    finding_bins = max(1, min(target - len(reserved), len(groups)))
    bins = len(reserved) + finding_bins
    if bins < target:
        warnings.append(f"CHAPTER_TARGET_REDUCED_{bins}_OF_{target}")

    total = sum(len(theme["directions"]) for theme in groups)
    ideal = total / finding_bins
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
    buckets: list[list[int]] = [[] for _ in range(finding_bins)]
    loads = [0] * len(buckets)
    for index in ordered:
        lightest = min(range(len(buckets)), key=lambda b: (loads[b], b))
        buckets[lightest].append(index)
        loads[lightest] += len(pieces[index]["directions"])
    chapters = []
    # Reserved tiers lead the report: the reader meets the analytic claims and
    # the materials that could not be parsed before the bulk observations, not
    # after them.
    for tier in reserved:
        chapters.append({"name": tier["name"], "themes": [tier]})
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


def _chapter_write_row(direction, cid, paths=None) -> dict:
    """One direction as the chapter writer sees it: label, text, quotes.

    ``paths`` carries each cited material's directory. The bare file name is
    not enough to say what an object is: Default.xml alone reads as "some
    config", while 控制端/Quasar v1.4.1/Profiles/Default.xml names the program.
    """
    paths = paths or {}
    return {
        "title": direction.title,
        "kind": direction.finding_kind,
        "description": direction.description,
        "supporting": [
            {"file": cid.get(ref.material_id, ""),
             "where": paths.get(ref.material_id, ""), "quote": ref.quote}
            for ref in direction.supporting_refs
        ],
        "counter": [
            {"file": cid.get(ref.material_id, ""),
             "where": paths.get(ref.material_id, ""), "quote": ref.quote}
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


# Named artifacts a chapter talks about, as they appear in prompt prose. The
# heading namer uses these to title a chapter after its actual subject.
_SUBJECT_TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9_.\-]{2,}(?:\.[A-Za-z0-9]{2,5})?")
# Subjects too generic to name a chapter with, on top of the library list. These
# are artifact TYPES and host constants that appear in almost every direction;
# they crowd out the one specific name a reader needs.
_SUBJECT_STOPWORDS = frozenset({
    "EXE", "DLL", "SYS", "BIN", "XML", "JSON", "HTML", "TEXT", "TRUE", "FALSE",
    "NULL", "HTTP", "HTTPS", "SYSTEM", "WINDOWS", "USERS", "PROGRAMDATA",
    "APPDATA", "TEMP", "DESKTOP", "ADMIN", "USER", "DATA", "FILE", "FILES",
    "PREFETCH", "VERBOSE", "CRITICAL", "ERROR", "WARNING", "INFORMATION",
    "EVENT", "EVENTS", "EMPTY", "SOURCE_GROUP", "SQLITE", "REGISTRY", "LOG",
    "LOGS", "MACHINE", "ORIGINAL", "NEUTRAL", "FIRST", "PARTIAL", "NULL",
    "HTTP", "HTTPS", "SSH", "TRUE", "FALSE", "DESKTOP-02H4UFI",
})


def _subject_rank(token: str) -> int:
    """Sort key: 0 for a specific named object, 1 for everything else.

    A specific subject is what a reader searches for: a product or tool name
    (Quasar, PrivaZer, mscoree), a path component, a host or volume id. Bare
    ALL-CAPS tokens in this corpus are almost always artifact types or host
    constants, and a lowercase dictionary word is prose, not a name — ranking
    those as specific put 166 of 339 directions into the "has a subject" tier.
    """
    stem = token.rsplit(".", 1)[0]
    if not re.search(r"[A-Za-z]", stem):
        return 1
    # A single short lowercase word is ordinary prose ("found", "empty").
    if stem.islower() and len(stem) <= 6 and not re.search(r"[0-9_.\-]", stem):
        return 1
    if stem.isupper():
        return 1
    # Mixed case (Quasar, PrivaZer), embedded digits/dots/underscores, or a long
    # lowercase identifier (mscoree, microsoftedgeupdate) name something.
    if any(ch.isupper() for ch in stem[1:]) or stem[:1].isupper():
        return 0
    if re.search(r"[0-9_.\-]", stem) or len(stem) >= 8:
        return 0
    return 1


def _chapter_subjects(chapter) -> list[str]:
    """The distinct concrete subjects a chapter's directions name, most telling first.

    Deterministic order: specific named objects before generic artifact types,
    then frequency desc, then name asc — so the same chapter always offers the
    namer the same subjects.
    """
    counts: dict[str, int] = {}
    for direction in chapter_directions(chapter):
        text = f"{direction.title} {direction.description}"
        for match in _SUBJECT_TOKEN_RE.findall(text):
            token = match.strip()
            if not token:
                continue
            stem = token.rsplit(".", 1)[0].upper()
            if stem in _GENERIC_DEPENDENCIES or stem in _SUBJECT_STOPWORDS:
                continue
            if token.upper() in _GENERIC_DEPENDENCIES:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(),
                    key=lambda kv: (_subject_rank(kv[0]), -kv[1], kv[0]))
    return [token for token, _count in ranked[:_MAX_HEADING_SUBJECTS]]


def _chapter_lead_name(chapter) -> str:
    """The theme that should name the chapter when the namer gives nothing usable.

    Prefers a theme carrying an inference over the largest one: a hypothesis is
    what the chapter is FOR. Falls back to the largest theme. Never invents a
    name — the result is always one of the chapter's own theme names.
    """
    members = chapter["themes"]
    if not members:
        return chapter["name"]
    inferred = [t for t in members
                if any(d.finding_kind == "hypothesis" for d in t["directions"])]
    pool = inferred or members
    return max(pool, key=lambda t: (len(t["directions"]), t["name"]))["name"]


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
    # Two particles in a row ("WinRM与的PowerShell执行") is a grammar error the
    # namer produced on PC.E01. It cannot be repaired by trimming: the sentence
    # itself is broken, so ask again.
    if re.search(r"[与和及在对于把将被从向][的了]", stripped):
        return True
    # A single identifier ("PowerShell", "material.dll", "FormatExtFs") names an
    # object but says nothing about it. Two PC.E01 chapters were published with
    # exactly those headings; the reader learns nothing from them. A short
    # pure-ASCII token is a label, not a topic.
    if (re.fullmatch(r"[A-Za-z0-9_.\-]+", stripped) and len(stripped) <= 20):
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

    The namer also sees the chapter's concrete subjects (the named artifacts and
    objects its directions talk about). Without them a chapter holding a Quasar
    RAT configuration was titled "MATERIAL相关执行异常研判" — the theme names
    described formatting conventions, not content, so the heading carried no
    information the reader could act on.
    """
    names = [theme["name"] for theme in chapter["themes"]]
    subjects = _chapter_subjects(chapter)
    fallback = _shorten_heading(_chapter_lead_name(chapter), _MAX_HEADING_CHARS)
    try:
        response = await llm.chat_completion(
            STAGE_CHAPTER_HEADING_SYSTEM_V1,
            json.dumps({"topics": names, "subjects": subjects}, ensure_ascii=False),
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
        # Nothing usable: every theme name is a bare object list. Say what the
        # chapter records about them rather than publishing the list alone.
        labelled = _label_bare_artifacts(fallback)
        if labelled != fallback:
            return labelled
    return fallback


def _label_bare_artifacts(name: str) -> str:
    """Append the action a bare artifact label is missing.

    A bare process name ("RUNTIMEBROKER") is a label, not a title; it tells the
    reader what the chapter is about only if it says what happened. The verb has
    to match the artifact: a DLL is loaded or parsed, never executed, so
    "material.dll 执行痕迹" would be a false statement about the evidence.
    """
    if not name:
        return name
    if re.fullmatch(r"[A-Za-z0-9_.\- ]+", name) and len(name) <= _MAX_HEADING_CHARS:
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension in ("dll", "sys", "ocx"):
            suffix = "解析痕迹"
        elif extension in ("xml", "json", "ini", "txt", "log", "cfg"):
            suffix = "配置记录"
        else:
            suffix = "执行痕迹"
        labelled = f"{name} {suffix}"
        if len(labelled) <= _MAX_HEADING_CHARS:
            return labelled
        # No room for a verb: keep the object name rather than a truncated verb.
        return name
    # A CJK enumeration ("WinRM与PowerShell") gets the generic verb.
    if _is_heading_fragment(name):
        labelled = f"{name} 执行痕迹"
        if len(labelled) <= _MAX_HEADING_CHARS:
            return labelled
    return name


def _part_role(part_index: int, parts_total: int) -> str:
    """Where one written part sits inside its chapter.

    A chapter too large for one request is written in parts, and each part used
    to open with its own "本章围绕…展开" and close with its own "综合来看…".
    Joined with blank lines that produced a chapter with four total-opening
    sentences and two conclusions (chapter 4 of the PC.E01 report: 7,039
    characters, 21 paragraphs, the same "no events found" statement rephrased
    four times). Only the first part may introduce and only the last may
    conclude; the middle parts go straight into their subject.
    """
    if parts_total <= 1:
        return "single"
    if part_index == 0:
        return "first"
    if part_index == parts_total - 1:
        return "last"
    return "middle"


# Appended to the system prompt for a part that is not allowed to introduce or
# conclude. Kept as prompt text rather than a payload field: the writer treats
# JSON keys as data, and this is an instruction about shape.
_PART_ROLE_INSTRUCTIONS = {
    "first": (
        "\n\n本章材料过多，分多段撰写，本段是第 1 段（不是最后一章）。"
        "本段只写本章的引言与本段涉及的材料，不要写全章结论，"
        "不要出现“综合来看”“综上”这类收束语；结论由最后一段写。"
    ),
    "middle": (
        "\n\n本章材料过多，分多段撰写，本段是中间段。"
        "禁止写引言：不要出现“本章围绕…展开”“本批材料呈现…”“综合来看”“综上”"
        "这类开题或收束句，直接以具体对象或具体异常开头，写完本段材料即止。"
    ),
    "last": (
        "\n\n本章材料过多，分多段撰写，本段是最后一段。"
        "禁止写引言：不要出现“本章围绕…展开”“本批材料呈现…”，"
        "直接以具体对象开头；本段末尾写全章结论（综合前述各段，一两句即可）。"
    ),
}


def _strip_repeated_scaffolding(text: str) -> str:
    """Remove duplicate chapter openings/conclusions left by joined parts.

    The role instructions tell each part what it may write, but a prompt alone
    is not a guarantee — a middle part still opened with "本章材料集中呈现两
    类情况" on one run. This is the deterministic backstop: keep the first
    introducing sentence and the last concluding sentence, drop the rest.

    A repeated opening is stripped at the SENTENCE, not the paragraph: the
    paragraph that follows it usually carries the part's findings, so dropping
    the whole paragraph would delete evidence along with the scar.
    """
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        return text
    intro_re = re.compile(
        r"^\s*(?:本章|本批材料|该章|这一章)"
        r"[^。]{0,60}?(?:展开|呈现|聚焦|围绕|反映|涵盖|涉及)[^。]*。")
    seen_intro = False
    cleaned: list[str] = []
    for paragraph in paragraphs:
        stripped = paragraph.strip()
        if intro_re.match(stripped):
            if seen_intro:
                remainder = intro_re.sub("", stripped, count=1).strip()
                if len(remainder) < _CHAPTER_MIN_CHARS // 3:
                    # Nothing left but the opening: this paragraph was pure
                    # lead-in, so the whole paragraph goes.
                    continue
                stripped = remainder
            else:
                seen_intro = True
        cleaned.append(stripped)
    # The same chapter must not conclude twice. Keep only the final
    # "综合来看"/"综上" paragraph; earlier ones are part-level wrap-ups.
    conclusion_indexes = [
        i for i, p in enumerate(cleaned)
        if re.match(r"^\s*(?:综合来看|综上|总体来看|综合上述)", p)
    ]
    if len(conclusion_indexes) > 1:
        drop = set(conclusion_indexes[:-1])
        cleaned = [p for i, p in enumerate(cleaned) if i not in drop]
    return "\n\n".join(cleaned)


# Narrative chapters habitually list execution counts instead of interpreting
# them: chapter 8 of the PC.E01 report carried 14 instances of "X.EXE 运行 N 次"
# in one chapter, six of them inside a single paragraph that read as a Prefetch
# table transcribed into sentences. The write prompt now forbids it; this is the
# deterministic check that catches a non-compliant answer.
_EXEC_COUNT_RE = re.compile(
    r"[A-Za-z0-9_.\-]{3,}\.(?:EXE|exe)[^。；\n]{0,12}?"
    r"(?:运行|执行)\s*(?:了\s*)?\d+\s*次")
_MAX_EXEC_COUNTS_PER_PARAGRAPH = 3
# Whole-chapter budget. Per-paragraph counting was satisfied by spreading the
# same table over five paragraphs: chapter 8 still published 18 named execution
# counts across the chapter while no single paragraph exceeded three. A chapter
# that names more than this many programs with counts is a table, however it is
# paragraph-broken.
_MAX_EXEC_COUNTS_PER_CHAPTER = 8


def _paragraph_is_an_inventory(paragraph: str) -> bool:
    """True when a paragraph reads as a frequency table rather than analysis."""
    return len(_EXEC_COUNT_RE.findall(paragraph)) > _MAX_EXEC_COUNTS_PER_PARAGRAPH


def _inventory_free(text: str) -> bool:
    """True when no paragraph of a chapter is an execution-count inventory."""
    return not any(_paragraph_is_an_inventory(p) for p in text.split("\n\n"))


def _compress_inventory(paragraph: str, keep: int = _MAX_EXEC_COUNTS_PER_PARAGRAPH) -> str:
    """Rewrite an over-budget counting paragraph into a grouped statement.

    The rewrite request is not enough: on the PC.E01 run two chapters came back
    from the rewrite still listing every program and its count (an 18-instance
    chapter, nine of them in one sentence). Prompt-only enforcement fails here
    because the model treats the count table as the content, so the backstop is
    deterministic: keep the first ``keep`` named programs, replace the rest with
    one grouped clause that preserves the count range and the fact of the
    activity. ``keep`` drops to 1 when a chapter's total budget still does not
    fit after the first pass.
    """
    matches = list(_EXEC_COUNT_RE.finditer(paragraph))
    if len(matches) <= keep:
        return paragraph
    kept = matches[:keep]
    dropped = matches[keep:]
    counts = []
    for match in dropped:
        found = re.search(r"(\d+)\s*次", match.group())
        if found:
            counts.append(int(found.group(1)))
    # Build the grouped clause from the whole dropped span so the sentence's own
    # punctuation and connectors are removed with it.
    start, end = dropped[0].start(), dropped[-1].end()
    # Extend to the sentence end so the leftover enumeration marks disappear.
    tail = paragraph[end:]
    stop = re.search(r"[。；;！!？?]", tail)
    grouped = ""
    if counts:
        low, high = min(counts), max(counts)
        span = f"{low}" if low == high else f"{low} 至 {high}"
        grouped = f"另有 {len(dropped)} 个系统组件各有 {span} 次执行"
    replacement = (grouped + "。") if grouped else "。"
    # Cut back to the beginning of the clause: the kept text must not end on a
    # dangling enumeration mark or a half-written connector.
    head = paragraph[:start].rstrip("：:，,、；; ")
    if head and head[-1] in "。！？!?":
        # The kept part already ended a sentence; a semicolon after it would
        # read as "…多次运行。；另有 N 个…".
        rebuilt = f"{head}{replacement}"
    elif head:
        rebuilt = f"{head}；{replacement}"
    else:
        rebuilt = replacement.lstrip("；")
    remainder = paragraph[end:]
    if stop is None:
        return rebuilt
    rest = remainder[stop.end():].lstrip()
    if not rest:
        return rebuilt
    # Two grouped clauses in a row ("另有 2 个…。另有 6 个…。") carry no extra
    # information; merge them into one by summing the components and widening
    # the range. This happens when a paragraph is compressed twice.
    merged = re.match(r"^另有\s*(\d+)\s*个系统组件各有\s*(\d+)(?:\s*至\s*(\d+))?\s*次执行。",
                      rest)
    if merged and grouped:
        prev = re.search(r"另有\s*(\d+)\s*个系统组件各有\s*(\d+)(?:\s*至\s*(\d+))?\s*次执行。$",
                         rebuilt)
        if prev:
            total = int(prev.group(1)) + int(merged.group(1))
            lows = [int(x) for x in prev.groups()[1:] + merged.groups()[1:] if x]
            low, high = min(lows), max(lows)
            span = f"{low}" if low == high else f"{low} 至 {high}"
            rebuilt = rebuilt[:prev.start()] + \
                f"另有 {total} 个系统组件各有 {span} 次执行。"
            rest = rest[merged.end():].lstrip()
            if not rest:
                return rebuilt
    return f"{rebuilt}{rest}"


def _compress_inventories(text: str) -> str:
    """Reduce a chapter's execution-count listing to a readable budget.

    Two limits apply. A paragraph with more than ``_MAX_EXEC_COUNTS_PER_PARAGRAPH``
    counts is compressed first (it is unambiguously a table). If the chapter as
    a whole still names more than ``_MAX_EXEC_COUNTS_PER_CHAPTER`` programs with
    counts, the densest paragraphs are compressed until the chapter fits —
    otherwise spreading the same table across five paragraphs satisfies the
    per-paragraph rule while the chapter still reads as an inventory.
    """
    paragraphs = text.split("\n\n")
    invents = [_EXEC_COUNT_RE.findall(p) for p in paragraphs]

    def compress(index: int, keep: int = _MAX_EXEC_COUNTS_PER_PARAGRAPH) -> None:
        paragraphs[index] = _compress_inventory(paragraphs[index], keep)
        invents[index] = _EXEC_COUNT_RE.findall(paragraphs[index])

    for index, found in enumerate(invents):
        if len(found) > _MAX_EXEC_COUNTS_PER_PARAGRAPH:
            compress(index)

    total = sum(len(found) for found in invents)
    # Second pass: the chapter still names too many programs. Tighten the
    # densest paragraphs to a single named example each — one concrete program
    # plus a grouped statement is what a reader needs; the full table belongs
    # in the stage material, not in the chapter.
    while total > _MAX_EXEC_COUNTS_PER_CHAPTER:
        candidates = [(len(found), index) for index, found in enumerate(invents)
                      if len(found) > 1]
        if not candidates:
            break
        _count, index = max(candidates)
        before = len(invents[index])
        compress(index, keep=1)
        if len(invents[index]) >= before:
            break
        total = sum(len(found) for found in invents)
    return "\n\n".join(paragraphs)


async def _chapter_summary(heading: str, body: str, llm) -> str:
    """The chapter's own one-or-two-sentence closing statement.

    Kept out of the chapter body on purpose: the body is generated per part in
    parallel, so a "summarize yourself" instruction inside the body either
    produced several conclusions (one per part) or none. Asking for the
    summary as a separate, small call against the finished body means exactly
    one closing statement per chapter and it never competes with the body's
    token budget.

    Returns "" when the model gives nothing usable. An empty summary renders
    nothing; the chapter still publishes — prose is never discarded because
    its closing sentence failed.
    """
    try:
        response = await llm.chat_completion(
            STAGE_CHAPTER_SUMMARY_SYSTEM_V1,
            json.dumps({"heading": heading, "content": body[:6000]},
                       ensure_ascii=False),
            max_tokens=400, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades
        logger.warning("Chapter summary synthesis failed for %r: %s", heading, exc)
        return ""
    content = response.get("content")
    if not isinstance(content, str):
        return ""
    summary = _clean_chapter_summary(content)
    if not summary:
        logger.info("Chapter summary for %r unusable; publishing without it", heading)
    return summary


# A summary that opens with a stock connector reads as padding: the reader
# already knows it is the end of the chapter. Only empty openers are stripped —
# "本章材料共同显示…" is a real statement and is kept verbatim.
_SUMMARY_LEAD_RE = re.compile(
    r"^\s*(?:综上所述|综合来看|总体来看|总的来说|综上|总之)[，,：:]\s*")
_SUMMARY_MIN_CHARS = 20
_SUMMARY_MAX_CHARS = 220


def _plain_models_text(value: str) -> str:
    """Strip the wrappers a small model puts around a one-line answer.

    A model asked for "just the sentence" still answers with the JSON shape
    from a neighbouring prompt often enough to matter: this run published
    ``{"overview":"..."}`` verbatim into the first chapter, because only three
    key names were recognised. Any single-string object is unwrapped now, so
    the reader never sees the wrapper.
    """
    text = (value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = _loads_strict(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            string_values = [v for v in parsed.values() if isinstance(v, str) and v.strip()]
            for key in ("summary", "overview", "content", "text", "result"):
                if isinstance(parsed.get(key), str) and parsed[key].strip():
                    text = parsed[key].strip()
                    break
            else:
                if len(string_values) == 1:
                    text = string_values[0].strip()
    return text.strip().strip('"“”「」\u3000 ')


def _clean_chapter_summary(raw: str) -> str:
    """Normalize one chapter summary; return "" when it is not usable.

    Unusable means: empty, still contains a prompt-internal identifier, or so
    short it cannot be a statement. A summary that merely starts with
    "综上所述" is repaired, not rejected — the sentence after it carries the
    content.
    """
    text = _plain_models_text(raw)
    text = strip_material_ids(text)
    text = re.sub(r"\s*\n+\s*", " ", text).strip()
    text = _SUMMARY_LEAD_RE.sub("", text).strip()
    if len(text) < _SUMMARY_MIN_CHARS:
        return ""
    if _MATERIAL_ID_RE.search(text) or "evidence_key" in text.lower():
        return ""
    if _NO_EVIDENCE_CLAIM_RE.search(text):
        # The summary must not deny the chapter it summarizes.
        return ""
    if len(text) > _SUMMARY_MAX_CHARS:
        cut = text[:_SUMMARY_MAX_CHARS]
        boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
        text = cut[:boundary + 1] if boundary >= _SUMMARY_MIN_CHARS else cut
    return text


async def write_chapters(chapters, materials, llm, *, concurrency: int = 1):
    """Write one chapter per packed chapter (report shape v5).

    Returns ``(sections, warnings)`` where each section is
    ``{"heading": str, "content": str, "summary": str,
    "direction_ids": tuple[str, ...]}``.
    A chapter that does not fit one request is written in parts; every part
    keeps the chapter's heading so the report still has exactly one chapter
    per packed chapter. Parts are role-scoped (first/middle/last) so a joined
    chapter reads as one continuous argument instead of several stapled ones.
    Each published chapter also carries its own closing summary, synthesized
    from the finished body (see ``_chapter_summary``).
    """
    cid = {m.material_id: stage_citation_name(m.evidence_key) for m in materials}
    paths = {m.material_id: stage_citation_key_path(m.evidence_key) for m in materials}
    jobs = []
    for index, chapter in enumerate(chapters):
        directions = chapter_directions(chapter)
        rows = [_chapter_write_row(d, cid, paths) for d in directions]
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
                "part_role": _part_role(part_index, len(parts)),
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
        system_prompt = STAGE_CHAPTER_WRITE_SYSTEM_V1 + _PART_ROLE_INSTRUCTIONS.get(
            job["part_role"], "")

        async def ask(prompt):
            response = await llm.chat_completion(
                prompt, payload,
                # A chapter body is up to 4000 characters of Chinese prose plus
                # the JSON wrapper. 4096 tokens truncated long chapters
                # mid-string, and the parse error dropped the whole chapter (one
                # run lost 38 directions to "Unterminated string").
                max_tokens=8192, temperature=0.0)
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("CHAPTER_SECTION_UNUSABLE")
            return content

        content = await ask(system_prompt)
        try:
            heading, text = _parse_chapter_section(content)
        except ValueError as exc:
            if str(exc) != "CHAPTER_DENIES_OWN_EVIDENCE":
                raise
            # One retry with an explicit reminder: the model declared part of
            # its own input had no evidence. The reminder goes into the system
            # prompt, never appended to the JSON payload — appending broke the
            # payload the retry was supposed to resend.
            retry_prompt = system_prompt + (
                "\n\n注意：上一版错误地声明本章某个主题没有材料。"
                "本章所有 directions 都有材料支撑，请把全部材料写成同一结论的不同侧面，"
                "不得出现“未提供任何发现”“无法作出结论”这类表述。")
            heading, text = _parse_chapter_section(await ask(retry_prompt))
        if not _inventory_free(text):
            # One rewrite with the violation named. The inventory rule is the
            # one the writer bypasses most: it is easy to satisfy "no filename
            # lists" by translating the same table into counting sentences.
            logger.info("Chapter %d part %d is a frequency inventory; rewriting",
                        job["chapter_index"] + 1, job["part_index"] + 1)
            inventory_prompt = system_prompt + (
                "\n\n注意：上一版把执行记录写成了频次清单"
                "（同一段里多次出现“某程序运行 N 次”）。"
                "请改写：每个段落最多点名为 3 个程序给出次数，其余按组件类别合并成"
                "一句话概括，并写出这些执行对本章结论意味着什么。")
            try:
                rewritten_heading, rewritten = _parse_chapter_section(
                    await ask(inventory_prompt))
            except ValueError:
                logger.warning(
                    "Chapter %d part %d rewrite failed; keeping the first version",
                    job["chapter_index"] + 1, job["part_index"] + 1)
            else:
                if _inventory_free(rewritten):
                    heading, text = rewritten_heading, rewritten
                else:
                    logger.warning(
                        "Chapter %d part %d still reads as an inventory after "
                        "the rewrite; compressing the counting paragraphs",
                        job["chapter_index"] + 1, job["part_index"] + 1)
        if not _inventory_free(text):
            # Deterministic backstop, applied whatever the rewrite produced:
            # the model reliably keeps the table even when told not to.
            text = _compress_inventories(text)
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
        if len(parts) > 1:
            body = _strip_repeated_scaffolding(body)
        direction_ids = tuple(
            direction_id for part in parts for direction_id in part["direction_ids"])
        # The summary is derived from the FINAL body (after part joining and
        # scaffolding cleanup), so it cannot describe text the reader will not
        # see. Fan out below: summaries are independent of each other.
        sections.append({"heading": heading, "content": body, "summary": "",
                         "direction_ids": direction_ids})
    if sections:
        summaries = await _gather_bounded(
            [_chapter_summary(section["heading"], section["content"], llm)
             for section in sections],
            concurrency)
        for section, outcome in zip(sections, summaries):
            if isinstance(outcome, BaseException):
                logger.warning("Chapter summary rejected for %r: %s",
                               section["heading"], outcome)
                continue
            if outcome:
                section["summary"] = outcome
        _deduplicate_summary_openings(sections)
    return sections, tuple(warnings)


# Openers that make every chapter's closing sentence sound the same. A live v5
# run produced seven summaries in a row starting with "现有材料只能说明…", which
# reads as a template rather than seven distinct judgements. The prompt now
# forbids these openers; this is the deterministic backstop.
_SUMMARY_STOCK_OPENERS = (
    "现有材料只能说明", "现有材料表明", "现有材料显示", "本章材料显示",
    "本章材料表明", "材料显示", "材料表明", "整体而言", "总体而言",
)


def _strip_stock_opener(summary: str) -> str:
    """Drop a stock lead-in so the summary starts on its own judgement."""
    for opener in _SUMMARY_STOCK_OPENERS:
        if not summary.startswith(opener):
            continue
        rest = summary[len(opener):].lstrip("，,：: ")
        # Only strip when a real clause follows; otherwise the opener IS the
        # sentence and removing it would leave a fragment.
        if len(rest) >= _SUMMARY_MIN_CHARS:
            stripped = rest[:1].upper() + rest[1:] if rest[:1].isascii() else rest
            return stripped
    return summary


def _deduplicate_summary_openings(sections) -> None:
    """Rewrite repeated stock openers so chapters do not all sound alike.

    Applies only to openers that occur more than once in the report: one
    chapter legitimately saying "材料显示" is fine, seven in a row is a tell.
    """
    counts: dict[str, int] = {}
    for section in sections:
        for opener in _SUMMARY_STOCK_OPENERS:
            if (section.get("summary") or "").startswith(opener):
                counts[opener] = counts.get(opener, 0) + 1
                break
    repeated = {opener for opener, count in counts.items() if count > 1}
    if not repeated:
        return
    for section in sections:
        summary = section.get("summary") or ""
        if not summary:
            continue
        if any(summary.startswith(opener) for opener in repeated):
            stripped = _strip_stock_opener(summary)
            if stripped != summary:
                section["summary"] = stripped


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
    # Induction sees where each direction's evidence lives: that is what lets
    # it group by case object (Quasar 控制端, PrivaZer 安装包) rather than by
    # material type (all Prefetch / all evtx), which is the difference between
    # a case-reading table and an artifact inventory.
    paths = {m.material_id: stage_citation_key_path(m.evidence_key) for m in materials}
    try:
        themes, theme_warnings = await induce_themes(
            directions, llm, concurrency=concurrency, split_oversized=False,
            paths=paths)
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
    # Carry the raw themes out with the sections: the exhaustive thread table
    # reuses the same (already validated, every-direction-exactly-once)
    # grouping instead of paying for a second induction pass.
    return _ChapterNarrative(sections, themes)


class _ChapterNarrative(list):
    """Section rows plus the raw theme grouping they were written from.

    Behaves exactly like the plain list of section dicts every caller and test
    already handles; ``themes`` is extra payload for the thread table.
    """

    def __init__(self, sections=(), themes=()):
        super().__init__(sections)
        self.themes = tuple(themes)


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


def _trim_leading_particle(text: str) -> str:
    """Drop a heading's leading function word left by a cut.

    Cutting "同名文件material.dll的多版本…" at the ASCII→CJK boundary produced
    the published heading "的material.dll多版本PE结构差": the cut landed one
    character late, so the label began with the possessive "的". A heading may
    not open with a particle — it reads as a broken fragment.

    The same cut can leave the particle at the END ("DESKTOP-02H4UFI的"), which
    is equally unusable: it promises a noun that the truncation removed.
    """
    text = re.sub(r"^[的了和与及或在对于把将被从向、，,。：:而并]\s*", "", text.strip())
    text = re.sub(r"[的了和与及或在对于把将被从向而并]+$", "", text).strip()
    # "WinRM与的PowerShell" — a conjunction followed by a possessive is a
    # grammar error; drop the possessive and keep the conjunction.
    return re.sub(r"([与和及])的", r"\1", text)


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
            return _trim_leading_particle(head[:cut].rstrip(" 、，, /|：:与和及"))
    # A boundary just after a separator reads naturally.
    for separator in ("、", "，", ",", " ", "/", "|", "：", ":"):
        cut = head.rfind(separator)
        if cut >= max(4, limit // 2):
            return _trim_leading_particle(head[:cut].rstrip("、，, /|：:"))
    # Otherwise prefer ending the label at a script change (an ASCII token
    # followed by Chinese text) rather than inside the ASCII identifier.
    for index in range(len(head) - 1, max(4, limit // 2) - 1, -1):
        if head[index].isascii() != head[index - 1].isascii():
            return _trim_leading_particle(head[:index].rstrip())
    return _trim_leading_particle(head)


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


def _verification_checklist(directions, *, limit: int = 8) -> list[str]:
    """Turn the directions' own missing-information notes into actions.

    The advisory chapter used to be two fixed sentences plus a count of
    warnings — it named nothing to go and check, which is the one thing a
    reader wants from it. Every direction already records what it could not
    establish (``missing_information``); those notes are exactly the open
    questions, so they become the checklist.

    Ordered by how much evidence the direction carries: a gap under a
    well-supported finding is worth closing first. Duplicates are collapsed
    because the same gap (no command line, no file hash) recurs across dozens
    of directions.
    """
    ranked = sorted(
        (d for d in directions if d.missing_information),
        key=lambda d: (-len(d.supporting_refs), d.title),
    )
    seen: set[str] = set()
    checklist: list[str] = []
    for direction in ranked:
        for gap in direction.missing_information:
            # These notes come from the discovery model, which sometimes writes
            # a prompt-internal id ("与 m0178 配置的关联关系") — that note was
            # published verbatim as checklist item 3, where the reader has no
            # way to resolve it. Scrub ids at the same boundary as chapter
            # prose, then drop the note if it was nothing but an id reference.
            note = strip_material_ids(gap.strip().rstrip("。；;，,"))
            if not note or len(note) < 6:
                continue
            # Normalize only for de-duplication; publish the original wording.
            key = re.sub(r"[\s，,。；;、]", "", note)[:40]
            if key in seen:
                continue
            seen.add(key)
            checklist.append(note)
            if len(checklist) >= limit:
                return checklist
    return checklist


def _advisory_text(directions, warnings) -> str:
    """The closing chapter: what an investigator should go and check."""
    lines = ["逐项核对调查方向的支持材料、相反材料和缺失信息。材料记载、机器推断及案情假设"
             "分别处理；没有人工复核的结论不得自动作为已确认事实。"]
    checklist = _verification_checklist(directions)
    if checklist:
        lines.append("")
        lines.append("优先补齐以下缺口（按所涉发现的材料支撑度排序）：")
        lines.extend(f"{index}. {note}。" for index, note in enumerate(checklist, 1))
    if warnings:
        lines.append("")
        lines.append(f"另有 {len(warnings)} 项分析或覆盖限制，详见本轮材料与差异清单。")
    return "\n".join(lines)


# The first chapter's recall table is a reading aid, not the evidence index:
# the stage panel already lists every material. 40 rows is what fits on one
# screen without turning chapter 1 into a 900-row spreadsheet, and the sort is
# by how much the report leaned on each item, so the cut is at the least-used
# tail rather than an arbitrary slice.
_RECALL_TABLE_LIMIT = 40

_SUBJECT_NAMES_IN_SUMMARY = 3

# One sentence per table row: short enough to scan, long enough to say which
# finding the material backs and with what concrete content.
# The thread table is a case-reading aid, not a chapter: a row large enough to
# hide a distinct case object is useless, so oversized groups are split by
# object before they are published.
_THEME_ROW_MAX_DIRECTIONS = 40

# Objects below this many directions are folded into the parent thread instead
# of becoming one-line threads of their own.
_THREAD_OBJECT_MIN_DIRECTIONS = 3

# Thread names are scanned, not read: 24 characters keeps them on one line.
_THREAD_NAME_MAX = 24

_CONTRIBUTION_MIN_CHARS = 20
_CONTRIBUTION_MAX_CHARS = 200

_RECALL_TOPIC_LABELS = {
    "funds": "资金", "identity_accounts": "人员账号", "communications": "通讯",
    "location": "位置", "network": "网络", "tools": "工具",
}
_RECALL_TYPE_LABELS = {
    "document": "文档", "chat_record": "聊天记录", "transaction_record": "交易记录",
    "image": "图片", "log": "日志", "android_artifact": "Android 工件",
    "other": "其他材料", "unknown": "类型未定",
}


def _recall_stats(materials, narrative, directions, classifications=None):
    """Compute the evidence recall table from the report as it will be read.

    Every count comes from the rendered chapters' own citation sets, so the
    table can never disagree with the prose: a material appears here only when
    at least one published chapter cites it. ``classifications`` supplies the
    frozen priority/type labels; without them the row keeps "unassessed" rather
    than guessing.

    Deterministic: same inputs, same rows. Nothing here is model-written.
    """
    directions_by_id = {d.direction_id: d for d in directions}
    by_material_id = {m.material_id: m for m in materials}
    cite_order = {m.material_id: index for index, m in enumerate(materials, 1)}
    classification_by_key = {
        item.evidence_key: item for item in (getattr(classifications, "items", ()) or ())
    }
    # ``references`` counts the quote spans a material contributes to the
    # published chapters (how much evidence it supplies); ``chapters`` counts
    # how many chapters cite it (how broadly it is relied on). They answer
    # different questions, which is why both columns exist.
    references: dict[str, int] = {}
    chapters: dict[str, int] = {}
    rows_by_key: dict[str, dict] = {}
    # Which findings each material backed, so the table can say what the
    # material contributed instead of only how often it was cited.
    direction_titles: dict[str, list[str]] = {}
    chapter_headings: dict[str, list[str]] = {}
    for row in narrative or ():
        direction_ids = row.get("direction_ids")
        if direction_ids is None:
            continue
        material_ids = set()
        heading = (row.get("heading") or "").strip()
        for direction_id in direction_ids:
            direction = directions_by_id.get(direction_id)
            if direction is None:
                continue
            for ref in (*direction.supporting_refs, *direction.counter_refs):
                material_ids.add(ref.material_id)
                references[ref.material_id] = references.get(ref.material_id, 0) + 1
                titles = direction_titles.setdefault(ref.material_id, [])
                if direction.title not in titles:
                    titles.append(direction.title)
        for material_id in material_ids:
            chapters[material_id] = chapters.get(material_id, 0) + 1
            if heading:
                headings = chapter_headings.setdefault(material_id, [])
                if heading not in headings:
                    headings.append(heading)

    for material_id, reference_count in references.items():
        material = by_material_id.get(material_id)
        if material is None:
            continue
        item = classification_by_key.get(material.evidence_key)
        rows_by_key[material.evidence_key] = {
            "material": material,
            "citation_id": f"c{cite_order[material_id]:03}",
            "references": reference_count,
            "chapters": chapters.get(material_id, 0),
            "classification": item,
            "direction_titles": tuple(direction_titles.get(material_id, ())),
            "chapter_headings": tuple(chapter_headings.get(material_id, ())),
        }
    ordered = sorted(
        rows_by_key.values(),
        key=lambda entry: (
            -entry["references"], -entry["chapters"],
            cite_order[entry["material"].material_id],
        ),
    )
    available = sum(
        1 for m in materials if m.status != "unavailable" and bool(m.text))
    return {
        "total_materials": len(materials),
        "available_materials": available,
        "unavailable_materials": len(materials) - available,
        "recalled": len(ordered),
        "total_references": sum(entry["references"] for entry in ordered),
        "entries": ordered,
    }


def _fallback_contribution(entry) -> str:
    """What a material contributed, derived from the frozen facts alone.

    Used when the per-row model call fails or answers unusably. It names the
    findings the material backs and what kind of material it is, which is
    strictly less than the model can say but never wrong — the row must never
    publish an empty or invented explanation.
    """
    material = entry["material"]
    titles = entry.get("direction_titles") or ()
    headings = entry.get("chapter_headings") or ()
    type_label = {"text": "文本记录", "parsed_text": "解析文本",
                  "android_record": "Android 派生记录", "audio_transcript": "机器转写",
                  "image": "图像", "machine_visual": "机器视觉观察",
                  "unavailable": "不可读材料"}.get(material.kind, "材料")
    parts = [f"该{type_label}"]
    if titles:
        parts.append("支撑「" + "」「".join(titles[:3]) + "」")
        if len(titles) > 3:
            parts[-1] += f" 等 {len(titles)} 项调查方向"
    else:
        parts.append("支撑本章结论")
    if headings:
        parts.append("，出现在「" + "」「".join(headings[:2]) + "」")
        if len(headings) > 2:
            parts[-1] += f" 等 {len(headings)} 章"
    if material.status == "partial":
        parts.append("；本轮仅解析了部分内容，引用范围以冻结片段为准")
    return "".join(parts) + "。"


def _clean_contribution(raw: str) -> str:
    """Validate one row's contribution; "" means "use the fallback"."""
    text = _plain_models_text(raw)
    text = strip_material_ids(text)
    text = re.sub(r"\s*\n+\s*", " ", text).strip()
    if len(text) < _CONTRIBUTION_MIN_CHARS:
        logger.info("Recall contribution too short (%d chars); using fallback", len(text))
        return ""
    if len(text) > _CONTRIBUTION_MAX_CHARS:
        # A long answer is usually a good one that ran on: cut at a sentence
        # boundary instead of discarding it for the generic fallback.
        cut = text[:_CONTRIBUTION_MAX_CHARS]
        boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("，"))
        text = cut[:boundary + 1] if boundary >= _CONTRIBUTION_MIN_CHARS else cut
    if _MATERIAL_ID_RE.search(text) or "evidence_key" in text.lower():
        logger.info("Recall contribution carries an internal id; using fallback")
        return ""
    if re.search(r"引用\s*\d+\s*次|被\s*\d+\s*章引用", text):
        # Counts already sit in the row header; repeating them is noise.
        logger.info("Recall contribution only restates counts; using fallback")
        return ""
    return text


async def compose_recall_contributions(stats, llm=None, *, concurrency: int = 1):
    """One "what did this material contribute" line per published row.

    Each call sees only that row's own frozen facts (its file name, type, the
    direction titles it backs, and a bounded excerpt of its frozen text), so
    the explanation cannot describe a material it was not given. Failures are
    per row: a rejected answer falls back to ``_fallback_contribution`` and the
    table still publishes.

    Returns a mapping ``evidence_key -> contribution``.
    """
    entries = stats["entries"][:_RECALL_TABLE_LIMIT]
    if llm is None or not entries:
        return {}

    async def one(entry):
        material = entry["material"]
        item = entry["classification"]
        payload = json.dumps({
            "name": stage_citation_name(material.evidence_key),
            "material_type": getattr(item, "material_type", "unknown") or "unknown",
            "topics": list(getattr(item, "topics", ()) or ()),
            "priority": getattr(item, "priority", "unassessed") or "unassessed",
            "found_in_chapters": list(entry.get("chapter_headings") or ()),
            "supports_directions": list((entry.get("direction_titles") or ())[:6]),
            "materials": material.text[:1200],
            "read_status": material.status,
            "limitations": list(material.limitations)[:3],
        }, ensure_ascii=False)
        try:
            response = await llm.chat_completion(
                STAGE_RECALL_CONTRIBUTION_SYSTEM_V1, payload,
                max_tokens=400, temperature=0.0)
        except Exception as exc:  # noqa: BLE001 - one row never sinks the table
            logger.warning("Recall contribution failed for %s: %s",
                           material.evidence_key, exc)
            return entry["material"].evidence_key, ""
        content = response.get("content")
        if not isinstance(content, str):
            return entry["material"].evidence_key, ""
        return entry["material"].evidence_key, _clean_contribution(content)

    results = await _gather_bounded([one(entry) for entry in entries], concurrency)
    contributions: dict[str, str] = {}
    for outcome in results:
        if isinstance(outcome, BaseException):
            logger.warning("Recall contribution rejected: %s", outcome)
            continue
        key, text = outcome
        if text:
            contributions[key] = text
    return contributions


def _recall_table(stats, contributions=None) -> EvidenceRecallTable:
    """The published recall table: top rows plus honest coverage notes."""
    contributions = contributions or {}
    rows = []
    for entry in stats["entries"][:_RECALL_TABLE_LIMIT]:
        material = entry["material"]
        item = entry["classification"]
        rows.append(EvidenceRecallRow(
            citation_id=entry["citation_id"],
            evidence_key=material.evidence_key,
            evidence_name=stage_citation_name(material.evidence_key),
            material_type=getattr(item, "material_type", "unknown") or "unknown",
            priority=getattr(item, "priority", "unassessed") or "unassessed",
            topics=tuple(getattr(item, "topics", ()) or ()),
            reference_count=entry["references"],
            chapter_count=entry["chapters"],
            material_status=material.status,
            contribution=(contributions.get(material.evidence_key)
                          or _fallback_contribution(entry)),
        ))
    notes = []
    omitted = stats["recalled"] - len(rows)
    if omitted > 0:
        notes.append(f"本表按引用次数列出前 {len(rows)} 份被引材料，"
                     f"其余 {omitted} 份见本轮材料清单。")
    unreferenced = stats["available_materials"] - stats["recalled"]
    if unreferenced > 0:
        notes.append(f"另有 {unreferenced} 份可用材料未被任何章节引用，"
                     "其内容未进入本报告正文。")
    if stats["unavailable_materials"]:
        notes.append(f"{stats['unavailable_materials']} 份材料不可读，"
                     "按读取限制处理，未回退使用历史摘要。")
    return EvidenceRecallTable(
        total_materials=stats["total_materials"],
        recalled_materials=stats["recalled"],
        unavailable_materials=stats["unavailable_materials"],
        total_citations=stats["total_references"],
        rows=tuple(rows),
        notes=tuple(notes),
    )


def _deterministic_overview(envelope, stats, directions) -> str:
    """Overview fallback used when the overview model call is unavailable.

    It states only counts and the strongest named objects, so it remains true
    when it replaces the model's prose. Without this the first chapter would
    open straight into a methods paragraph, which is exactly the gap the
    overview exists to close.
    """
    phase_a = envelope.analysis_mode == "evidence_only"
    observations = sum(1 for d in directions if d.finding_kind == "observation")
    hypotheses = len(directions) - observations
    subjects = []
    for direction in sorted(directions, key=lambda d: -len(d.supporting_refs)):
        for token in _SUBJECT_TOKEN_RE.findall(f"{direction.title} {direction.description}"):
            stem = token.rsplit(".", 1)[0].upper()
            if stem in _GENERIC_DEPENDENCIES or token.upper() in _SUBJECT_STOPWORDS:
                continue
            if _subject_rank(token) != 0 or token in subjects:
                continue
            subjects.append(token)
            if len(subjects) >= 6:
                break
        if len(subjects) >= 6:
            break
    parts = [
        f"本轮在 {stats['total_materials']} 份入报材料中形成 {observations} 条有材料支撑的观察"
        f"与 {hypotheses} 条待核方向，正文有 {stats['recalled']} 份材料被实际引用"
        f"（合计 {stats['total_references']} 处引用）。",
    ]
    if subjects:
        parts.append("材料中反复出现的具体对象包括 " + "、".join(subjects) + "；"
                     "它们的用途与关联仍需按各章结论核实。")
    if phase_a:
        parts.append("本轮未使用案情描述、人工备注或历史 AI 摘要，"
                     "因此报告只描述材料本身反映的活动，不对案件性质作推断。")
    else:
        parts.append("本轮案情只作为调查语境；材料未支持的部分按待核假设处理，"
                     "不构成已确认事实。")
    return "".join(parts)


async def compose_case_overview(envelope, materials, directions, narrative,
                                comparisons=(), classifications=None, llm=None,
                                *, timeout=None) -> str:
    """Write the report's opening whole-case summary.

    The model sees the finished chapters' headings and closing summaries plus
    the strongest directions — never the raw materials — so the overview can
    only restate what the report already established. Any failure returns the
    deterministic fallback: a report without an opening is still readable, and
    the first chapter must never fail because this one call did.
    """
    stats = _recall_stats(materials, narrative, directions, classifications)
    fallback = _deterministic_overview(envelope, stats, directions)
    if llm is None or not narrative:
        return fallback
    chapters = [
        {"heading": row.get("heading", ""), "summary": row.get("summary", "")}
        for row in narrative[:_MAX_REPORT_CHAPTERS]
    ]
    key_directions = [
        {"title": d.title, "kind": d.finding_kind, "origin": d.origin,
         "description": d.description[:300],
         "supporting": len(d.supporting_refs), "counter": len(d.counter_refs)}
        for d in sorted(directions, key=lambda d: (-len(d.supporting_refs), d.title))[:12]
    ]
    payload = json.dumps({
        "analysis_mode": envelope.analysis_mode,
        "case_context": envelope.case_description or None,
        "scope": {
            "total_materials": stats["total_materials"],
            "available_materials": stats["available_materials"],
            "unavailable_materials": stats["unavailable_materials"],
            "recalled_materials": stats["recalled"],
            "total_citations": stats["total_references"],
        },
        "chapters": chapters,
        "key_directions": key_directions,
        "comparison_counts": (
            {status: sum(1 for c in comparisons if c.status == status)
             for status in sorted({c.status for c in comparisons})}
            if comparisons else {}
        ),
    }, ensure_ascii=False)
    try:
        response = await llm.chat_completion(
            STAGE_CASE_OVERVIEW_SYSTEM_V1, payload, max_tokens=1600, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 - overview never fails the report
        logger.warning("Case overview synthesis failed; using deterministic summary: %s", exc)
        return fallback
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        return fallback
    overview = _clean_overview(content)
    if not overview:
        logger.warning("Case overview unusable; using deterministic summary")
        return fallback
    return overview


# Pipeline vocabulary that means nothing to a reader holding the report: the
# overview once opened with "本批材料围绕…展开", which reads like an internal
# batch log rather than a case summary.
_BATCH_VOICE_RE = re.compile(r"本批(?:材料|批次)?|该批(?:材料|批次)")


def _clean_overview(raw: str) -> str:
    """Normalize the overview: no ids, no markdown, no batch voice, sane length."""
    text = _plain_models_text(raw)
    text = strip_material_ids(text)
    text = _BATCH_VOICE_RE.sub("这批材料", text)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 120:
        return ""
    if _MATERIAL_ID_RE.search(text) or "evidence_key" in text.lower():
        return ""
    if len(text) > 2400:
        cut = text[:2400]
        boundary = max(cut.rfind("。"), cut.rfind("\n"))
        text = cut[:boundary + 1] if boundary > 0 else cut
    return text


def chapter_one_heading(envelope) -> str:
    """The first chapter's published title.

    It carries the case overview and the recall table, so naming it
    "研判范围与方法" alone would undersell what the reader finds there; the
    scope/methods paragraph is still the section's opening, unchanged.
    """
    return "案件总述与证据召回"


# A summary that claims the *unrecalled* materials were "recalled but unused"
# inverts the table. The table's own note says they never entered the prose, so
# a summary that says otherwise is replaced by the deterministic sentence.
_RECALL_SUMMARY_CONTRADICTION_RE = re.compile(
    r"(?:已|虽已|虽然)(?:被)?召回[^。；]{0,20}?未(?:被)?(?:任何)?(?:章节)?引用"
    r"|召回(?:但|却)[^。；]{0,12}?未(?:被)?引用"
)


def _fragment_summary(directions, *, limit: int = 3) -> str:
    """Closing statement for a deterministic fragment chapter.

    The fragment renderer is the fallback shape, but a chapter with no closing
    statement breaks the report's contract just as visibly as the narrative
    path would. The sentence is built from the fragment's own directions, so it
    cannot contradict what the fragments above it say.
    """
    if not directions:
        return ""
    observations = sum(1 for d in directions if d.finding_kind == "observation")
    hypotheses = len(directions) - observations
    subjects = [d.title for d in directions[:_SUBJECT_NAMES_IN_SUMMARY]]
    parts = [f"本组 {len(directions)} 项内容中，材料观察 {observations} 项、"
             f"待核假设 {hypotheses} 项"]
    if subjects:
        parts[0] += "，涉及" + "、".join(subjects)
    parts[0] += "；以上仅为材料层面的归纳，是否成立仍需按各项缺失信息核查。"
    return "".join(parts)


def _comparison_summary(by_status, labels, total) -> str:
    """Closing statement for the difference chapter (case-guided only)."""
    if not total:
        return ""
    changing = sum(len(by_status.get(status, ())) for status in ("contradicted", "revised"))
    weakened = len(by_status.get("weakened", ()))
    supported = len(by_status.get("supported", ()))
    if changing:
        return (f"{total} 项基线方向中，{supported} 项得到支持，"
                f"{changing} 项被相反材料或修正意见改变；这些方向以本轮对照结论为准。")
    if weakened:
        return (f"{total} 项基线方向中，{supported} 项得到支持、{weakened} 项支持减弱，"
                "没有方向被推翻，但减弱项的原判断不宜直接沿用。")
    return (f"{total} 项基线方向中 {supported} 项得到本轮材料支持，"
            "未出现相反材料；首次判断可继续沿用，但仍受本轮读取范围限制。")


def _advisory_summary(directions, warnings) -> str:
    """Closing statement for the manual-review chapter."""
    gaps = sum(1 for d in directions if d.missing_information)
    base = (f"{gaps} 项方向记录着直接决定定性的缺口，应优先补齐后再核对本章结论；"
            "未完成人工复核前，报告中的判断不得作为已确认事实。")
    if warnings:
        base += f"另有 {len(warnings)} 项分析或覆盖限制需在复核时一并确认。"
    return base


def _recall_summary_fallback(stats) -> str:
    """Two sentences that are guaranteed true, used when the model fails."""
    if not stats["recalled"]:
        return (f"本轮 {stats['total_materials']} 份入报材料未形成可引用的章节结论，"
                "证据召回为空，报告仅保留研判范围与核查建议。")
    top = stats["entries"][0]
    name = stage_citation_name(top["material"].evidence_key)
    return (f"{stats['total_materials']} 份入报材料中有 {stats['recalled']} 份被正文实际引用，"
            f"合计 {stats['total_references']} 处引用；引用最多的 {name} 涉及 "
            f"{top['chapters']} 个章节。未被引用的材料不构成本报告的结论依据。")


async def compose_recall_summary(stats, overview, llm=None) -> str:
    """The one-to-two-sentence conclusion printed after the recall table.

    Grounded on the table's own numbers, so it can state coverage as fact
    instead of hedging. Falls back to a deterministic sentence.
    """
    fallback = _recall_summary_fallback(stats)
    if llm is None:
        return fallback
    top_rows = [
        {"name": stage_citation_name(entry["material"].evidence_key),
         "references": entry["references"], "chapters": entry["chapters"]}
        for entry in stats["entries"][:10]
    ]
    payload = json.dumps({
        "scope": {
            "total_materials": stats["total_materials"],
            "available_materials": stats["available_materials"],
            "unavailable_materials": stats["unavailable_materials"],
            "recalled_materials": stats["recalled"],
            "total_citations": stats["total_references"],
            # Stated explicitly: the summary must not describe these materials
            # as "recalled but uncited" — they never reached a chapter.
            "available_but_not_recalled": max(0, stats["available_materials"] - stats["recalled"]),
        },
        "top_recalled": top_rows,
        "overview": overview[:1200],
    }, ensure_ascii=False)
    try:
        response = await llm.chat_completion(
            STAGE_RECALL_SUMMARY_SYSTEM_V1, payload, max_tokens=320, temperature=0.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recall summary synthesis failed: %s", exc)
        return fallback
    content = response.get("content")
    if not isinstance(content, str):
        return fallback
    summary = _clean_chapter_summary(content)
    if summary and _RECALL_SUMMARY_CONTRADICTION_RE.search(summary):
        # The model described non-recalled materials as "recalled but unused",
        # which is the opposite of what the table's notes say. The deterministic
        # sentence is correct, so prefer it over a wrong one.
        logger.warning("Recall summary contradicts the table; using fallback")
        return fallback
    return summary or fallback


# Concrete values a reader expects to see in a case thread: addresses, config
# keys, accounts, artifact names, versions, counts. Every candidate is kept
# only if it occurs verbatim in the thread's own quotes, which are already
# char-span-anchored in the frozen materials — so a published key fact can
# never be a value the evidence does not contain.
# Ordered by how much they tell an investigator: a C2 address or a registry
# path beats a file name, and a copyright line tells nothing. The previous
# order let MIT/Apache license text fill a Quasar thread's fact list.
_THREAD_FACT_PATTERNS = (
    r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b",          # C2 / host:port
    r"<[A-Za-z][\w]*>[^<\n]{1,80}</[A-Za-z][\w]*>",            # <Hosts>…</Hosts>
    r"(?:HKCU|HKLM|HKU)[\\/][^\s，。；、「」]+",                 # registry path
    r"\b[A-Za-z0-9_.\-]+\s*=\s*(?:True|False|\d+)\b",       # Key=False
    r"\b[\w.\- @[\]]*@[A-Za-z0-9.\-]+",                     # account
    r"[A-Za-z]:\\[^\s，。；、「\"]+",                           # absolute path
    r"\b[\w.\-]+\.(?:exe|dll|txt|ini|xml|evtx|pf|log|7z|dat|db|json|docx|xlsx|lnk)\b",
    r"运行\s*\d+\s*次",
    r"\b[0-9a-f]{32,64}\b",                                    # hashes only
)
# License/notice boilerplate is never a case fact.
_THREAD_FACT_NOISE_RE = re.compile(
    r"copyright|license|licence|permission is hereby granted|all rights reserved|"
    r"\bmit\b|\bapache\b|\bbsd\b|warranty|^v?\d+(?:\.\d+)+$",
    re.IGNORECASE)
_THREAD_FACT_MAX = 6


def _extract_thread_facts(quotes):
    """Pull concrete values out of a thread's quotes, verbatim-anchored."""
    facts, seen = [], set()
    corpus = "\n".join(quotes)
    for pattern in _THREAD_FACT_PATTERNS:
        for match in re.findall(pattern, corpus):
            token = match.strip()
            if len(token) < 4 or len(token) > 80 or token.lower() in seen:
                continue
            if _THREAD_FACT_NOISE_RE.search(token):
                continue
            seen.add(token.lower())
            facts.append(token)
            if len(facts) >= _THREAD_FACT_MAX:
                return tuple(facts)
    return tuple(facts)


def _merge_duplicate_threads(theme_rows) -> None:
    """Fold threads whose relabeled names collapsed to the same thread.

    Induction may keep two groups with near-identical subjects apart (its merge
    stage refuses to combine groups beyond 30 directions); after relabeling they
    read as the same case thread, so the members fold back together and the
    stronger contribution survives. Exhaustiveness is preserved: no direction
    is dropped or duplicated.
    """
    by_name: dict[str, dict] = {}
    duplicates = []
    for row in theme_rows:
        key = re.sub(r"\s+", "", row.get("name") or row["theme_name"])
        if key not in by_name:
            by_name[key] = row
            continue
        keeper = by_name[key]
        duplicates.append(row)
        keeper["members"] = tuple(keeper["members"]) + tuple(row["members"])
        keeper["direction_titles"] = tuple(dict.fromkeys(
            (*keeper["direction_titles"], *row["direction_titles"])))
        keeper["quotes"] = tuple(dict.fromkeys(
            (*keeper["quotes"], *row["quotes"])))
        keeper["reference_count"] += row["reference_count"]
        keeper["material_count"] = max(keeper["material_count"], row["material_count"])
        keeper["chapter_numbers"] = tuple(dict.fromkeys(
            (*keeper["chapter_numbers"], *row["chapter_numbers"])))
        if len(row.get("contribution") or "") > len(keeper.get("contribution") or ""):
            keeper["contribution"] = row.get("contribution")
        keeper["facts"] = tuple(dict.fromkeys((
            *(keeper.get("facts") or ()), *(row.get("facts") or ()))))[:_THREAD_FACT_MAX]
    for row in duplicates:
        theme_rows.remove(row)


def _fallback_thread(row) -> str:
    """Deterministic thread summary used when the relabel call is unusable."""
    titles = row["direction_titles"][:2]
    base = f"该线索聚合了 {len(row['members'])} 项调查方向"
    if titles:
        base += "，包括「" + "」「".join(titles) + "」"
    base += f"，涉及 {row['material_count']} 份材料、{row['reference_count']} 处引文"
    if row["chapter_numbers"]:
        base += "，分布见第 " + "、".join(str(n) for n in row["chapter_numbers"][:4]) + " 章"
    return base + "；各发现的证据强度以本章正文与缺失信息为准。"



# A thread name must name a case OBJECT and say what about it. Names that only
# list artifacts or only describe a generic activity read as an inventory row:
# "PrivaZer安装包DLL注册" tells an investigator nothing to chase, while
# "Quasar 控制端配置与 C2 驻留" does.
_THREAD_BEHAVIOUR_RE = re.compile(
    r"驻留|回连|外联|启动|执行|注入|提权|清理|删除|导出|泄露|外传|下载|安装|"
    r"崩溃|报错|异常|失败|缺失|为空|缺口|遗留|痕迹|配置|写入|加载|调用|"
    r"连接|登录|枚举|扫描|加密|解密|持久化|反取证|部署|运行|触发|篡改|绕过|"
    r"无可读|无法读取|未提取|空白|倒置|重复|可疑|暴露|未加密|已关闭|禁用|"
    r"核对|比对|矛盾|不符|不一致|关联|印证|"
    r"空数据|无数据|为空|空值|异常值|倒置|错乱|缺失|空白|未激活|未启动|"
    r"撤销|回滚|覆盖|残留|遗留|同源|重复|并存|邻近|聚集|集中|同步")
# Names made only of artifact nouns ("DLL 注册", "API", "日志", "记录") without
# an object that a human would recognise as software/directory/subject.
_THREAD_VAGUE_OBJECTS = (
    "材料观察", "系统组件", "组件执行", "系统进程", "其他", "杂项", "综合",
    "相关内容", "相关执行", "待核线索", "异常记录", "未知对象",
    "重点可疑对象", "可疑对象", "重点对象", "主要发现", "关键发现",
)


# Generic subsystem labels: they describe a category of activity, not an object
# an investigator would go and look at.
_THREAD_GENERIC_SUBJECTS = frozenset({
    "服务控制", "系统进程", "系统组件", "常规活动", "背景材料", "系统服务",
    "运行状态", "使用痕迹", "系统配置", "应用活动",
})

# Technology words that name a mechanism rather than a case object. A thread
# called "服务控制与驱动加载API" says what the artifacts can DO, not what in
# this case is worth chasing.
_THREAD_MECHANISM_RE = re.compile(
    r"API|\bPID\b|驱动加载|注册表|文件系统|网络协议|句柄|线程|内存页|"
    r"系统调用|内核|Win32|COM|WMI|RPC", re.IGNORECASE)


def _thread_name_is_readable(name: str) -> bool:
    """True when a thread name names a concrete case object AND a behaviour.

    Deliberately mechanical and testable. Accepted when the name contains:
      - a behaviour word, AND
      - a concrete subject: a named artifact token (WMIADAP, PrivaZer,
        Default.xml), or a CJK noun that is not pure mechanism vocabulary.
    Rejected names are rebuilt from the thread's own subjects by
    ``_fallback_thread_name``.
    """
    compact = re.sub(r"[\s、，,与和及：:]+", "", name)
    # Whole-name vagueness only: a named subject plus "相关执行" is fine
    # ("WMIADAP相关执行"), while a name that IS a vague phrase is not.
    if compact in _THREAD_VAGUE_OBJECTS:
        return False
    for vague in _THREAD_VAGUE_OBJECTS:
        if name.startswith(vague) and len(compact) - len(vague) < 3:
            return False
    if not _THREAD_BEHAVIOUR_RE.search(name):
        return False
    identifiers = [token for token in re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{2,}", name)
                   if token.upper() not in _THREAD_MECHANISM_WORDS]
    if identifiers:
        return True
    stem = _THREAD_BEHAVIOUR_RE.sub("", name)
    stem = re.sub(r"[A-Za-z0-9_.\-]+", "", stem)
    for raw in re.split(r"[与和及、，,：:\s]+", stem):
        word = raw.strip("的")
        if len(word) < 2 or word in _THREAD_MECHANISM_CJK:
            continue
        # A CJK subject qualifies when it is not wholly built from mechanism
        # vocabulary ("服务控制" vs "内存转储" / "计划任务" / "控制端").
        if not all(part in _THREAD_MECHANISM_CJK for part in _cjk_segments(word)):
            return True
    return False


def _cjk_segments(word: str):
    """Split a CJK word into the mechanism-vocabulary segments it contains."""
    segments, rest = [], word
    for term in sorted(_THREAD_MECHANISM_CJK, key=len, reverse=True):
        if term in rest:
            segments.append(term)
            rest = rest.replace(term, "|")
    segments.extend(part for part in rest.split("|") if part)
    return segments


_THREAD_MECHANISM_WORDS = frozenset({
    "API", "PID", "DLL", "EXE", "LOG", "EVTX", "PF", "INI", "XML", "COM", "WMI",
    "RPC", "SQL", "HTTP", "TCP", "UDP", "DNS", "TLS", "SSH",
})

# CJK mechanism vocabulary: these describe HOW artifacts work, not WHAT in this
# case is worth chasing. A name made only of these has no case object.
_THREAD_MECHANISM_CJK = frozenset({
    "服务控制", "驱动加载", "注册表", "文件系统", "网络协议", "内存", "线程",
    "内核", "系统调用", "加载", "调用", "控制", "服务", "驱动", "系统",
    "进程", "组件", "记录", "日志", "执行", "相关", "基线", "活动", "配置",
})


def _fallback_thread_name(row) -> str:
    """Deterministic object+behaviour name built from the thread's own facts.

    Uses the most specific named subject in the thread's direction titles and
    quotes (a program, directory component, or config key), then the strongest
    behaviour word from its titles. Never invents a subject.
    """
    text = " ".join(row["direction_titles"]) + " " + " ".join(row["quotes"][:3])
    subjects = []
    for token in _SUBJECT_TOKEN_RE.findall(text):
        stem = token.rsplit(".", 1)[0].upper()
        if stem in _GENERIC_DEPENDENCIES or token.upper() in _SUBJECT_STOPWORDS:
            continue
        if token in subjects:
            continue
        subjects.append(token)
        if len(subjects) >= 2:
            break
    behaviour = re.search(_THREAD_BEHAVIOUR_RE, " ".join(row["direction_titles"]))
    if subjects and behaviour:
        return _shorten_heading(f"{subjects[0]} {behaviour.group(0)}", 24)
    if subjects:
        return _shorten_heading(f"{subjects[0]} 相关痕迹", 24)
    return _shorten_heading(row["theme_name"], 24)


def _trim_thread_label(name: str) -> str:
    """Shorten an over-long thread name without cutting a word in half.

    A raw slice produced "RuntimeBroker 多实例高频执" and "Windows Store 商店
    数据库缓" — labels cut mid-word, which read as broken text. Prefer the last
    separator inside the budget, then the last complete Latin token.
    """
    if len(name) <= _THREAD_NAME_MAX:
        return name
    budget = name[:_THREAD_NAME_MAX]
    for sep in ("，", ",", "、", "：", ":", " ", "与", "和", "及"):
        cut = budget.rfind(sep)
        if cut >= 6:
            candidate = budget[:cut].strip(" 与和及、，,：:")
            if len(candidate) >= 4:
                return candidate
    # No separator: drop a trailing partial Latin word or CJK fragment.
    candidate = re.sub(r"[A-Za-z]+$", "", budget).strip()
    if len(candidate) >= max(4, _THREAD_NAME_MAX // 2):
        return candidate
    candidate = re.sub(r"[\u4e00-\u9fff]{1,2}$", "", budget).strip()
    return candidate or budget


def _clean_thread_fields(raw_name, raw_contribution, raw_facts, row):
    """Validate the relabel answer for one thread; None means "use fallback"."""
    name = _plain_models_text(raw_name)
    name = re.sub(r"^\d+[.、：:]\s*", "", name).strip()
    # An over-long name is a formatting miss, not a reason to discard a good
    # answer: shorten at a natural boundary instead. A raw slice produced
    # "RuntimeBroker 多实例高频执" and "Windows Store 商店数据库缓" — labels
    # cut mid-word, which read as broken text.
    if len(name) > _THREAD_NAME_MAX:
        name = _trim_thread_label(name)
    if not (2 <= len(name) <= _THREAD_NAME_MAX) or _MATERIAL_ID_RE.search(name):
        return None
    if not _thread_name_is_readable(name):
        # A name that names no object or no behaviour is repaired from the
        # thread's own subjects, then from its own titles; never published as
        # an inventory label.
        repaired = _object_thread_name(
            name, row.get("theme_name") or "", row.get("members") or ())
        if _thread_name_is_readable(repaired):
            name = repaired
        else:
            name = _fallback_thread_name(row)
        if not _thread_name_is_readable(name):
            return None
    contribution = _plain_models_text(raw_contribution)
    contribution = strip_material_ids(contribution)
    contribution = re.sub(r"\s*\n+\s*", " ", contribution).strip()
    if len(contribution) < 20 or _MATERIAL_ID_RE.search(contribution):
        return None
    if len(contribution) > 220:
        cut = contribution[:220]
        boundary = max(cut.rfind("。"), cut.rfind("；"))
        contribution = cut[:boundary + 1] if boundary >= 20 else contribution
    facts = []
    if isinstance(raw_facts, list):
        allowed = {q.lower() for q in row["quotes"]}
        lowered = set()
        for value in raw_facts[:_THREAD_FACT_MAX]:
            if not isinstance(value, str):
                continue
            token = strip_material_ids(value.strip())
            # A key fact must exist verbatim in the thread's own quotes:
            # this is what keeps the bolded values anchored to evidence.
            if len(token) < 4 or token.lower() in lowered:
                continue
            # Model-chosen facts go through the same noise filter as extracted
            # ones: a Quasar thread once listed three copyright lines and no
            # config value at all.
            if _THREAD_FACT_NOISE_RE.search(token):
                continue
            if token.lower() not in allowed and not any(token.lower() in q.lower() for q in row["quotes"]):
                continue
            lowered.add(token.lower())
            facts.append(token)
    return name, contribution, tuple(facts)


# Materials that carry no case semantics: licenses, icons, AppX manifests and
# signatures ship with every installed program and are evidence of nothing by
# themselves. A direction built only on them reads as an inventory row, so the
# thread table ranks it last (it is never dropped from the evidence set or the
# appendix — the audit trail stays complete).
_LOW_VALUE_EVIDENCE_RE = re.compile(
    r"(?:license|licence|copying|notice|thirdparty|third_party|readme|changelog)"
    r"(?:\.[a-z0-9]+)?$|"
    r"\.(?:png|jpg|jpeg|gif|ico|svg|bmp|ttf|otf|woff2?)$|"
    r"appx(?:blockmap|manifest|signature)|manifest\.json$|"
    r"\b(?:logo|icon|splash|banner)[-.\w]*\.(?:png|jpg|ico|bmp)$",
    re.IGNORECASE)


def _is_low_value_evidence(evidence_key: str) -> bool:
    """True for bundled artifacts (licenses, icons, package manifests)."""
    name = stage_citation_name(evidence_key)
    return bool(_LOW_VALUE_EVIDENCE_RE.search(name))


def _object_thread_name(label, parent_name, rows) -> str:
    """Give a split part a name that says what happened, not just what it is.

    The split label is a directory ("RUNTIMEBROKER.EXE", "SmartScreen"), which
    names an object but says nothing about it. Add the strongest behaviour word
    from the part's own direction titles so the thread reads as a finding.
    Connectors and half-cut words are never allowed to survive a truncation.
    """
    title_blob = " ".join(d.title for d in rows)
    behaviour = _THREAD_BEHAVIOUR_RE.search(title_blob)
    verb = behaviour.group(0) if behaviour else ""
    # Prefer a whole phenomenon phrase from the first title ("空数据",
    # "卷影复制与备份活动"): a single verb loses what the artifact showed.
    phrase = ""
    for direction in rows:
        candidate = direction.title.strip()
        if _THREAD_BEHAVIOUR_RE.search(candidate):
            phrase = re.split(r"[，,；;。]", candidate)[0].strip()
            break
    base = (label or parent_name or "").strip()
    if not base:
        return _fallback_thread_name({"direction_titles": tuple(d.title for d in rows),
                                      "quotes": (), "theme_name": "未命名线索"})
    # The label may be a prefix of its own title ("Cortana DOMStore" of
    # "Cortana DOMStore 空数据"): the remainder is the phenomenon to append.
    if phrase and phrase.startswith(base) and len(phrase) > len(base):
        remainder = phrase[len(base):].strip(" 与和及、，,：:-")
        # A title that repeats the label ("代码完整性…" / "代码完整性重复评估")
        # leaves repeated words in the remainder; strip the shared prefix.
        shared = 0
        for a, b in zip(base, remainder):
            if a != b:
                break
            shared += 1
        if shared >= 4:
            remainder = remainder[shared:].strip(" 与和及、，,：:-")
        if remainder and len(base) + len(remainder) + 1 <= _THREAD_NAME_MAX:
            return _clean_thread_label(f"{base} {remainder}")
        return _clean_thread_label(
            f"{_shorten_heading(base, max(6, _THREAD_NAME_MAX - len(remainder) - 1))} {remainder}")
    in_label = _THREAD_BEHAVIOUR_RE.search(base)
    if verb and not in_label:
        # Use the phenomenon phrase when it fits, else the bare verb.
        tail = phrase if phrase and len(phrase) <= 12 else verb
        room = max(6, _THREAD_NAME_MAX - len(tail) - 1)
        stem = _shorten_heading(base, room)
        return _clean_thread_label(f"{stem} {tail}")
    if in_label:
        # The label already carries a verb; shorten around it so the verb is
        # the part that survives ("RUNDLL32 与 RUNONCE 执行记录" -> "RUNDLL32 执行").
        head = base[:in_label.start()].strip(" 与和及、，,：:")
        head = _clean_thread_label(_shorten_heading(
            head, max(4, _THREAD_NAME_MAX - len(in_label.group(0)) - 1))) or ""
        combined = f"{head} {in_label.group(0)}".strip()
        return combined[:_THREAD_NAME_MAX]
    return _clean_thread_label(_shorten_heading(base, _THREAD_NAME_MAX)) or base[: _THREAD_NAME_MAX]


_DANGLING_THREAD_TAIL = ("与", "和", "及", "的", "在", "对", "将", "把", "从", "向")


def _clean_thread_label(text: str) -> str:
    """Drop a dangling connector / half identifier left by a truncation."""
    label = text.strip(" 与和及、，,：:-")
    # A trailing partial Latin word ("RUNONCE 执") is a cut, not a word.
    label = re.sub(r"[\s]+[A-Za-z]{1,2}$", "", label)
    for tail in _DANGLING_THREAD_TAIL:
        if label.endswith(tail):
            label = label[: -len(tail)].strip(" 与和及、，,：:-")
    return label


def _split_theme_by_object(theme, directions_by_id, paths, limit):
    """Split an oversized theme along its case OBJECTS, not by count.

    Slicing a 172-direction theme into 30-direction chunks produces parts that
    all still say "PrivaZer 安装包", which is what buried Quasar: the object
    never got its own group. Grouping the members by the directory their
    evidence lives in keeps each part a recognisable object, and only the
    genuinely undifferentiated tail falls back to size chunks.
    """
    members = theme["directions"]
    buckets: dict[str, list] = {}
    for direction in members:
        dirs = []
        for ref in (*direction.supporting_refs, *direction.counter_refs):
            path = paths.get(ref.material_id) or ""
            if path:
                dirs.append(_object_directory(path))
        key = max(dirs, key=len) if dirs else ""
        buckets.setdefault(key, []).append(direction)
    if len(buckets) <= 1:
        return None
    # Objects with real weight become their own thread. The long tail of small
    # objects is grouped together rather than published as dozens of
    # single-direction threads: a table of 200 one-row threads is an inventory
    # again, only sorted differently.
    ordered = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    major = [(key, rows) for key, rows in ordered
             if len(rows) >= _THREAD_OBJECT_MIN_DIRECTIONS]
    minor = [row for key, rows in ordered
             if len(rows) < _THREAD_OBJECT_MIN_DIRECTIONS for row in rows]
    parts = [(key, tuple(rows)) for key, rows in major]
    if minor:
        # The tail keeps the parent theme's name; it is honestly labelled as a
        # collection rather than pretending to be one object.
        parts.append((theme["name"], tuple(minor[:_THEME_ROW_MAX_DIRECTIONS])))
        for start in range(_THEME_ROW_MAX_DIRECTIONS, len(minor), _THEME_ROW_MAX_DIRECTIONS):
            parts.append((theme["name"], tuple(
                minor[start:start + _THEME_ROW_MAX_DIRECTIONS])))
    return parts


def _object_label(rows, paths) -> str:
    """The most common enclosing directory among a set of directions."""
    counts: dict[str, int] = {}
    for direction in rows:
        for ref in (*direction.supporting_refs, *direction.counter_refs):
            path = paths.get(ref.material_id) or ""
            if not path:
                continue
            label = _object_directory(path)
            counts[label] = counts.get(label, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))[0]


# Directory names that describe a file's role inside a product, not the
# product itself. Skipping them is what makes Default.xml resolve to
# "Quasar v1.4.1" instead of "Profiles".
# Shared artifact stores: every program writes here, so a directory under one
# of them identifies a material TYPE, never a case object.
_SYSTEM_DIRS = frozenset({
    "prefetch", "system32", "syswow64", "winevt", "logs", "log", "temp", "tmp",
    "cache", "recent", "tasks", "drivers", "config", "software", "system",
    "currentcontrolset", "microsoft", "windows", "users", "programdata",
    "appdata", "local", "roaming", "desktop", "documents", "downloads",
})

_STRUCTURAL_DIRS = frozenset({
    "profiles", "profile", "config", "configs", "settings", "data", "bin",
    "lib", "libs", "src", "include", "resources", "assets", "plugins",
    "desktop", "documents", "downloads", "appdata", "local", "roaming",
    "program files", "program files (x86)", "windows", "system32", "users",
    "admin", "temp", "tmp", "cache", "logs", "log", "thirdpartylicenses",
    "3rdpartylicenses", "localstate", "appdata_local", "current", "retail",
    "release", "debug", "x64", "x86", "amd64",
})


def _object_directory(path: str) -> str:
    """The case-object directory of a path: the leaf-most meaningful folder.

    Default.xml sits in .../控制端/Quasar v1.4.1/Profiles/, and "Quasar v1.4.1"
    — not "Profiles" — is what names the object. Walk up from the file and take
    the first directory that is not a structural role name.
    """
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts:
        return path
    for part in reversed(parts[:-1]):
        if part.lower() in _STRUCTURAL_DIRS:
            continue
        if part.lower() in _SYSTEM_DIRS:
            # System-wide artifact folders (Prefetch, Logs, System32) are shared
            # by hundreds of unrelated programs; grouping by them produces one
            # 114-direction "Prefetch" thread that names no case object.
            break
        if len(part) >= 3:
            return part[:40]
    # No meaningful directory above the file: fall back to the file's own name
    # without extension (SVCHOST.EXE-67EC2DA7.pf -> SVCHOST), which at least
    # names the object rather than the artifact type.
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", parts[-1])
    stem = re.split(r"[-_]", stem)[0]
    return (stem or parts[-1])[:40]


def _prepare_theme_rows(envelope, themes, materials, directions, narrative):
    """One row of raw facts per theme, ordered by evidence weight."""
    cite_order = {m.material_id: i for i, m in enumerate(materials, 1)}
    offset = 1 + (0 if envelope.analysis_mode == "evidence_only" else 1)
    chapter_of_direction: dict[str, set[int]] = {}
    for index, row in enumerate(narrative or ()):
        number = offset + index + 1
        # One direction can be cited by several chapters; the thread must show
        # every chapter it appears in, not just the first.
        for direction_id in row.get("direction_ids") or ():
            chapter_of_direction.setdefault(direction_id, set()).add(number)
    # An oversized theme is split along its case objects before it becomes a
    # row: a 172-direction "PrivaZer 安装包" group used to swallow Quasar,
    # Foxmail and every other object that happened to share a directory.
    expanded = []
    for theme in themes:
        members = tuple(theme.get("directions") or ())
        if len(members) > _THEME_ROW_MAX_DIRECTIONS:
            parts = _split_theme_by_object(
                {"name": theme.get("name") or "", "directions": members},
                {d.direction_id: d for d in members},
                {m.material_id: stage_citation_key_path(m.evidence_key) for m in materials},
                _THEME_ROW_MAX_DIRECTIONS)
            if parts:
                new_parts = []
                for label, rows in parts:
                    name = _object_thread_name(label, theme.get("name") or "", rows)
                    # Same readability gate as a model-written name: a part
                    # that still names only artifacts is not published.
                    if not _thread_name_is_readable(name):
                        name = _fallback_thread_name({
                            "theme_name": theme.get("name") or "未命名线索",
                            "direction_titles": tuple(d.title for d in rows),
                            "quotes": tuple(
                                r.quote for d in rows
                                for r in (*d.supporting_refs, *d.counter_refs)),
                        })
                    new_parts.append({"name": name, "directions": rows})
                expanded.extend(new_parts)
                continue
        expanded.append(theme)

    theme_rows = []
    for theme in expanded:
        members = tuple(theme.get("directions") or ())
        if not members:
            continue
        refs = [r for d in members for r in (*d.supporting_refs, *d.counter_refs)]
        material_ids = {r.material_id for r in refs}
        chapter_numbers = tuple(sorted(set().union(*(
            chapter_of_direction[d.direction_id]
            for d in members if d.direction_id in chapter_of_direction))))
        # A thread is "low value" when every material it cites is a bundled
        # artifact (license/icon/manifest): it stays in the table for audit but
        # must not outrank a real case object.
        material_keys = [m.evidence_key for m in materials if m.material_id in material_ids]
        low_value = bool(material_keys) and all(
            _is_low_value_evidence(key) for key in material_keys)
        raw_name = (theme.get("name") or "").strip()
        if raw_name in ("未归类材料观察", "未归类", "no_theme", ""):
            # The induction's catch-all bucket has no object; name it from the
            # strongest subject it actually contains.
            raw_name = _fallback_thread_name({
                "theme_name": raw_name or "未归类",
                "direction_titles": tuple(d.title for d in members),
                "quotes": tuple(r.quote for r in refs)})
        theme_rows.append({
            "theme_name": raw_name or "未命名线索",
            "members": members,
            "direction_titles": tuple(d.title for d in members),
            "quotes": tuple(r.quote for r in refs),
            "reference_count": len(refs),
            "material_count": len(material_ids),
            "chapter_numbers": chapter_numbers,
            "low_value": low_value,
        })
    # Real case objects first; bundled-artifact threads sink to the bottom even
    # when they happen to have many quotes (an install bundle can out-cite a
    # single suspicious config).
    theme_rows.sort(key=lambda r: (
        bool(r.get("low_value")), -r["reference_count"], -r["material_count"],
        r["theme_name"]))
    return theme_rows


def _build_thread_table(envelope, theme_rows, materials, directions):
    """Assemble the published table; deterministic names/facts when unlabeled."""
    cite_order = {m.material_id: i for i, m in enumerate(materials, 1)}
    by_material = {m.material_id: m for m in materials}
    rows, covered_materials = [], set()
    for row in theme_rows:
        material_ids = {r.material_id for d in row["members"]
                        for r in (*d.supporting_refs, *d.counter_refs)}
        covered_materials.update(mid for mid in material_ids if mid in by_material)
        citation_ids = tuple(
            f"c{cite_order[mid]:03}" for mid in sorted(
                material_ids, key=lambda x: cite_order.get(x, 10 ** 9)))
        rows.append(EvidenceThreadRow(
            name=row.get("name") or row["theme_name"],
            contribution=row.get("contribution") or _fallback_thread(row),
            # Quotes are the anchored source of truth; when a thread's quotes
            # are empty the direction text is the next best place, since those
            # tokens were themselves derived from quoted material.
            key_facts=row.get("facts") or _extract_thread_facts(
                row["quotes"] or row["direction_titles"]),
            direction_count=len(row["members"]),
            material_count=row["material_count"],
            reference_count=row["reference_count"],
            chapter_count=len(row["chapter_numbers"]),
            chapter_numbers=row["chapter_numbers"],
            citation_ids=citation_ids,
            low_value=bool(row.get("low_value")),
        ))
    covered = sum(r.direction_count for r in rows)
    notes = [f"全部 {len(directions)} 项调查方向已归入 {len(rows)} 条线索，"
             "未出现遗漏或重复。"]
    uncovered = len(directions) - covered
    if uncovered:
        notes.append(f"另有 {uncovered} 项方向未归入任何线索。")
    return EvidenceThreadTable(
        covered_directions=covered,
        total_directions=len(directions),
        total_materials=len(covered_materials),
        rows=tuple(rows),
        notes=tuple(notes),
    )


async def compose_evidence_threads(envelope, themes, materials, directions, narrative,
                                   llm=None, *, concurrency: int = 1):
    """Build the exhaustive case-thread table from the induced theme grouping.

    Exhaustive by construction: themes come from the same induction pass that
    the chapters were written from, and induction guarantees every direction
    lands in exactly one group — so the table covers all findings, per the
    report's contract. The relabel call only renames threads, writes their
    contribution and picks anchored key facts; a failed or unusable answer
    falls back to the deterministic naming and summary per thread.

    Returns an :class:`EvidenceThreadTable`, or ``None`` without themes.
    """
    if not themes or not directions:
        return None
    theme_rows = _prepare_theme_rows(envelope, themes, materials, directions, narrative)
    if llm is not None and theme_rows:
        # ONE relabel call for the whole table: chunked calls renamed similar
        # themes independently, so the published table grew duplicate threads
        # ("CodeIntegrity..." twice) and whole chunks fell back when one answer
        # was malformed. A single call sees every thread and cannot collide.
        payload = json.dumps({"threads": [
            {"index": i + 1,
             "name": row["theme_name"],
             "found_in_chapters": list(row["chapter_numbers"][:4]),
             "supports": list(row["direction_titles"][:8]),
             "samples": [q[:120] for q in row["quotes"][:4]],
             } for i, row in enumerate(theme_rows)]}, ensure_ascii=False)
        try:
            response = await llm.chat_completion(
                STAGE_EVIDENCE_THREAD_SYSTEM_V1, payload,
                max_tokens=8000, temperature=0.0)
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("THREAD_RELABEL_EMPTY")
            parsed = _loads_strict(_plain_models_text(content))
            items = parsed.get("threads") if isinstance(parsed, dict) else None
            if not isinstance(items, list):
                raise ValueError("THREAD_RELABEL_SHAPE")
            relabeled_count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                if not isinstance(index, int) or not 1 <= index <= len(theme_rows):
                    continue
                row = theme_rows[index - 1]
                cleaned = _clean_thread_fields(
                    item.get("name"), item.get("contribution"),
                    item.get("key_facts"), row)
                if cleaned is None:
                    continue
                row["name"], row["contribution"], row["facts"] = cleaned
                relabeled_count += 1
            logger.info("Thread relabel: %d/%d threads relabeled",
                        relabeled_count, len(theme_rows))
        except Exception as exc:  # noqa: BLE001 - fallback naming stays truthful
            logger.warning("Thread relabel failed (%s); using grouping names", exc)
        _merge_duplicate_threads(theme_rows)

    return _build_thread_table(envelope, theme_rows, materials, directions)


def render_stage_report(envelope, materials, directions, comparisons, warnings, narrative=None,
                        *, overview=None, recall_summary=None, classifications=None,
                        recall_contributions=None, thread_table=None):
    phase_a = envelope.analysis_mode == "evidence_only"
    directions_by_id = {d.direction_id: d for d in directions}
    warnings = list(warnings)
    citations = tuple(StructuredReportCitation(citation_id=f"c{i:03}", evidence_key=m.evidence_key)
                      for i, m in enumerate(materials, 1))
    cid = {m.material_id: c.citation_id for m, c in zip(materials, citations)}
    available = sum(m.status != "unavailable" and bool(m.text) for m in materials)
    stats = _recall_stats(materials, narrative, directions, classifications)
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
    # Chapter 1 keeps the scope paragraph verbatim and expands it. Order matters:
    # the reader meets the whole case first, then the reading limits that qualify
    # it — the scope paragraph in front made the chapter open with "911 份材料、
    # 116 份不可用" before saying anything about the case.
    front_overview = overview or _deterministic_overview(envelope, stats, directions)
    if narrative:
        first_content = f"{front_overview}\n\n{scope}".strip()
    else:
        # Fragment fallback: no chapters were written, so there is nothing to
        # recall and the overview would only restate the scope paragraph.
        first_content = scope
    sections = [StructuredReportSection(
        heading=chapter_one_heading(envelope), content=first_content,
        citation_ids=scope_citation_ids,
        summary=(recall_summary or _recall_summary_fallback(stats)) if narrative else "",
        thread_table=(thread_table or _build_thread_table(
            envelope,
            _prepare_theme_rows(envelope, getattr(narrative, "themes", ()) or (),
                                materials, directions, narrative),
            materials, directions)) if narrative else None)]
    if not phase_a:
        sections.append(StructuredReportSection(
            heading="本次案情（待核语境）", content=envelope.case_description,
            # The case text is the analyst's own words, so its closing line must
            # not restate it as a finding. It says what the text is FOR.
            summary="以上案情由办案人员提供，仅作为本轮研判的调查语境；"
                    "材料未支持的部分不作为已确认事实。"))
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
                citation_ids=citation_ids,
                summary=_clean_chapter_summary(row.get("summary", ""))
                if row.get("summary") else ""))
    else:
        for start in range(0, len(directions), 8):
            chosen = directions[start:start + 8]
            texts, refs = [], []
            for direction in chosen:
                # These strings come straight from the discovery/comparison
                # models, so they can carry prompt-internal ids. Scrub at the
                # publish boundary: the fragment path used to print "与 m0178
                # 配置的关联关系" and the diff chapter printed the same ids.
                texts.append(("材料观察：" if direction.finding_kind == "observation" else "待核方向：")
                             + strip_material_ids(direction.title) + "\n"
                             + strip_material_ids(direction.description))
                if direction.origin == "case_only":
                    texts.append("此项仅由案情提出，尚无材料支持。")
                for label, sources in (("支持片段", direction.supporting_refs), ("相反或限制片段", direction.counter_refs)):
                    for ref in sources:
                        texts.append(f"{label}（{cid[ref.material_id]}）：{ref.quote}")
                        refs.append(cid[ref.material_id])
                if direction.missing_information:
                    texts.append("仍缺信息：" + "；".join(
                        strip_material_ids(note) for note in direction.missing_information))
                if direction.alternative_explanations:
                    texts.append("其他可能解释：" + "；".join(
                        strip_material_ids(note) for note in direction.alternative_explanations))
            sections.append(StructuredReportSection(
                heading=f"{'材料自主发现' if phase_a else '案情对照发现'}（{start // 8 + 1}）",
                content="\n\n".join(texts), citation_ids=tuple(dict.fromkeys(refs)),
                summary=_fragment_summary(chosen)))
    if not directions:
        sections.append(StructuredReportSection(heading="调查方向与限制",
            content="本次可读材料尚未形成有来源支持的调查方向；这不等于不存在相关活动。",
            summary="本轮未形成可引用的调查方向，报告不据此推断是否存在相关活动。"))
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
                lines.append(f"- {strip_material_ids(title)}："
                             f"{strip_material_ids(comparison.reason)}")
            remaining = len(chosen) - _COMPARISON_DETAIL_LIMIT
            if remaining > 0:
                lines.append(f"- 另有 {remaining} 项同类差异，详见阶段材料清单。")
        citation_ids = tuple(dict.fromkeys(
            cid[r.material_id] for status in notable
            for c in by_status.get(status, ())
            for r in (*c.supporting_refs, *c.counter_refs)))
        sections.append(StructuredReportSection(
            heading="与首次研判的差异", content="\n".join(lines),
            citation_ids=citation_ids,
            summary=_comparison_summary(by_status, labels, total)))
    if narrative and dropped_chars:
        warnings.append(f"NARRATIVE_OVERFLOW_DROPPED_{dropped_chars}_CHARS")
    sections.append(StructuredReportSection(heading="人工核查建议",
        content=_advisory_text(directions, warnings),
        summary=_advisory_summary(directions, warnings)))
    # Appendix, AFTER every chapter (contract): the per-material recall detail.
    # Chapter 1 now leads with the human-readable thread table; this table keeps
    # the file-level audit trail (which file, cited where, contributing what).
    if narrative:
        detail = _recall_table(stats, recall_contributions)
        if detail.rows:
            sections.append(StructuredReportSection(
                heading="附录：证据召回明细",
                content=(f"以下按引用次数列出全部被正文实际引用的 {detail.recalled_materials} 份材料"
                         f"（合计 {detail.total_citations} 处引文）；每一行说明该材料在本次研判中"
                         "支撑或限制了哪个结论，点击引用标记可回查冻结原文。"),
                citation_ids=(),
                summary=(f"本附录共登记 {detail.recalled_materials} 份被正文引用的材料、"
                         f"{detail.total_citations} 处引文；正文结论以各章为准，"
                         "本表用于逐条回查证据来源。"),
                recall_table=detail))
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
