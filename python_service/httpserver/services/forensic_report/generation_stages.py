"""Two report modes within the existing executor; no separate service/jobs."""
from __future__ import annotations

import base64
import hashlib
import json

from .generation_sources import digest, material
from .generation_structured import _loads_strict
from .generation_prompts import STAGE_DISCOVERY_SYSTEM_V1, STAGE_COMPARE_SYSTEM_V1, NEUTRAL_IMAGE_PROMPT_V1
from .generation_prompts import STAGE_DISCOVERY_SYSTEM_V2, STAGE_COMPARE_SYSTEM_V2
from .models import (
    DirectionBatch, InvestigationDirection, MaterialSpan, ComparisonSuggestion,
    DirectionComparison, StageAnalysis, StructuredReportResponse, StructuredReportSection,
    StructuredReportCitation, ClassificationQuestion,
)

BATCH_SIZE = 3
READING_CHARS = 4000
REQUEST_CHAR_LIMIT = 26000
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


def validate_refs(refs, sent, full):
    result = []
    for ref in refs:
        if (ref.material_id not in sent or not ref.quote.strip()
                or ref.quote not in sent[ref.material_id] or ref.quote not in full[ref.material_id].text):
            raise ValueError("DIRECTION_SOURCE_QUOTE_INVALID")
        start = full[ref.material_id].text.index(ref.quote)
        result.append(MaterialSpan(material_id=ref.material_id, quote=ref.quote,
                                   character_start=start, character_end=start + len(ref.quote),
                                   ambiguous=full[ref.material_id].text.find(ref.quote, start + 1) >= 0))
    return tuple(result)


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


async def discover_directions(envelope, materials, llm):
    full = {m.material_id: m for m in materials}
    readable = [m for m in materials if m.text and m.status != "unavailable"]
    directions, warnings, successful = {}, [], 0
    baseline = envelope.baseline.directions if envelope.baseline else ()

    async def run(rows, prior=(), summaries=()):
        nonlocal successful
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
        response = await llm.chat_completion(STAGE_DISCOVERY_SYSTEM_V2 if envelope.prompt_version.endswith(":v2") else STAGE_DISCOVERY_SYSTEM_V1, request, max_tokens=4096, temperature=0.0)
        values = parse_directions(response.get("content", ""), sent, full, envelope, {d.direction_id for d in prior})
        directions.update((d.direction_id, d) for d in values)
        successful += 1

    for start in range(0, len(readable), BATCH_SIZE):
        chosen = readable[start:start + BATCH_SIZE]
        ids = {m.material_id for m in chosen}
        prior = [d for d in baseline if any(r.material_id in ids for r in (*d.supporting_refs, *d.counter_refs))][:4]
        try:
            await run([prompt_material(m) for m in chosen], prior)
        except (ValueError, KeyError, TypeError):
            warnings.append(f"DIRECTION_BATCH_REJECTED_{start // BATCH_SIZE + 1}")
    if not successful:
        raise ValueError("NO_VALIDATED_NEUTRAL_ANALYSIS")
    # A bounded cross-batch pass joins literal supports from prior batches.
    # Original findings stay present even if this additional review fails.
    first_pass = list(directions.values())
    if len(readable) > BATCH_SIZE and len(first_pass) > 1:
        for start in range(0, len(first_pass), 8):
            chosen = first_pass[start:start + 8]
            snippets = {}
            for d in chosen:
                for ref in (*d.supporting_refs, *d.counter_refs):
                    snippets.setdefault(ref.material_id, []).append(ref.quote)
            rows = [prompt_material(full[key], "\n".join(dict.fromkeys(quotes)))
                    for key, quotes in snippets.items()]
            prior_ids = {key for d in chosen for key in d.baseline_direction_ids}
            try:
                await run(rows, [d for d in baseline if d.direction_id in prior_ids],
                          [{"title": d.title, "description": d.description[:300]} for d in chosen])
            except (ValueError, KeyError, TypeError):
                warnings.append(f"CROSS_MATERIAL_REVIEW_REJECTED_{start // 8 + 1}")
    return tuple(directions.values()), tuple(warnings)


async def compare_directions(envelope, materials, llm, current_directions=()):
    if envelope.baseline is None:
        return (), ()
    full = {m.material_id: m for m in materials}
    comparisons, warnings = [], []
    for prior in envelope.baseline.directions:
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
            comparisons.append(DirectionComparison(**{
                **value.model_dump(mode="json"), "supporting_refs": supports, "counter_refs": counters,
            }))
        except (ValueError, KeyError, TypeError):
            warnings.append(f"COMPARISON_REJECTED_{prior.direction_id}")
            comparisons.append(DirectionComparison(baseline_direction_id=prior.direction_id,
                status="insufficient", reason="本轮比较未通过来源校验，不能据此改变首次判断。",
                missing_information=("需要人工核对该方向及其原始材料。",)))
    return tuple(comparisons), tuple(warnings)


def render_stage_report(envelope, materials, directions, comparisons, warnings):
    phase_a = envelope.analysis_mode == "evidence_only"
    citations = tuple(StructuredReportCitation(citation_id=f"c{i:03}", evidence_key=m.evidence_key)
                      for i, m in enumerate(materials, 1))
    cid = {m.material_id: c.citation_id for m, c in zip(materials, citations)}
    available = sum(m.status != "unavailable" and bool(m.text) for m in materials)
    scope = (f"本轮在已入报的 {len(materials)} 份材料范围内研判，可用 {available} 份，"
             f"不可用 {len(materials) - available} 份。只使用冻结的解析片段或明确标记的机器观察，"
             "不代表全镜像或全文穷尽分析。引用位置指向冻结文本字符，不是磁盘偏移。")
    scope += ("未使用案情描述、人工备注、历史 AI 摘要或已接受分析。" if phase_a else
              "本轮复用首次报告的同一批冻结材料，没有新增证据。人工案情仅作为调查语境。")
    sections = [StructuredReportSection(heading="研判范围与方法", content=scope,
                                       citation_ids=tuple(c.citation_id for c in citations))]
    if not phase_a:
        sections.append(StructuredReportSection(heading="本次案情（待核语境）", content=envelope.case_description))
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
        titles = {d.direction_id: d.title for d in envelope.baseline.directions}
        labels = {"supported": "得到支持", "revised": "需要修正", "weakened": "支持减弱",
                  "contradicted": "存在相反材料", "insufficient": "依据不足", "case_only": "仅案情提出"}
        for start in range(0, len(comparisons), 8):
            chosen = comparisons[start:start + 8]
            sections.append(StructuredReportSection(heading=f"与首次研判的差异（{start // 8 + 1}）",
                content="\n\n".join(f"{titles[c.baseline_direction_id]}：{labels[c.status]}\n{c.reason}" for c in chosen),
                citation_ids=tuple(dict.fromkeys(cid[r.material_id] for c in chosen
                                                 for r in (*c.supporting_refs, *c.counter_refs)))))
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
