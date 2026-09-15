"""Tests for cluster map-reduce analysis and Graphiti ingestion (SPEC §6/§9)."""

import sqlite3

from httpserver.services.case_analysis.cluster_analyzer import (
    analyze_cluster_members,
    build_analysis_episodes,
    chunk_member_lines,
    lines_from_members,
)
from httpserver.services.case_analysis.schema import (
    ensure_cluster_analysis_schema,
    mark_analysis_ingested,
)


class _FakeLLM:
    """Records analyze_event_cluster calls; replies from a script of results."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    async def analyze_event_cluster(self, event_data, prompt=None):
        self.calls.append({"event_data": event_data, "prompt": prompt})
        if self.results:
            return self.results.pop(0)
        return {
            "analysis": {"summary": "s", "description": "d", "keywords": ["k"]},
            "model": "fake",
        }


def test_chunk_member_lines_respects_count_and_char_bounds():
    lines = [f"- line {i}: some evidence text" for i in range(10)]
    chunks = chunk_member_lines(lines, chunk_size=4, max_chars=10_000)
    assert [len(c.splitlines()) for c in chunks] == [4, 4, 2]

    # Char budget splits before the line-count bound is reached.
    fat_lines = [f"- {'x' * 50} {i}" for i in range(4)]
    chunks = chunk_member_lines(fat_lines, chunk_size=10, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert len(chunks) > 1


def test_chunk_member_lines_never_drops_or_cuts_lines():
    lines = [f"- {i}" for i in range(7)] + ["- " + "y" * 500]
    chunks = chunk_member_lines(lines, chunk_size=3, max_chars=100)
    rejoined = [line for chunk in chunks for line in chunk.splitlines()]
    assert rejoined == lines


def test_lines_from_members_formats_rows():
    rows = [
        {"timestamp": 120, "event_type": "MODIFIED", "file_path": "/foo/a", "description": "d1"},
        {"timestamp": 121, "event_type": "MODIFIED", "file_path": None, "description": None},
    ]
    assert lines_from_members(rows) == [
        "- 120: MODIFIED | /foo/a | d1",
        "- 121: MODIFIED |  | ",
    ]


async def test_analyze_cluster_members_single_chunk_one_call():
    llm = _FakeLLM()
    lines = lines_from_members([
        {"timestamp": 120, "event_type": "MODIFIED", "file_path": "/a", "description": "x"},
        {"timestamp": 121, "event_type": "MODIFIED", "file_path": "/b", "description": "y"},
    ])
    result = await analyze_cluster_members(
        llm, event_type="MODIFIED", time_window=2, member_lines=lines, chunk_size=10
    )

    assert len(llm.calls) == 1
    assert "### 事件清单（共 2 条）" in llm.calls[0]["event_data"]["description"]
    assert "/a" in llm.calls[0]["event_data"]["description"]
    assert result["analysis"]["summary"] == "s"


async def test_analyze_cluster_members_map_reduce_over_all_chunks():
    llm = _FakeLLM()
    lines = [f"- line {i}" for i in range(5)]
    result = await analyze_cluster_members(
        llm,
        event_type="MODIFIED",
        time_window=2,
        member_lines=lines,
        chunk_size=2,
        concurrency=2,
    )

    # 3 map chunks + 1 reduce merge = 4 calls; every line reached the LLM.
    assert len(llm.calls) == 4
    map_bodies = "\n".join(
        call["event_data"]["description"] for call in llm.calls[:3]
    )
    for i in range(5):
        assert f"- line {i}" in map_bodies
    assert "第 1/3 片" in llm.calls[0]["event_data"]["description"]
    reduce_body = llm.calls[3]["event_data"]["description"]
    assert "各片要点" in reduce_body
    assert result["map_calls"] == 3
    assert result["reduce_calls"] == 1


def test_build_analysis_episodes_embeds_coordinate_and_record_id():
    episodes = build_analysis_episodes({
        "id": 42,
        "event_type": "MODIFIED",
        "bucket_seconds": 300,
        "time_window": 7,
        "parent_directory": "/etc/",
        "description": "analysis text",
    })
    assert len(episodes) == 1
    assert episodes[0].name.endswith("#a42")
    assert "300s/7 @ /etc/" in episodes[0].name
    assert '"analysis_id": 42' in episodes[0].episode_body


def test_build_analysis_episodes_empty_description_yields_nothing():
    assert build_analysis_episodes({"id": 1, "description": ""}) == []


def test_mark_analysis_ingested_is_idempotent(tmp_path):
    path = tmp_path / "events.db"
    ensure_cluster_analysis_schema(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO event_cluster_analyses (task_id, bucket_seconds, bucket_index, "
            "event_type, parent_directory, member_count, member_min_id, member_max_id, "
            "members_hash, trigger_source, created_at) VALUES "
            "('t', 60, 1, 'MODIFIED', '/x/', 1, 1, 1, 'h', 'pipeline', 1)"
        )
        conn.commit()
        row_id = conn.execute("SELECT id FROM event_cluster_analyses").fetchone()[0]

    assert mark_analysis_ingested(str(path), [row_id], when=999) == 1
    assert mark_analysis_ingested(str(path), [row_id], when=1234) == 0

    with sqlite3.connect(path) as conn:
        value = conn.execute(
            "SELECT ingested_at FROM event_cluster_analyses WHERE id = ?", (row_id,)
        ).fetchone()[0]
    assert value == 999
