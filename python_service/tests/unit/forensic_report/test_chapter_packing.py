"""Chapter packing: the chapter count is a property of the code, not the model.

Asking an LLM for "exactly 10 themes" returned 22/17/22/17/21 across five
identical temperature-0 calls, so the report cannot rely on the model to bound
its own length. These tests pin the deterministic packer that replaces it.
"""

import json

import pytest

from httpserver.services.forensic_report import generation_stages as gs
from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan


def _theme(name, count):
    quote = MaterialSpan(material_id="m001", quote="片段", character_start=0,
                         character_end=2, ambiguous=False)
    return {"name": name, "directions": tuple(
        InvestigationDirection(
            direction_id=f"{name}-{i}", title=f"{name} 观察{i}",
            description=f"{name} 的材料观察。", finding_kind="observation",
            supporting_refs=(quote,), counter_refs=(), missing_information=(),
            alternative_explanations=(), baseline_direction_ids=(),
            case_context_quote="", origin="material",
        ) for i in range(count)
    )}


# ---------------------------------------------------------------------------
# The chapter count contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_count,target,expected", [
    (23, 10, 10),
    (24, 10, 10),
    (40, 10, 10),
    (60, 12, 12),
    (10, 10, 10),
])
def test_chapter_count_equals_target(theme_count, target, expected):
    """Chapter count is exactly the target, whatever the theme count."""
    themes = [_theme(f"T{i}", 3 + i % 5) for i in range(theme_count)]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, target)

    assert len(chapters) == expected


def test_chapter_count_shrinks_when_themes_are_fewer_than_target():
    """With fewer themes than chapters, the target cannot be met honestly."""
    themes = [_theme(f"T{i}", 5) for i in range(3)]

    chapters, warnings = gs.pack_themes_into_chapters(themes, 10)

    assert len(chapters) == 3
    assert any(w.startswith("CHAPTER_TARGET_REDUCED") for w in warnings)


def test_no_direction_is_lost_or_duplicated():
    """Packing may merge and split themes, but never drops evidence."""
    themes = [_theme(f"T{i}", 1 + (i * 7) % 30) for i in range(25)]
    expected = {d.direction_id for t in themes for d in t["directions"]}

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 10)
    packed = [d.direction_id for c in chapters for d in gs.chapter_directions(c)]

    assert sorted(packed) == sorted(expected)
    assert len(packed) == len(set(packed))


def test_packing_is_deterministic():
    """Same input, same chapters — the count must not vary between runs."""
    themes = [_theme(f"T{i}", 2 + (i * 11) % 25) for i in range(20)]

    first, _ = gs.pack_themes_into_chapters(themes, 10)
    second, _ = gs.pack_themes_into_chapters(themes, 10)

    assert [c["name"] for c in first] == [c["name"] for c in second]
    assert [len(gs.chapter_directions(c)) for c in first] == [
        len(gs.chapter_directions(c)) for c in second]


def test_chapters_are_balanced():
    """A huge theme must not make one chapter several times another."""
    sizes = [34, 22, 16, 15, 8, 7, 7, 6, 6, 6, 5, 5, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3, 2]
    themes = [_theme(f"T{i}", size) for i, size in enumerate(sizes)]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 10)
    loads = [len(gs.chapter_directions(c)) for c in chapters]

    # Without splitting the oversized themes the spread was 21 (34 vs 13).
    assert max(loads) - min(loads) <= 6
    assert sum(loads) == sum(sizes)


def test_oversized_theme_is_split_and_reported():
    themes = [_theme("巨大主题", 40), _theme("小主题", 2)]

    chapters, warnings = gs.pack_themes_into_chapters(themes, 4)

    assert any(w.startswith("THEME_SPLIT_FOR_BALANCE") for w in warnings)
    # Both halves keep the theme name so the reader can see they belong together.
    names = [t["name"] for c in chapters for t in c["themes"]]
    assert names.count("巨大主题") >= 2


def test_empty_themes_are_ignored():
    themes = [{"name": "空", "directions": ()}, _theme("有内容", 4)]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 5)

    assert len(chapters) == 1
    assert len(gs.chapter_directions(chapters[0])) == 4


def test_no_themes_yields_no_chapters():
    chapters, warnings = gs.pack_themes_into_chapters([], 10)
    assert chapters == []
    assert warnings == ()


def test_each_chapter_has_a_lead_theme():
    """The chapter name comes from its largest theme, never invented."""
    themes = [_theme("甲", 10), _theme("乙", 2), _theme("丙", 2)]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 2)

    for chapter in chapters:
        names = {t["name"] for t in chapter["themes"]}
        assert chapter["name"] in names
        lead = max(chapter["themes"], key=lambda t: len(t["directions"]))
        assert chapter["name"] == lead["name"]


# ---------------------------------------------------------------------------
# Chapter writing
# ---------------------------------------------------------------------------


def _materials(count=3):
    from httpserver.services.forensic_report.generation_sources import material
    return tuple(material(f"m{i:03d}", f"file:/case/材料{i}.txt", kind="text",
                          status="ready", text="材料正文" * 20)
                 for i in range(1, count + 1))


class _WriterLLM:
    """Answers chapter writes and heading synthesis from scripted payloads."""

    def __init__(self, body=None):
        self.body = body
        self.calls = []

    async def chat_completion(self, system, user, **kwargs):
        body = json.loads(user)
        self.calls.append(body)
        if "topics" in body:
            return {"content": "综合命名标题"}
        text = self.body or ("本批材料显示存在多项待核活动。" * 20)
        return {"content": json.dumps(
            {"heading": "模型自拟标题", "content": text}, ensure_ascii=False)}


@pytest.mark.asyncio
async def test_chapter_writing_emits_one_section_per_chapter():
    themes = [_theme("甲", 3), _theme("乙", 3)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 2)

    sections, warnings = await gs.write_chapters(chapters, _materials(), _WriterLLM())

    assert len(sections) == 2
    assert warnings == ()


@pytest.mark.asyncio
async def test_chapter_writing_uses_one_heading_per_chapter(monkeypatch):
    """Parts of one chapter must not become separate chapters."""
    themes = [_theme("甲", 4)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 1)
    monkeypatch.setattr(gs, "_split_chapter_rows",
                        lambda rows, limit=gs.REQUEST_CHAR_LIMIT: [[r] for r in rows])

    sections, _warnings = await gs.write_chapters(
        chapters, _materials(), _WriterLLM())

    assert len(sections) == 1
    # A single-theme chapter still goes through the namer: the theme name is a
    # grouping label ("OfficeHub"), too terse to be a chapter title.
    assert sections[0]["heading"] == "综合命名标题"


@pytest.mark.asyncio
async def test_chapter_writing_keeps_direction_provenance():
    themes = [_theme("甲", 2)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 1)

    sections, _warnings = await gs.write_chapters(
        chapters, _materials(), _WriterLLM())

    assert sections[0]["direction_ids"] == tuple(
        d.direction_id for d in themes[0]["directions"])


@pytest.mark.asyncio
async def test_chapter_writing_isolates_a_failed_chapter():
    themes = [_theme("甲", 2), _theme("乙", 2)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 2)

    class HalfBroken(_WriterLLM):
        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            if "topics" in body:
                return {"content": "标题"}
            if not self.calls:
                self.calls.append(body)
                raise RuntimeError("provider down")
            self.calls.append(body)
            return {"content": json.dumps(
                {"heading": "标题", "content": "材料观察。" * 80},
                ensure_ascii=False)}

    sections, warnings = await gs.write_chapters(chapters, _materials(), HalfBroken())

    assert len(sections) == 1
    assert any(w.startswith("CHAPTER_SECTION_REJECTED") for w in warnings)


@pytest.mark.asyncio
async def test_chapter_writing_rejects_a_stub():
    themes = [_theme("甲", 2)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 1)

    sections, warnings = await gs.write_chapters(
        chapters, _materials(), _WriterLLM(body="太短"))

    assert sections == []
    assert any(w.startswith("CHAPTER_SECTION_REJECTED") for w in warnings)


def test_piece_label_prefers_a_name_the_parent_does_not_use():
    """Slices of one theme must not all be labelled after the parent."""
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)

    def direction(title):
        return InvestigationDirection(
            direction_id=title, title=title, description=title,
            finding_kind="observation", supporting_refs=(quote,),
            counter_refs=(), missing_information=(),
            alternative_explanations=(), baseline_direction_ids=(),
            case_context_quote="", origin="material")

    piece = (direction("SVCHOST.EXE 执行"), direction("SVCHOST.EXE 再次执行"))
    label = gs._piece_label("系统进程执行", piece)
    assert "SVCHOST" in label
    assert label != "系统进程执行"


# ---------------------------------------------------------------------------
# Generic system libraries must not name a chapter
#
# A PC.E01 chapter was titled "KERNEL32相关执行": KERNEL32.DLL is the most
# cited module across every prefetch record, so the frequency-based label picked
# it, while the chapter actually covered SVCHOST, DLLHOST and RUNTIMEBROKER.
# ---------------------------------------------------------------------------


def test_piece_label_ignores_generic_dependencies():
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)

    def direction(title):
        return InvestigationDirection(
            direction_id=title, title=title, description=title,
            finding_kind="observation", supporting_refs=(quote,),
            counter_refs=(), missing_information=(),
            alternative_explanations=(), baseline_direction_ids=(),
            case_context_quote="", origin="material")

    # KERNEL32 appears most often but says nothing about the slice.
    piece = (
        direction("KERNEL32.DLL 被引用"),
        direction("KERNEL32.DLL 再次被引用"),
        direction("KERNEL32.DLL 第三次引用"),
        direction("SVCHOST.EXE 执行记录"),
    )
    label = gs._piece_label("系统进程执行", piece)

    assert "KERNEL32" not in label
    assert "SVCHOST" in label


def test_piece_label_falls_back_when_only_generic_dependencies_exist():
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)
    piece = tuple(InvestigationDirection(
        direction_id=f"d{i}", title="KERNEL32.DLL 引用", description="KERNEL32.DLL 引用",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    ) for i in range(3))

    assert gs._piece_label("系统进程执行", piece) == "系统进程执行"


def test_chapter_prompts_forbid_generic_dependency_naming():
    from httpserver.services.forensic_report.generation_prompts import (
        STAGE_CHAPTER_HEADING_SYSTEM_V1, STAGE_CHAPTER_WRITE_SYSTEM_V1,
    )

    for prompt in (STAGE_CHAPTER_HEADING_SYSTEM_V1, STAGE_CHAPTER_WRITE_SYSTEM_V1):
        assert "KERNEL32" in prompt
        assert "NTDLL" in prompt


def test_chapter_write_prompt_forbids_filename_lists():
    """43 file names in one 4,302-character chapter is an inventory, not prose."""
    from httpserver.services.forensic_report.generation_prompts import (
        STAGE_CHAPTER_WRITE_SYSTEM_V1,
    )

    assert "严禁连续罗列文件名清单" in STAGE_CHAPTER_WRITE_SYSTEM_V1
    assert "共 N 份" in STAGE_CHAPTER_WRITE_SYSTEM_V1


def test_chapter_write_prompt_limits_boilerplate_caveats():
    """Every chapter ended with "需结合其他日志核实", which carries no information."""
    from httpserver.services.forensic_report.generation_prompts import (
        STAGE_CHAPTER_WRITE_SYSTEM_V1,
    )

    assert "限制性内容每章最多 2 句" in STAGE_CHAPTER_WRITE_SYSTEM_V1
    assert "需结合其他日志进一步核实" in STAGE_CHAPTER_WRITE_SYSTEM_V1


def test_bare_noun_list_is_a_fragment():
    """A chapter titled "SVCHOST、WMI" names two objects and says nothing."""
    assert gs._is_heading_fragment("SVCHOST、WMI")
    assert gs._is_heading_fragment("SVCHOST与DLLHOST")
    assert gs._is_heading_fragment("A、B、C")
    assert gs._is_heading_fragment("事件日志与")


def test_statement_headings_are_not_fragments():
    for heading in ("EXPLORER执行与空XML根节点异常",
                    "FTK Imager多次执行痕迹研判",
                    "事件日志解析为空或重复",
                    "SVCHOST多实例执行",
                    "OfficeHub"):
        assert not gs._is_heading_fragment(heading), heading


def test_heading_rejects_generic_dependency_and_fragment(monkeypatch):
    """Both rejection rules apply to the namer's answer, not only the fallback."""
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)
    direction = InvestigationDirection(
        direction_id="d1", title="SVCHOST 执行", description="SVCHOST 执行",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    )
    chapter = {"name": "系统进程执行",
               "themes": [{"name": "系统进程执行", "directions": (direction,)}]}

    class BadNamer:
        def __init__(self, answer):
            self.answer = answer

        async def chat_completion(self, system, user, **kwargs):
            return {"content": self.answer}

    import asyncio as _asyncio
    for bad in ("KERNEL32相关执行", "SVCHOST、WMI"):
        result = _asyncio.run(gs._chapter_heading(chapter, BadNamer(bad)))
        assert result != bad, bad
        assert not gs._names_generic_dependency(result)
        assert not gs._is_heading_fragment(result)


# ---------------------------------------------------------------------------
# A chapter must not deny its own evidence
#
# A PC.E01 chapter said "MSEDGEWEBVIEW2 的 Prefetch 记录共 18 份" and then
# "未提供任何直接指向 MSEDGEWEBVIEW2 组件的发现与引文 … 无法作出任何结论".
# Two unrelated themes had been packed into one chapter and the writer treated
# them as mutually exclusive inputs.
# ---------------------------------------------------------------------------


def test_self_contradicting_chapter_is_rejected():
    from httpserver.services.forensic_report.generation_stages import (
        _NO_EVIDENCE_CLAIM_RE,
    )

    contradictions = (
        "本章围绕 MSEDGEWEBVIEW2 展开，但输入材料中未提供任何直接指向该组件的发现与引文。",
        "因此无法就 MSEDGEWEBVIEW2 的执行行为作出任何结论。",
        "本批材料中未包含相关记录。",
        "现有材料未提供相关发现。",
    )
    for text in contradictions:
        assert _NO_EVIDENCE_CLAIM_RE.search(text), text


def test_normal_caveats_are_not_contradictions():
    from httpserver.services.forensic_report.generation_stages import (
        _NO_EVIDENCE_CLAIM_RE,
    )

    acceptable = (
        "本批材料显示 18 份 Prefetch 记录，运行次数 1 至 24 次。",
        "缺少该程序的命令行参数，无法确认其调用目标。",
        "材料未提供该程序的命令行参数。",
        "本章材料覆盖内核、网络与远程桌面日志。",
    )
    for text in acceptable:
        assert not _NO_EVIDENCE_CLAIM_RE.search(text), text


@pytest.mark.asyncio
async def test_chapter_denying_evidence_is_rewritten_once():
    """One retry with a reminder, then the chapter is accepted."""
    themes = [_theme("甲", 2)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 1)

    class ContradictingThenFixed:
        def __init__(self):
            self.writes = 0

        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            if "topics" in body:
                return {"content": "标题"}
            self.writes += 1
            if self.writes == 1:
                return {"content": json.dumps({
                    "heading": "标题",
                    "content": "本章材料中未提供任何相关发现。" + ("补充说明。" * 60),
                }, ensure_ascii=False)}
            return {"content": json.dumps({
                "heading": "标题",
                "content": "材料显示存在多项执行痕迹。" * 30,
            }, ensure_ascii=False)}

    llm = ContradictingThenFixed()
    sections, warnings = await gs.write_chapters(chapters, _materials(), llm)

    assert llm.writes == 2
    assert len(sections) == 1
    assert warnings == ()


# ---------------------------------------------------------------------------
# Comparison chapters are bounded by outcome, not by row count
#
# A case-guided PC.E01 report had 281 comparisons and rendered one chapter per
# 8 rows: 36 "与首次研判的差异（n）" chapters, turning a 10-chapter report into
# 49 chapters / 94k characters.
# ---------------------------------------------------------------------------


def _comparison(status, index):
    from httpserver.services.forensic_report.models import DirectionComparison, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)
    return DirectionComparison(
        baseline_direction_id=f"d{index:04d}", status=status,
        reason=f"对照理由{index}：" + "材料支持该判断。" * 5,
        supporting_refs=(quote,), counter_refs=(), missing_information=(),
        case_context_quote="",
    )


def _case_envelope(baseline_count=300):
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)
    count = baseline_count
    baseline = tuple(InvestigationDirection(
        direction_id=f"d{i:04d}", title=f"基线方向{i}", description="基线描述",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    ) for i in range(count))

    baseline_view = type("B", (), {
        "directions": baseline, "report_id": "r1",
        "report_sha256": "0" * 64, "priorities": {}})()

    return type("Env", (), {
        "analysis_mode": "case_guided",
        "case_description": "案情语境",
        "evidence_scope_hash": "0" * 64,
        "baseline": baseline_view,
    })()


def _materials_for_citations(count=3):
    from httpserver.services.forensic_report.generation_sources import material
    return tuple(material(f"m{i:03d}", f"file:/case/材料{i}.txt", kind="text",
                          status="ready", text="x" * 400)
                 for i in range(1, count + 1))


def test_comparison_chapters_are_grouped_by_outcome():
    """281 comparisons must not become 36 chapters."""
    comparisons = tuple(
        _comparison(status, i)
        for i, status in enumerate(["supported"] * 150 + ["insufficient"] * 80
                                   + ["weakened"] * 51)
    )

    response, _stage = gs.render_stage_report(
        _case_envelope(len(comparisons)), _materials_for_citations(), (),
        comparisons, ())

    comparison_chapters = [s for s in response.sections
                           if s.heading.startswith("与首次研判的差异")]
    # One summary chapter, not one per outcome type or per 8 rows.
    assert len(comparison_chapters) == 1
    body = comparison_chapters[0].content
    assert "得到支持 150 项" in body
    assert "依据不足 80 项" in body


def test_comparison_chapters_cap_total_length():
    comparisons = tuple(_comparison("supported", i) for i in range(200))

    response, _stage = gs.render_stage_report(
        _case_envelope(len(comparisons)), _materials_for_citations(), (),
        comparisons, ())

    comparison_chapters = [s for s in response.sections
                           if s.heading.startswith("与首次研判的差异")]
    assert len(comparison_chapters) == 1
    # Confirmations are summarized, not listed: 200 rows must not become prose.
    body = comparison_chapters[0].content
    assert len(body) < 1000
    assert "得到支持 200 项" in body


def test_report_without_comparisons_has_no_difference_chapters():
    class EvidenceOnlyEnv:
        analysis_mode = "evidence_only"
        case_description = ""
        evidence_scope_hash = "0" * 64
        baseline = None

    response, _stage = gs.render_stage_report(
        EvidenceOnlyEnv(), _materials_for_citations(), (), (), ())
    assert not [s for s in response.sections
                if s.heading.startswith("与首次研判的差异")]
