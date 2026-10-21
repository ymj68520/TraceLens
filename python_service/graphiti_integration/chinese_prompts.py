"""Simplified-Chinese prompt overrides for graphiti_core.

graphiti_core's built-in prompts are English-only and its combined-extraction
rule ("write each fact in the dominant language of its source episode") makes
English forensic artifacts produce English entity summaries and edge facts —
the long English paragraphs shown in the knowledge-graph detail panel.

This module overrides the prompts that produce user-visible narrative text via
graphiti's official ``prompt_library`` hook (``create_prompt_library``), so the
LLM writes facts and summaries in Simplified Chinese while forensic identifiers
(file names, paths, hashes, hostnames, registry keys, ...) stay verbatim.

Coverage follows the two live ingestion paths of this graphiti version:

- Single ``add_episode`` (the path ``GraphitiIngestor.ingest_episode`` drives):
  node extraction (``extract_nodes.*`` — entity names only, kept verbatim, not
  overridden), fact extraction via ``extract_edges.edge`` (overridden — this is
  where panel-visible fact text is produced), batch node summarization
  (overridden).
- ``add_episode_bulk`` with the default ``use_combined_extraction=True``:
  ``extract_nodes_and_edges.extract_message`` (overridden), plus the same
  batch summarization.

Deliberately NOT overridden: ``extract_summary`` (single-node variant, no
callers in this graphiti version), ``classify_nodes`` / ``extract_attributes``
(structural JSON output), dedupe groups (internal decisions), and
``summarize_nodes.summarize_context`` (no callers in this graphiti version).

Every override replicates the default template's context sections field for
field — most importantly the ``custom_extraction_instructions`` section that
carries FORENSIC_EXTRACTION_INSTRUCTIONS. Dropping that section would silently
revert forensic extraction to graphiti's "discard paths/hashes/IPs" behaviour.
"""

from __future__ import annotations

import os
from typing import Any

from graphiti_core.prompts.lib import ChatPromptLibrary, create_prompt_library
from graphiti_core.prompts.models import ChatPrompt, Message
from graphiti_core.prompts.prompt_helpers import to_prompt_json
from graphiti_core.utils.text_utils import MAX_SUMMARY_CHARS

# Set GRAPHITI_PROMPT_LANGUAGE=en to fall back to graphiti's default English
# prompts without a code revert (kill switch for the Chinese overrides).
LANGUAGE_ENV = 'GRAPHITI_PROMPT_LANGUAGE'

_SYSTEM_COMBINED = (
    '你为 AI 智能体构建长期记忆。从每段记录中提取实体和关系事实，'
    '供后续回答问题和继续分析使用。原始记录之后将不可用：只会保留你提取的'
    '实体和事实，因此每条事实必须能独立读懂。'
)

# Faithful Chinese adaptation of graphiti's combined-extraction instruction
# text (_C2_INSTRUCTION_TEXT). The one deliberate change is the language rule:
# facts are always written in Simplified Chinese while entity names keep their
# source spelling, so English artifact text no longer yields English facts.
_COMBINED_INSTRUCTION_TEXT = f"""# 目标
把当前消息转化为知识图谱：一份实体列表和它们之间的关系事实（边）列表。好的结果能让分析者不看原始文本就能回答"谁说了、做了、想要、拥有、计划、感觉、推荐或知道什么"。

# 好输出的标准
- 完整：覆盖每条有实际内容的记录和发言者，包括长输入中靠后的内容。偏好、观点、计划、承诺、请求、提问、情绪、经历、建议和结果都算数。只跳过无内容的回合（"你好！"、"谢谢！"）。
- 归因明确：当某个有名字的人、账号或组织陈述、推荐或做了某事，该行为者就是 source_entity_name，事实文本中要写明行为者。
- 自包含：每条事实是一个完整的中文句子，使用实体名（不用代词），保留具体细节（数字、日期、价格、版本、名称），脱离上下文也能读懂。
- 紧凑：一条陈述对应一条事实。同一条陈述列举的多个条目合并进一条事实（"Marina 计划换成毛衣和长裤。"），除非每个条目各有细节。不要为每个列表项单独造事实或实体。同一条事实在多条 episode 中重复出现时只输出一次，并在 episode_indices 中列出全部编号。

# 实体
- 说话人：用可获得的最完整的名字。当消息头包含档案字段（first_name 和 last_name、given_name 和 family_name、user_alias、screen_name）时使用完整人名，例如 "Marisol Beckett"。拿不到名字时才用 "User"。
- 其他实体：有名字的人、组织、地点、产品、文件、工单、项目、事件、文档及有名字或描述的对象，以及某人从事的爱好和活动。使用来源文本中最具体的称呼，不超过 5 个词的名词短语。属于某人的物品、宠物、项目或作品用所有格名（"Calvin 的吉他"），而不是光杆名词。
- 不要从这些内容造实体：代词或未解析的指代（"该城市"、"此问题"）；模糊抽象概念（"增长"、"人生"、"时间"）；时刻、日期、数量、价格、时长、测量值或坐标（保留在事实文本中，除非该值本身是边的端点，如版本号字符串）；选项或模板词（"同意"、"强烈反对"）；祈使句式建议（"批量购买"的主题是"批量采购"）；引用的口号或习语；教程示例值（"/path/to/source"、"file.txt"）。
- 每个实体只出现一次，用 ENTITY TYPES 中的 entity_type_id 分类。只从当前消息中提取实体；先前消息和 [CONTEXT EPISODE] 消息仅用于解析指代。
- 【实体名书写（重要）】实体名保留来源文本的原文。文件名、路径、用户名、主机名、进程名、IP、注册表键、哈希、URL、版本号等标识符绝不翻译、转写或改写（例如 "brndlog.txt"、"C:\\\\Users"、"8ac346e35f..." 必须原样保留）。

# 事实
- source_entity_name 与 target_entity_name 必须取自 extracted_entities 中的实体名。若端点是一个值（如版本号），把它作为实体加入。
- 把行为者直接连到对象（"Calvin -> PERFORMED_IN -> Tokyo"）。不要经由描述性名词中转关系（不要写 "城市灯光 -> LOCATED_IN -> Tokyo"），也不要把行为者的陈述变成它提到的两个名词之间的事实。
- 仅当陈述只关于一个实体且没有其他更合适的已提取实体时，才使用自指事实（source 与 target 相同），例如惯例、感受或健康状态（"Evan 膝盖有伤。"）。
- 事实涉及两个已提取实体时，必须同时用作 source 和 target。
- 用先前消息和 [CONTEXT EPISODE] 消息解析当前消息的指代，写出解析后的事实（"所有努力得到了回报"要写成究竟是什么得到了回报）。[CONTEXT EPISODE] 消息只是让你按顺序阅读对话的上下文回合。
- episode_indices 填事实来源的零基 [Episode N] 编号。[CONTEXT EPISODE] 不是编号 episode：不要从中提取事实，也不要给它们编号。
- 【语言要求（重要）】每条事实的 fact 文本一律用简体中文书写为完整、自包含的自然语言句子；句中引用的文件名、路径、用户名、主机名、IP、哈希、版本号、注册表键、URL 等标识符及专有名词保留原文，不要翻译。relation_type 用英文 SCREAMING_SNAKE_CASE 标签。
- 事实只陈述来源说了什么，不加推理、模糊限定词（"似乎"、"暗示"）或评论。

# 输出
只返回 JSON 对象：{{"extracted_entities":[{{"name":"...","entity_type_id":0}}],"edges":[{{"source_entity_name":"...","target_entity_name":"...","relation_type":"...","fact":"...","episode_indices":[0]}}]}}。"""


def _edge_types_section(edge_types: list[dict] | None, strict_edge_types: bool = False) -> str:
    """Mirror of the default FACT TYPES section, rules translated to Chinese."""
    if not edge_types:
        return ''
    relation_type_rules = (
        '- relation_type 必须取自上面列出的 fact_type_name。\n'
        '- 若某个关系不匹配任何 FACT TYPE，跳过它，不要新造 relation_type。'
        if strict_edge_types
        else '- 关系匹配某个 FACT TYPE 时，用该 fact_type_name 作为 relation_type。\n'
        '- 没有匹配的 FACT TYPE 时，自行推导 SCREAMING_SNAKE_CASE 关系类型\n'
        '  （如 WORKS_AT、LOGGED_IN_AT、WROTE_FILE）。'
    )
    return f"""
<FACT TYPES>
{to_prompt_json(edge_types)}
</FACT TYPES>
RELATION TYPE RULES:
{relation_type_rules}
"""


def _custom_instructions_section(custom_extraction_instructions: str | None) -> str:
    """Mirror of the default CUSTOM INSTRUCTIONS section (rules translated).

    The injected instruction body (FORENSIC_EXTRACTION_INSTRUCTIONS) is passed
    through verbatim — it is English by design and defines the forensic entity
    policy this pipeline depends on.
    """
    if not custom_extraction_instructions:
        return ''
    return f"""
<CUSTOM INSTRUCTIONS>
{custom_extraction_instructions}
</CUSTOM INSTRUCTIONS>
CUSTOM INSTRUCTION RULES:
- CUSTOM INSTRUCTIONS 来自本图谱的所有者，必须遵守。当 CUSTOM INSTRUCTIONS 与上述任何规则冲突时，以 CUSTOM INSTRUCTIONS 为准。
"""


# Appended AFTER <CURRENT MESSAGES>: models weight the end of the user message
# heavily, and without this closing reminder English episode text pulls the
# output back to English (observed with deepseek-flash in e2e verification).
_COMBINED_LANGUAGE_REMINDER = """
<OUTPUT LANGUAGE (MANDATORY)>
违反本节的输出视为无效输出。每条 fact 的值必须是用简体中文书写的完整句子。
实体名以及事实中引用的文件名、路径、哈希、主机名、用户名、注册表键、URL、版本号保留英文原文，不翻译。
relation_type 保持英文 SCREAMING_SNAKE_CASE。

Example — source text: "The branding setup routine generated the diagnostic log file brndlog.txt. The MD5 hash 8ac346e35f6784d1a9208a098a4d7119 identifies the file."
GOOD fact value: "Windows Internet Explorer 的品牌配置例程生成了诊断日志文件 brndlog.txt，MD5 哈希 8ac346e35f6784d1a9208a098a4d7119 标识了该文件。"
BAD fact value: "The branding setup routine generated the diagnostic log file brndlog.txt."
</OUTPUT LANGUAGE (MANDATORY)>
"""


def combined_extract_message(context: dict[str, Any]) -> ChatPrompt:
    return ChatPrompt.from_messages([
        Message(role='system', content=_SYSTEM_COMBINED),
        Message(
            role='user',
            content=f"""{_COMBINED_INSTRUCTION_TEXT}

<ENTITY TYPES>
{context['entity_types']}
</ENTITY TYPES>
{_edge_types_section(context.get('edge_types'), context.get('strict_edge_types', False))}
{_custom_instructions_section(context.get('custom_extraction_instructions'))}
<PREVIOUS MESSAGES>
{to_prompt_json([ep for ep in context['previous_episodes']])}
</PREVIOUS MESSAGES>

<CURRENT MESSAGES>
{context['episode_content']}
</CURRENT MESSAGES>
{_COMBINED_LANGUAGE_REMINDER}""",
        ),
    ])


# ---------------------------------------------------------------- summaries


_SUMMARY_GUIDELINES = f"""摘要准则：
1. 只输出事实内容。不要解释你在做什么、为什么这么做，也不要提及任何限制或约束。
2. 只使用提供的消息和已有摘要，绝不推断证据没有直接支持的内容。
3. 摘要信息密集且紧扣该实体，直接陈述事实，保持在 {MAX_SUMMARY_CHARS} 字符以内。
4. 保留所有有实质关联的名称、角色、地点、日期、数量和时间限定词（须为证据明确支持的）。
5. 用紧凑的事实句，不用空泛的主题式措辞或元语言。
6. 当持久事实就是所说话的内容时，直接陈述内容本身，而不是描述"某人说了什么"。
7. 仅当"说、问、分享、展示、宣布、告知"这个行为本身就是重要事实时才使用沟通类动词。
8. 避免"提到"、"描述"、"表示"、"报告"、"指出"、"讨论"、"提及"等转述填充动词，除非沟通行为本身就是要紧的事实。
9. 消息提供了时间锚点且有助于定位事实时，保留时间锚点。
10. 以实体名或直接的事实开头，不要以"一个"、"这个"开头，除非该写法是实体名的一部分。
11. 【语言要求（重要）】摘要一律用简体中文书写（第三人称，2-6 个信息密集的句子）；文件名、路径、用户名、主机名、IP、哈希、版本号、注册表键、URL 等标识符及专有名词保留原文，不要翻译。
12. 永远不要提及来源材料或总结过程，不要出现"摘要"、"实体"、"分类"、"被标记"、"似乎"、"暗示"等元语言，也不要把"该实体"当代词使用——用实体的真实名称或自然的代词。"""


def _entity_type_descriptions_section(context: dict[str, Any]) -> str:
    """Mirror of the default ENTITY_TYPE_DESCRIPTIONS section (rules translated)."""
    descriptions = context.get('entity_type_descriptions')
    if not descriptions:
        return ''
    return f"""
<ENTITY_TYPE_DESCRIPTIONS>
{to_prompt_json(descriptions)}
</ENTITY_TYPE_DESCRIPTIONS>
当实体类型出现在 ENTITY_TYPE_DESCRIPTIONS 中时，用该描述判断哪些事实与该类型最相关。绝不在摘要文本本身中提及实体类型、类型描述或分类。"""


def _output_language_reminder() -> str:
    """Closing language reminder shared by the summary prompts."""
    return f"""
<OUTPUT LANGUAGE (MANDATORY)>
违反本节的输出视为无效输出。每条 summary 的值必须是用简体中文书写的 2-6 个信息密集的第三人称句子。
文件名、路径、哈希、主机名、用户名、URL、版本号等标识符保留英文原文，不翻译。

Example — evidence: "The branding setup routine generated the diagnostic log file brndlog.txt."
GOOD summary value: "品牌配置例程生成了诊断日志文件 brndlog.txt。"
BAD summary value: "The branding setup routine generated the diagnostic log file brndlog.txt."
</OUTPUT LANGUAGE (MANDATORY)>
"""


def summaries_batch(context: dict[str, Any]) -> ChatPrompt:
    return ChatPrompt.from_messages([
        Message(
            role='system',
            content='你是一个根据给定上下文生成简洁实体摘要的助手。所有输出使用简体中文。',
        ),
        Message(
            role='user',
            content=f"""根据消息（MESSAGES）和实体列表（ENTITIES），为每个需要更新的实体生成更新后的摘要。
每条摘要必须少于 {MAX_SUMMARY_CHARS} 个字符。

{_SUMMARY_GUIDELINES}

<MESSAGES>
{to_prompt_json(context['previous_episodes'])}
{to_prompt_json(context['episode_content'])}
</MESSAGES>
{_entity_type_descriptions_section(context)}
<ENTITIES>
{to_prompt_json(context['entities'])}
</ENTITIES>

把消息中的相关信息与该实体已有的摘要内容合并。只为有实质信息可总结的实体返回摘要。
某实体在消息中无相关信息且无已有摘要时，可以跳过它。
{_output_language_reminder()}""",
        ),
    ])


def summaries_from_episodes(context: dict[str, Any]) -> ChatPrompt:
    return ChatPrompt.from_messages([
        Message(
            role='system',
            content=(
                '你从 episode 文本中维护信息密集的实体记忆。只使用 EPISODES 中明确陈述的事实'
                '和 EXISTING_SUMMARY 中已存在的持久事实，绝不推断证据之外的内容。'
                '所有输出使用简体中文；文件名、路径、哈希、主机名等标识符保留原文。'
            ),
        ),
        Message(
            role='user',
            content=f"""绝不输出关于总结过程本身的元语言。只使用提供的 EPISODES 中的事实。
每条摘要必须少于 {MAX_SUMMARY_CHARS} 个字符，用简体中文写 2-6 个信息密集的第三人称句子。
保留所有有实质关联且被明确支持的名称、角色、日期、数量和随时间的变化。

对下面每个实体，仅用提供的 EPISODES 和该实体已有的摘要生成更新后的摘要。

<EPISODES>
{to_prompt_json(context['previous_episodes'])}
{to_prompt_json(context['episode_content'])}
</EPISODES>
{_entity_type_descriptions_section(context)}
<ENTITIES>
{to_prompt_json(context['entities'])}
</ENTITIES>

只为有实质信息可总结的实体返回摘要。
某实体在 episode 中无相关信息且无已有摘要时，可以跳过它。
{_output_language_reminder()}""",
        ),
    ])


def summarize_pair(context: dict[str, Any]) -> ChatPrompt:
    return ChatPrompt.from_messages([
        Message(
            role='system',
            content='你是一个把多条摘要合并为一条信息密集事实摘要的助手。所有输出使用简体中文。',
        ),
        Message(
            role='user',
            content=f"""把下面两条摘要中的信息合成为一条信息密集的摘要。

要求：
- 保留所有有实质关联且被明确支持的名称、角色、地点、日期、数量和随时间的变化。
- 用紧凑的事实句，不用空泛的主题式措辞。
- 当持久事实就是所说话的内容时，直接陈述内容本身，而不是描述"某人说了什么"。
- 避免"提到"、"描述"、"表示"、"报告"、"指出"、"讨论"等转述填充动词，除非沟通行为本身就是要紧的事实。
- 【语言要求】用简体中文书写；文件名、路径、哈希、主机名等标识符及专有名词保留原文。
- 摘要必须少于 {MAX_SUMMARY_CHARS} 个字符。

摘要：
{to_prompt_json(context['node_summaries'])}
""",
        ),
    ])


# ---------------------------------------------------------------- edge facts

# The single-episode add_episode path (the one GraphitiIngestor.ingest_episode
# drives) extracts facts via extract_edges.edge — NOT the combined prompt,
# which only runs under add_episode_bulk. This override is what actually makes
# panel-visible fact text Chinese. Structure mirrors the default template;
# the fact language mandate closes the message (models weight the tail).
_EDGE_SYSTEM = (
    '你是从文本中抽取事实三元组的专家。'
    '1. 抽取的事实三元组要附带相关日期信息。'
    '2. CURRENT_MESSAGE 可能包含多个带各自时间戳的 episode；'
    "用每个 episode 的时间戳解析该 episode 内的时间指代。"
    'REFERENCE_TIME 是没有 per-episode 时间戳时的回退值。'
    '所有 fact 的值必须用简体中文书写；标识符（文件名、路径、哈希、主机名等）保留原文。'
)


def _edge_types_section_separate(edge_types, strict_edge_types: bool) -> str:
    if not edge_types:
        return ''
    relation_type_rules = (
        '- relation_type 必须取自上面提供的 fact_type_name。\n'
        '- 若关系不匹配任何 FACT_TYPE，跳过它，不要新造 relation_type。'
        if strict_edge_types
        else '- 提供了 FACT_TYPES 且关系匹配某个类型（考虑实体类型签名）时，'
        '用该 fact_type_name 作为 relation_type。\n'
        '- 否则根据关系谓词推导 SCREAMING_SNAKE_CASE 的 relation_type'
        '（如 WORKS_AT、LOGGED_IN_AT、WROTE_FILE）。'
    )
    return f"""
<FACT_TYPES>
{to_prompt_json(edge_types)}
</FACT_TYPES>

# RELATION TYPE RULES（关系类型规则）

{relation_type_rules}
"""


def edge_fact(context: dict[str, Any]) -> ChatPrompt:
    return ChatPrompt.from_messages([
        Message(role='system', content=_EDGE_SYSTEM),
        Message(
            role='user',
            content=f"""
<PREVIOUS_MESSAGES>
{to_prompt_json(context['previous_episodes'])}
</PREVIOUS_MESSAGES>

<CURRENT_MESSAGE>
{context['episode_content']}
</CURRENT_MESSAGE>

<ENTITIES>
{to_prompt_json(context['nodes'])}
</ENTITIES>

<REFERENCE_TIME>
{context['reference_time']}  # ISO 8601 (UTC)；用于解析相对时间表述
</REFERENCE_TIME>
{_edge_types_section_separate(context.get('edge_types'), context.get('strict_edge_types', False))}
# 任务
从当前消息中抽取给定 ENTITIES 之间的全部事实关系。只抽取同时满足以下条件的事实：
- 涉及 ENTITIES 列表中两个【不同】的实体；
- 在当前消息中明确陈述或毫无歧义地隐含，且能表示为知识图谱中的边；
- 事实应尽量使用实体名而非代词。

PREVIOUS MESSAGES 的信息只能用于消解指代或支撑连贯性。

{context['custom_extraction_instructions']}

# 抽取规则

1. **实体名校验**：source_entity_name 与 target_entity_name 只能使用上面 ENTITIES 列表中的 `name` 值。
   - **关键**：使用列表之外的名字会导致该边被拒绝。
2. 每条事实必须涉及两个**不同**实体——source_entity_name 与 target_entity_name 绝不能指向同一实体。
3. 优先抽取涉及两个不同实体的事实。当一句话描述某个单一实体的具体细节（品牌名、具体物品、外观、数量、地点、有名字的活动）时，不要丢弃它：在 ENTITIES 列表中找到该细节关联的另一个实体，构成规范三元组（如 实体 -> OWNS -> 物品实体、实体 -> LIVES_IN -> 地点实体、实体 -> HAS_ATTRIBUTE -> 细节实体）。只有当列表中没有任何第二个实体可以锚定该细节时才跳过。
4. 不要输出语义重复的事实，即使它们出现在当前消息的不同 episode 中。但若后面的 episode 为先前的事实补充了具体细节（品牌、数量、颜色、地点等具体属性），把更详细的版本作为新事实抽取——这不算重复。只有传达的信息具体程度相同时才算重复。
5. `fact` 必须保留源文本中的全部具体细节：专有名词、品牌名、产品名、型号、数量、颜色、材质、外观描述、具体物品、有名地点和有名字的活动。可以改写句式，但绝不泛化：
   - 绝不把 "Gamecube" 泛化为"游戏机"、把 "Ford Mustang" 泛化为"汽车"、把 "wool coat" 泛化为"外套"。
   - 不要逐字照抄原文，但源文本中每个具体名词、数字和描述符都必须保留在 `fact` 中。
6. 用 `REFERENCE_TIME` 解析模糊或相对时间表述（如"上周"）。当前消息包含多个带时间戳的 episode 时，优先使用事实来源 episode 的时间戳。
7. 不要凭无关事件幻觉或推断时间边界。

# 日期时间规则

- 使用带 "Z" 后缀的 ISO 8601 (UTC)（如 2025-04-30T00:00:00Z）。
- 事实正在进行（现在时）时，`valid_at` 取事实来源 episode 的时间戳；没有则用 REFERENCE_TIME。
- 将来时的计划、承诺、日程或截止期，`valid_at` 取 episode 时间戳 / REFERENCE_TIME，不要取未来发生日期。
- 未来发生日期和截止期保留在 `fact` 文本中。不要把软截止期（"2026年3月前"、"Q3结束前"）当作 `invalid_at`。
- 仅当事实描述的进行状态在该时刻结束时才用未来日期作 `invalid_at`。
- 表达了变更/终止时，把相关时间戳填入 `invalid_at`。
- 没有明确或可解析的时间时，两个字段都留 null。
- 只提到日期（无时间）时按 00:00:00；只提到年份时用 1 月 1 日 00:00:00。
- REFERENCE_TIME 为 2020-01-01T00:00:00Z 时的示例：
  - "Emma 将于 2022 年 12 月 25 日搬到东京" -> valid_at 2020-01-01T00:00:00Z, invalid_at null。
  - "Alice 将在 2024 年 7 月 30 日前完成项目" -> valid_at 2020-01-01T00:00:00Z, invalid_at null。

<OUTPUT LANGUAGE (MANDATORY)>
违反本节的输出视为无效输出。每条 `fact` 的值必须是用简体中文书写的完整、自包含的句子。
实体名以及事实中引用的文件名、路径、哈希、主机名、用户名、注册表键、URL、版本号保留英文原文，不翻译。
relation_type 保持英文 SCREAMING_SNAKE_CASE。

Example — source text: "The MD5 hash 8ac346e35f6784d1a9208a098a4d7119 identifies the file brndlog.txt."
GOOD fact value: "MD5 哈希 8ac346e35f6784d1a9208a098a4d7119 标识了文件 brndlog.txt。"
BAD fact value: "The MD5 hash 8ac346e35f6784d1a9208a098a4d7119 identifies the file brndlog.txt."
</OUTPUT LANGUAGE (MANDATORY)>
        """,
        ),
    ])

_OVERRIDES = {
    'extract_nodes_and_edges': {'extract_message': combined_extract_message},
    'extract_nodes': {
        'extract_summaries_batch': summaries_batch,
        'extract_entity_summaries_from_episodes': summaries_from_episodes,
    },
    'extract_edges': {'edge': edge_fact},
    'summarize_nodes': {'summarize_pair': summarize_pair},
}

_LIBRARY: ChatPromptLibrary | None = None


def chinese_prompt_library() -> ChatPromptLibrary | None:
    """The composed prompt library, or None when the kill switch is set.

    Returns a process-wide singleton; ``create_prompt_library`` validates every
    override name at build time, so a graphiti upgrade that renames a prompt
    group fails loudly here instead of silently reverting to English.
    """
    global _LIBRARY
    if (os.getenv(LANGUAGE_ENV) or 'zh').strip().lower() in {'en', 'english'}:
        return None
    if _LIBRARY is None:
        _LIBRARY = create_prompt_library(_OVERRIDES)
    return _LIBRARY
