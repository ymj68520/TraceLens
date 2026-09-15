"""
Phase 7 regression tests: D8 version chaining (analysis_id_upstream), the
§9-L3 Graphiti ingestion state machine for file analyses (#fa naming, rich
body, ingested_at marking after full batch success), build_analysis_episodes
extra_body, and the §9-L2 source_stale comparison.
"""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from httpserver.config import Settings
from httpserver.services.case_analysis.cluster_analyzer import (
    build_analysis_episodes,
)
from httpserver.services.case_analysis.file_schema import (
    ensure_file_analysis_schema,
    mark_analyses_ingested,
)
from httpserver.services.case_analysis.file_analyzer import FileAnalyzer
from httpserver.services.investigation_service import InvestigationService
from httpserver.services.llm.llm_service import LLMService


def _files_db(tmp_path, with_files=True):
    db = str(tmp_path / "t_files.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, md5 TEXT,"
        " mtime INTEGER, ctime INTEGER, llm_summary TEXT, llm_description"
        " TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, llm_model_used"
        " TEXT)"
    )
    if with_files:
        conn.execute(
            "INSERT INTO files (path, md5, mtime) VALUES ('/a', 'md5a', 1700000000)"
        )
    conn.commit()
    conn.close()
    ensure_file_analysis_schema(db)
    return db


def _service():
    return LLMService(Settings())


class TestVersionChain:
    def test_upstream_links_previous_latest(self, tmp_path):
        db = _files_db(tmp_path)
        svc = _service()
        assert svc.persist_to_files_db(db_path=db, file_path="/a",
                                       description="v1", summary="s",
                                       keywords="k", model_used="m",
                                       task_id="t", trigger_source="pipeline")
        assert svc.persist_to_files_db(db_path=db, file_path="/a",
                                       description="v2", summary="s",
                                       keywords="k", model_used="m",
                                       task_id="t", trigger_source="reanalyze")
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM file_analyses ORDER BY id"
            ).fetchall()
        assert rows[1]["analysis_id_upstream"] == rows[0]["id"]

    def test_upstream_includes_migrated(self, tmp_path):
        db = _files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE files SET llm_description='CLI旧描述',"
                " llm_analyzed_at=1726000000, llm_model_used='cli' WHERE path='/a'"
            )
            conn.commit()
        svc = _service()
        assert svc.persist_to_files_db(db_path=db, file_path="/a",
                                       description="案情描述", summary="s",
                                       keywords="k", model_used="m",
                                       task_id="t", trigger_source="pipeline")
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM file_analyses ORDER BY id"
            ).fetchall()
        assert [r["trigger_source"] for r in rows] == ["migrated", "pipeline"]
        assert rows[1]["analysis_id_upstream"] == rows[0]["id"]


class TestIngestedStateMachine:
    def test_mark_idempotent(self, tmp_path):
        db = _files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            for _ in range(2):
                conn.execute(
                    "INSERT INTO file_analyses (task_id, file_path, md5,"
                    " description, trigger_source, created_at)"
                    " VALUES ('t', '/a', '', 'd', 'pipeline', 1)"
                )
            conn.commit()
        assert mark_analyses_ingested(db, [1, 2]) == 2
        assert mark_analyses_ingested(db, [1, 2]) == 0  # already marked

    async def test_episode_cites_record_and_marks_after_success(self, tmp_path):
        db = _files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO file_analyses (task_id, file_path, md5, summary,"
                " description, keywords, model, trigger_source, created_at)"
                " VALUES ('t', '/a', 'md5a', '摘要', '详细', 'k1,k2', 'm',"
                " 'pipeline', 1)"
            )
            conn.commit()

        ingestor = MagicMock()
        ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=2, total_episodes=2, failed=0, errors=[]
        ))
        graphiti = MagicMock()
        graphiti.initialize = AsyncMock()
        graphiti._get_task_graph = AsyncMock(return_value={"ingestor": ingestor})
        analyzer = FileAnalyzer(SimpleNamespace(), MagicMock(), graphiti)

        ok = await analyzer.ingest_to_knowledge_graph(
            "t1", "案情",
            [{"file_path": "/a", "description": "详细", "success": True}],
            files_db_path=db,
        )

        assert ok is True
        episodes = ingestor.batch_ingest.await_args.kwargs["episodes"]
        file_eps = [e for e in episodes if e.name.startswith("文件分析")]
        assert file_eps and "#fa1" in file_eps[0].name
        assert '"md5"' in file_eps[0].episode_body
        assert "k1" in file_eps[0].episode_body
        with sqlite3.connect(db) as conn:
            marked = conn.execute(
                "SELECT ingested_at FROM file_analyses WHERE id = 1"
            ).fetchone()[0]
        assert marked is not None

    async def test_failed_batch_leaves_ingested_null(self, tmp_path):
        db = _files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO file_analyses (task_id, file_path, md5,"
                " description, trigger_source, created_at)"
                " VALUES ('t', '/a', '', '详细', 'pipeline', 1)"
            )
            conn.commit()

        ingestor = MagicMock()
        ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=0, total_episodes=1, failed=1,
            errors=[{"episode": "x", "error": "LLM extraction failed"}],
        ))
        graphiti = MagicMock()
        graphiti.initialize = AsyncMock()
        graphiti._get_task_graph = AsyncMock(return_value={"ingestor": ingestor})
        analyzer = FileAnalyzer(SimpleNamespace(), MagicMock(), graphiti)

        await analyzer.ingest_to_knowledge_graph(
            "t1", "案情",
            [{"file_path": "/a", "description": "详细", "success": True}],
            files_db_path=db,
        )

        with sqlite3.connect(db) as conn:
            marked = conn.execute(
                "SELECT ingested_at FROM file_analyses WHERE id = 1"
            ).fetchone()[0]
        assert marked is None  # stays pending for the next gap-fill


class TestExtraBody:
    def test_case_level_tags_merge(self):
        episodes = build_analysis_episodes(
            {"id": 5, "event_type": "T", "bucket_seconds": 60,
             "time_window": 3, "description": "内容"},
            extra_body={"source_image": "IMG2", "task_id": "t9"},
        )
        assert '"source_image": "IMG2"' in episodes[0].episode_body
        assert '"task_id": "t9"' in episodes[0].episode_body

    def test_no_extra_body_default_unchanged(self):
        episodes = build_analysis_episodes(
            {"id": 6, "event_type": "T", "bucket_seconds": 60,
             "time_window": 3, "description": "内容"},
        )
        assert "#a6" in episodes[0].name
        assert "source_image" not in episodes[0].episode_body


class TestFileStale:
    def _svc(self):
        return InvestigationService.__new__(InvestigationService)

    def test_stale_when_analysis_newer_than_snapshot(self, tmp_path):
        db = _files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE files SET llm_analyzed_at = 1726000000 WHERE path = '/a'"
            )
            conn.commit()
        svc = self._svc()
        snapshot = {"source_updated_at": 1700000000}
        assert svc._file_stale(snapshot, db, "file:/a") is True

    def test_fresh_when_analysis_older_or_equal(self, tmp_path):
        db = _files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE files SET llm_analyzed_at = 1600000000 WHERE path = '/a'"
            )
            conn.commit()
        svc = self._svc()
        assert svc._file_stale({"source_updated_at": 1700000000}, db, "file:/a") is False

    def test_cluster_keys_and_missing_snapshot_never_stale(self, tmp_path):
        db = _files_db(tmp_path)
        svc = self._svc()
        assert svc._file_stale({"source_updated_at": 1}, db, "cluster:v1:5:X") is False
        assert svc._file_stale({}, db, "file:/a") is False
        assert svc._file_stale({"source_updated_at": None}, db, "file:/a") is False
