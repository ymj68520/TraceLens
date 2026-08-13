"""Versioned prompt templates for Secondary Analysis (Phase C4b-2).

IMMUTABILITY RULE — once a prompt version string is assigned (e.g.
``"investigation-evidence-analysis:v1"``), the prompt text must NEVER be
modified in-place. To change a prompt, create a new version (v2, v3...) and
update ``CURRENT_PROMPT_VERSION``. This guarantees ``input_hash`` stability:
the same ``prompt_version`` always maps to the same prompt text across all
deployments and across time. A SHA-256 regression test locks each version's
text so accidental edits are caught immediately.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Version registry
# ---------------------------------------------------------------------------

CURRENT_PROMPT_VERSION = "investigation-evidence-analysis:v1"

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
# Registry
# ---------------------------------------------------------------------------

PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    CURRENT_PROMPT_VERSION: (SECONDARY_ANALYSIS_SYSTEM_V1, SECONDARY_ANALYSIS_USER_TEMPLATE_V1),
}


def get_prompt(version: str) -> tuple[str, str]:
    """Look up (system_prompt, user_template) for a prompt version.

    Raises ValueError if the version is not registered.
    """
    entry = PROMPT_REGISTRY.get(version)
    if entry is None:
        raise ValueError(f"unknown prompt version: {version!r}")
    return entry


def _format_snapshot_text(envelope: dict) -> tuple[str, str, str, str]:
    """Extract human-readable fields from the envelope's evidence_snapshot.

    Returns (evidence_type, evidence_key, snapshot_text, initial_summary,
    initial_description).
    """
    snap = envelope.get("evidence_snapshot", {})
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


def build_user_prompt(user_template: str, envelope: dict) -> str:
    """Build the user prompt from the envelope data (E3: only from envelope)."""
    evidence_type, evidence_key, snapshot_text, initial_summary, initial_description = (
        _format_snapshot_text(envelope)
    )
    return user_template.format(
        evidence_type=evidence_type,
        evidence_key=evidence_key,
        snapshot_text=snapshot_text,
        initial_summary=initial_summary,
        initial_description=initial_description,
    )
