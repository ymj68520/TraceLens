"""
Phase 2 (data foundation) regression tests for the file-analysis SPEC.

Covers §12 Phase 2 acceptance: schema idempotency, atomic three-write
persistence, D19 legacy-cache archival (exactly once), the D4 analyzed-check
switch (file_analyses is the sole authority), and the D17 extraction-method
provenance chain (extractor → persist).
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from httpserver.config import Settings
from httpserver.services.case_analysis.file_analyzer import FileAnalyzer
from httpserver.services.case_analysis.file_schema import (
    analysis_stats,
    ensure_file_analysis_schema,
    latest_analysis,
)
from httpserver.services.extractors.markitdown_extractor import MarkitdownExtractor
from httpserver.services.llm.llm_service import LLMService


def make_files_db(tmp_path, rows=(), llm_cache=()):
    """Task files db with a minimal files table (+optional CLI-era cache)."""
    db = str(tmp_path / "task_files.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT,"
        " name TEXT, md5 TEXT, mtime INTEGER, ctime INTEGER, size INTEGER,"
        " llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,"
        " llm_analyzed_at INTEGER, llm_model_used TEXT)"
    )
    for path, md5 in rows:
        conn.execute(
            "INSERT INTO files (path, name, md5, mtime) VALUES (?, ?, ?, 1000)",
            (path, Path(path).name, md5),
        )
    for path, summary, desc, analyzed_at, model in llm_cache:
        conn.execute(
            "UPDATE files SET llm_summary=?, llm_description=?,"
            " llm_analyzed_at=?, llm_model_used=? WHERE path=?",
            (summary, desc, analyzed_at, model, path),
        )
    conn.commit()
    conn.close()
    return db


def _service():
    return LLMService(Settings())


class TestSchemaIdempotent:
    def test_ensure_twice_no_side_effects(self, tmp_path):
        db = make_files_db(tmp_path)
        ensure_file_analysis_schema(db)
        with sqlite3.connect(db) as conn:
            ddl1 = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='file_analyses'"
            ).fetchone()[0]
            idx1 = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND tbl_name='file_analyses' ORDER BY name"
            ).fetchall()
        ensure_file_analysis_schema(db)
        with sqlite3.connect(db) as conn:
            ddl2 = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='file_analyses'"
            ).fetchone()[0]
            idx2 = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND tbl_name='file_analyses' ORDER BY name"
            ).fetchall()
        assert ddl1 == ddl2
        assert idx1 == idx2


class TestThreeWrite:
    def test_success_writes_all_three(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("/data/a.txt", "md5a")])
        ok = _service().persist_to_files_db(
            db_path=db, file_path="/data/a.txt", description="案情描述",
            summary="描", keywords="k1", model_used="m1",
            task_id="t1", trigger_source="pipeline",
            extraction_method="markitdown",
        )
        assert ok
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            files_row = conn.execute(
                "SELECT * FROM files WHERE path='/data/a.txt'"
            ).fetchone()
            assert files_row["llm_description"] == "案情描述"
            assert files_row["llm_analyzed_at"] is not None

            rec = conn.execute("SELECT * FROM file_analyses").fetchone()
            assert rec["trigger_source"] == "pipeline"
            assert rec["task_id"] == "t1"
            assert rec["md5"] == "md5a"
            assert rec["extraction_method"] == "markitdown"
            assert rec["ingested_at"] is None  # graphiti state machine pending

            fd = conn.execute("SELECT * FROM file_descriptions").fetchone()
            assert fd["description"] == "案情描述"
            assert fd["is_relevant"] == 1  # D16: first analysis defaults in

    def test_fail_closed_missing_row(self, tmp_path):
        db = make_files_db(tmp_path)
        ok = _service().persist_to_files_db(
            db_path=db, file_path="/ghost.txt", description="d",
            summary="s", keywords="k", model_used="m",
        )
        assert not ok
        with sqlite3.connect(db) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM file_analyses"
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='file_descriptions'"
            ).fetchone()[0] == 0

    def test_fail_closed_missing_db(self, tmp_path):
        assert not _service().persist_to_files_db(
            db_path=str(tmp_path / "nope.db"), file_path="/a", description="d",
            summary="s", keywords="k", model_used="m",
        )

    def test_atomic_rollback_on_failure(self, tmp_path, monkeypatch):
        db = make_files_db(tmp_path, rows=[("/data/a.txt", "md5a")])
        svc = _service()

        def boom(conn):
            raise RuntimeError("simulated step-3 failure")

        monkeypatch.setattr(svc, "_ensure_file_descriptions_schema", boom)
        ok = svc.persist_to_files_db(
            db_path=db, file_path="/data/a.txt", description="新描述",
            summary="s", keywords="k", model_used="m",
        )
        assert not ok
        with sqlite3.connect(db) as conn:
            # Rolled back: cache untouched, no truth row, no archive.
            assert conn.execute(
                "SELECT llm_description FROM files WHERE path='/data/a.txt'"
            ).fetchone()[0] is None
            assert conn.execute(
                "SELECT COUNT(*) FROM file_analyses"
            ).fetchone()[0] == 0

    def test_is_relevant_not_reset_on_reanalysis(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("/a", "m1")])
        svc = _service()
        svc.persist_to_files_db(db_path=db, file_path="/a",
                                description="d1", summary="s", keywords="k",
                                model_used="m")
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE file_descriptions SET is_relevant = 0")
            conn.commit()
        svc.persist_to_files_db(db_path=db, file_path="/a",
                                description="d2", summary="s", keywords="k",
                                model_used="m", trigger_source="reanalyze")
        with sqlite3.connect(db) as conn:
            v = conn.execute(
                "SELECT is_relevant FROM file_descriptions"
            ).fetchone()[0]
        assert v == 0  # D16: user toggle survives


class TestLegacyArchival:
    def test_archives_cli_cache_once(self, tmp_path):
        db = make_files_db(
            tmp_path, rows=[("/data/a.txt", "md5a")],
            llm_cache=[("/data/a.txt", "cli摘要", "CLI通用描述", 1726000000,
                        "cli-model")],
        )
        svc = _service()
        assert svc.persist_to_files_db(
            db_path=db, file_path="/data/a.txt", description="案情描述",
            summary="s", keywords="k", model_used="m1",
            task_id="t1", trigger_source="pipeline",
        )
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM file_analyses ORDER BY id"
            ).fetchall()
        assert [r["trigger_source"] for r in rows] == ["migrated", "pipeline"]
        assert rows[0]["description"] == "CLI通用描述"
        assert rows[0]["created_at"] == 1726000000
        assert rows[0]["analysis_id_upstream"] is None

        # Second overwrite: the archived row is not duplicated (D19 idempotent)
        assert svc.persist_to_files_db(
            db_path=db, file_path="/data/a.txt", description="第二次",
            summary="s", keywords="k", model_used="m1",
            task_id="t1", trigger_source="reanalyze",
        )
        with sqlite3.connect(db) as conn:
            migrated = conn.execute(
                "SELECT COUNT(*) FROM file_analyses WHERE trigger_source='migrated'"
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM file_analyses"
            ).fetchone()[0]
        assert migrated == 1
        assert total == 3

    def test_no_archive_for_clean_row(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("/data/a.txt", "md5a")])
        svc = _service()
        svc.persist_to_files_db(db_path=db, file_path="/data/a.txt",
                                description="d", summary="s", keywords="k",
                                model_used="m")
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT trigger_source FROM file_analyses"
            ).fetchall()
        assert [r[0] for r in rows] == ["interactive"]


class TestAccessors:
    def test_latest_and_stats(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("/a", "m1"), ("/b", "m2"),
                                           ("/c", None)])
        ensure_file_analysis_schema(db)
        svc = _service()
        svc.persist_to_files_db(db_path=db, file_path="/a", description="v1",
                                summary="s", keywords="k", model_used="m",
                                task_id="t", trigger_source="pipeline")
        svc.persist_to_files_db(db_path=db, file_path="/a", description="v2",
                                summary="s", keywords="k", model_used="m",
                                task_id="t", trigger_source="reanalyze")

        rec = latest_analysis(db, "/a")
        assert rec["description"] == "v2"

        stats = analysis_stats(db)
        assert stats["total"] == 3
        assert stats["analyzed"] == 1
        assert stats["pending"] == 2
        assert stats["stale"] == 0  # record md5 copied from files row

    def test_stale_counts_md5_mismatch(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("/a", "md5-new")])
        ensure_file_analysis_schema(db)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO file_analyses (task_id, file_path, md5,"
                " description, trigger_source, created_at)"
                " VALUES ('t', '/a', 'md5-old', 'd', 'pipeline', 1)"
            )
            conn.commit()
        assert analysis_stats(db)["stale"] == 1


def _no_extractor():
    locator = MagicMock()
    locator.get_extractor.return_value = None
    return patch(
        "httpserver.services.document_extractor.get_document_extractor_locator",
        return_value=locator,
    )


def _analyzer_settings():
    """Settings stand-in with the one attribute analyze_files really reads."""
    settings = MagicMock()
    settings.llm_max_concurrency = 3
    return settings


def _mock_llm_writing_to(db):
    """LLM stub whose analyze/read are mocked but whose persist is the real
    three-write implementation bound to ``db`` (the test asserts on the
    persisted truth row, so the write must be real)."""
    llm = MagicMock()
    llm.persist_to_files_db = LLMService(Settings()).persist_to_files_db
    return llm


class TestAnalyzedCheck:
    """D4: the analyzed-check reads file_analyses, not file_descriptions."""

    async def test_descriptions_without_record_are_reanalyzed(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("a.txt", "md5a")])
        target = tmp_path / "a.txt"
        target.write_text("content")
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE file_descriptions (id INTEGER PRIMARY KEY"
                " AUTOINCREMENT, file_path TEXT UNIQUE, description TEXT,"
                " summary TEXT, keywords TEXT, model_used TEXT,"
                " is_relevant INTEGER DEFAULT 1, created_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO file_descriptions (file_path, description,"
                " created_at) VALUES ('a.txt', '旧描述', 1)"
            )
            conn.commit()

        llm = _mock_llm_writing_to(db)
        llm.analyze = AsyncMock(
            return_value={"analysis": {"description": "新案情描述"}, "model": "m1"}
        )
        llm.read_file_content = AsyncMock(return_value="content")
        analyzer = FileAnalyzer(_analyzer_settings(), llm, None)

        with _no_extractor():
            results = await analyzer.analyze_files(
                db, ["a.txt"], "案情", extraction_dir=str(tmp_path), task_id="t1"
            )

        llm.analyze.assert_awaited_once()  # NOT skipped
        assert results[0]["description"] == "新案情描述"
        rec = latest_analysis(db, "a.txt")
        assert rec is not None
        assert rec["extraction_method"] == "raw_text"
        assert rec["trigger_source"] == "pipeline"

    async def test_recorded_file_is_skipped(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("a.txt", "md5a")])
        ensure_file_analysis_schema(db)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO file_analyses (task_id, file_path, md5,"
                " description, model, trigger_source, created_at)"
                " VALUES ('t0', 'a.txt', 'md5a', '旧记录', 'm0', 'pipeline', 1)"
            )
            conn.commit()

        llm = MagicMock()
        llm.analyze = AsyncMock()
        analyzer = FileAnalyzer(MagicMock(), llm, None)

        with _no_extractor():
            results = await analyzer.analyze_files(
                db, ["a.txt"], "案情", extraction_dir=str(tmp_path), task_id="t1"
            )

        llm.analyze.assert_not_awaited()  # skipped by the truth record
        assert results[0]["description"] == "旧记录"
        assert results[0]["success"] is True

    async def test_extraction_method_recorded(self, tmp_path):
        db = make_files_db(tmp_path, rows=[("a.txt", "md5a")])
        target = tmp_path / "a.txt"
        target.write_text("content")
        llm = _mock_llm_writing_to(db)
        llm.analyze = AsyncMock(
            return_value={"analysis": {"description": "d"}, "model": "m"}
        )
        analyzer = FileAnalyzer(_analyzer_settings(), llm, None)

        fake_extractor = MagicMock()

        async def fake_detailed(path):
            return "markdown内容", "markitdown"

        fake_extractor.extract_to_markdown_detailed = fake_detailed
        locator = MagicMock()
        locator.get_extractor.return_value = fake_extractor

        with patch(
            "httpserver.services.document_extractor.get_document_extractor_locator",
            return_value=locator,
        ):
            await analyzer.analyze_files(
                db, ["a.txt"], "案情", extraction_dir=str(tmp_path), task_id="t1"
            )

        rec = latest_analysis(db, "a.txt")
        assert rec["extraction_method"] == "markitdown"
        assert rec["trigger_source"] == "pipeline"
        assert rec["task_id"] == "t1"


class TestMarkitdownDetailed:
    async def test_reports_markitdown(self, tmp_path):
        f = tmp_path / "smoke.html"
        f.write_text("<html><body><h1>Hi</h1>forensic</body></html>")
        ex = MarkitdownExtractor()
        if ex._md is None:
            pytest.skip("markitdown engine unavailable in this venv")
        content, method = await ex.extract_to_markdown_detailed(str(f))
        assert method == "markitdown"
        assert "Hi" in content

    async def test_fallback_reports_legacy(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hello")
        ex = MarkitdownExtractor()
        ex._md = None  # simulate missing engine
        fb = MagicMock()

        async def fb_detailed(path):
            return "legacy内容", "TxtExtractor"

        fb.extract_to_markdown_detailed = fb_detailed
        ex._fallback_map = {".txt": fb}

        content, method = await ex.extract_to_markdown_detailed(str(f))
        assert method == "legacy:TxtExtractor"
        assert content == "legacy内容"
