"""Prompt registry and builders for frozen report generation (Phase R2c).

The R2b-frozen version identity (``REPORT_GENERATION_PROMPT_VERSION``) is
the registry key; this module defines the actual prompt text and the
explicit prompt -> output-contract mapping. Changing a prompt's semantics
requires a NEW version string -- existing admitted rows keep executing
their recorded contract.

Version history:
- ``final-report:v1``: single-shot generation over the whole envelope.
- ``final-report:v2``: case-background-driven narrative (background lives
  in the hash-covered envelope, rendered into every user prompt) with
  outline-then-per-section generation; evidence is presented through a
  deterministic per-item projection so the full snapshot never has to fit
  one output budget. The v2 system prompt is shared by both stages.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .generation import REPORT_GENERATION_PROMPT_VERSION
from .models import (
    CASE_DESCRIPTION_MAX_CHARS,
    EnvelopeEvidenceItemV1,
    ReportGenerationEnvelopeV1,
    ReportGenerationEnvelopeV2,
)

# Envelope schema -> executable prompt versions (R2C1: the LLM input is the
# persisted envelope; compatibility is checked before execution).
REPORT_GENERATION_PROMPT_V1 = "final-report:v1"
REPORT_GENERATION_PROMPT_V2 = "final-report:v2"

REPORT_GENERATION_ENVELOPE_COMPAT: dict[int, frozenset[str]] = {
    1: frozenset({REPORT_GENERATION_PROMPT_V1}),
    2: frozenset({REPORT_GENERATION_PROMPT_V2}),
}

# Prompt version -> structured output contract identity.
REPORT_GENERATION_PROMPT_OUTPUT_CONTRACT: dict[str, str] = {
    REPORT_GENERATION_PROMPT_V1: "structured_final_report_v1",
    REPORT_GENERATION_PROMPT_V2: "structured_final_report_v2",
}

REPORT_GENERATION_PROMPT_REGISTRY: dict[str, tuple[str, str]] = {}

REPORT_GENERATION_SYSTEM_V1 = """\
你是一名数字取证最终报告撰写专家。你只能基于提供的冻结输入生成报告，不得引入任何外部信息。

严格语义边界：
- Evidence Snapshot 是 authoritative 证据事实（Evidence Source）。
- accepted Secondary Analysis 是分析员已接受的派生结论/上下文，不是新的 Evidence Source。
- Claim 是派生结论；其 evidence_refs 只是该分析的历史 provenance，不会扩大本报告的引用范围。
- Report Evidence 集合（main + appendix）是分析员为本报告显式选定的 Evidence 全集。
- 不得发明 Evidence ID、Analysis ID、Claim ID 或 citation ID。
- 不得引用 Report Evidence 集合之外的任何 Evidence（即使 Claim 的 evidence_refs 提到它）。
- 不得把 accepted Analysis 当作原始证据引用；引用分析时只能使用其冻结 analysis_id。
- 不得把事件、图谱、时间线当作 Evidence。
- 不得输出任何审核决定或建议的复核结论。

只输出一个 JSON object，字段只能是 title、sections、citations；不得输出 Markdown、代码围栏或解释文字。
sections[*] 的字段是 heading、content、citation_ids。
citations[*] 的字段是 citation_id、evidence_key、analysis_id（可为 null）、claim_id（可为 null）。
content 是纯文本叙述；需要佐证的句子在 citation_ids 中给出对应 citation_id。
analysis_id 只有在对应 Evidence 冻结绑定了 accepted Analysis 时才可非 null；claim_id 只有在该冻结 Analysis 的 claims 中存在时才可使用。
"""

REPORT_GENERATION_USER_TEMPLATE_V1 = """\
请基于以下冻结 Report 输入生成最终报告。

任务 ID: {task_id}
Report Evidence 引用边界（只允许引用这些 evidence_key）:
{allowed_ids}

冻结输入（Evidence Snapshots 与可选的 accepted Analysis/Claims）:
{envelope_json}

输出要求：只返回严格 JSON：
{{"title":"...","sections":[{{"heading":"...","content":"...","citation_ids":["..."]}}],"citations":[{{"citation_id":"...","evidence_key":"...","analysis_id":null,"claim_id":null}}]}}
"""

REPORT_GENERATION_PROMPT_REGISTRY[REPORT_GENERATION_PROMPT_V1] = (
    REPORT_GENERATION_SYSTEM_V1,
    REPORT_GENERATION_USER_TEMPLATE_V1,
)

REPORT_GENERATION_SYSTEM_V2 = """\
你是一名数字取证最终报告撰写专家。案件背景（case_description）是本报告的叙事主线：报告必须围绕案情组织证据、还原犯罪手法与关键事实，为办案人员服务，而不是罗列系统文件。

严格语义边界：
- Evidence Snapshot 是唯一权威的证据事实；案件背景是办案人员提供的侦查背景，用于组织叙事，不得把背景中的推测当成已证事实，也不得虚构背景与证据之外的内容。
- 只能引用白名单内的 evidence_key；不得发明任何 evidence_key、citation_id 或其他 ID。
- 不得把事件、图谱、时间线当作 Evidence；不得输出审核决定或建议的复核结论。
- 全文使用简体中文；内容是纯文本叙述，不得使用任何 Markdown 标记。

只输出一个严格 JSON object，不得输出 Markdown 代码围栏、注释或解释文字。
"""

REPORT_GENERATION_OUTLINE_USER_TEMPLATE_V2 = """\
请基于以下案件背景与证据分组清单，为本案最终报告拟定章节大纲。

任务 ID: {task_id}

案件背景:
{case_description}

证据分组（每组每行一个条目：evidence_key | 摘要要点）:
{groups_brief}

大纲要求：
1. 只返回严格 JSON：{{"title":"...","sections":[{{"heading":"...","brief":"本章要写什么（50字内）","group_ids":["分组ID"]}}]}}
2. 3 到 15 个章节，数量与证据规模相称，不要为凑数拆分或注水；sections[0] 必须是案件背景章，heading 以"案件背景"开头、group_ids 为空数组，内容将围绕案情背景与检材概况展开；
3. 每个证据分组必须至少被一个章节引用；分组 "{fallback_group}"（{fallback_name}）多为系统组件噪声，必须被恰好一个章节完整承接，该章以清单方式简述、不逐条展开；
4. 章节顺序服务于案情：关键证据（作案手法、资金、远程控制、恢复数据等）应成章展开，系统类分组靠后。
"""

REPORT_GENERATION_SECTION_USER_TEMPLATE_V2 = """\
请撰写本案最终报告的一章。

任务 ID: {task_id}

案件背景:
{case_description}

本章在报告中的位置：第 {section_no} 章，共 {section_total} 章。
全报告大纲（仅供把握行文衔接，不要越章展开）:
{outline_brief}

本章任务：heading="{heading}";要点={brief}

本章引用白名单（只能引用这些 evidence_key，逐条给出，勿遗漏关键证据）:
{allowed_ids}

本章证据材料（Evidence Snapshot 投影，JSON）:
{projection}

写作要求：
1. 只返回严格 JSON：{{"heading":"...","content":"...","citations":[{{"citation_id":"c001","evidence_key":"..."}}]}}
2. content 为 400 到 2000 字的简体中文叙述，纯文本无 Markdown；围绕案件背景组织，先结论后细节，关键事实句都要有对应 citation；
3. heading 沿用本章任务给定的 heading；citation_id 从 c001 开始连续编号，章内唯一；
4. 证据材料未覆盖的案情信息可以直接叙述但不得编造具体数据；材料与案情无关时如实说明关联有限。
"""

REPORT_GENERATION_PROMPT_REGISTRY[REPORT_GENERATION_PROMPT_V2] = (
    REPORT_GENERATION_SYSTEM_V2,
    REPORT_GENERATION_OUTLINE_USER_TEMPLATE_V2,
)

# Prompt-version -> per-section user template (v2 executes sections with the
# shared v2 system prompt and the section template; v1 has no section stage).
SECTION_USER_TEMPLATE_BY_VERSION: dict[str, str] = {
    REPORT_GENERATION_PROMPT_V2: REPORT_GENERATION_SECTION_USER_TEMPLATE_V2,
}


def get_report_generation_prompt(version: str) -> tuple[str, str]:
    entry = REPORT_GENERATION_PROMPT_REGISTRY.get(version)
    if entry is None:
        raise ValueError(f"unknown report generation prompt version: {version!r}")
    return entry


def get_section_user_prompt_template(version: str) -> str:
    template = SECTION_USER_TEMPLATE_BY_VERSION.get(version)
    if template is None:
        raise ValueError(f"prompt version has no section stage: {version!r}")
    return template


def build_report_generation_user_prompt(
    user_template: str, envelope: ReportGenerationEnvelopeV1 | ReportGenerationEnvelopeV2
) -> str:
    """The user prompt is the persisted envelope, verbatim and complete.

    The executor passes exactly this text to the LLM (R2C1/R2C2): no live
    re-read of report evidence, files.db, events, or graph can leak in.
    """
    envelope_json = json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    allowed_ids = "\n".join(envelope.allowed_report_evidence_ids) or "none"
    return user_template.format(
        task_id=envelope.task_id,
        allowed_ids=allowed_ids,
        envelope_json=envelope_json,
    )


def _format_epoch(value: int | None) -> str | None:
    if value is None or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def project_evidence_item(item: EnvelopeEvidenceItemV1) -> dict:
    """Deterministic prompt-side projection of one Evidence Snapshot.

    The envelope stays the frozen full input; this projection only bounds
    what one section prompt carries (description truncated, metadata
    slimmed) so per-section prompts stay within a usable token budget.
    """
    payload = item.snapshot.payload
    described = payload.model_dump(mode="json")
    description = described.get("initial_description") or ""
    return {
        "evidence_key": item.evidence_key,
        "path": described.get("normalized_path"),
        "name": described.get("name"),
        "size": described.get("size"),
        "mtime": _format_epoch(described.get("mtime")),
        "is_deleted": bool(described.get("is_deleted")),
        "summary": described.get("initial_summary"),
        "keywords": described.get("initial_keywords"),
        "description": description[:600],
    }


def render_evidence_projection(items: list[EnvelopeEvidenceItemV1]) -> str:
    lines = [json.dumps(project_evidence_item(i), ensure_ascii=False) for i in items]
    return "\n".join(lines)


def render_group_inventory(
    group_id: str, group_name: str, items: list[EnvelopeEvidenceItemV1]
) -> str:
    """One line per item: evidence_key | path | summary head (outline input)."""
    lines = []
    for item in items:
        payload = item.snapshot.payload
        summary = (payload.initial_summary or "").replace("\n", " ")[:120]
        lines.append(
            f"{group_id}[{group_name}] {item.evidence_key} | "
            f"{payload.normalized_path} | {summary}"
        )
    return "\n".join(lines)


__all__ = [
    "CASE_DESCRIPTION_MAX_CHARS",
    "REPORT_GENERATION_ENVELOPE_COMPAT",
    "REPORT_GENERATION_PROMPT_OUTPUT_CONTRACT",
    "REPORT_GENERATION_PROMPT_REGISTRY",
    "SECTION_USER_TEMPLATE_BY_VERSION",
    "build_report_generation_user_prompt",
    "get_report_generation_prompt",
    "get_section_user_prompt_template",
    "project_evidence_item",
    "render_evidence_projection",
    "render_group_inventory",
]
