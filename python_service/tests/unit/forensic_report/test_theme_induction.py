"""Theme induction (report shape v3, stages 1-2).

The model only returns direction_id membership; quotes and citations are
re-attached by the caller. These tests pin the recovery rules: a wrong model
answer must degrade to an addressable grouping, never to lost evidence.
"""

import json

import pytest

from httpserver.services.forensic_report import generation_stages as gs
from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan


def _material(index=1):
    from httpserver.services.forensic_report.generation_sources import material
    return material(f"m{index:03d}", f"file:/case/材料{index}.txt", kind="text",
                    status="ready", text="材料正文" * 20)


def _direction(index, title, *, refs=1, kind="observation"):
    quote = MaterialSpan(material_id=f"m{index:03d}", quote="片段" * 10,
                         character_start=0, character_end=20, ambiguous=False)
    return InvestigationDirection(
        direction_id=f"d{index:04d}",
        title=title,
        description=f"{title} 的材料观察描述。",
        finding_kind=kind,
        supporting_refs=tuple(quote for _ in range(refs)),
        counter_refs=(),
        missing_information=(),
        alternative_explanations=(),
        baseline_direction_ids=(),
        case_context_quote="",
        origin="material",
    )


def _directions(count):
    return tuple(_direction(i, f"观察项{i}") for i in range(1, count + 1))


class FakeLLM:
    """Answers induction calls from a scripted mapping keyed by call order."""

    def __init__(self, local_answers, merge_answer=None):
        self.local_answers = list(local_answers)
        self.merge_answer = merge_answer
        self.calls = []

    async def chat_completion(self, system, user, **kwargs):
        self.calls.append((system, user))
        if system == gs.STAGE_THEME_MERGE_SYSTEM_V1:
            return {"content": json.dumps(self.merge_answer, ensure_ascii=False)}
        answer = self.local_answers.pop(0)
        return {"content": json.dumps(answer, ensure_ascii=False)}


def _ids(*names):
    return list(names)


# ---------------------------------------------------------------------------
# Projection and chunking
# ---------------------------------------------------------------------------


def test_projection_keeps_only_identification_fields():
    """Induction needs to know what a direction is about, not its quotes."""
    row = gs._direction_projection(_direction(1, "SVCHOST 执行记录", refs=3))
    assert set(row) == {"id", "title", "kind", "description"}
    assert row["id"] == "d0001"
    assert "片段" not in json.dumps(row, ensure_ascii=False)


def test_chunking_respects_the_request_budget():
    directions = _directions(400)
    chunks = gs._chunk_directions(directions, limit=6000)
    assert len(chunks) > 1
    for chunk in chunks:
        # Measure exactly what induce_themes sends.
        payload = gs._theme_payload([gs._direction_projection(d) for d in chunk])
        # A single direction may overshoot on its own; otherwise stay in budget.
        assert len(payload) <= 6000 or len(chunk) == 1
    assert sum(len(c) for c in chunks) == len(directions)


def test_chunking_covers_every_direction_once():
    directions = _directions(50)
    chunks = gs._chunk_directions(directions, limit=2000)
    flat = [d.direction_id for chunk in chunks for d in chunk]
    assert flat == [d.direction_id for d in directions]


# ---------------------------------------------------------------------------
# Local theme parsing: recovery instead of rejection
# ---------------------------------------------------------------------------


def test_local_parse_accepts_a_complete_answer():
    themes, unassigned = gs._parse_local_themes(
        json.dumps({"themes": [{"name": "程序执行", "ids": _ids("d0001", "d0002")},
                               {"name": "日志观察", "ids": _ids("d0003")}],
                    "no_theme": []}, ensure_ascii=False),
        {"d0001", "d0002", "d0003"},
    )
    assert [t["name"] for t in themes] == ["程序执行", "日志观察"]
    assert unassigned == []


def test_local_parse_drops_invented_ids():
    """A hallucinated id must never reach the citation layer."""
    themes, unassigned = gs._parse_local_themes(
        json.dumps({"themes": [{"name": "程序执行", "ids": ["d0001", "d9999"]}],
                    "no_theme": []}, ensure_ascii=False),
        {"d0001", "d0002"},
    )
    assert themes[0]["ids"] == ["d0001"]
    assert unassigned == ["d0002"]


def test_local_parse_keeps_first_assignment_for_duplicates():
    themes, unassigned = gs._parse_local_themes(
        json.dumps({"themes": [{"name": "甲", "ids": ["d0001"]},
                               {"name": "乙", "ids": ["d0001", "d0002"]}],
                    "no_theme": []}, ensure_ascii=False),
        {"d0001", "d0002"},
    )
    assert themes[0]["ids"] == ["d0001"]
    assert themes[1]["ids"] == ["d0002"]
    assert unassigned == []


def test_local_parse_recovers_silently_dropped_ids():
    """Evidence the model forgot is still evidence: it becomes unassigned."""
    themes, unassigned = gs._parse_local_themes(
        json.dumps({"themes": [{"name": "程序执行", "ids": ["d0001"]}],
                    "no_theme": []}, ensure_ascii=False),
        {"d0001", "d0002", "d0003"},
    )
    assert [t["ids"] for t in themes] == [["d0001"]]
    assert unassigned == ["d0002", "d0003"]


def test_local_parse_honours_explicit_no_theme():
    themes, unassigned = gs._parse_local_themes(
        json.dumps({"themes": [{"name": "程序执行", "ids": ["d0001"]}],
                    "no_theme": ["d0002"]}, ensure_ascii=False),
        {"d0001", "d0002"},
    )
    assert unassigned == ["d0002"]


def test_local_parse_truncates_an_overlong_theme_name():
    themes, _ = gs._parse_local_themes(
        json.dumps({"themes": [{"name": "很长" * 30, "ids": ["d0001"]}],
                    "no_theme": []}, ensure_ascii=False),
        {"d0001"},
    )
    assert len(themes[0]["name"]) <= gs._THEME_NAME_MAX_CHARS


def test_local_parse_rejects_a_non_object_answer():
    with pytest.raises(ValueError, match="THEME_OUTPUT_INVALID"):
        gs._parse_local_themes("[]", {"d0001"})


# ---------------------------------------------------------------------------
# Merge parsing
# ---------------------------------------------------------------------------


def test_merge_parse_maps_local_themes_to_global_themes():
    local = [{"chunk": 1, "name": "程序执行", "ids": ["d1"]},
             {"chunk": 2, "name": "进程痕迹", "ids": ["d2"]}]
    themes, unmerged = gs._parse_merge_themes(
        json.dumps({"themes": [{"name": "程序执行痕迹",
                                "sources": [{"chunk": 1, "name": "程序执行"},
                                            {"chunk": 2, "name": "进程痕迹"}]}],
                    "no_theme": []}, ensure_ascii=False),
        local,
    )
    assert themes == [{"name": "程序执行痕迹", "locals": [0, 1]}]
    assert unmerged == []


def test_merge_parse_reports_local_themes_the_model_left_out():
    local = [{"chunk": 1, "name": "甲", "ids": ["d1"]},
             {"chunk": 1, "name": "乙", "ids": ["d2"]}]
    themes, unmerged = gs._parse_merge_themes(
        json.dumps({"themes": [{"name": "全局", "sources": [{"chunk": 1, "name": "甲"}]}],
                    "no_theme": []}, ensure_ascii=False),
        local,
    )
    assert themes == [{"name": "全局", "locals": [0]}]
    assert unmerged == [1]


def test_merge_parse_ignores_unknown_local_theme_names():
    local = [{"chunk": 1, "name": "甲", "ids": ["d1"]}]
    themes, unmerged = gs._parse_merge_themes(
        json.dumps({"themes": [{"name": "全局",
                                "sources": [{"chunk": 1, "name": "不存在"},
                                            {"chunk": 1, "name": "甲"}]}],
                    "no_theme": []}, ensure_ascii=False),
        local,
    )
    assert themes == [{"name": "全局", "locals": [0]}]
    assert unmerged == []


# ---------------------------------------------------------------------------
# End-to-end induction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_induction_covers_every_direction_exactly_once():
    directions = _directions(6)
    llm = FakeLLM([{"themes": [{"name": "程序执行", "ids": ["d0001", "d0002", "d0003"]},
                               {"name": "日志观察", "ids": ["d0004", "d0005", "d0006"]}],
                    "no_theme": []}])

    themes, warnings = await gs.induce_themes(directions, llm)

    seen = [d.direction_id for theme in themes for d in theme["directions"]]
    assert sorted(seen) == sorted(d.direction_id for d in directions)
    assert len(seen) == len(set(seen))
    assert warnings == ()


@pytest.mark.asyncio
async def test_induction_merges_local_themes_across_chunks(monkeypatch):
    """The merge stage is what stops one artifact becoming several themes."""
    directions = _directions(8)
    monkeypatch.setattr(gs, "_chunk_directions",
                        lambda ds, limit=gs.REQUEST_CHAR_LIMIT: [ds[:4], ds[4:]])
    llm = FakeLLM(
        [{"themes": [{"name": "SVCHOST 执行", "ids": ["d0001", "d0002"]},
                     {"name": "其他程序", "ids": ["d0003", "d0004"]}], "no_theme": []},
         {"themes": [{"name": "SVCHOST 痕迹", "ids": ["d0005", "d0006"]},
                     {"name": "日志观察", "ids": ["d0007", "d0008"]}], "no_theme": []}],
        merge_answer={"themes": [
            {"name": "SVCHOST 执行痕迹",
             "sources": [{"chunk": 1, "name": "SVCHOST 执行"},
                         {"chunk": 2, "name": "SVCHOST 痕迹"}]},
            {"name": "其他程序执行",
             "sources": [{"chunk": 1, "name": "其他程序"}]},
            {"name": "日志观察",
             "sources": [{"chunk": 2, "name": "日志观察"}]},
        ], "no_theme": []},
    )

    themes, _warnings = await gs.induce_themes(directions, llm)

    svchost = next(t for t in themes if t["name"] == "SVCHOST 执行痕迹")
    assert [d.direction_id for d in svchost["directions"]] == [
        "d0001", "d0002", "d0005", "d0006"]


@pytest.mark.asyncio
async def test_induction_keeps_evidence_when_the_merge_fails(monkeypatch):
    """A broken merge must not cost the report its whole grouping."""
    directions = _directions(4)
    monkeypatch.setattr(gs, "_chunk_directions",
                        lambda ds, limit=gs.REQUEST_CHAR_LIMIT: [ds[:2], ds[2:]])
    llm = FakeLLM(
        [{"themes": [{"name": "甲", "ids": ["d0001", "d0002"]}], "no_theme": []},
         {"themes": [{"name": "乙", "ids": ["d0003", "d0004"]}], "no_theme": []}],
        merge_answer={"themes": "not-a-list"},
    )

    themes, warnings = await gs.induce_themes(directions, llm)

    assert "THEME_MERGE_REJECTED" in warnings
    seen = [d.direction_id for theme in themes for d in theme["directions"]]
    assert sorted(seen) == ["d0001", "d0002", "d0003", "d0004"]


@pytest.mark.asyncio
async def test_induction_keeps_evidence_when_a_chunk_is_rejected(monkeypatch):
    directions = _directions(4)
    monkeypatch.setattr(gs, "_chunk_directions",
                        lambda ds, limit=gs.REQUEST_CHAR_LIMIT: [ds[:2], ds[2:]])

    class HalfBrokenLLM(FakeLLM):
        async def chat_completion(self, system, user, **kwargs):
            self.calls.append((system, user))
            if system == gs.STAGE_THEME_MERGE_SYSTEM_V1:
                return {"content": json.dumps(
                    {"themes": [{"name": "全部", "sources": [
                        {"chunk": 1, "name": "甲"}]}], "no_theme": []},
                    ensure_ascii=False)}
            if not self.local_answers:
                raise RuntimeError("provider down")
            return {"content": json.dumps(self.local_answers.pop(0), ensure_ascii=False)}

    llm = HalfBrokenLLM([{"themes": [{"name": "甲", "ids": ["d0001", "d0002"]}],
                          "no_theme": []}])

    themes, warnings = await gs.induce_themes(directions, llm)

    assert any(w.startswith("THEME_LOCAL_REJECTED") for w in warnings)
    seen = [d.direction_id for theme in themes for d in theme["directions"]]
    assert sorted(seen) == ["d0001", "d0002", "d0003", "d0004"]


@pytest.mark.asyncio
async def test_induction_falls_back_to_one_theme_when_nothing_groups():
    directions = _directions(3)

    class BrokenLLM:
        async def chat_completion(self, system, user, **kwargs):
            raise RuntimeError("provider down")

    themes, warnings = await gs.induce_themes(directions, BrokenLLM())

    assert len(themes) == 1
    assert len(themes[0]["directions"]) == 3
    assert any(w.startswith("THEME_LOCAL_REJECTED") for w in warnings)


@pytest.mark.asyncio
async def test_induction_returns_nothing_for_no_directions():
    themes, warnings = await gs.induce_themes((), FakeLLM([]))
    assert themes == ()
    assert warnings == ()


# ---------------------------------------------------------------------------
# Stage 3: theme writing
# ---------------------------------------------------------------------------


def _theme(name, directions):
    return {"name": name, "directions": tuple(directions)}


class WritingLLM:
    """Returns a section per write call; records the payloads it received."""

    def __init__(self, answer=None):
        self.answer = answer
        self.payloads = []

    async def chat_completion(self, system, user, **kwargs):
        self.payloads.append(json.loads(user))
        if self.answer is not None:
            return {"content": json.dumps(self.answer, ensure_ascii=False)}
        body = json.loads(user)
        names = [row["title"] for row in body["directions"]]
        return {"content": json.dumps({
            "heading": f"{body['theme']}的研判结论",
            "content": "本批材料显示：" + "、".join(names) + "。" + "该结论仅基于冻结解析片段。" * 20,
        }, ensure_ascii=False)}


@pytest.mark.asyncio
async def test_theme_writing_emits_one_section_per_theme():
    themes = (_theme("程序执行", _directions(2)),
              _theme("日志观察", (_direction(9, "日志观察"),)))
    llm = WritingLLM()

    sections, warnings = await gs.write_theme_chapters(
        themes, (_material(),), llm)

    assert len(sections) == 2
    assert warnings == ()
    # The theme name is the chapter label; the writer's own heading would
    # otherwise name the material type instead of the topic.
    assert sections[0]["heading"] == "程序执行"
    assert sections[1]["heading"] == "日志观察"


@pytest.mark.asyncio
async def test_theme_writing_splits_an_oversized_theme():
    """A theme too large for one request becomes several parts, same theme."""
    themes = (_theme("程序执行", _directions(8)),)

    parts = gs._split_theme_parts(
        [gs._theme_write_row(d, {}) for d in themes[0]["directions"]], limit=900)

    assert len(parts) > 1
    assert sum(len(p) for p in parts) == 8


@pytest.mark.asyncio
async def test_theme_writing_truncates_an_overlong_section():
    themes = (_theme("程序执行", _directions(1)),)
    llm = WritingLLM({"heading": "结论", "content": "很长的正文。" * 2000})

    sections, _ = await gs.write_theme_chapters(themes, (_material(),), llm)

    assert len(sections) == 1
    assert len(sections[0]["content"]) <= gs._THEME_CHAPTER_MAX_CHARS


@pytest.mark.asyncio
async def test_theme_writing_rejects_a_stub_section():
    themes = (_theme("程序执行", _directions(1)),)
    llm = WritingLLM({"heading": "结论", "content": "太短"})

    sections, warnings = await gs.write_theme_chapters(themes, (_material(),), llm)

    assert sections == []
    assert any(w.startswith("THEME_SECTION_REJECTED") for w in warnings)


@pytest.mark.asyncio
async def test_theme_writing_isolates_one_failed_theme():
    themes = (_theme("甲", _directions(1)), _theme("乙", (_direction(9, "乙观察"),)))

    class HalfBroken:
        def __init__(self):
            self.calls = 0

        async def chat_completion(self, system, user, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider down")
            return {"content": json.dumps({
                "heading": "乙的结论",
                "content": "乙主题的材料观察。" * 30}, ensure_ascii=False)}

    sections, warnings = await gs.write_theme_chapters(themes, (_material(),), HalfBroken())

    assert len(sections) == 1
    assert any(w.startswith("THEME_SECTION_REJECTED") for w in warnings)


@pytest.mark.asyncio
async def test_theme_sections_keep_the_directions_they_were_written_from():
    """Provenance is what makes citations exact instead of name-matched."""
    directions = _directions(2)
    themes = (_theme("程序执行", directions),)

    sections, _ = await gs.write_theme_chapters(
        themes, (_material(),), WritingLLM())

    assert sections[0]["direction_ids"] == tuple(d.direction_id for d in directions)


# ---------------------------------------------------------------------------
# Stage 4: opening summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_parses_findings_and_leads():
    sections = [{"heading": "甲", "content": "材料显示甲存在。后文略。",
                 "direction_ids": ("d0001",)}]

    class SummaryLLM:
        async def chat_completion(self, system, user, **kwargs):
            return {"content": json.dumps({
                "key_findings": ["发现一", "发现二"],
                "priority_leads": ["线索一"],
                "coverage_note": "覆盖 10 份材料",
            }, ensure_ascii=False)}

    result = await gs.write_report_summary(sections, SummaryLLM())

    assert result == (["发现一", "发现二"], ["线索一"], "覆盖 10 份材料")


@pytest.mark.asyncio
async def test_summary_returns_none_when_unusable():
    sections = [{"heading": "甲", "content": "材料显示甲存在。", "direction_ids": ()}]

    class Broken:
        async def chat_completion(self, system, user, **kwargs):
            return {"content": "not json"}

    assert await gs.write_report_summary(sections, Broken()) is None


@pytest.mark.asyncio
async def test_summary_returns_none_for_no_sections():
    assert await gs.write_report_summary([], WritingLLM()) is None


@pytest.mark.asyncio
async def test_summary_caps_findings_and_leads():
    sections = [{"heading": "甲", "content": "材料显示甲存在。", "direction_ids": ()}]

    class Verbose:
        async def chat_completion(self, system, user, **kwargs):
            return {"content": json.dumps({
                "key_findings": [f"发现{i}" for i in range(20)],
                "priority_leads": [f"线索{i}" for i in range(20)],
                "coverage_note": "",
            }, ensure_ascii=False)}

    findings, leads, _note = await gs.write_report_summary(sections, Verbose())

    assert len(findings) == gs._SUMMARY_FINDINGS_MAX
    assert len(leads) == gs._SUMMARY_LEADS_MAX


# ---------------------------------------------------------------------------
# Citations resolved from direction provenance
# ---------------------------------------------------------------------------


def test_theme_citations_resolve_from_direction_refs():
    materials = tuple(_material(i) for i in range(1, 4))
    directions = (_direction(1, "甲", refs=1),)
    by_id = {d.direction_id: d for d in directions}

    citations = gs._theme_citations(
        [d.direction_id for d in directions], by_id, materials)

    # _direction(1) quotes m001, which is the first material.
    assert citations == ("c001",)


def test_theme_citations_ignore_unknown_direction_ids():
    materials = (_material(1),)

    assert gs._theme_citations(["d9999"], {}, materials) == ()


def test_theme_citations_are_deduplicated_and_ordered():
    materials = tuple(_material(i) for i in range(1, 4))
    shared = MaterialSpan(material_id="m002", quote="共享片段", character_start=0,
                          character_end=4, ambiguous=False)
    first = _direction(1, "甲")
    second = _direction(2, "乙")
    first = first.model_copy(update={"supporting_refs": (shared,)})
    second = second.model_copy(update={"supporting_refs": (shared,)})
    by_id = {first.direction_id: first, second.direction_id: second}

    citations = gs._theme_citations(
        [first.direction_id, second.direction_id], by_id, materials)

    assert citations == ("c002",)




# ---------------------------------------------------------------------------
# Oversized themes are split deterministically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_theme_is_split_into_distinguishable_parts(monkeypatch):
    """A 218-direction theme produced four chapters with the same conclusion.

    The prompt asks for small themes, but one huge theme survived it. The
    split must happen in code, and each part must be distinguishable.
    """
    directions = _directions(60)
    llm = FakeLLM([{"themes": [{"name": "系统进程执行", "ids": [d.direction_id for d in directions]}],
                    "no_theme": []}])

    themes, warnings = await gs.induce_themes(directions, llm)

    assert len(themes) == 3  # 60 / 25 -> 25 + 25 + 10
    assert all(len(t["directions"]) <= gs._THEME_MAX_DIRECTIONS for t in themes)
    names = [t["name"] for t in themes]
    assert len(set(names)) == len(names)
    assert any(w.startswith("THEME_SPLIT") for w in warnings)
    # No direction is lost or duplicated by the split.
    seen = [d.direction_id for t in themes for d in t["directions"]]
    assert sorted(seen) == sorted(d.direction_id for d in directions)


@pytest.mark.asyncio
async def test_split_parts_use_the_theme_name_as_heading(monkeypatch):
    """Parts of one theme must not each invent a competing conclusion title.

    On PC.E01 a split theme produced four chapters whose independently written
    headings all said "…指向常规活动". The theme name is the stable label.
    """
    directions = _directions(4)
    themes = ({"name": "系统进程执行", "directions": directions},)
    # Force the split without needing a huge fixture.
    monkeypatch.setattr(gs, "_split_theme_parts",
                        lambda rows, limit=gs.REQUEST_CHAR_LIMIT: [[r] for r in rows])
    llm = WritingLLM()

    sections, _ = await gs.write_theme_chapters(
        themes, (_material(),), llm)

    assert len(sections) == 4
    headings = [s["heading"] for s in sections]
    assert all(h.startswith("系统进程执行") for h in headings)
    assert len(set(headings)) == 4


# ---------------------------------------------------------------------------
# Aggregated discovery (report shape v3, direction A)
#
# The v1 prompt asks for at most 4 directions per batch with a quote per
# direction, which the model answered as "one observation per file": 532
# directions for 767 materials, 258 quoting exactly one file. The aggregate
# prompt asks for grouping by subject with several files per finding.
# ---------------------------------------------------------------------------


def test_aggregate_prompt_asks_for_grouping_not_per_file_findings():
    from httpserver.services.forensic_report.generation_prompts import (
        STAGE_DISCOVERY_AGGREGATE_V1,
    )

    prompt = STAGE_DISCOVERY_AGGREGATE_V1
    assert "不得一份材料写一条观察" in prompt
    assert "合并为一条方向" in prompt
    # Multiple files may support one finding.
    assert "最多 6 条" in prompt


def test_shorten_heading_keeps_a_complete_bracket_suffix():
    """A split theme's "（2）" marker must survive shortening.

    The script-change rule cut at the ASCII→CJK boundary right before "（",
    so chapters rendered as "CHROME.EXE多实例Prefetc（2" and could not be told
    apart from their siblings.
    """
    for name in ("CHROME.EXE多实例Prefetch（2）", "系统宿主进程Prefetch执行（13）"):
        assert gs._shorten_heading(name, 24) == name


def test_shorten_heading_drops_an_incomplete_bracket_suffix():
    """When "（n）" does not fit, drop the whole marker instead of half of it."""
    result = gs._shorten_heading("很长很长很长很长很长很长很长很长（12）", 12)
    assert "（" not in result
    assert "12" not in result
