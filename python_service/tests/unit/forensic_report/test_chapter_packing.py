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
    assert sections[0]["heading"] == "甲"


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
