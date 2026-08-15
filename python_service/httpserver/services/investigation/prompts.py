"""Versioned prompt templates for Secondary Analysis (Phase C4b-2/C4c).

IMMUTABILITY RULE — once a prompt version string is assigned (e.g.
``"investigation-evidence-analysis:v1"``), the prompt text must NEVER be
modified in-place. To change a prompt, create a new version (v2, v3...) and
update ``CURRENT_PROMPT_VERSION``. This guarantees ``input_hash`` stability:
the same ``prompt_version`` always maps to the same prompt text across all
deployments and across time. A SHA-256 regression test locks each version's
text so accidental edits are caught immediately.
"""

from __future__ import annotations

from typing import Union

from .models import (
    AnalysisInputEnvelopeV1,
    AnalysisInputEnvelopeV2,
    EventRefreshEnvelopeV2,
)

EVENT_REFRESH_PROMPT_VERSION = "investigation-event-refresh:v1"
REFRESH_ENVELOPE_PROMPT_COMPAT: dict[int, frozenset[str]] = {
    2: frozenset({EVENT_REFRESH_PROMPT_VERSION}),
}
REFRESH_PROMPT_OUTPUT_CONTRACT = {
    EVENT_REFRESH_PROMPT_VERSION: "structured_event_narrative_v1",
}

EVENT_REFRESH_SYSTEM_V1 = """\\
你是一名数字取证调查事件叙事整理专家。你只能基于提供的冻结输入生成事件标题和摘要。

严格语义边界：
- envelope.links[*].evidence_key 才是本 Event 的 authoritative Evidence IDs。
- Evidence Snapshot 是证据事实。
- accepted Analysis 和 Claims 是已被分析员接受的派生上下文，不是新的 Evidence Source。
- Claim 的 evidence_refs 只是该 accepted analysis 的历史 provenance；即使引用其他 ID，也不会扩大 Event 的 Evidence membership。
- base title/summary 是旧 Event narrative，不是 Evidence Source。
- 不得发明 Evidence ID、文件、事件、Claim 或审核字段。

只输出一个 JSON object，字段只能是 title、summary；不得输出 Markdown、代码围栏或解释文字。
"""

EVENT_REFRESH_USER_TEMPLATE_V1 = """\\
请基于以下冻结 Event 输入生成新的事件叙事。

Event ID: {event_id}
基础版本: {base_version}
旧标题: {base_title}
旧摘要: {base_summary}

Authoritative Event Evidence IDs:
{evidence_ids}

冻结 Evidence Snapshots 与 accepted derived context:
{links_text}

输出要求：只返回严格 JSON：{{"title":"...","summary":"..."}}。
"""

EVENT_REFRESH_PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    EVENT_REFRESH_PROMPT_VERSION: (
        EVENT_REFRESH_SYSTEM_V1,
        EVENT_REFRESH_USER_TEMPLATE_V1,
    ),
}


def get_event_refresh_prompt(version: str) -> tuple[str, str]:
    entry = EVENT_REFRESH_PROMPT_REGISTRY.get(version)
    if entry is None:
        raise ValueError(f"unknown event refresh prompt version: {version!r}")
    return entry


def _format_refresh_link(link) -> str:
    accepted = link.accepted_analysis
    lines = [f"Evidence ID: {link.evidence_key}", f"Snapshot: {link.snapshot}"]
    if accepted is None:
        lines.append("Accepted Analysis: none")
    else:
        lines.extend([
            f"Accepted Analysis {accepted.analysis_id} v{accepted.version}:",
            f"  description: {accepted.description or 'none'}",
            f"  summary: {accepted.summary or 'none'}",
            f"  claims: {accepted.claims}",
            "  claim evidence_refs are historical provenance, not Event links",
        ])
    return "\\n".join(lines)


def build_event_refresh_user_prompt(
    user_template: str, envelope: EventRefreshEnvelopeV2
) -> str:
    links_text = "\\n\\n".join(_format_refresh_link(link) for link in envelope.links) or "none"
    evidence_ids = "\\n".join(link.evidence_key for link in envelope.links) or "none"
    return user_template.format(
        event_id=envelope.event_id,
        base_version=envelope.base_version,
        base_title=envelope.base_title,
        base_summary=envelope.base_summary or "none",
        evidence_ids=evidence_ids,
        links_text=links_text,
    )

# ---------------------------------------------------------------------------
# Version registry
# ---------------------------------------------------------------------------

CURRENT_PROMPT_VERSION = "investigation-evidence-analysis:v3"

# Input envelope compatibility. V2 input is shared by historical legacy v2
# and current structured v3 output contracts.
ENVELOPE_PROMPT_COMPAT: dict[int, frozenset[str]] = {
    1: frozenset({"investigation-evidence-analysis:v1"}),
    2: frozenset({"investigation-evidence-analysis:v2", "investigation-evidence-analysis:v3"}),
}
PROMPT_OUTPUT_CONTRACT: dict[str, str] = {
    "investigation-evidence-analysis:v1": "legacy_text",
    "investigation-evidence-analysis:v2": "legacy_text",
    "investigation-evidence-analysis:v3": "structured_claims_v1",
}

# ---------------------------------------------------------------------------
# v1 prompt text (IMMUTABLE — do not edit after release; create v2 instead)
# ---------------------------------------------------------------------------

SECONDARY_ANALYSIS_SYSTEM_V1 = """\
你是一名数字取证分析专家。你将收到一份不可变的证据快照（Evidence Snapshot）及其初始分析结果。\
你的任务是针对该证据进行二次分析（Secondary Analysis），提供比初始分析更深入、更结构化的取证见解。

输出要求：
1. 输出纯文本，不使用 Markdown 格式（不用 **、#、- 等标记）
2. 全部使用中文
3. 先用一两句话给出简要总结，然后给出详细分析
4. 不要输出 JSON、代码块或任何结构化标记
5. 仅基于提供的快照数据进行分析，不要臆造不存在的数据
6. 如果快照数据不足以做出判断，明确指出数据缺失
"""

SECONDARY_ANALYSIS_USER_TEMPLATE_V1 = """\
请对以下证据快照进行二次分析。

证据类型：{evidence_type}
证据标识：{evidence_key}

快照数据：
{snapshot_text}

初始分析摘要：{initial_summary}
初始分析描述：{initial_description}

请先用一两句话简要总结该证据的取证价值，然后给出详细分析，包括但不限于：
- 该证据在案件中的潜在作用
- 与其他证据可能的关联
- 需要进一步调查的方向
"""

# ---------------------------------------------------------------------------
# v2 prompt text (IMMUTABLE — do not edit after release; create v3 instead)
# ---------------------------------------------------------------------------

SECONDARY_ANALYSIS_SYSTEM_V2 = """\
你是一名数字取证分析专家。你将收到一份不可变的证据快照（Evidence Snapshot）、相关证据快照、\
以及分析员提供的调查语境（Analyst Note / Case Context）。

重要语义区分（CCTX1）：
- 证据快照（Evidence Snapshot）和相关证据快照（Related Evidence Snapshot）：是事实数据，\
可以作为分析的事实依据。
- 分析员备注（Analyst Note）和案件语境（Case Context）：仅为调查方向、假设或关注点，\
不是证据来源。若某个判断仅基于分析员备注或案件语境，必须明确表述为"调查方向"或"待验证假设"，\
不得描述为证据已证明的事实。

输出要求：
1. 输出纯文本，不使用 Markdown 格式（不用 **、#、- 等标记）
2. 全部使用中文
3. 先用一两句话给出简要总结，然后给出详细分析
4. 不要输出 JSON、代码块或任何结构化标记
5. 仅基于提供的快照数据进行分析，不要臆造不存在的数据
6. 如果快照数据不足以做出判断，明确指出数据缺失
"""

SECONDARY_ANALYSIS_USER_TEMPLATE_V2 = """\
请对以下证据快照进行二次分析。

证据类型：{evidence_type}
证据标识：{evidence_key}

快照数据：
{snapshot_text}

初始分析摘要：{initial_summary}
初始分析描述：{initial_description}

相关证据：
{related_evidence_text}

分析员备注（调查语境，非证据）：
{analyst_note}

案件语境（调查方向，非证据）：
{case_context}

请先用一两句话简要总结该证据的取证价值，然后给出详细分析，包括但不限于：
- 该证据在案件中的潜在作用
- 与相关证据的关联分析
- 需要进一步调查的方向

注意：分析员备注和案件语境仅作为调查参考，不得作为已证实事实引用。
"""

# v3 is immutable. It changes ONLY the output contract, not the input envelope.
SECONDARY_ANALYSIS_SYSTEM_V3 = """\
你是一名数字取证分析专家。请基于提供的证据快照、相关证据快照和分析员语境进行二次分析。

严格输出要求：
1. 只输出一个合法 JSON 对象，不要输出 Markdown、代码围栏或解释文字
2. 顶层字段只能是 description、summary、claims
3. claims 必须是数组；每个 Claim 只能包含 claim_type、claim_text、evidence_refs
4. claim_type 只能是 FACT、INFERENCE、HYPOTHESIS
5. evidence_refs 只能使用输入中明确展示的 canonical Evidence ID，不得创造、解释或规范化新的 ID
6. Analyst Note / Case Context 只是调查语境，不是 Evidence，不能作为事实来源
7. FACT 应尽量提供 Evidence refs；不确定内容使用 INFERENCE 或 HYPOTHESIS
8. 不要输出 grounding_status、accepted、rejected 或任何审核字段
"""

SECONDARY_ANALYSIS_USER_TEMPLATE_V3 = """\
请对以下输入执行结构化二次分析，并严格按照系统要求输出 JSON。

证据类型：{evidence_type}
证据标识：{evidence_key}
快照数据：
{snapshot_text}

初始分析摘要：{initial_summary}
初始分析描述：{initial_description}

相关证据：
{related_evidence_text}

分析员备注（调查语境，非证据）：
{analyst_note}

案件语境（调查方向，非证据）：
{case_context}
"""

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    "investigation-evidence-analysis:v1": (SECONDARY_ANALYSIS_SYSTEM_V1, SECONDARY_ANALYSIS_USER_TEMPLATE_V1),
    "investigation-evidence-analysis:v2": (SECONDARY_ANALYSIS_SYSTEM_V2, SECONDARY_ANALYSIS_USER_TEMPLATE_V2),
    "investigation-evidence-analysis:v3": (SECONDARY_ANALYSIS_SYSTEM_V3, SECONDARY_ANALYSIS_USER_TEMPLATE_V3),
}


def get_prompt(version: str) -> tuple[str, str]:
    """Look up (system_prompt, user_template) for a prompt version.

    Raises ValueError if the version is not registered.
    """
    entry = PROMPT_REGISTRY.get(version)
    if entry is None:
        raise ValueError(f"unknown prompt version: {version!r}")
    return entry


# ---------------------------------------------------------------------------
# Prompt building (typed — V1/V2 dispatched via isinstance)
# ---------------------------------------------------------------------------

def _format_snapshot_text(
    envelope: Union[AnalysisInputEnvelopeV1, AnalysisInputEnvelopeV2],
) -> tuple[str, str, str, str, str]:
    """Extract human-readable fields from the envelope's evidence_snapshot.

    Returns (evidence_type, evidence_key, snapshot_text, initial_summary,
    initial_description).
    """
    snap = envelope.evidence_snapshot
    evidence_type = snap.get("evidence_type", "unknown")
    evidence_key = snap.get("evidence_key", "")
    payload = snap.get("payload", {})

    lines: list[str] = []
    initial_summary = "无"
    initial_description = "无"

    if evidence_type == "file":
        lines.append(f"文件路径: {payload.get('normalized_path', '未知')}")
        lines.append(f"文件名: {payload.get('name', '未知')}")
        if payload.get("extension"):
            lines.append(f"扩展名: {payload['extension']}")
        if payload.get("category"):
            lines.append(f"分类: {payload['category']}")
        if payload.get("type"):
            lines.append(f"类型: {payload['type']}")
        if payload.get("size") is not None:
            lines.append(f"大小: {payload['size']} 字节")
        if payload.get("md5"):
            lines.append(f"MD5: {payload['md5']}")
        if payload.get("mtime") is not None:
            lines.append(f"修改时间: {payload['mtime']}")
        if payload.get("ctime") is not None:
            lines.append(f"创建时间: {payload['ctime']}")
        if payload.get("is_deleted") is not None:
            lines.append(f"已删除: {'是' if payload['is_deleted'] else '否'}")
        if payload.get("scene_type"):
            lines.append(f"场景类型: {payload['scene_type']}")
        if payload.get("initial_summary"):
            initial_summary = payload["initial_summary"]
        if payload.get("initial_description"):
            initial_description = payload["initial_description"]
        if payload.get("initial_keywords"):
            lines.append(f"初始关键词: {payload['initial_keywords']}")
        if payload.get("initial_model"):
            lines.append(f"初始分析模型: {payload['initial_model']}")
    elif evidence_type == "cluster":
        lines.append(f"时间聚类(分钟): {payload.get('unix_minute', '未知')}")
        lines.append(f"事件类型: {payload.get('event_type', '未知')}")
        if payload.get("cluster_start") is not None:
            lines.append(f"聚类起始: {payload['cluster_start']}")
        if payload.get("cluster_end") is not None:
            lines.append(f"聚类结束: {payload['cluster_end']}")
        if payload.get("event_count") is not None:
            lines.append(f"事件数量: {payload['event_count']}")
        if payload.get("representative_timestamp") is not None:
            lines.append(f"代表时间戳: {payload['representative_timestamp']}")
    else:
        lines.append("(未知证据类型)")

    return evidence_type, evidence_key, "\n".join(lines), initial_summary, initial_description


def _format_related_evidence_text(entries: tuple) -> str:
    """Format V2 related evidence entries into human-readable text."""
    if not entries:
        return "无"
    lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        snap = entry.snapshot
        payload = snap.get("payload", {})
        evidence_type = snap.get("evidence_type", "unknown")
        lines.append(f"相关证据 {i}: {entry.evidence_key}")
        if evidence_type == "file":
            lines.append(f"  文件路径: {payload.get('normalized_path', '未知')}")
            lines.append(f"  文件名: {payload.get('name', '未知')}")
            if payload.get("size") is not None:
                lines.append(f"  大小: {payload['size']} 字节")
            desc = payload.get("initial_description")
            if desc:
                lines.append(f"  初始描述: {desc[:200]}")
        elif evidence_type == "cluster":
            lines.append(f"  时间聚类: {payload.get('unix_minute', '未知')}")
            lines.append(f"  事件类型: {payload.get('event_type', '未知')}")
            if payload.get("event_count") is not None:
                lines.append(f"  事件数量: {payload['event_count']}")
    return "\n".join(lines)


def build_user_prompt(
    user_template: str,
    envelope: Union[AnalysisInputEnvelopeV1, AnalysisInputEnvelopeV2],
) -> str:
    """Build the user prompt from the typed envelope data (E3: only from envelope).

    V1 templates use only evidence fields; V2 templates add context placeholders.
    Both receive all params (extra params are ignored by str.format).
    """
    evidence_type, evidence_key, snapshot_text, initial_summary, initial_description = (
        _format_snapshot_text(envelope)
    )

    params = {
        "evidence_type": evidence_type,
        "evidence_key": evidence_key,
        "snapshot_text": snapshot_text,
        "initial_summary": initial_summary,
        "initial_description": initial_description,
        "analyst_note": "无",
        "case_context": "无",
        "related_evidence_text": "无",
    }

    if isinstance(envelope, AnalysisInputEnvelopeV2):
        if envelope.analyst_note:
            params["analyst_note"] = envelope.analyst_note
        if envelope.case_context:
            params["case_context"] = envelope.case_context
        if envelope.related_evidence:
            params["related_evidence_text"] = _format_related_evidence_text(
                envelope.related_evidence
            )

    return user_template.format(**params)
