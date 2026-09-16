"""
Phase 1 regression tests for the file-analysis redesign SPEC (C1).

Cluster episodes must have exactly one builder/owner — ClusterAnalyzer's
SPEC-format ingestor (``build_analysis_episodes``, episode names carrying
``#a{analysis_id}``, the ``ingested_at`` state machine). These tests pin the
removal of every legacy-format cluster episode injection point:

- the public ingestion functions no longer accept ``cluster_descriptions``;
- FileAnalyzer's KG ingestion builds case/file episodes only;
- the manual-Ingest gap-fill reads ONLY ``event_cluster_analyses`` (legacy
  per-event ``llm_*`` cache rows are never rebuilt into pseudo-clusters) and
  marks rows ingested through the shared cluster_analyzer ingestor.
"""

import inspect
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from httpserver.services.case_analysis.case_analysis_parts._core import (
    CaseAnalysisCoreMixin,
)
from httpserver.services.case_analysis.cluster_analyzer import (
    ensure_cluster_analysis_schema,
)
from httpserver.services.case_analysis.file_analyzer import FileAnalyzer
from httpserver.services.graphiti_parts._ingest import GraphitiIngestMixin
from httpserver.services.ingestion_job_parts._worker import (
    fetch_pending_cluster_analyses,
    ingest_pending_cluster_analyses,
)
from httpserver.services.windows_artifacts.windows_analyzer import (
    WindowsArtifactAnalyzer,
)


def _ok_ingestor(successful=1):
    ingestor = MagicMock()
    ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
        successful=successful, total_episodes=successful, failed=0, errors=[]
    ))
    return ingestor


def _mock_graphiti(ingestor):
    graphiti = MagicMock()
    graphiti.initialize = AsyncMock()
    graphiti._get_task_graph = AsyncMock(return_value={"ingestor": ingestor})
    return graphiti


class TestNoClusterDescriptionsParam:
    def test_public_ingest_functions(self):
        """The legacy cluster-injection parameter must be gone everywhere."""
        for fn in (
            FileAnalyzer.ingest_to_knowledge_graph,
            CaseAnalysisCoreMixin.ingest_to_knowledge_graph,
            GraphitiIngestMixin.ingest_task_episodes,
            WindowsArtifactAnalyzer.ingest_to_knowledge_graph,
        ):
            assert "cluster_descriptions" not in inspect.signature(fn).parameters, fn


class TestFileIngestEpisodesOnly:
    async def test_file_ingest_builds_no_cluster_episodes(self):
        """KG ingestion from the file analyzer yields case/file episodes only —
        cluster episodes come exclusively from ClusterAnalyzer."""
        ingestor = _ok_ingestor()
        analyzer = FileAnalyzer(MagicMock(), MagicMock(), _mock_graphiti(ingestor))

        ok = await analyzer.ingest_to_knowledge_graph(
            "t1", "案情背景", [
                {"file_path": "/a.txt", "description": "文件内容", "success": True},
            ]
        )

        assert ok is True
        episodes = ingestor.batch_ingest.await_args.kwargs["episodes"]
        assert episodes
        assert all(not ep.name.startswith("事件簇分析") for ep in episodes)
        assert any(ep.name.startswith("文件分析") for ep in episodes)


class TestWorkerClusterGapfill:
    """The manual-Ingest path-A must gap-fill from ``event_cluster_analyses``
    through the shared SPEC-format ingestor, never from the ``llm_*`` cache."""

    def _make_events_db(self, tmp_path, with_analyses=True, with_legacy=True,
                        empty_description=False):
        events_db = str(tmp_path / "task_events.db")
        ensure_cluster_analysis_schema(events_db)
        with sqlite3.connect(events_db) as conn:
            if with_analyses:
                description = "" if empty_description else "完整簇分析内容"
                conn.execute(
                    "INSERT INTO event_cluster_analyses ("
                    " task_id, bucket_epoch_offset, bucket_seconds, bucket_index,"
                    " event_type, parent_directory, member_count, member_min_id,"
                    " member_max_id, members_hash, summary, description, keywords,"
                    " model, trigger_source, analysis_id_upstream, created_at,"
                    " ingested_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("t1", 0, 60, 5, "FILE_CREATE", "/data/", 3, 1, 3, "hash",
                     "摘要", description, "k1,k2", "test/model", "pipeline",
                     None, 1726300000, None),
                )
            if with_legacy:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS events ("
                    " id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT,"
                    " llm_description TEXT)"
                )
                conn.execute(
                    "INSERT INTO events (timestamp, event_type, llm_description)"
                    " VALUES (100, 'FILE_CREATE', 'legacy pseudo-cluster')"
                )
            conn.commit()
        return events_db

    async def test_reads_only_analyses_table_and_marks_ingested(self, tmp_path):
        events_db = self._make_events_db(tmp_path)
        ingestor = _ok_ingestor()
        graphiti = _mock_graphiti(ingestor)

        pending = fetch_pending_cluster_analyses(events_db)
        assert len(pending) == 1
        assert pending[0]["event_type"] == "FILE_CREATE"

        ingested = await ingest_pending_cluster_analyses(
            graphiti, "t1", pending, events_db=events_db
        )

        assert ingested == 1
        episodes = ingestor.batch_ingest.await_args.kwargs["episodes"]
        assert len(episodes) == 1
        assert "#a" in episodes[0].name  # SPEC-format episode naming
        with sqlite3.connect(events_db) as conn:
            row = conn.execute(
                "SELECT ingested_at FROM event_cluster_analyses WHERE id = 1"
            ).fetchone()
        assert row[0] is not None

    async def test_legacy_cache_rows_are_ignored(self, tmp_path):
        """A pre-SPEC db with only per-event llm_* rows yields no pending work."""
        events_db = self._make_events_db(tmp_path, with_analyses=False)
        assert fetch_pending_cluster_analyses(events_db) == []

    async def test_empty_description_row_not_pending(self, tmp_path):
        events_db = self._make_events_db(tmp_path, empty_description=True)
        assert fetch_pending_cluster_analyses(events_db) == []

    async def test_already_ingested_rows_not_repicked(self, tmp_path):
        events_db = self._make_events_db(tmp_path)
        with sqlite3.connect(events_db) as conn:
            conn.execute(
                "UPDATE event_cluster_analyses SET ingested_at = 1726300001"
            )
            conn.commit()
        assert fetch_pending_cluster_analyses(events_db) == []

    async def test_missing_db_is_noop(self, tmp_path):
        assert fetch_pending_cluster_analyses(str(tmp_path / "ghost.db")) == []
        assert fetch_pending_cluster_analyses("") == []
