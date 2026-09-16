"""
Phase 4 (Graphiti budget & time) regression tests for the file-analysis SPEC:
D11 chunk-budget derivation, D13 LM Studio probe with fallback semantics,
and D12 forensic reference_time on file and cluster episodes.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from httpserver.services.case_analysis.cluster_analyzer import build_analysis_episodes
from httpserver.services.case_analysis.file_analyzer import FileAnalyzer
from httpserver.services.case_analysis.file_schema import (
    ensure_file_analysis_schema,
    file_forensic_time,
)
from httpserver.services.graphiti_parts import episode_budget


def _settings(tokens=3000, base="http://lm:1234", model="org/model"):
    return SimpleNamespace(
        graphiti_max_episode_tokens=tokens,
        llm_text_base_url=base,
        llm_text_model=model,
    )


class _FakeAsyncClient:
    payload: dict = {}
    error: Exception = None
    calls = 0

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        _FakeAsyncClient.calls += 1
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if _FakeAsyncClient.error:
            raise _FakeAsyncClient.error
        resp = MagicMock()
        resp.json.return_value = _FakeAsyncClient.payload
        return resp


@pytest.fixture(autouse=True)
def _reset_budget_cache(monkeypatch):
    monkeypatch.setattr(episode_budget, "_cached_chars", None)
    yield
    monkeypatch.setattr(episode_budget, "_cached_chars", None)


class TestEpisodeBudget:
    def test_chars_from_tokens_formula(self):
        assert episode_budget.chars_from_tokens(3000) == 9000
        assert episode_budget.chars_from_tokens(614) == 1842
        assert episode_budget.chars_from_tokens(10) == 768  # floor at 256 tokens

    def test_fallback_without_probe(self):
        assert episode_budget.episode_chunk_chars(_settings(tokens=2000)) == 6000
        assert episode_budget.episode_chunk_chars() == 9000  # SPEC default budget

    async def test_probe_narrows_to_context(self, monkeypatch):
        _FakeAsyncClient.payload = {"data": [
            {"id": "deepseek-v3", "max_context_length": 999999},
            {"id": "org/model", "max_context_length": 4096},
        ]}
        monkeypatch.setattr(episode_budget.httpx, "AsyncClient", _FakeAsyncClient)

        chars = await episode_budget.resolve_and_cache(_settings())

        # effective = min(3000, floor(4096 × 0.15) = 614) → 614 × 3
        assert chars == 1842
        assert episode_budget.episode_chunk_chars() == 1842  # cached

    async def test_probe_failure_falls_back_to_configured(self, monkeypatch):
        _FakeAsyncClient.error = RuntimeError("LM Studio down")
        monkeypatch.setattr(episode_budget.httpx, "AsyncClient", _FakeAsyncClient)

        chars = await episode_budget.resolve_and_cache(_settings(tokens=2500))

        assert chars == 7500  # configured, unchanged behavior (D13)

    async def test_probe_runs_once(self, monkeypatch):
        _FakeAsyncClient.payload = {"data": []}  # no context → configured
        _FakeAsyncClient.calls = 0
        monkeypatch.setattr(episode_budget.httpx, "AsyncClient", _FakeAsyncClient)
        settings = _settings()

        await episode_budget.resolve_and_cache(settings)
        assert _FakeAsyncClient.calls == 1
        await episode_budget.resolve_and_cache(settings)
        assert _FakeAsyncClient.calls == 1  # cached, no second probe


class TestClusterEpisodeTime:
    def test_reference_time_is_bucket_start(self):
        episodes = build_analysis_episodes({
            "id": 7, "event_type": "T", "bucket_seconds": 60,
            "time_window": 10, "bucket_epoch_offset": 57600,
            "parent_directory": "/d/", "cluster_count": 3,
            "description": "分析内容",
        })
        assert len(episodes) == 1
        assert episodes[0].reference_time == datetime.fromtimestamp(10 * 60 + 57600)

    def test_missing_offset_defaults_to_zero(self):
        episodes = build_analysis_episodes({
            "id": 8, "event_type": "T", "bucket_seconds": 60,
            "time_window": 10, "description": "分析内容",
        })
        assert episodes[0].reference_time == datetime.fromtimestamp(600)

    def test_absurd_timestamp_falls_back_to_now(self):
        episodes = build_analysis_episodes({
            "id": 9, "event_type": "T", "bucket_seconds": 60,
            "time_window": 10 ** 12, "description": "分析内容",
        })
        assert isinstance(episodes[0].reference_time, datetime)


def _make_files_db(tmp_path, path="/a", mtime=None, ctime=None):
    db = str(tmp_path / "t_files.db")
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, md5 TEXT,"
        " mtime INTEGER, ctime INTEGER)"
    )
    conn.execute("INSERT INTO files (path, mtime, ctime) VALUES (?, ?, ?)",
                 (path, mtime, ctime))
    conn.commit()
    conn.close()
    return db


class TestFileEpisodeTime:
    def _graphiti(self):
        ingestor = MagicMock()
        ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=1, total_episodes=1, failed=0, errors=[]
        ))
        graphiti = MagicMock()
        graphiti.initialize = AsyncMock()
        graphiti._get_task_graph = AsyncMock(return_value={"ingestor": ingestor})
        return graphiti, ingestor

    async def test_reference_time_is_file_mtime(self, tmp_path):
        db = _make_files_db(tmp_path, mtime=1700000000, ctime=1690000000)
        graphiti, ingestor = self._graphiti()
        analyzer = FileAnalyzer(SimpleNamespace(), MagicMock(), graphiti)

        await analyzer.ingest_to_knowledge_graph(
            "t1", "案情", [{"file_path": "/a", "description": "d", "success": True}],
            files_db_path=db,
        )

        episodes = [ep for ep in ingestor.batch_ingest.await_args.kwargs["episodes"]
                    if ep.name.startswith("文件分析")]
        assert episodes[0].reference_time == datetime.fromtimestamp(1700000000)

    async def test_mtime_null_falls_back_to_ctime(self, tmp_path):
        db = _make_files_db(tmp_path, mtime=None, ctime=1690000000)
        graphiti, ingestor = self._graphiti()
        analyzer = FileAnalyzer(SimpleNamespace(), MagicMock(), graphiti)

        await analyzer.ingest_to_knowledge_graph(
            "t1", "案情", [{"file_path": "/a", "description": "d", "success": True}],
            files_db_path=db,
        )

        episodes = [ep for ep in ingestor.batch_ingest.await_args.kwargs["episodes"]
                    if ep.name.startswith("文件分析")]
        assert episodes[0].reference_time == datetime.fromtimestamp(1690000000)

    async def test_no_db_falls_back_to_now(self, tmp_path):
        graphiti, ingestor = self._graphiti()
        analyzer = FileAnalyzer(SimpleNamespace(), MagicMock(), graphiti)

        before = datetime.now()
        await analyzer.ingest_to_knowledge_graph(
            "t1", "案情", [{"file_path": "/a", "description": "d", "success": True}],
        )
        after = datetime.now()

        episodes = [ep for ep in ingestor.batch_ingest.await_args.kwargs["episodes"]
                    if ep.name.startswith("文件分析")]
        assert before <= episodes[0].reference_time <= after

    def test_file_forensic_time_missing_row(self, tmp_path):
        db = _make_files_db(tmp_path)
        assert file_forensic_time(db, "/ghost") is None
        assert file_forensic_time(str(tmp_path / "nope.db"), "/a") is None
        ensure_file_analysis_schema(db)  # smoke: helper unaffected by schema
