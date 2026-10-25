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
        _envelope(), _materials(), _directions(), (), model, theme_shaped=False)
    # Composition keeps the model's heading; skeleton retitling happens at render.
    assert sections and sections[0]["heading"] == "检材范围与构成"

    response, _stage = render_stage_report(_envelope(), _materials(), _directions(), (), (), sections)
    headings = [s.heading for s in response.sections]
    # The two generic skeleton headings are re-titled from their own content.
    assert headings == [
        "研判范围与方法", "本轮共读取两份冻结材料",
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
        _envelope(), _materials(), _directions(), (), model, theme_shaped=False) is None

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
        _envelope(), _materials(), _directions(), (), model, theme_shaped=False)
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
    assert scope.heading == "研判范围与方法"
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
        theme_shaped=False,
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

    assert report_concurrency(SimpleNamespace(llm_max_concurrency=32)) == 32
    # Absent or malformed settings fall back to the pipeline default.
    assert report_concurrency(SimpleNamespace()) == DEFAULT_REPORT_CONCURRENCY
    assert report_concurrency(None) == DEFAULT_REPORT_CONCURRENCY
    assert report_concurrency(SimpleNamespace(llm_max_concurrency="bad")) == DEFAULT_REPORT_CONCURRENCY
    # Never below one (a zero/negative budget would deadlock the semaphore).
    assert report_concurrency(SimpleNamespace(llm_max_concurrency=0)) == 1
    # Capped so a large env value cannot flood the provider.
    assert report_concurrency(SimpleNamespace(llm_max_concurrency=1000)) == 32


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
