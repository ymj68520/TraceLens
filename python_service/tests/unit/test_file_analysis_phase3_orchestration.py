"""
Phase 3 (orchestration & concurrency) regression tests for the file-analysis
SPEC: round ordering (artifact ∥ file → cluster, D8/D10), failure-visible
partial marking (§5.3), and the D14 reanalyze concurrency budget.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from httpserver.services.case_analysis.case_analysis_parts._pipelines import (
    CaseAnalysisPipelinesMixin,
)
from httpserver.services.case_analysis.file_analyzer import FileAnalyzer


def _svc(tmp_path, *, with_windows=True, windows_service_ok=True):
    """Pipelines-mixin instance with mocked rounds dependencies."""
    svc = CaseAnalysisPipelinesMixin.__new__(CaseAnalysisPipelinesMixin)
    # These tests exercise the Round C cluster pipeline itself; the MVP gate
    # (mvp-phase1-acceptance §4.1) is covered in test_mvp_feature_gates.py.
    svc.settings = SimpleNamespace(llm_max_concurrency=3, event_llm_analysis_enabled=True)
    events_db = _touch(tmp_path, "events.db")
    windows_db = _touch(tmp_path, "windows.db") if with_windows else ""
    svc._cpp_backend = MagicMock()
    svc._cpp_backend.get_task = AsyncMock(return_value={
        "output_events_db": events_db,
        "output_windows_db": windows_db,
    })
    svc._cluster_analyzer = MagicMock()
    svc._cluster_analyzer.analyze_and_ingest_clusters = AsyncMock(
        return_value=[{"event_type": "X", "success": True}]
    )
    if windows_service_ok:
        svc._windows_service = MagicMock()
        svc.analyze_windows_artifacts = AsyncMock(return_value={
            "filter": {"selected_count": 3}, "analysis": {"analyzed_count": 3},
        })
    else:
        svc._windows_service = None
    return svc


def _touch(tmp_path, name):
    p = tmp_path / name
    p.write_text("")
    return str(p)


class TestRoundOrchestration:
    async def test_cluster_starts_only_after_file_round(self, tmp_path):
        """D8: the cluster round must not start before the file round persisted."""
        svc = _svc(tmp_path)
        events = []

        async def file_round(*args, **kwargs):
            events.append("file_done")
            return [{"file_path": "/a", "description": "d", "success": True}]

        async def cluster_round(*args, **kwargs):
            events.append("cluster_started")
            return [{"success": True}]

        svc.generate_file_descriptions = file_round
        svc._cluster_analyzer.analyze_and_ingest_clusters = cluster_round

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", ["/a"], "案情", "", None,
        )

        assert events == ["file_done", "cluster_started"]
        assert rounds["partial"] is False
        assert rounds["descriptions"][0]["description"] == "d"
        assert rounds["steps"]["event_clusters"]["success"] is True

    async def test_artifact_round_runs_and_records_summary(self, tmp_path):
        db = _touch(tmp_path, "windows.db")
        svc = _svc(tmp_path)
        svc._cpp_backend.get_task = AsyncMock(return_value={
            "output_events_db": "", "output_windows_db": db,
        })
        svc.generate_file_descriptions = AsyncMock(return_value=[])

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", [], "案情", "", None,
        )

        svc.analyze_windows_artifacts.assert_awaited_once()
        assert rounds["steps"]["artifacts"]["success"] is True
        assert rounds["steps"]["artifacts"]["summary"]["filter"]["selected_count"] == 3

    async def test_artifact_failure_marks_partial_without_blocking(self, tmp_path):
        db = _touch(tmp_path, "windows.db")
        svc = _svc(tmp_path)
        svc._cpp_backend.get_task = AsyncMock(return_value={
            "output_events_db": _touch(tmp_path, "events.db"),
            "output_windows_db": db,
        })
        svc.analyze_windows_artifacts = AsyncMock(side_effect=RuntimeError("LLM down"))
        svc.generate_file_descriptions = AsyncMock(return_value=[{"success": True}])

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", ["/a"], "案情", "", None,
        )

        assert rounds["partial"] is True
        assert rounds["steps"]["artifacts"]["failed"] is True
        assert "LLM down" in rounds["steps"]["artifacts"]["reason"]
        # Other rounds unaffected
        assert rounds["steps"]["file_round"]["analyzed"] == 1
        assert rounds["steps"]["event_clusters"]["success"] is True

    async def test_file_failure_marks_partial_cluster_still_runs(self, tmp_path):
        svc = _svc(tmp_path, with_windows=False)
        svc._cpp_backend.get_task = AsyncMock(return_value={
            "output_events_db": _touch(tmp_path, "events.db"),
            "output_windows_db": "",
        })
        svc.generate_file_descriptions = AsyncMock(
            side_effect=RuntimeError("no llm endpoint")
        )

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", ["/a"], "案情", "", None,
        )

        assert rounds["partial"] is True
        assert rounds["steps"]["file_round"]["failed"] is True
        assert rounds["descriptions"] == []
        assert rounds["steps"]["event_clusters"]["success"] is True

    async def test_cluster_failure_marks_partial(self, tmp_path):
        svc = _svc(tmp_path, with_windows=False)
        svc._cpp_backend.get_task = AsyncMock(return_value={
            "output_events_db": _touch(tmp_path, "events.db"),
            "output_windows_db": "",
        })
        svc.generate_file_descriptions = AsyncMock(return_value=[])
        svc._cluster_analyzer.analyze_and_ingest_clusters = AsyncMock(
            side_effect=RuntimeError("budget blown")
        )

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", ["/a"], "案情", "", None,
        )

        assert rounds["partial"] is True
        assert rounds["steps"]["event_clusters"]["failed"] is True

    async def test_missing_dbs_are_visible_skips_not_failures(self, tmp_path):
        svc = _svc(tmp_path, with_windows=False)
        svc._cpp_backend.get_task = AsyncMock(return_value={
            "output_events_db": "", "output_windows_db": "",
        })
        svc.generate_file_descriptions = AsyncMock(return_value=[])

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", [], "案情", "", None,
        )

        assert rounds["partial"] is False
        assert rounds["steps"]["artifacts"]["skipped"] is True
        assert rounds["steps"]["event_clusters"]["skipped"] is True

    async def test_missing_windows_service_is_failure_not_skip(self, tmp_path):
        db = _touch(tmp_path, "windows.db")
        svc = _svc(tmp_path, windows_service_ok=False)
        svc._cpp_backend.get_task = AsyncMock(return_value={
            "output_events_db": "", "output_windows_db": db,
        })
        svc.generate_file_descriptions = AsyncMock(return_value=[])

        rounds = await svc._execute_analysis_rounds(
            "t1", "unused.db", [], "案情", "", None,
        )

        # D1: a mandatory AI round that cannot run is a visible failure.
        assert rounds["partial"] is True
        assert rounds["steps"]["artifacts"]["failed"] is True


class TestReanalyzeConcurrency:
    async def test_concurrency_bounded_and_order_preserved(self):
        analyzer = FileAnalyzer(SimpleNamespace(llm_max_concurrency=2), MagicMock(), None)

        active = 0
        peak = 0

        async def fake_reanalyze(**kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {
                "file_path": kwargs["file_path"],
                "description": "d",
                "model_used": "m",
                "success": True,
            }

        analyzer._reanalyze_single_file = fake_reanalyze

        paths = [f"/data/f{i}.txt" for i in range(6)]
        results = await analyzer.reanalyze_files("t1", paths, "hint", "")

        assert peak == 2  # llm_max_concurrency budget honored
        assert [r["file_path"] for r in results] == paths  # order preserved
        assert all(r["success"] for r in results)

    async def test_single_failure_isolated(self):
        analyzer = FileAnalyzer(SimpleNamespace(llm_max_concurrency=3), MagicMock(), None)

        async def fake_reanalyze(*, file_path, **kwargs):
            if "bad" in file_path:
                raise RuntimeError("boom")
            return {"file_path": file_path, "description": "d", "success": True}

        analyzer._reanalyze_single_file = fake_reanalyze

        results = await analyzer.reanalyze_files(
            "t1", ["/data/ok1.txt", "/data/bad.txt", "/data/ok2.txt"], "hint", ""
        )

        assert results[1]["success"] is False
        assert "boom" in results[1]["error"]
        assert results[0]["success"] and results[2]["success"]
