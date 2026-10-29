"""Stage narrative composition: validated directions woven into chapters."""
import json

import pytest

from httpserver.services.forensic_report.generation_prompts import STAGE_NARRATIVE_SYSTEM_V1
from httpserver.services.forensic_report.generation_sources import material
from httpserver.services.forensic_report.generation_stages import (
    _derived_heading, compose_stage_narrative, render_stage_report,
    stage_citation_name, strip_material_ids,
)
from httpserver.services.forensic_report.models import (
    InvestigationDirection, MaterialSpan,
)


class _Env:
    """Read-model stub: only fields the composer/renderer touch."""
    def __init__(self, mode="evidence_only"):
        self.analysis_mode = mode
        self.case_description = "" if mode == "evidence_only" else "案情语境"
        self.evidence_scope_hash = "0" * 64
        self.baseline = None
        # discover_directions selects the v1/v2 prompt by suffix; without this
        # the lookup raises AttributeError, which the batch guard records as a
        # rejection and the whole discovery reports NO_VALIDATED_NEUTRAL_ANALYSIS.
        self.prompt_version = "final-report:evidence-only:v2"


def _envelope(mode="evidence_only"):
    return _Env(mode)


def _materials():
    return (
        material("m001", "file:/case/话术/7要素.docx", kind="text", status="ready",
                 text="培训话术正文片段"),
        material("m002", "file:/case/账目.xlsx", kind="text", status="ready",
                 text="转账记录摘录"),
    )


def _directions():
    quote = MaterialSpan(material_id="m001", quote="培训话术正文片段", character_start=0,
                         character_end=8, ambiguous=False)
    return (
        InvestigationDirection(
            direction_id="d1", title="话术培训材料", description="材料包含话术培训文档。",
            finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
            missing_information=("材料原始来源",), alternative_explanations=(),
            baseline_direction_ids=(), case_context_quote="", origin="material",
        ),
    )


class NarrativeModel:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    async def chat_completion(self, system, user, **kwargs):
        self.calls.append(system)
        # The prompt carries the batch position; compare against the rendered form.
        assert system == STAGE_NARRATIVE_SYSTEM_V1.replace("__PART__", "1/1")
        body = json.loads(user)
        assert body["validated_directions"][0]["supporting"][0]["file"] == "7要素.docx"
        return {"content": json.dumps(self.payload, ensure_ascii=False), "model": "synthetic"}


@pytest.mark.asyncio
async def test_narrative_sections_render_with_filename_citations():
    payload = {"sections": [
        {"heading": "检材范围与构成",
         "content": "本轮共读取两份冻结材料。其中 7要素.docx 为话术培训类文档，账目.xlsx 为账目摘录，"
                    "两者均通过来源哈希校验后进入本轮研判，未使用历史 AI 摘要替代原文。"},
        {"heading": "异常与待核线索",
         "content": "话术培训文档 7要素.docx 出现在窝点镜像中，其用途与流转链条仍需核对原件；账目文件账目.xlsx 中的"
                    "资金记录尚未与具体账户建立归属关系。上述两项仍缺原始来源信息，需人工调取完整文件核对。"},
    ]}
    model = NarrativeModel(payload)
    sections = await compose_stage_narrative(
        _envelope(), _materials(), _directions(), (), model, chapter_shaped=False)
    # Composition keeps the model's heading; skeleton retitling happens at render.
    assert sections and sections[0]["heading"] == "检材范围与构成"

    response, _stage = render_stage_report(_envelope(), _materials(), _directions(), (), (), sections)
    headings = [s.heading for s in response.sections]
    # Chapter 1 now carries the case overview and the thread table; the two
    # generic skeleton headings below it are still re-titled from their content.
    # The batch path has no direction provenance, so the per-material appendix
    # is (honestly) absent: nothing can be attributed file-by-file.
    assert headings == [
        "案件总述与证据召回", "本轮共读取两份冻结材料",
        "话术培训文档 7要素.docx 出现在窝点镜像中", "人工核查建议",
    ]
    body = response.sections[1]
    assert "c001" in body.citation_ids and "c002" in body.citation_ids
    clue = response.sections[2]
    assert clue.citation_ids == ("c001", "c002")
    assert response.sections[-1].heading == "人工核查建议"


@pytest.mark.asyncio
async def test_invalid_narrative_payload_returns_none_and_fragment_fallback():
    model = NarrativeModel({"sections": [{"heading": "x", "content": "短"}]})
    assert await compose_stage_narrative(
        _envelope(), _materials(), _directions(), (), model, chapter_shaped=False) is None

    response, _stage = render_stage_report(_envelope(), _materials(), _directions(), (), (), None)
    assert any(s.heading.startswith("材料自主发现") for s in response.sections)


def test_citation_name_handles_flat_and_nested_paths():
    assert stage_citation_name("file:/话术/7要素.docx") == "7要素.docx"
    assert stage_citation_name("file:README.txt") == "README.txt"


# Regression (PC.E01): the prompt forbade material ids but nothing enforced it,
# so 55 "m0084"-style identifiers reached published prose where a reader cannot
# resolve them. Composition must scrub them before the section is accepted.
@pytest.mark.asyncio
async def test_material_ids_are_stripped_from_narrative():
    # Two sections: the validator now enforces the prompt's "3 to 6" shape with
    # a floor of 2, so a single-section answer is rejected as a stub.
    payload = {"sections": [
        {"heading": "检材范围与构成",
         "content": "本轮材料包括 7要素.docx（m0012）与账目.xlsx。m0013 为重复的空内容，"
                    "不构成独立佐证；m0014、m0015 的机器视觉描述近似，无法确认来源。"
                    "上述材料均通过来源哈希校验，未使用历史摘要替代原文。"},
        {"heading": "信息缺口与核查建议",
         "content": "7要素.docx（m0016）与账目.xlsx 的原始来源尚未提供，需人工调取完整文件核对；"
                    "m0017 的机器视觉描述与 m0018 近似，不能计为独立佐证。"
                    "两份材料的形成时间与流转路径均需补充，方可判断其与案件事实的关联。"},
    ]}
    model = NarrativeModel(payload)
    sections = await compose_stage_narrative(
        _envelope(), _materials(), _directions(), (), model, chapter_shaped=False)
    assert sections
    body = "\n".join(s["content"] for s in sections)
    for identifier in ("m0012", "m0013", "m0014", "m0015", "m0016", "m0017", "m0018"):
        assert identifier not in body
    # The real file names survive, since they are how the reader locates evidence.
    assert "7要素.docx" in body and "账目.xlsx" in body
    # No empty brackets or doubled spaces left behind by the deletion.
    assert "（）" not in body and "()" not in body and "  " not in body


def test_strip_material_ids_keeps_words_that_merely_contain_digits():
    assert strip_material_ids("型号 m1234 已核对") == "型号 已核对"
    # A token that only looks similar must not be touched.
    assert strip_material_ids("md5 为 abc123，m1 不是编号") == "md5 为 abc123，m1 不是编号"
    assert strip_material_ids("文件名 am0012.txt 保留") == "文件名 am0012.txt 保留"


# Regression: ids are often enumerated in runs, and deleting each token on its
# own left the connector behind ("m003、m004" -> "mm"). A run must be removed
# as one unit together with the enumeration marks and the preposition that
# introduced it, so the sentence keeps its own subject.
def test_strip_material_ids_removes_enumerated_runs():
    assert strip_material_ids("m003、m004 均指向同一来源。") == "均指向同一来源。"
    assert strip_material_ids("m001、m002 与 m003 均一致。") == "均一致。"
    assert strip_material_ids("m001 与 m002 记录了登录。") == "记录了登录。"
    assert strip_material_ids("根据 m0001 与 m0002，攻击者使用了 RDP。") == "攻击者使用了 RDP。"
    assert strip_material_ids("见 m001、m002、m003 三份材料。") == "三份材料。"
    assert strip_material_ids("结合 m005 可判断存在横向移动。") == "可判断存在横向移动。"


def test_strip_material_ids_handles_brackets_and_mid_sentence_ids():
    assert strip_material_ids("（m012）该文件为事件日志。") == "该文件为事件日志。"
    assert strip_material_ids("该日志（m007）显示异常。") == "该日志显示异常。"
    assert strip_material_ids("m001 显示登录，m002 显示注销。") == "显示登录，显示注销。"
    # Four-digit ids and sentence-initial ids are the same class.
    assert strip_material_ids("m1234 是唯一的例外") == "是唯一的例外"


# Regression: eight batches each answered with the prescribed skeleton, so the
# report read as "检材范围与构成（2）…（8）". Repeated skeleton headings are now
# re-titled from the batch's own content instead of being numbered.
def test_repeated_skeleton_headings_are_derived_from_content():
    narrative = [
        {"heading": "检材范围与构成", "content": "本轮材料为 Quasar 远控控制端配置。详见 settings.xml。"},
        {"heading": "检材范围与构成（2）",
         "content": "材料中 Chrome 组件清单与本地化资源占多数。涉及 messages.json。"},
        {"heading": "远程控制工具部署", "content": "Quasar 控制端监听 4782 端口，启用了 UPnP。"},
    ]
    response, _stage = render_stage_report(
        _envelope(), _materials(), _directions(), (), (), narrative)
    headings = [s.heading for s in response.sections]
    assert headings[1] == "本轮材料为 Quasar 远控控制端配置"
    assert headings[2] == "Chrome 组件清单与本地化资源占多数"
    # A heading the model actually wrote as a topic is preserved verbatim.
    assert headings[3] == "远程控制工具部署"


def test_derived_heading_falls_back_when_content_is_too_short():
    # Nothing usable to derive from: keep the original rather than emit "。".
    assert _derived_heading("信息缺口与核查建议", "。") == "信息缺口与核查建议"
    assert _derived_heading("信息缺口与核查建议（3）", "。") == "信息缺口与核查建议（3）"



def test_derived_heading_cuts_at_a_natural_boundary():
    # A hard 24-char cut produced "default_cloud_config.jso"; the label must
    # end at a clause boundary or a dot, never mid-identifier.
    # The label starts after an opening file name, so it is a phrase rather
    # than a bare identifier, and it ends at the clause boundary.
    heading = _derived_heading(
        "检材范围与构成",
        "材料中 default_cloud_config.json 与 protocol.json 记录浏览器内置配置，"
        "涉及 regionBlockList 字段。")
    assert heading == "protocol.json 记录浏览器内置配置"
    assert len(heading) <= 24

    # Never end mid-identifier.
    heading = _derived_heading(
        "检材范围与构成", "本批材料覆盖 registry hive 与事件日志导出文件" + "x" * 30 + "。")
    assert not heading.endswith("x")


# Regression: narrative batches habitually open with a chapter self-reference,
# so the derived label read "本章围绕本机账号" — a sentence fragment, not a
# topic. The lead-in and its introducing verb are dropped.
def test_derived_heading_drops_chapter_self_reference():
    assert (_derived_heading(
        "检材范围与构成",
        "本章围绕本机账号、凭据类文件与远控客户端账户日志，梳理与身份和账号活动相关的线索。")
        == "本机账号、凭据类文件与远控客户端账户日志")
    assert (_derived_heading(
        "检材范围与构成",
        "本章汇总检材中反映主机联网与访问行为的证据，按SSH已知主机记录组织。")
        == "检材中反映主机联网与访问行为的证据")
    assert (_derived_heading(
        "检材范围与构成",
        "本章承接前六章未能归入既定主题的材料，逐类说明其来源。")
        == "前六章未能归入既定主题的材料，逐类说明其来源")
    # A real topic heading is never rewritten.
    assert _derived_heading("人员账号与身份信息", "本章围绕账号。") == "人员账号与身份信息"


# Regression: a repeated *topic* heading ("材料观察") produced the same
# "（2）（3）" stapling tell as the skeleton headings did. The second batch is
# re-titled from its own content instead.
def test_repeated_topic_headings_are_derived_from_content():
    from httpserver.services.forensic_report.generation_stages import (
        _SKELETON_HEADINGS,
    )

    batches = [
        {"heading": "材料观察",
         "content": "本批材料显示用户 admin 在 2025-05-19 登录系统，涉及账号活动。"},
        {"heading": "材料观察",
         "content": "本批材料显示 Quasar 控制端配置了 4782 监听端口。"},
    ]
    seen = {}
    headings = []
    for row in batches:
        heading = _derived_heading(row["heading"], row["content"])
        seen[heading] = seen.get(heading, 0) + 1
        if seen[heading] > 1:
            derived = _derived_heading(_SKELETON_HEADINGS[0], row["content"])
            if derived and derived not in seen:
                heading = derived
                seen[heading] = 1
            else:
                heading = f"{heading}（{seen[heading]}）"
        headings.append(heading)

    assert headings[0] == "材料观察"
    assert headings[1] == "Quasar 控制端配置了 4782 监听端口"
    assert not any("（2）" in h for h in headings)


# ---------------------------------------------------------------------------
# Report shape regressions found in the PC.E01 end-to-end run.
#
# That report had 21 chapters, but the scope chapter claimed all 586 citations
# while the narrative chapters used 171 of them; one chapter had absorbed
# 30,543 characters of overflow; and 4 of 9 narrative batches were rejected
# because each carried 31-36 directions.
# ---------------------------------------------------------------------------


def test_scope_chapter_does_not_claim_every_citation():
    """The scope chapter is a methods note; it carries no citations.

    Attaching the readable set still put 645 ids on a 123-character paragraph
    in a PC.E01 report, so chapter 1 claimed almost the whole evidence list
    while the findings chapters carried the rest.
    """
    response, _stage = render_stage_report(
        _envelope(), _materials(), _directions(), (), ())
    scope = response.sections[0]
    assert scope.heading == "案件总述与证据召回"
    assert scope.citation_ids == ()
    # The findings still carry their citations.
    assert any(s.citation_ids for s in response.sections[1:])


def test_unreferenced_citations_are_not_published():
    """Only citations a section references reach the manifest."""
    from httpserver.services.forensic_report.generation_execution import (
        build_citation_manifest,
    )

    response, _stage = render_stage_report(
        _envelope(), _materials(), _directions(), (), ())
    referenced = {c for s in response.sections for c in s.citation_ids}
    snapshot = type("S", (), {"captured_at": 0})()
    envelope = type("E", (), {
        "main_evidence": tuple(
            type("I", (), {"evidence_key": c.evidence_key, "bound_analysis": None,
                           "snapshot": snapshot})()
            for c in response.citations),
        "appendix_evidence": (),
    })()

    entries = build_citation_manifest(response, envelope)

    assert {e.citation_id for e in entries} == referenced


@pytest.mark.asyncio
async def test_narrative_batches_are_bounded_by_direction_count():
    """A batch must stay small enough for one answer to cover.

    Byte-only batching packed 36 directions into a batch; the model then
    returned malformed sections and the batch was dropped entirely.
    """
    from httpserver.services.forensic_report import generation_stages

    directions = []
    for i in range(40):
        quote = MaterialSpan(material_id="m001", quote="培训话术正文片段",
                             character_start=0, character_end=8, ambiguous=False)
        directions.append(InvestigationDirection(
            direction_id=f"d{i}", title=f"方向{i}", description="材料包含话术培训文档。",
            finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
            missing_information=(), alternative_explanations=(),
            baseline_direction_ids=(), case_context_quote="", origin="material",
        ))

    class RecordingModel:
        def __init__(self):
            self.sizes = []

        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            self.sizes.append(len(body["validated_directions"]))
            part = body["part"]
            return {"content": json.dumps({"sections": [
                {"heading": f"章节{part}", "content": "本轮材料显示存在多项待核活动，" * 6},
            ]}, ensure_ascii=False), "model": "synthetic"}

    model = RecordingModel()
    await compose_stage_narrative(
        _envelope(), _materials(), tuple(directions), (), model,
        chapter_shaped=False,
    )

    assert model.sizes, "no batches were composed"
    assert max(model.sizes) <= generation_stages._MAX_DIRECTIONS_PER_BATCH


def test_overflow_chapters_are_not_merged_without_bound():
    """Merging past the chapter cap must stay bounded.

    The unbounded merge produced a single 30,543-character chapter, six times
    any other chapter and unreadable as a section.
    """
    from httpserver.services.forensic_report import generation_stages

    one_chapter = "材料显示存在待核活动。" * 400
    narrative = [
        {"heading": f"主题{i}", "content": one_chapter}
        for i in range(generation_stages._MAX_REPORT_CHAPTERS + 6)
    ]
    response, stage = render_stage_report(
        _envelope(), _materials(), _directions(), (), (), narrative=narrative)

    assert len(response.sections) <= generation_stages._MAX_REPORT_CHAPTERS + 2
    # Overflow is dropped, never merged into an unrelated chapter: merging
    # produced a 7k-character chapter carrying two unrelated topics. No
    # chapter may exceed what a single batch produced.
    assert max(len(s.content) for s in response.sections) <= len(one_chapter)
    assert any("NARRATIVE_OVERFLOW_DROPPED" in w for w in stage.warnings)


# ---------------------------------------------------------------------------
# Report shape v5: chapter summaries, the case overview and the recall table.
# ---------------------------------------------------------------------------


def _recall_appendix(response):
    """The per-material detail table now lives in the appendix AFTER all chapters."""
    for section in response.sections:
        if section.heading.startswith("附录：证据召回明细"):
            return section
    return None


def _narrative_rows(materials, directions, *, summary="本章表明存在待核活动，仍需补齐原始凭据。"):
    """A chapter-shaped narrative row carrying its own direction provenance."""
    return [{"heading": "话术培训材料", "content": "材料包含话术培训文档。" * 20,
             "summary": summary,
             "direction_ids": tuple(d.direction_id for d in directions)}]


def test_each_chapter_carries_its_own_summary():
    directions = _directions()
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (),
        _narrative_rows(_materials(), directions))
    chapter = next(s for s in response.sections if s.heading == "话术培训材料")
    assert chapter.summary == "本章表明存在待核活动，仍需补齐原始凭据。"


def test_chapter_summary_is_optional_for_older_narratives():
    """A narrative written before summaries existed still renders."""
    directions = _directions()
    rows = _narrative_rows(_materials(), directions, summary="")
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (), rows)
    chapter = next(s for s in response.sections if s.heading == "话术培训材料")
    assert chapter.summary == ""


def _themed(rows, directions, name="话术培训材料"):
    from httpserver.services.forensic_report.generation_stages import _ChapterNarrative
    return _ChapterNarrative(rows, [{"name": name, "directions": tuple(directions)}])


def test_first_chapter_carries_overview_and_recall_table():
    """Chapter 1 = scope paragraph + whole-case overview + thread table.

    The per-material recall detail moved to the appendix after all chapters
    (报告契约：先线索，后逐文件明细)."""
    directions = _directions()
    rows = _narrative_rows(_materials(), directions)
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (),
        _themed(rows, directions),
        overview="全案总述正文，说明材料整体呈现什么。")

    first = response.sections[0]
    assert first.heading == "案件总述与证据召回"
    # The overview comes first (the reader meets the case), then the reading
    # limits that qualify it.
    assert "本轮在已入报的 2 份材料范围内研判" in first.content
    assert "全案总述正文" in first.content
    assert first.content.index("全案总述正文") < first.content.index("本轮在已入报的 2 份材料范围内研判")

    threads = first.thread_table
    assert threads is not None
    # Exhaustive: the only direction is covered by the only thread.
    assert threads.covered_directions == 1
    assert threads.total_directions == 1
    thread = threads.rows[0]
    assert thread.name
    assert thread.contribution
    assert thread.direction_count == 1
    assert thread.material_count == 1
    assert thread.citation_ids == ("c001",)
    assert first.summary

    appendix = _recall_appendix(response)
    assert appendix is not None and appendix.recall_table is not None
    # The appendix must be the LAST section, after every chapter.
    assert response.sections[-1] is appendix
    table = appendix.recall_table
    # m001 is quoted by the only direction; m002 is readable but nothing cites
    # it, so it must not appear as recalled evidence.
    assert table.total_materials == 2
    assert table.recalled_materials == 1
    assert {row.evidence_name for row in table.rows} == {"7要素.docx"}
    assert any("未被任何章节引用" in note for note in table.notes)


def test_recall_table_counts_references_and_chapters():
    """Counts come from the chapters' own citation sets, never from the model."""
    directions = _directions()
    rows = [
        {"heading": "话术培训材料", "content": "材料包含话术培训文档。" * 20,
         "summary": "", "direction_ids": ("d1",)},
        {"heading": "再次引用同一材料", "content": "材料再次提到培训话术正文片段。" * 20,
         "summary": "", "direction_ids": ("d1",)},
    ]
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (), _themed(rows, directions))

    table = _recall_appendix(response).recall_table
    row = next(r for r in table.rows if r.evidence_name == "7要素.docx")
    assert row.chapter_count == 2
    # Both chapters cite the same material, so the report refers to it twice.
    assert row.reference_count == 2
    assert table.total_citations == 2
    # The thread table aggregates the same evidence at case level.
    threads = response.sections[0].thread_table
    assert threads.rows[0].direction_count == 1
    assert threads.rows[0].chapter_numbers == (2, 3)


def test_recall_rows_explain_what_each_material_contributed():
    """The table says what a material contributed, not just how often it was cited."""
    directions = _directions()
    rows = _narrative_rows(_materials(), directions)
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (), rows)

    table = _recall_appendix(response).recall_table
    row = table.rows[0]
    assert row.contribution
    # The deterministic fallback names the finding the material backs.
    assert "话术培训材料" in row.contribution
    # ...and reads as a sentence, not a stitched fragment ("的成立").
    assert "的成立" not in row.contribution
    assert "支撑「" in row.contribution
    # Counts are demoted to a footnote, so they must not lead the explanation.
    assert not row.contribution.startswith("引用")


def test_model_contribution_is_used_when_usable():
    directions = _directions()
    rows = _narrative_rows(_materials(), directions)
    contributions = {
        "file:/case/话术/7要素.docx":
            "支撑话术培训材料的认定，正文引用的培训话术正文片段表明该文档用于话术演练，"
            "但缺少原始来源与流转路径。",
    }
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (), rows,
        recall_contributions=contributions)

    row = _recall_appendix(response).recall_table.rows[0]
    assert row.contribution.startswith("支撑话术培训材料的认定")
    assert "培训话术正文片段" in row.contribution


@pytest.mark.asyncio
async def test_contribution_rejects_counts_and_uses_fallback_per_row():
    """A rejected per-row answer never leaves the row without an explanation."""
    from httpserver.services.forensic_report.generation_stages import (
        _clean_contribution, _recall_stats, compose_recall_contributions,
    )

    directions = _directions()
    stats = _recall_stats(_materials(), _narrative_rows(_materials(), directions), directions)

    class CountingModel:
        async def chat_completion(self, system, user, **kwargs):
            return {"content": "该材料被引用 5 次，被 2 章引用，对本案很重要。"}

    contributions = await compose_recall_contributions(stats, llm=CountingModel())
    assert contributions == {}
    # A count-only answer is not a contribution.
    assert _clean_contribution("该材料被引用 5 次，被 2 章引用。") == ""


@pytest.mark.asyncio
async def test_contribution_falls_back_when_the_provider_fails():
    from httpserver.services.forensic_report.generation_stages import (
        _recall_stats, compose_recall_contributions,
    )

    directions = _directions()
    stats = _recall_stats(_materials(), _narrative_rows(_materials(), directions), directions)

    class BrokenModel:
        async def chat_completion(self, system, user, **kwargs):
            raise RuntimeError("provider down")

    assert await compose_recall_contributions(stats, llm=BrokenModel()) == {}
    # The table still publishes a deterministic sentence for each row.
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (),
        _narrative_rows(_materials(), directions), recall_contributions={})
    assert all(row.contribution for row in _recall_appendix(response).recall_table.rows)


def test_recall_table_reports_unreferenced_materials():
    """A readable material no chapter cites is stated, not silently dropped."""
    directions = _directions()
    rows = _narrative_rows(_materials()[:1] and _materials(), directions)
    # Only one material is quoted by the direction.
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (), rows)
    table = _recall_appendix(response).recall_table
    assert table.recalled_materials == 1
    assert any("未被任何章节引用" in note for note in table.notes)


def test_every_deterministic_chapter_also_gets_a_summary():
    """The contract is one closing statement per chapter, whatever shape it took."""
    response, _stage = render_stage_report(
        _envelope(), _materials(), _directions(), (), (), None)

    chapters = [s for s in response.sections if s.heading != "案件总述与证据召回"]
    assert chapters, "fragment fallback produced no chapters"
    for chapter in chapters:
        assert chapter.summary, f"chapter without summary: {chapter.heading}"


def test_difference_chapter_summary_counts_the_outcomes():
    from httpserver.services.forensic_report.generation_stages import _comparison_summary

    by_status = {"supported": [1, 2], "revised": [3], "contradicted": []}
    labels = {"supported": "得到支持", "revised": "需要修正", "weakened": "支持减弱",
              "contradicted": "存在相反材料", "insufficient": "依据不足", "case_only": "仅案情提出"}
    summary = _comparison_summary(by_status, labels, 3)
    assert "3 项基线方向" in summary and "2 项得到支持" in summary and "1 项" in summary


def test_overview_drops_pipeline_batch_voice():
    """"本批材料围绕…" reads like an internal batch log, not a case summary."""
    from httpserver.services.forensic_report.generation_stages import _clean_overview

    text = ("本批材料围绕受害主机磁盘镜像与相关日志展开，整体呈现 Windows 桌面主机的使用痕迹，"
            "时间跨度集中在 2025 年 5 月 19 日至 20 日，反复出现服务宿主与清理工具。"
            "该批材料同时存在大量空日志，构成实质性的分析缺口，需结合原始记录核实。")
    cleaned = _clean_overview(text)
    assert "本批" not in cleaned and "该批" not in cleaned
    assert "这批材料" in cleaned


def test_case_context_chapter_has_its_own_closing_line():
    """Every chapter carries a summary, including the case-context chapter."""
    class _GuidedEnv(_Env):
        def __init__(self):
            super().__init__("case_guided")
            # StageAnalysis requires the full baseline lineage for a guided
            # report; the renderer only reads these three attributes here.
            from types import SimpleNamespace
            self.baseline = SimpleNamespace(
                report_id="rep-a", report_sha256="b" * 64,
                evidence_scope_hash="0" * 64, directions=(), priorities={},
                text_models=(), materials=())

    response, _stage = render_stage_report(
        _GuidedEnv(), _materials(), _directions(), (), ())
    case_chapter = next(s for s in response.sections if s.heading == "本次案情（待核语境）")
    assert case_chapter.summary
    assert "调查语境" in case_chapter.summary


def test_advisory_checklist_never_publishes_material_ids():
    """The review checklist quoted "与 m0178 配置的关联关系" to the reader.

    missing_information comes from the discovery model, so it can contain the
    prompt's own material ids; the advisory chapter is the last place a reader
    looks for an actionable gap, not for "m0178".
    """
    from httpserver.services.forensic_report.generation_stages import (
        _advisory_text, _verification_checklist,
    )
    quote = MaterialSpan(material_id="m001", quote="培训话术正文片段", character_start=0,
                         character_end=8, ambiguous=False)
    direction = InvestigationDirection(
        direction_id="d1", title="话术材料", description="材料包含话术培训文档。",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=("与 m0178 配置的关联关系", "缺少该程序的命令行参数"),
        alternative_explanations=(), baseline_direction_ids=(),
        case_context_quote="", origin="material",
    )
    response, _stage = render_stage_report(
        _envelope(), _materials(), (direction,), (), ())

    advisory = next(s for s in response.sections if s.heading == "人工核查建议")
    assert "m0178" not in advisory.content
    assert "缺少该程序的命令行参数" in advisory.content
    # The note is scrubbed, not silently dropped when it still says something.
    assert any("配置的关联关系" in note for note in _verification_checklist((direction,)))
    assert "m0178" not in _advisory_text((direction,), ())


def test_fragment_and_difference_chapters_never_publish_material_ids():
    """Raw model text published in the fallback paths is scrubbed too."""
    quote = MaterialSpan(material_id="m001", quote="培训话术正文片段", character_start=0,
                         character_end=8, ambiguous=False)
    direction = InvestigationDirection(
        direction_id="d1", title="与 m0178 配置相关", description="材料显示 m0179 被引用。",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=("与 m0178 的关联",), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    )
    response, _stage = render_stage_report(
        _envelope(), _materials(), (direction,), (), (), narrative=None)

    fragment = next(s for s in response.sections if s.heading.startswith("材料自主发现"))
    assert "m0178" not in fragment.content and "m0179" not in fragment.content


def test_difference_chapter_reason_is_scrubbed_of_material_ids():
    """The comparison reason is model text and carried "m0334" into the report."""
    from httpserver.services.forensic_report.models import DirectionComparison

    quote = MaterialSpan(material_id="m001", quote="培训话术正文片段", character_start=0,
                         character_end=8, ambiguous=False)
    baseline_direction = InvestigationDirection(
        direction_id="d0001", title="Prefetch 哈希差异", description="基线描述",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    )
    comparison = DirectionComparison(
        baseline_direction_id="d0001", status="revised",
        reason="材料实际显示 m0330 为 0x37d25f9a、m0333 为 0x37d25f9e，基线描述需修正。",
        supporting_refs=(quote,), counter_refs=(), missing_information=(),
        case_context_quote="",
    )
    baseline = type("B", (), {
        "directions": (baseline_direction,), "report_id": "r1",
        "report_sha256": "0" * 64, "priorities": {}})()

    class _Guided(_Env):
        def __init__(self):
            super().__init__("case_guided")
            self.baseline = baseline

    response, _stage = render_stage_report(
        _Guided(), _materials(),
        (baseline_direction,), (comparison,), ())

    diff = next(s for s in response.sections if s.heading == "与首次研判的差异")
    assert "m0330" not in diff.content and "m0333" not in diff.content
    assert "0x37d25f9a" in diff.content


def test_prompt_projection_includes_the_material_path():
    """83/911 materials carry case semantics ONLY in the path.

    Default.xml contains <Hosts>192.168.10.30:4782;</Hosts> and nothing that
    names Quasar; the directory 控制端/Quasar v1.4.1/ is the only place the
    case object exists. Without the path the model can only say "a config".
    """
    from httpserver.services.forensic_report.generation_sources import material
    from httpserver.services.forensic_report.generation_stages import prompt_material

    source = material(
        "m001",
        "file:/Users/admin/Desktop/控制端/Quasar v1.4.1/Profiles/Default.xml",
        kind="text", status="ready", text="<Hosts>192.168.10.30:4782;</Hosts>")
    row = prompt_material(source)
    assert row["path"] == "/Users/admin/Desktop/控制端/Quasar v1.4.1/Profiles/Default.xml"
    # The text itself never mentions the program: the path has to be there.
    assert "Quasar" not in row["text"]


def test_prompt_path_is_bounded_but_keeps_the_naming_tail():
    from httpserver.services.forensic_report.generation_sources import material
    from httpserver.services.forensic_report.generation_stages import (
        _PROMPT_PATH_MAX, prompt_material,
    )

    long_key = ("file:/Users/admin/AppData/Local/Packages/"
                + "MICROSOFT.MICROSOFTOFFICEHUB_19.2505.46065.0_X64__8WEKYB3D8BBWE/"
                + "x" * 300 + "/Retail/settings.dat")
    row = prompt_material(material("m002", long_key, kind="text", status="ready", text="t"))
    assert len(row["path"]) <= _PROMPT_PATH_MAX + 1
    # The tail (which names the object) survives; the head is boilerplate.
    assert row["path"].endswith("settings.dat")
    assert row["path"].startswith("…")


def test_discovery_prompt_uses_path_but_forbids_path_only_conclusions():
    from httpserver.services.forensic_report.generation_prompts import (
        STAGE_DISCOVERY_AGGREGATE_V1,
    )

    prompt = STAGE_DISCOVERY_AGGREGATE_V1
    assert "path 字段是材料的完整存放位置" in prompt
    # Naming by path is required...
    assert "必须指出" in prompt
    # ...but a directory name alone may never become a conclusion.
    assert "path 只是位置，不是事实" in prompt
    assert "Crack" in prompt and "凭据泄露" in prompt


def test_chapter_writer_receives_the_directory_not_just_the_filename():
    """A bare file name cannot say what an object is; the writer needs where."""
    from httpserver.services.forensic_report.generation_stages import _chapter_write_row
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan

    quote = MaterialSpan(material_id="m001", quote="培训话术正文片段",
                         character_start=0, character_end=8, ambiguous=False)
    direction = InvestigationDirection(
        direction_id="d1", title="话术材料", description="材料包含话术培训文档。",
        finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material")
    row = _chapter_write_row(
        direction, {"m001": "Default.xml"},
        {"m001": "/Users/admin/Desktop/控制端/Quasar v1.4.1/Profiles/Default.xml"})

    assert row["supporting"][0]["file"] == "Default.xml"
    assert row["supporting"][0]["where"].endswith("控制端/Quasar v1.4.1/Profiles/Default.xml")


def test_thread_names_must_name_an_object_and_a_behaviour():
    """A name is rejected unless it names both a case object and what happened.

    "服务控制与驱动加载API" only names a mechanism; "系统进程执行基线" only
    names a category. Both read as inventory rows, so they are rebuilt from the
    thread's own concrete subjects.
    """
    from httpserver.services.forensic_report.generation_stages import (
        _thread_name_is_readable,
    )

    readable = (
        "Quasar 控制端配置与 C2 驻留",
        "PrivaZer 计划任务提权清理",
        "Edge关闭SmartScreen与崩溃",
        "WMIADAP相关执行",
        "RUNDLL32调用控制面板组件",
        "内存转储无可读字符串",
    )
    for name in readable:
        assert _thread_name_is_readable(name), name

    unreadable = (
        "服务控制与驱动加载API",
        "系统进程执行基线",
        "材料观察",
        "重点可疑对象",
        "可疑对象",
    )
    for name in unreadable:
        assert not _thread_name_is_readable(name), name


def test_unreadable_thread_name_is_rebuilt_from_its_own_subjects():
    """The fallback names a real subject from the thread, never an empty label."""
    from httpserver.services.forensic_report.generation_stages import (
        _clean_thread_fields,
    )

    row = {
        "theme_name": "系统进程执行",
        "direction_titles": ("PrivaZer 清理后 PowerShell 执行",),
        "quotes": ("PrivaZer 清理痕迹与 PowerShell 调用相邻",),
    }
    cleaned = _clean_thread_fields(
        "系统进程执行基线",
        "该线索聚合了若干系统进程的执行记录，需结合其他日志核实其来源与目的。",
        [], row)
    assert cleaned is not None
    name, _contribution, _facts = cleaned
    assert "PrivaZer" in name
    assert name != "系统进程执行基线"


def test_indication_prompt_groups_by_case_object_not_material_type():
    """Theme grouping decides what the thread table can say.

    Grouping by material type ("all Prefetch") is what buried Quasar's two
    directions inside a 103-direction PrivaZer install bundle.
    """
    from httpserver.services.forensic_report.generation_prompts import (
        STAGE_THEME_LOCAL_SYSTEM_V1, STAGE_THEME_MERGE_SYSTEM_V1,
    )

    local = STAGE_THEME_LOCAL_SYSTEM_V1
    assert "案件对象" in local
    assert "where" in local            # the path projection reaches induction
    assert "不要按材料类型归" in local
    # The old "8 to 25 per theme" floor forced distinct objects together.
    assert "3 到 20 个方向" in local

    merge = STAGE_THEME_MERGE_SYSTEM_V1
    assert "30" in merge
    assert "PrivaZer 计划任务" in merge


def test_low_value_evidence_is_recognised_and_ranked_last():
    """Bundled artifacts (license/icon/manifest) must not outrank a case object."""
    from httpserver.services.forensic_report.generation_stages import (
        _is_low_value_evidence,
    )

    for key in ("file:/x/PrivaZer/LICENSE", "file:/x/Be.HexEditor_license.txt",
                "file:/x/Logo150.scale-100.png", "file:/x/AppxManifest.xml",
                "file:/x/AppxSignature.p7x"):
        assert _is_low_value_evidence(key), key
    for key in ("file:/x/Default.xml", "file:/x/foxmail.log",
                "file:/x/PrivaZer.ini", "file:/x/passwords.txt"):
        assert not _is_low_value_evidence(key), key


def test_threads_backed_only_by_bundled_artifacts_sort_last():
    from httpserver.services.forensic_report.generation_sources import material
    from httpserver.services.forensic_report.generation_stages import (
        _ChapterNarrative, _prepare_theme_rows,
    )
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan

    case_mat = material("m001", "file:/Users/admin/Desktop/控制端/Quasar/Default.xml",
                        kind="text", status="ready", text="<Hosts>192.168.10.30:4782;</Hosts>")
    license_mat = material("m002", "file:/Program Files/PrivaZer/LICENSE",
                           kind="text", status="ready", text="MIT License")
    q1 = MaterialSpan(material_id="m001", quote="<Hosts>192.168.10.30:4782;</Hosts>",
                      character_start=0, character_end=29, ambiguous=False)
    q2 = MaterialSpan(material_id="m002", quote="MIT License", character_start=0,
                      character_end=11, ambiguous=False)
    case_dir = InvestigationDirection(
        direction_id="d1", title="控制端配置与回连参数", description="配置含回连地址。",
        finding_kind="observation", supporting_refs=(q1,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material")
    lic_dir = InvestigationDirection(
        direction_id="d2", title="许可证文件", description="安装包自带许可证。",
        finding_kind="observation", supporting_refs=(q2,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material")
    narrative = _ChapterNarrative(
        [{"heading": "控制端配置", "content": "正文。" * 30, "summary": "",
          "direction_ids": ("d1", "d2")}],
        [{"name": "许可证与随附文件", "directions": (lic_dir,)},
         {"name": "Quasar 控制端配置", "directions": (case_dir,)}])

    rows = _prepare_theme_rows(_envelope(), narrative.themes,
                              (case_mat, license_mat), (case_dir, lic_dir), narrative)
    # The case-object thread leads even though the license thread is bunded.
    assert rows[0]["low_value"] is False
    assert rows[-1]["low_value"] is True


def test_oversized_theme_splits_along_case_objects_not_counts():
    """A 172-direction install bundle must not swallow a distinct case object."""
    from httpserver.services.forensic_report.generation_sources import material
    from httpserver.services.forensic_report.generation_stages import (
        _ChapterNarrative, _prepare_theme_rows, _split_theme_by_object,
    )
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan

    mats = (
        material("m001", "file:/Users/admin/Desktop/控制端/Quasar v1.4.1/Profiles/Default.xml",
                 kind="text", status="ready", text="<Hosts>192.168.10.30:4782;</Hosts>"),
        material("m002", "file:/Program Files (x86)/PrivaZer/PrivaMenu11.dll",
                 kind="text", status="ready", text="PrivaZer menu"),
        material("m003", "file:/Program Files (x86)/PrivaZer/AppxManifest.xml",
                 kind="text", status="ready", text="manifest"),
    )

    def direction(did, mid, title):
        quote = MaterialSpan(material_id=mid, quote=mats[int(mid[1:]) - 1].text[:8],
                             character_start=0, character_end=8, ambiguous=False)
        return InvestigationDirection(
            direction_id=did, title=title, description=title,
            finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
            missing_information=(), alternative_explanations=(),
            baseline_direction_ids=(), case_context_quote="", origin="material")

    dirs = (direction("d1", "m001", "Quasar 控制端配置"),
            direction("d2", "m002", "PrivaZer 菜单组件"),
            direction("d3", "m003", "PrivaZer 清单"))
    paths = {m.material_id: m.evidence_key for m in mats}

    # With the default 3-direction floor each object is the tail; the split is
    # exercised at limit=2 with the floor lowered via the module constant.
    import httpserver.services.forensic_report.generation_stages as stages
    original = stages._THREAD_OBJECT_MIN_DIRECTIONS
    stages._THREAD_OBJECT_MIN_DIRECTIONS = 1
    try:
        parts = _split_theme_by_object(
            {"name": "PrivaZer 安装包", "directions": dirs},
            {d.direction_id: d for d in dirs}, paths, limit=2)
    finally:
        stages._THREAD_OBJECT_MIN_DIRECTIONS = original

    assert parts is not None
    labels = [label for label, _rows in parts]
    # The Quasar directory becomes its own part instead of being absorbed.
    assert any("Quasar" in label for label in labels), labels
    assert any("PrivaZer" in label for label in labels), labels
    # Exhaustive: every direction survives the split exactly once.
    split_ids = [d.direction_id for _label, rows in parts for d in rows]
    assert sorted(split_ids) == ["d1", "d2", "d3"]


def test_object_directory_skips_structural_folder_names():
    from httpserver.services.forensic_report.generation_stages import _object_directory

    assert _object_directory(
        "/Users/admin/Desktop/控制端/Quasar v1.4.1/Profiles/Default.xml") == "Quasar v1.4.1"
    assert _object_directory(
        "/Program Files (x86)/PrivaZer/PrivaMenu11.dll") == "PrivaZer"
    # Hitting only structural names falls back to the parent, never to "Profiles".
    assert _object_directory("/x/SomeTool/bin/data/file.txt") == "SomeTool"


def test_thread_key_facts_prefer_case_values_over_licence_boilerplate():
    """A Quasar thread's facts must be its C2 and config, not MIT/Apache text."""
    from httpserver.services.forensic_report.generation_stages import (
        _extract_thread_facts,
    )

    facts = _extract_thread_facts([
        "Copyright (c) 2010-2018 George Mamaladze",
        "The MIT License",
        "<Hosts>192.168.10.30:4782;</Hosts>",
        "<HideFile>True</HideFile>",
    ])
    assert any("192.168.10.30:4782" in fact for fact in facts)
    assert any("HideFile" in fact for fact in facts)
    assert not any("MIT" in fact or "Copyright" in fact for fact in facts)


def test_long_thread_names_are_trimmed_without_cutting_words():
    """A raw slice produced "RuntimeBroker 多实例高频执" and "…数据库缓"."""
    from httpserver.services.forensic_report.generation_stages import (
        _THREAD_NAME_MAX, _trim_thread_label,
    )

    for raw in ("RuntimeBroker 多实例高频执行记录汇总",
                "Windows Store 商店数据库缓存与日志"):
        trimmed = _trim_thread_label(raw)
        assert len(trimmed) <= _THREAD_NAME_MAX
        # Never ends on a half-cut Latin word or a dangling connector.
        assert not trimmed.endswith(("与", "和", "及", "的")), trimmed
        # A 1-2 char Latin tail ("…JS 错误遥测与崩") is a cut word.
        tail = trimmed.split()[-1] if trimmed.split() else trimmed
        assert not (tail.isascii() and len(tail) <= 2 and len(trimmed) > len(tail)), trimmed


def test_duplicate_thread_names_fold_members_together():
    """Induction may keep two same-subject groups apart (25-direction merge
    cap); after relabeling they read as one thread, so the table must fold
    them instead of showing the same case thread twice."""
    from httpserver.services.forensic_report.generation_stages import (
        _merge_duplicate_threads,
    )

    rows = [
        {"name": "CodeIntegrity 与 DPAPI 重复记录", "members": ("a", "b"),
         "direction_titles": ("重复验证记录",), "quotes": ("引文甲",),
         "reference_count": 12, "material_count": 4,
         "chapter_numbers": (4,), "contribution": "较完整的说明。", "facts": ()},
        {"name": "CodeIntegrity 与 DPAPI 重复记录", "members": ("c",),
         "direction_titles": ("重复密文记录",), "quotes": ("引文乙",),
         "reference_count": 5, "material_count": 2,
         "chapter_numbers": (10,), "contribution": "", "facts": ()},
        {"name": "内存转储缺口", "members": ("d",),
         "direction_titles": ("内存转储",), "quotes": ("引文丙",),
         "reference_count": 3, "material_count": 1,
         "chapter_numbers": (9,), "contribution": "独立线索。", "facts": ()},
    ]
    _merge_duplicate_threads(rows)

    assert len(rows) == 2
    folded = rows[0]
    assert folded["direction_titles"] == ("重复验证记录", "重复密文记录")
    assert folded["reference_count"] == 17
    assert folded["chapter_numbers"] == (4, 10)
    # The stronger contribution survives the fold.
    assert folded["contribution"] == "较完整的说明。"
    assert rows[1]["name"] == "内存转储缺口"


def test_thread_facts_must_come_from_thread_quotes():
    """Anchoring: a key fact that appears in no thread quote is dropped."""
    from httpserver.services.forensic_report.generation_stages import (
        _clean_thread_fields,
    )

    row = {"quotes": ("配置指向 192.168.10.30:4782 并写入启动项",)}
    cleaned = _clean_thread_fields(
        "Quasar 远控驻留",
        "客户端配置指向回连地址并写入启动项，服务端同端口监听，两端互证；外联未证实。",
        ["192.168.10.30:4782", "HideFile=True"],  # HideFile is NOT in the quote
        row)
    assert cleaned is not None
    name, contribution, facts = cleaned
    assert facts == ("192.168.10.30:4782",)


@pytest.mark.asyncio
async def test_thread_relabel_maps_by_index_and_tolerates_partial_answers():
    """Answers map by index; a missing/invalid entry falls back for that thread only."""
    from httpserver.services.forensic_report.generation_stages import (
        compose_evidence_threads,
    )

    quote1 = MaterialSpan(material_id="m001", quote="培训话术正文片段", character_start=0,
                          character_end=8, ambiguous=False)
    quote2 = MaterialSpan(material_id="m002", quote="转账记录摘录", character_start=0,
                          character_end=6, ambiguous=False)
    d1 = InvestigationDirection(
        direction_id="d1", title="话术培训材料", description="材料包含话术培训文档。",
        finding_kind="observation", supporting_refs=(quote1,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material")
    d2 = InvestigationDirection(
        direction_id="d2", title="账目摘录", description="材料包含转账记录。",
        finding_kind="observation", supporting_refs=(quote2,), counter_refs=(),
        missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material")
    rows = _themed([
        {"heading": "话术培训材料", "content": "材料包含话术培训文档。" * 20,
         "summary": "", "direction_ids": ("d1",)},
        {"heading": "账目摘录核对", "content": "账目文件显示转账记录摘录。" * 20,
         "summary": "", "direction_ids": ("d2",)},
    ], (d1, d2))

    class RelabelModel:
        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            # Thread 1 answers with an index; thread 2 is missing entirely.
            return {"content": json.dumps({"threads": [
                {"index": 2, "name": "话术文档与账目摘录核对",
                 "contribution": "话术文档与转账摘录共同支撑话术演练场景的判断，"
                                 "但仍缺原始来源，无法关联具体案件行为。",
                 "key_facts": ["转账记录摘录"]},
            ]}, ensure_ascii=False)}

    table = await compose_evidence_threads(
        _envelope(), [{"name": "话术培训材料", "directions": (d1,)},
                      {"name": "账目摘录", "directions": (d2,)}],
        _materials(), (d1, d2), rows, llm=RelabelModel())

    assert table.covered_directions == 2
    assert table.total_directions == 2
    # The answer carried index 2, so thread 2 got the relabel and thread 1
    # (missing from the answer) fell back deterministically.
    assert table.rows[1].name == "话术文档与账目摘录核对"
    assert table.rows[0].contribution.startswith("该线索聚合了")
    assert table.rows[1].key_facts == ("转账记录摘录",)
    # Both threads still carry their chapter anchors.
    assert table.rows[0].chapter_numbers == (2,)
    assert table.rows[1].chapter_numbers == (3,)


def test_recall_table_absent_in_fragment_fallback():
    """Without chapters nothing was recalled, so there is no table to show."""
    response, _stage = render_stage_report(
        _envelope(), _materials(), _directions(), (), (), None)
    assert response.sections[0].recall_table is None
    assert response.sections[0].heading == "案件总述与证据召回"


def test_recall_table_uses_frozen_classification_labels():
    from httpserver.services.forensic_report.models import (
        ReportClassifications, ReportEvidenceClassification,
    )
    directions = _directions()
    rows = _narrative_rows(_materials(), directions)
    classifications = ReportClassifications(items=(
        ReportEvidenceClassification(
            evidence_key="file:/case/话术/7要素.docx", material_type="document",
            topics=("communications",), priority="P1", reason="涉及话术",
            basis_type="neutral_material", source_hash="a" * 64,
        ),
    ))
    response, _stage = render_stage_report(
        _envelope(), _materials(), directions, (), (), rows,
        classifications=classifications)

    table = _recall_appendix(response).recall_table
    row = next(r for r in table.rows if r.evidence_name == "7要素.docx")
    assert row.material_type == "document"
    assert row.priority == "P1"
    assert row.topics == ("communications",)


def test_recall_table_is_bounded_and_says_what_it_omits():
    """A 900-material scope must not render a 900-row table."""
    from httpserver.services.forensic_report import generation_stages as stages
    from httpserver.services.forensic_report.generation_sources import material
    from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan

    many = tuple(
        material(f"m{i:03d}", f"file:/case/材料{i}.txt", kind="text",
                 status="ready", text="材料正文" * 10)
        for i in range(1, stages._RECALL_TABLE_LIMIT + 15)
    )
    direction = InvestigationDirection(
        direction_id="d1", title="多材料观察", description="大量材料共同支持同一观察。",
        finding_kind="observation",
        supporting_refs=tuple(
            MaterialSpan(material_id=m.material_id, quote="材料正文",
                         character_start=0, character_end=4, ambiguous=False)
            for m in many),
        counter_refs=(), missing_information=(), alternative_explanations=(),
        baseline_direction_ids=(), case_context_quote="", origin="material",
    )
    rows = [{"heading": "多材料观察", "content": "材料正文重复出现。" * 20,
             "summary": "", "direction_ids": ("d1",)}]
    response, _stage = render_stage_report(
        _envelope(), many, (direction,), (), (), rows)

    table = _recall_appendix(response).recall_table
    assert len(table.rows) == stages._RECALL_TABLE_LIMIT
    assert table.recalled_materials == len(many)
    assert any("其余" in note for note in table.notes)


def test_overview_fallback_states_counts_without_inventing_facts():
    from httpserver.services.forensic_report.generation_stages import (
        _deterministic_overview, _recall_stats,
    )

    directions = _directions()
    stats = _recall_stats(_materials(), _narrative_rows(_materials(), directions), directions)
    overview = _deterministic_overview(_envelope(), stats, directions)

    assert "2 份入报材料" in overview
    assert "1 条有材料支撑的观察" in overview
    assert "未使用案情描述" in overview


@pytest.mark.asyncio
async def test_overview_uses_the_model_and_falls_back_on_failure():
    from httpserver.services.forensic_report.generation_stages import compose_case_overview

    directions = _directions()
    rows = _narrative_rows(_materials(), directions)

    class OverviewModel:
        def __init__(self, answer=None, error=None):
            self.answer, self.error = answer, error

        async def chat_completion(self, system, user, **kwargs):
            if self.error:
                raise self.error
            return {"content": self.answer}

    good = OverviewModel(answer="本案材料的核心是话术培训文档，需要核对原始来源。"
                               + "材料同时显示该文档被多次打开，其流转路径尚未确定。" * 4)
    assert "核心是话术培训文档" in await compose_case_overview(
        _envelope(), _materials(), directions, rows, llm=good)

    broken = OverviewModel(error=RuntimeError("provider down"))
    fallback = await compose_case_overview(
        _envelope(), _materials(), directions, rows, llm=broken)
    assert "2 份入报材料" in fallback


@pytest.mark.asyncio
async def test_overview_rejects_ids_and_short_answers():
    from httpserver.services.forensic_report.generation_stages import compose_case_overview

    directions = _directions()
    rows = _narrative_rows(_materials(), directions)

    class ShortModel:
        async def chat_completion(self, system, user, **kwargs):
            return {"content": "材料见 m0001。"}

    overview = await compose_case_overview(
        _envelope(), _materials(), directions, rows, llm=ShortModel())
    # Unusable answer falls back rather than publishing an id to the reader.
    assert "m0001" not in overview


def test_json_wrapped_chapter_answers_are_unwrapped():
    """A model answers the summary prompt with JSON; the reader must not see it.

    A live v5 run published `{"overview":"..."}` verbatim as the first
    chapter's body, because only three key names were unwrapped.
    """
    from httpserver.services.forensic_report.generation_stages import _plain_models_text

    assert _plain_models_text('{"overview":"全案总述正文。"}') == "全案总述正文。"
    assert _plain_models_text('{"summary":"小结句。"}') == "小结句。"
    assert _plain_models_text('{"result":"结果句。"}') == "结果句。"
    # A single unrecognised string value is still the answer.
    assert _plain_models_text('{"whatever":"唯一字符串值。"}') == "唯一字符串值。"
    # No JSON: unchanged.
    assert _plain_models_text("裸文本答案。") == "裸文本答案。"


def test_recall_summary_contradicting_the_table_is_rejected():
    """Non-recalled materials must not be described as recalled-but-unused."""
    from httpserver.services.forensic_report.generation_stages import (
        _RECALL_SUMMARY_CONTRADICTION_RE,
    )

    wrong = "388 份材料支持结论；其余可用材料虽已召回，却未被任何章节引用。"
    assert _RECALL_SUMMARY_CONTRADICTION_RE.search(wrong)
    right = "388 份材料进入正文，共 780 处引用；其余 407 份可用材料没有进入正文。"
    assert not _RECALL_SUMMARY_CONTRADICTION_RE.search(right)


@pytest.mark.asyncio
async def test_recall_summary_falls_back_when_the_model_inverts_coverage():
    from httpserver.services.forensic_report.generation_stages import (
        _recall_stats, compose_recall_summary,
    )

    directions = _directions()
    stats = _recall_stats(_materials(), _narrative_rows(_materials(), directions), directions)

    class InvertingModel:
        async def chat_completion(self, system, user, **kwargs):
            return {"content": "388 份材料支持结论，其余可用材料虽已召回，却未被任何章节引用。"}

    summary = await compose_recall_summary(stats, "总述", llm=InvertingModel())
    assert "虽已召回" not in summary
    assert "1 处引用" in summary or "被正文实际引用" in summary


@pytest.mark.asyncio
async def test_chapter_summary_rejects_prompt_internal_ids():
    from httpserver.services.forensic_report.generation_stages import _clean_chapter_summary

    assert _clean_chapter_summary("详见 m0012 与 m0013。") == ""
    assert _clean_chapter_summary("本章材料不足。") == ""
    # A stock connector is stripped, not fatal.
    cleaned = _clean_chapter_summary(
        "综上所述，本章材料共同显示远控配置已写入，但回连是否实际发生仍需网络日志佐证。")
    assert cleaned.startswith("本章材料共同显示")
    assert "综上所述" not in cleaned


# ---------------------------------------------------------------------------
# Report pipeline concurrency.
#
# The report stage was fully serial: 365 LLM round trips on a PC.E01 run, and
# wall time tracked call count almost exactly. Batches within a stage are
# independent, so they fan out to the shared LLM budget
# (LLM_MAX_CONCURRENCY, already used by every analysis stage).
# ---------------------------------------------------------------------------


def test_report_concurrency_follows_shared_llm_budget():
    from types import SimpleNamespace
    from httpserver.services.forensic_report.generation_stages import (
        DEFAULT_REPORT_CONCURRENCY, report_concurrency,
    )

    # Lower budgets are honoured; a higher one is capped at the report default.
    # The previous contract passed 32 straight through, and a full generation at
    # that sustained rate hit a 33-second 429 window after ~490 calls, losing the
    # chapter-writing phase.
    assert report_concurrency(SimpleNamespace(llm_max_concurrency=4)) == 4
    assert report_concurrency(SimpleNamespace(llm_max_concurrency=32)) == DEFAULT_REPORT_CONCURRENCY
    # Absent or malformed settings fall back to the pipeline default.
    assert report_concurrency(SimpleNamespace()) == DEFAULT_REPORT_CONCURRENCY
    assert report_concurrency(None) == DEFAULT_REPORT_CONCURRENCY
    assert report_concurrency(SimpleNamespace(llm_max_concurrency="bad")) == DEFAULT_REPORT_CONCURRENCY
    # Never below one (a zero/negative budget would deadlock the semaphore).
    assert report_concurrency(SimpleNamespace(llm_max_concurrency=0)) == 1
    # Capped so a large env value cannot flood the provider.
    assert report_concurrency(SimpleNamespace(llm_max_concurrency=1000)) == DEFAULT_REPORT_CONCURRENCY


@pytest.mark.asyncio
async def test_gather_bounded_respects_limit_and_keeps_order():
    import asyncio
    from httpserver.services.forensic_report.generation_stages import _gather_bounded

    active = 0
    peak = 0

    async def job(value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value

    results = await _gather_bounded([job(i) for i in range(20)], 4)

    assert results == list(range(20))
    assert peak <= 4, f"limit exceeded: {peak} concurrent"
    assert peak > 1, "jobs never overlapped; fan-out did not happen"


@pytest.mark.asyncio
async def test_gather_bounded_isolates_a_failing_job():
    from httpserver.services.forensic_report.generation_stages import _gather_bounded

    async def ok():
        return "ok"

    async def boom():
        raise ValueError("bad batch")

    results = await _gather_bounded([ok(), boom(), ok()], 3)

    assert results[0] == "ok" and results[2] == "ok"
    assert isinstance(results[1], ValueError)


@pytest.mark.asyncio
async def test_discovery_batches_run_concurrently_and_merge_all_directions():
    """Discovery must fan out, and every batch's directions must survive."""
    import asyncio
    from httpserver.services.forensic_report.generation_stages import (
        BATCH_SIZE, discover_directions,
    )

    materials = tuple(
        material(f"m{i:03}", f"file:/case/f{i}.txt", kind="text", status="ready",
                 text=f"文件{i}的正文片段，包含足够长度用于引用校验。")
        for i in range(1, BATCH_SIZE * 3 + 1))

    active = 0
    peak = 0

    class LLM:
        async def chat_completion(self, system, user, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            body = json.loads(user)
            first = body["materials"][0]
            quote = first["text"][:12]
            return {"content": json.dumps({"directions": [{
                "title": f"观察{first['material_id']}",
                "description": "该材料包含可核查的记录。",
                "finding_kind": "observation",
                "supporting_refs": [{"material_id": first["material_id"], "quote": quote}],
            }]}, ensure_ascii=False), "model": "synthetic"}

    directions, warnings = await discover_directions(
        _envelope(), materials, LLM(), concurrency=4)

    assert peak > 1, "discovery ran serially"
    assert peak <= 4
    assert len(directions) >= 3, f"lost batch results: {len(directions)}"
    assert not warnings


@pytest.mark.asyncio
async def test_discovery_reports_each_rejected_batch_separately():
    """A rejected batch is recorded; the others still contribute."""
    from httpserver.services.forensic_report.generation_stages import (
        BATCH_SIZE, discover_directions,
    )

    materials = tuple(
        material(f"m{i:03}", f"file:/case/f{i}.txt", kind="text", status="ready",
                 text=f"文件{i}的正文片段，包含足够长度用于引用校验。")
        for i in range(1, BATCH_SIZE * 2 + 1))

    calls = {"n": 0}

    class LLM:
        async def chat_completion(self, system, user, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                return {"content": "not json", "model": "synthetic"}
            body = json.loads(user)
            first = body["materials"][0]
            return {"content": json.dumps({"directions": [{
                "title": f"观察{first['material_id']}",
                "description": "该材料包含可核查的记录。",
                "finding_kind": "observation",
                "supporting_refs": [{"material_id": first["material_id"],
                                     "quote": first["text"][:12]}],
            }]}, ensure_ascii=False), "model": "synthetic"}

    directions, warnings = await discover_directions(
        _envelope(), materials, LLM(), concurrency=1)

    assert len(directions) == 1, "the good batch must still contribute"
    assert len(warnings) == 1 and warnings[0].startswith("DIRECTION_BATCH_REJECTED_")


def test_pack_batches_respects_both_count_and_prompt_budget():
    """Batching must bound the serialized request, not just the item count.

    Materials vary ~20x in prompt size, so packing 10 per batch produced
    requests from 2.4k to 44k characters; 24 of 52 exceeded the 26k budget and
    were dropped before any LLM call, losing nearly half the evidence.
    """
    from httpserver.services.forensic_report.generation_stages import (
        REQUEST_CHAR_LIMIT, _pack_batches, prompt_material,
    )

    big = [material(f"m{i:03}", f"file:/case/big{i}.txt", kind="text", status="ready",
                    text="大材料正文" * 600) for i in range(12)]
    small = [material(f"m{100+i:03}", f"file:/case/s{i}.txt", kind="text", status="ready",
                      text="小") for i in range(12)]

    for label, group in (("large", big), ("small", small), ("mixed", big + small)):
        batches = _pack_batches(group)
        assert sum(len(b) for b in batches) == len(group), f"{label}: lost materials"
        for batch in batches:
            request = json.dumps({
                "analysis_mode": "evidence_only", "case_context": "",
                "materials": [prompt_material(m) for m in batch],
                "baseline_directions": [], "derived_summaries_not_evidence": [],
            }, ensure_ascii=False)
            assert len(request) <= REQUEST_CHAR_LIMIT, (
                f"{label}: batch of {len(batch)} is {len(request)} chars")


def test_pack_batches_caps_item_count_for_tiny_materials():
    """Size packing alone would put every tiny file in one request."""
    from httpserver.services.forensic_report.generation_stages import (
        BATCH_SIZE, _pack_batches,
    )

    tiny = [material(f"m{200+i:03}", f"file:/case/t{i}.txt", kind="text", status="ready",
                     text="x") for i in range(BATCH_SIZE * 2 + 3)]
    batches = _pack_batches(tiny)

    assert all(len(b) <= BATCH_SIZE for b in batches)
    assert len(batches) == 3
    assert sum(len(b) for b in batches) == len(tiny)


def test_pack_batches_keeps_an_oversized_material_alone():
    """One over-budget material gets its own batch, not silently dropped."""
    from httpserver.services.forensic_report.generation_stages import _pack_batches

    huge = material("m999", "file:/case/huge.txt", kind="text", status="ready",
                    text="超长正文" * 3000)
    batches = _pack_batches([huge])

    assert len(batches) == 1 and batches[0] == [huge]
