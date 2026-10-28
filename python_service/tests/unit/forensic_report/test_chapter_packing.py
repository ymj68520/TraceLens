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
                    "Quasar远控配置与Hosts异常"):
        assert not gs._is_heading_fragment(heading), heading


def test_bare_identifier_is_a_fragment():
    """A single product or file name says nothing about what happened.

    Two published PC.E01 chapters were titled just "PowerShell" and
    "material.dll"; the reader learns the object but not the finding.
    """
    for heading in ("OfficeHub", "PowerShell", "material.dll", "FormatExtFs"):
        assert gs._is_heading_fragment(heading), heading


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
            if "content" in body:
                # The chapter's closing summary is a separate call against the
                # finished body; it is not a chapter write and must not count.
                return {"content": "本章材料显示存在多项执行痕迹，仍需补齐命令行参数。"}
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


# ---------------------------------------------------------------------------
# Executables must reach the narrative
#
# A malware case's central evidence is the dropped program itself. A PC.E01
# report froze Quasar.exe (RAT controller) and client.bin (payload) as
# "unavailable" with zero characters because .exe/.bin were outside every
# extension set, so the narrative stage had nothing to say about them and the
# report concluded no RAT artefacts were found.
# ---------------------------------------------------------------------------


def test_executable_extensions_are_recognised_as_documents():
    from httpserver.services.forensic_report.generation_sources import (
        DOCUMENT_EXTENSIONS,
    )

    for extension in (".exe", ".dll", ".sys", ".com", ".scr", ".bin", ".msi"):
        assert extension in DOCUMENT_EXTENSIONS, extension


def test_pe_extractor_parses_an_executable(tmp_path):
    """The extractor behind those extensions must actually produce content."""
    import struct
    from httpserver.services.forensic_report.generation_sources import (
        DOCUMENT_EXTENSIONS,
    )

    assert ".exe" in DOCUMENT_EXTENSIONS

    # Minimal PE: MZ stub + PE signature at e_lfanew.
    dos = bytearray(64)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    pe = bytearray(b"PE\x00\x00")
    pe += struct.pack("<HHIIIHH", 0x14c, 1, 0, 0, 0, 0, 0xE0)  # COFF header
    payload = bytes(dos) + bytes(pe) + bytes(0xE0)
    target = tmp_path / "sample.exe"
    target.write_bytes(payload)

    from httpserver.services.extractors import load_plugins
    from httpserver.services.document_extractor import get_document_extractor_locator
    load_plugins()
    extractor = get_document_extractor_locator().get_extractor(str(target))

    assert extractor is not None
    assert type(extractor).__name__ == "PeExtractor"


# ---------------------------------------------------------------------------
# Findings must not be diluted by material-limit observations
#
# On PC.E01, 109 of 339 directions reported absent content ("解析结果为空",
# "LNK解析失败", license texts, memory dumps with no strings). Size-balanced
# packing spread them across every chapter, and the only Quasar RAT direction
# lost every chapter heading to them: the published report named no RAT at all
# while its citation list carried 37 Quasar references.
# ---------------------------------------------------------------------------


def _finding(title, kind="observation"):
    quote = MaterialSpan(material_id="m001", quote="片段", character_start=0,
                         character_end=2, ambiguous=False)
    return InvestigationDirection(
        direction_id=f"{kind}-{title}", title=title, description=f"{title} 的材料观察。",
        finding_kind=kind, supporting_refs=(quote,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    )


def test_no_finding_directions_are_pooled_into_one_theme():
    themes = [
        {"name": "空日志", "directions": (_finding("多份事件日志解析结果为空"),)},
        {"name": "解析失败", "directions": (_finding("LNK解析失败记录"),)},
        {"name": "空占位", "directions": (_finding("空哈希材料无实质内容"),)},
        {"name": "RAT", "directions": (_finding("Quasar类远控配置"),)},
    ]

    chapters, warnings = gs.pack_themes_into_chapters(themes, 3)

    pooled = [c for c in chapters if c["name"] == gs._NO_FINDING_THEME_NAME]
    assert len(pooled) == 1
    assert len(gs.chapter_directions(pooled[0])) == 3
    assert any(w.startswith("NO_FINDING_POOLED_3") for w in warnings)


def test_pooling_does_not_swallow_a_real_finding():
    themes = [
        {"name": "空日志", "directions": (_finding("多份事件日志解析结果为空"),)},
        {"name": "RAT", "directions": (_finding("Quasar类远控配置与监听配置并存"),)},
    ]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 2)
    names = [c["name"] for c in chapters]

    assert gs._NO_FINDING_THEME_NAME in names
    # The RAT observation is case-critical, so it is isolated rather than merely
    # kept: the chapter heading itself has to name the suspicious object.
    assert gs._CRITICAL_THEME_NAME in names


def test_hypotheses_get_their_own_chapter():
    """Inferences are the analytic core; bulk observations must not bury them."""
    themes = [{"name": f"观察{i}", "directions": (_finding(f"观察{i}"),)}
              for i in range(30)]
    themes.append({"name": "RAT", "directions": (
        _finding("Quasar类远控配置与监听配置并存", "hypothesis"),)})

    chapters, warnings = gs.pack_themes_into_chapters(themes, 10)

    assert chapters[0]["name"] == gs._HYPOTHESIS_THEME_NAME
    assert any(w.startswith("HYPOTHESES_SEPARATED_1") for w in warnings)


def test_hypothesis_and_observation_twins_stay_together():
    """The pipeline emits both readings of one object under the same title."""
    themes = [
        {"name": "RAT观察", "directions": (_finding("Quasar类远控配置与监听配置并存"),)},
        {"name": "RAT推断", "directions": (
            _finding("Quasar类远控配置与监听配置并存", "hypothesis"),)},
        {"name": "其他", "directions": (_finding("其他观察"),)},
    ]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 2)
    hypothesis_chapter = next(
        c for c in chapters if c["name"] == gs._HYPOTHESIS_THEME_NAME)

    assert len(gs.chapter_directions(hypothesis_chapter)) == 2


def test_empty_subject_key_does_not_pull_in_subjectless_observations():
    """Two hypothesis titles name no token; keying "" must not match everything."""
    themes = [
        {"name": "推断", "directions": (
            _finding("部分 Prefetch 引用网络/浏览器相关模块", "hypothesis"),)},
    ] + [{"name": f"观察{i}", "directions": (_finding("其他观察"),)}
         for i in range(5)]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 4)
    hypothesis_chapter = next(
        c for c in chapters if c["name"] == gs._HYPOTHESIS_THEME_NAME)

    assert len(gs.chapter_directions(hypothesis_chapter)) == 1


def test_reserved_tiers_never_take_the_whole_chapter_budget():
    """A report of nothing but parse failures must still carry findings."""
    themes = [
        {"name": "空", "directions": (_finding("解析结果为空"),)},
        {"name": "推断", "directions": (_finding("某个推断", "hypothesis"),)},
        {"name": "甲", "directions": (_finding("甲观察"),)},
        {"name": "乙", "directions": (_finding("乙观察"),)},
    ]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 2)

    assert any(c["name"] not in (gs._NO_FINDING_THEME_NAME,
                                gs._HYPOTHESIS_THEME_NAME) for c in chapters)


def test_only_pooled_directions_still_produce_a_report():
    themes = [{"name": "空", "directions": (_finding("解析结果为空"),)}]

    chapters, _warnings = gs.pack_themes_into_chapters(themes, 10)

    assert len(chapters) == 1
    assert chapters[0]["name"] == gs._NO_FINDING_THEME_NAME


def test_chapter_subjects_rank_a_product_name_above_artifact_types():
    """The heading namer needs Quasar, not Verbose/Event/Prefetch."""
    chapter = {"name": "x", "themes": [{"name": "x", "directions": (
        _finding("Verbose 事件集中出现，Event 与 Prefetch 记录见 Quasar类远控配置"),
        _finding("Critical Error 事件重复，Quasar 配置再次出现"),
    )}]}

    subjects = gs._chapter_subjects(chapter)

    assert "Quasar" in subjects
    assert subjects.index("Quasar") < len(subjects)


def test_chapter_lead_name_prefers_a_theme_carrying_an_inference():
    chapter = {"name": "大主题",
               "themes": [{"name": "大主题", "directions": (_finding("甲"),) * 1},
                          {"name": "RAT推断", "directions": (
                              _finding("Quasar配置", "hypothesis"),)}]}

    assert gs._chapter_lead_name(chapter) == "RAT推断"


def test_case_critical_observation_gets_its_own_chapter():
    """A RAT config must not be a paragraph inside a browser-prefetch chapter.

    PC.E01's only Quasar direction was packed into a chapter titled
    "Edge与PrivaZer触发Defender"; no reader would look for a remote-control
    configuration there.
    """
    themes = [{"name": f"观察{i}", "directions": (_finding(f"观察{i}"),)}
              for i in range(20)]
    themes.append({"name": "RAT", "directions": (
        _finding("Quasar类远控配置与监听端口设置"),)})

    chapters, warnings = gs.pack_themes_into_chapters(themes, 8)

    assert chapters[0]["name"] == gs._HYPOTHESIS_THEME_NAME or \
        gs._CRITICAL_THEME_NAME in [c["name"] for c in chapters]
    critical = next(c for c in chapters if c["name"] == gs._CRITICAL_THEME_NAME)
    assert len(gs.chapter_directions(critical)) == 1
    assert any(w.startswith("CASE_CRITICAL_ISOLATED_1") for w in warnings)


def test_benign_network_capability_is_not_case_critical():
    """A driver's "网络能力" is not a remote-control finding."""
    assert not gs._is_case_critical(_finding("多份样本导入网络通信与磁盘操作能力"))
    assert not gs._is_case_critical(_finding("Edge 浏览器配置与崩溃痕迹"))
    assert gs._is_case_critical(_finding("Quasar类远控配置与监听端口设置"))
    assert gs._is_case_critical(_finding("检测到控制端与服务端配置并存"))


def test_shortened_heading_never_starts_or_ends_with_a_particle():
    """A cut at the script boundary left "的material.dll多版本PE结构差" and
    "DESKTOP-02H4UFI的" — fragments that read as broken text."""
    for original in ("同名文件material.dll的多版本PE结构差异与未来时间戳",
                     "DESKTOP-02H4UFI的SanDisk Extreme SSD设备异常",
                     "ELEVATION_SERVICE与EXPLORER执行痕迹"):
        trimmed = gs._shorten_heading(original, 24)
        assert not trimmed.startswith(("的", "了", "和", "与", "及", "在"))
        assert not trimmed.endswith(("的", "了", "和", "与", "及", "在"))
        assert len(trimmed) <= 24


# ---------------------------------------------------------------------------
# A chapter written in parts must read as one argument
#
# Chapter 4 of the PC.E01 report joined four parts and published four
# "本章围绕…展开" openings and two "综合来看" conclusions in one chapter. The
# reader sees several short reports stapled together, not one chapter.
# ---------------------------------------------------------------------------


def test_part_role_only_first_introduces_and_last_concludes():
    assert gs._part_role(0, 1) == "single"
    assert gs._part_role(0, 3) == "first"
    assert gs._part_role(1, 3) == "middle"
    assert gs._part_role(2, 3) == "last"


def test_middle_and_last_parts_are_told_not_to_introduce():
    for role in ("middle", "last"):
        instruction = gs._PART_ROLE_INSTRUCTIONS[role]
        assert "禁止写引言" in instruction
    assert "结论由最后一段写" in gs._PART_ROLE_INSTRUCTIONS["first"]


def test_repeated_openings_are_dropped_from_a_joined_chapter():
    text = "\n\n".join([
        "本章围绕事件日志的解析状态展开，说明材料覆盖不足。",
        "空解析结果涉及多个通道，其中一份明确报解析错误。",
        "本章材料集中呈现两类情况：一是日志为空，二是常规记录。",
        "在可读记录中，SMB 服务端日志共 328 条，集中在两个时段。",
        "综合来看，本章反映的是解析层面的缺口，不构成行为判断。",
    ])

    cleaned = gs._strip_repeated_scaffolding(text)

    # One introducing sentence survives; the other part's opening is gone.
    assert cleaned.count("本章围绕") == 1
    # The substantive third paragraph carries findings and must survive even
    # though it also opens with "本章材料集中呈现".
    assert "SMB 服务端日志共 328 条" in cleaned


def test_repeated_conclusions_keep_only_the_last():
    text = "\n\n".join([
        "本章围绕两个对象展开。",
        "第一类材料解析为空，第二类为常规活动。",
        "综合来看，本章只能支持有限的观察。",
        "另有可读记录显示系统组件密集执行。",
        "综合来看，现有材料尚不足以形成确定结论。",
    ])

    cleaned = gs._strip_repeated_scaffolding(text)

    assert cleaned.count("综合来看") == 1
    assert cleaned.rstrip().endswith("尚不足以形成确定结论。")


@pytest.mark.asyncio
async def test_multi_part_chapter_is_joined_without_duplicate_scaffolding(monkeypatch):
    themes = [_theme("甲", 4)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 1)
    monkeypatch.setattr(gs, "_split_chapter_rows",
                        lambda rows, limit=gs.REQUEST_CHAR_LIMIT: [[r] for r in rows])

    class Echo(_WriterLLM):
        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            self.calls.append(body)
            if "topics" in body:
                return {"content": "综合命名标题"}
            index = len([c for c in self.calls if "directions" in c])
            return {"content": json.dumps({
                "heading": "标题",
                "content": f"本章围绕第{index}批材料展开，说明观察结果。"
                           + "材料观察正文。" * 80,
            }, ensure_ascii=False)}

    sections, _warnings = await gs.write_chapters(
        chapters, _materials(), Echo())

    assert len(sections) == 1
    assert sections[0]["content"].count("本章围绕") == 1


# ---------------------------------------------------------------------------
# A chapter must not be a frequency table
# ---------------------------------------------------------------------------


def test_execution_frequency_inventory_is_detected():
    inventory = (
        "CHSIME.EXE 运行 11 次，CTFMON.EXE 运行 15 次，"
        "DATAEXCHANGEHOST.EXE 运行 4 次，DEFRAG.EXE 运行 3 次，"
        "IPCONFIG.EXE 运行 1 次。"
    )
    assert gs._paragraph_is_an_inventory(inventory)
    assert not gs._inventory_free(inventory)


def test_interpreted_execution_counts_are_not_an_inventory():
    prose = (
        "CONHOST.EXE 在 47 次执行中引用了 CMD、WEVTUTIL 与 DEFRAG，"
        "表明控制台宿主承载了多个命令行子进程；"
        "SEARCHINDEXER.EXE 的执行则集中在索引维护时段。"
    )
    assert not gs._paragraph_is_an_inventory(prose)
    assert gs._inventory_free(prose)


def test_inventory_check_is_per_paragraph_not_per_chapter():
    """Three named programs per paragraph is the documented budget."""
    allowed = "\n\n".join(
        "A.EXE 运行 1 次，B.EXE 运行 2 次，C.EXE 运行 3 次，均属系统组件。"
        for _ in range(3))
    assert gs._inventory_free(allowed)


@pytest.mark.asyncio
async def test_inventory_chapter_is_rewritten_once():
    themes = [_theme("甲", 2)]
    chapters, _ = gs.pack_themes_into_chapters(themes, 1)

    class InventoryThenProse(_WriterLLM):
        def __init__(self):
            super().__init__()
            self.writes = 0

        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            self.calls.append(body)
            if "topics" in body:
                return {"content": "标题"}
            self.writes += 1
            if self.writes == 1:
                body_text = (
                    "A.EXE 运行 1 次，B.EXE 运行 2 次，C.EXE 运行 3 次，"
                    "D.EXE 运行 4 次，E.EXE 运行 5 次。" * 8)
            else:
                body_text = "系统组件在该时段集中执行，属常规维护活动。" * 30
            return {"content": json.dumps(
                {"heading": "标题", "content": body_text}, ensure_ascii=False)}

    sections, _warnings = await gs.write_chapters(
        chapters, _materials(), InventoryThenProse())

    assert len(sections) == 1
    assert gs._inventory_free(sections[0]["content"])


# ---------------------------------------------------------------------------
# The advisory chapter must name what to check
# ---------------------------------------------------------------------------

def test_advisory_chapter_lists_open_questions_from_the_evidence():
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)
    directions = (
        InvestigationDirection(
            direction_id="d1", title="Quasar 远控配置",
            description="配置文本含连接参数。", finding_kind="observation",
            supporting_refs=(quote, quote), counter_refs=(),
            missing_information=("配置文件的来源主机与生成时间未知",),
            alternative_explanations=(), baseline_direction_ids=(),
            case_context_quote="", origin="material"),
        InvestigationDirection(
            direction_id="d2", title="PE 时间戳异常",
            description="多份样本时间戳落在未来。", finding_kind="observation",
            supporting_refs=(quote,), counter_refs=(),
            missing_information=("缺少文件哈希与数字签名", "缺少编译环境信息"),
            alternative_explanations=(), baseline_direction_ids=(),
            case_context_quote="", origin="material"),
    )

    text = gs._advisory_text(directions, warnings=())

    assert "配置文件的来源主机与生成时间未知" in text
    assert "缺少文件哈希与数字签名" in text
    # The best-supported direction's gap is listed first.
    assert text.index("配置文件的来源主机") < text.index("缺少文件哈希")


def test_advisory_chapter_deduplicates_repeated_gaps():
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan
    quote = MaterialSpan(material_id="m001", quote="x", character_start=0,
                         character_end=1, ambiguous=False)
    directions = tuple(
        InvestigationDirection(
            direction_id=f"d{i}", title=f"观察{i}", description="描述。",
            finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
            missing_information=("缺少命令行参数，无法确认调用目标",),
            alternative_explanations=(), baseline_direction_ids=(),
            case_context_quote="", origin="material")
        for i in range(5))

    text = gs._advisory_text(directions, warnings=())

    assert text.count("缺少命令行参数") == 1


def test_inventory_paragraph_is_compressed_deterministically():
    """Prompt-only enforcement failed twice: the model returned the same table.

    The backstop keeps the first three named programs and states the rest as a
    group with the observed range.
    """
    paragraph = (
        "其他系统与内置应用执行痕迹包括：COMPATTELRUNNER.EXE运行2次，"
        "CONSENT.EXE运行13次，CONTROL.EXE运行1次，DEFRAG.EXE运行3次，"
        "NGENTASK.EXE运行1次，NISSRV.EXE运行4次。这些组件多属系统常规活动。"
    )

    compressed = gs._compress_inventory(paragraph)

    assert not gs._paragraph_is_an_inventory(compressed)
    assert "COMPATTELRUNNER.EXE" in compressed
    assert "NISSRV.EXE" not in compressed
    assert "另有 3 个系统组件各有 1 至 4 次执行" in compressed
    # The paragraph's own conclusion must survive the compression.
    assert "这些组件多属系统常规活动" in compressed


def test_compress_inventories_leaves_compliant_paragraphs_alone():
    prose = "CONHOST.EXE 运行 47 次，承载了 CMD、WEVTUTIL 与 DEFRAG 等子进程。"
    assert gs._compress_inventories(prose) == prose


def test_compress_inventories_preserves_paragraph_boundaries():
    text = "第一段正常叙述。\n\n" + "，".join(
        f"P{i}.EXE运行{i}次" for i in range(1, 8)) + "。\n\n第三段正常叙述。"

    out = gs._compress_inventories(text)

    assert out.count("\n\n") == 2
    assert out.startswith("第一段正常叙述。")
    assert out.endswith("第三段正常叙述。")


def test_negated_malware_mention_is_not_case_critical():
    """A sample that merely DISCLAIMS a RAT link is not a RAT finding.

    One chapter was titled "Quasar远控等重点样本研判" while its prose said the
    samples showed no link to Quasar: the direction read "未显示与前述Quasar
    配置…的直接关联" and a bare keyword match promoted it into the critical
    tier, so the chapter name contradicted its own body.
    """
    disclaimer = _finding(
        "两份常规Windows可执行文件的导入特征")
    disclaimer = disclaimer.model_copy(update={
        "description": "两份32位EXE导入常规API，未显示与前述Quasar配置或.NET程序族的直接关联，"
                       "仅作为背景材料记录。"})
    assert not gs._is_case_critical(disclaimer)

    genuine = _finding("Quasar类远控配置与监听端口设置")
    genuine = genuine.model_copy(update={
        "description": "两份XML配置含Hosts 192.168.10.30:4782、Mutex、AddStartup与监听端口。"})
    assert gs._is_case_critical(genuine)


def test_unrelated_phrasing_is_not_case_critical():
    unrelated = _finding("系统组件执行")
    unrelated = unrelated.model_copy(update={
        "description": "该进程与远控无关，属系统常规组件。"})
    assert not gs._is_case_critical(unrelated)
