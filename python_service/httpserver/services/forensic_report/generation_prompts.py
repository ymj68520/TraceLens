"""Prompt registry and builders for frozen report generation (Phase R2c).

The R2b-frozen version identity (``REPORT_GENERATION_PROMPT_VERSION``) is
the registry key; this module defines the actual prompt text and the
explicit prompt -> output-contract mapping. Changing a prompt's semantics
requires a NEW version string -- existing admitted rows keep executing
their recorded contract.
"""

from __future__ import annotations

import json

from .generation import REPORT_GENERATION_PROMPT_VERSION
from .models import ReportGenerationEnvelopeV1

# Envelope schema -> executable prompt versions (R2C1: the LLM input is the
# persisted envelope; compatibility is checked before execution).
REPORT_GENERATION_ENVELOPE_COMPAT: dict[int, frozenset[str]] = {
    1: frozenset({REPORT_GENERATION_PROMPT_VERSION}),
}

# Prompt version -> structured output contract identity.
REPORT_GENERATION_PROMPT_OUTPUT_CONTRACT: dict[str, str] = {
    REPORT_GENERATION_PROMPT_VERSION: "structured_final_report_v1",
}

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

REPORT_GENERATION_PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    REPORT_GENERATION_PROMPT_VERSION: (
        REPORT_GENERATION_SYSTEM_V1,
        REPORT_GENERATION_USER_TEMPLATE_V1,
    ),
}


def get_report_generation_prompt(version: str) -> tuple[str, str]:
    entry = REPORT_GENERATION_PROMPT_REGISTRY.get(version)
    if entry is None:
        raise ValueError(f"unknown report generation prompt version: {version!r}")
    return entry


def build_report_generation_user_prompt(
    user_template: str, envelope: ReportGenerationEnvelopeV1
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


__all__ = [
    "REPORT_GENERATION_ENVELOPE_COMPAT",
    "REPORT_GENERATION_PROMPT_OUTPUT_CONTRACT",
    "REPORT_GENERATION_PROMPT_REGISTRY",
    "build_report_generation_user_prompt",
    "get_report_generation_prompt",
]
