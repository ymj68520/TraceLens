"""Theme induction (report shape v3, stages 1-2).

The model only returns direction_id membership; quotes and citations are
re-attached by the caller. These tests pin the recovery rules: a wrong model
answer must degrade to an addressable grouping, never to lost evidence.
"""

import json

import pytest

from httpserver.services.forensic_report import generation_stages as gs
from httpserver.services.forensic_report.models import InvestigationDirection, MaterialSpan


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
