"""KG hardening Phase C (SPEC docs/specs/kg-ingestion-hardening.md §B1/§B2).

- single-flight locks: concurrent add_episode ingestion for the same graph
  group is serialized; different groups stay parallel;
- queue_kg_sync_job: self-running job with RUNNING -> COMPLETED/FAILED
  transitions and progress reporting;
- dispatch_kg_ingestion: queues when the job manager exists, falls back to
  inline ingestion otherwise.
"""

import asyncio
import sys
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from httpserver.services.case_analysis.case_analysis_parts._core import (
    CaseAnalysisCoreMixin,
)
from httpserver.services.case_analysis.file_analyzer import FileAnalyzer
from httpserver.services.graphiti_service import GraphitiService
from httpserver.services.ingestion_job_manager import IngestionJobManager
from httpserver.services.ingestion_job_models import JobStatus


def _graphiti_service():
    svc = GraphitiService.__new__(GraphitiService)
    svc.settings = mock.Mock()
    svc._ingest_locks = {}
    svc._task_graphs = {}
    svc._initialized = True
    svc._neo_driver = None
    svc._task_graphs_cache = None
    svc._task_graphs_cache_at = 0.0
    svc._jobs = {}
    svc._graphiti = None
    return svc


class _IngestionTracker:
    """Fake ingestor.batch_ingest that records peak concurrency."""

    def __init__(self, delay=0.05):
        self.delay = delay
        self.cur = 0
        self.max = 0
        self.groups = []

    async def batch_ingest(self, episodes, group_id, progress_callback=None):
        self.cur += 1
        self.max = max(self.max, self.cur)
        self.groups.append(group_id)
        await asyncio.sleep(self.delay)
        self.cur -= 1
        result = SimpleNamespace(
            successful=len(episodes), total_episodes=len(episodes),
            failed=0, errors=[],
        )
        return result


def _file_analyzer(graphiti_svc, tracker):
    fa = FileAnalyzer.__new__(FileAnalyzer)
    fa._graphiti_service = graphiti_svc
    graphiti_svc.initialize = mock.AsyncMock()
    graphiti_svc._get_task_graph = mock.AsyncMock(
        return_value={"config": mock.Mock(), "ingestor": tracker}
    )
    return fa


def _descriptions(n=1):
    return [
        {"file_path": f"/evidence/f{i}.txt", "description": f"d{i}", "success": True}
        for i in range(n)
    ]


class TestSingleFlightLock:
    @pytest.mark.asyncio
    async def test_same_group_serialized(self):
        svc = _graphiti_service()
        tracker = _IngestionTracker()
        fa = _file_analyzer(svc, tracker)

        await asyncio.gather(*[
            fa.ingest_to_knowledge_graph("task-1", "case", _descriptions(2))
            for _ in range(3)
        ])

        assert tracker.max == 1  # never two add_episode batches at once

    @pytest.mark.asyncio
    async def test_different_groups_parallel(self):
        svc = _graphiti_service()
        tracker = _IngestionTracker()
        fa = _file_analyzer(svc, tracker)

        await asyncio.gather(*[
            fa.ingest_to_knowledge_graph(f"task-{i}", "case", _descriptions(1))
            for i in range(3)
        ])

        assert tracker.max == 3  # different groups don't block each other

    @pytest.mark.asyncio
    async def test_worker_and_pipeline_share_the_lock(self):
        """The worker path funnels through GraphitiService.ingest_task_episodes,
        which takes the same per-group lock as the pipeline's direct
        batch_ingest — a joint run must still serialize."""
        svc = _graphiti_service()
        tracker = _IngestionTracker()
        fa = _file_analyzer(svc, tracker)

        async def fake_ingest_task_episodes(self, task_id, file_descriptions,
                                            cluster_descriptions=None,
                                            case_description=None,
                                            progress_callback=None):
            graph_entry = await svc._get_task_graph(task_id)
            ingestor = graph_entry["ingestor"]
            async with svc.lock_for_group(task_id):
                return await ingestor.batch_ingest(
                    episodes=file_descriptions, group_id=task_id
                )

        with mock.patch.object(
            GraphitiService, "ingest_task_episodes", fake_ingest_task_episodes
        ):
            await asyncio.gather(
                fa.ingest_to_knowledge_graph("task-x", "case", _descriptions(1)),
                svc.ingest_task_episodes("task-x", _descriptions(1)),
            )

        assert tracker.max == 1


class TestQueueKgSyncJob:
    @pytest.mark.asyncio
    async def test_job_runs_to_completed_with_progress(self):
        mgr = IngestionJobManager(settings=mock.Mock())
        mgr._use_redis = False

        seen_stages = []

        async def runner(progress):
            seen_stages.append("started")
            await progress("ingesting", "正在摄入 1/2")
            await progress("completed", "done")
            return {"ingested": True}

        job_id = await mgr.queue_kg_sync_job("task-1", runner)

        job = mgr._jobs[job_id]
        assert job.mode.value == "kg_sync"
        for _ in range(100):
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            await asyncio.sleep(0.01)
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 100
        assert job.result == {"ingested": True}
        assert "ingesting" in job.current_phase or seen_stages  # phases flowed

    @pytest.mark.asyncio
    async def test_runner_failure_marks_job_failed(self):
        mgr = IngestionJobManager(settings=mock.Mock())
        mgr._use_redis = False

        async def runner(progress):
            raise RuntimeError("LLM exploded")

        job_id = await mgr.queue_kg_sync_job("task-1", runner)

        job = mgr._jobs[job_id]
        for _ in range(100):
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            await asyncio.sleep(0.01)
        assert job.status == JobStatus.FAILED
        assert "LLM exploded" in job.error

    @pytest.mark.asyncio
    async def test_running_job_is_not_picked_up_by_worker_scan(self):
        """In-memory worker scans PENDING jobs; kg_sync must start RUNNING."""
        mgr = IngestionJobManager(settings=mock.Mock())
        mgr._use_redis = False

        async def runner(progress):
            await asyncio.sleep(0.2)
            return {}

        job_id = await mgr.queue_kg_sync_job("task-1", runner)

        pending = [j for j in mgr._jobs.values() if j.status == JobStatus.PENDING]
        assert mgr._jobs[job_id].status == JobStatus.RUNNING
        assert pending == []


class TestDispatchKgIngestion:
    def _service(self):
        svc = CaseAnalysisCoreMixin.__new__(CaseAnalysisCoreMixin)
        svc.ingest_to_knowledge_graph = mock.AsyncMock(return_value=True)
        return svc

    @pytest.mark.asyncio
    async def test_queues_job_when_manager_available(self):
        svc = self._service()

        real_mgr = IngestionJobManager(settings=mock.Mock())
        real_mgr._use_redis = False

        svc_mgr = mock.Mock()
        svc_mgr.ingestion_job_manager = real_mgr

        with mock.patch(
            "httpserver.dependencies.get_service_manager", return_value=svc_mgr
        ):
            step = await svc.dispatch_kg_ingestion(
                "task-1", "case", _descriptions(3),
                files_db_path="/data/tasks/task-1/files.db",
            )

        assert step["queued"] is True
        assert step["job_id"] in real_mgr._jobs
        assert step["file_episodes"] == 3
        # runner deferred the actual ingestion — not called inline yet
        svc.ingest_to_knowledge_graph.assert_not_called()

        job = real_mgr._jobs[step["job_id"]]
        for _ in range(100):
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            await asyncio.sleep(0.01)
        assert job.status == JobStatus.COMPLETED
        assert job.result["ingested"] is True
        svc.ingest_to_knowledge_graph.assert_awaited_once()
        _, kwargs = svc.ingest_to_knowledge_graph.await_args
        assert kwargs.get("files_db_path") == "/data/tasks/task-1/files.db"

    @pytest.mark.asyncio
    async def test_falls_back_to_inline_without_manager(self):
        svc = self._service()

        svc_mgr = mock.Mock()
        svc_mgr.ingestion_job_manager = None

        with mock.patch(
            "httpserver.dependencies.get_service_manager", return_value=svc_mgr
        ):
            step = await svc.dispatch_kg_ingestion(
                "task-1", "case", _descriptions(2)
            )

        assert step == {
            "ingested": True, "file_episodes": 2,
        }
        svc.ingest_to_knowledge_graph.assert_awaited_once()


class TestCancelJobsForTask:
    """Graph deletion must stop live ingestions for the group (F4)."""

    @pytest.mark.asyncio
    async def test_cancels_running_kg_sync_job_and_interrupts_runner(self):
        mgr = IngestionJobManager(settings=mock.Mock())
        mgr._use_redis = False

        started = asyncio.Event()
        interrupted = {"hit": False}

        async def runner(progress):
            started.set()
            try:
                await asyncio.sleep(30)
                return {}
            except asyncio.CancelledError:
                interrupted["hit"] = True
                raise

        job_id = await mgr.queue_kg_sync_job("task-1", runner)
        await asyncio.wait_for(started.wait(), timeout=2)

        cancelled = await mgr.cancel_jobs_for_task("task-1")

        assert cancelled == 1
        job = mgr._jobs[job_id]
        for _ in range(200):
            if job.status == JobStatus.CANCELLED:
                break
            await asyncio.sleep(0.01)
        assert job.status == JobStatus.CANCELLED
        for _ in range(200):
            if interrupted["hit"]:
                break
            await asyncio.sleep(0.01)
        assert interrupted["hit"] is True  # runner actually interrupted

    @pytest.mark.asyncio
    async def test_skips_terminal_jobs_and_other_tasks(self):
        mgr = IngestionJobManager(settings=mock.Mock())
        mgr._use_redis = False

        async def instant(progress):
            return {"ok": True}

        async def slow(progress):
            await asyncio.sleep(30)
            return {}

        done_id = await mgr.queue_kg_sync_job("task-1", instant)
        done = mgr._jobs[done_id]
        for _ in range(200):
            if done.status == JobStatus.COMPLETED:
                break
            await asyncio.sleep(0.01)

        other_id = await mgr.queue_kg_sync_job("task-2", slow)

        assert await mgr.cancel_jobs_for_task("task-1") == 0
        assert mgr._jobs[other_id].status == JobStatus.RUNNING

        # teardown: stop the slow job
        await mgr.cancel_jobs_for_task("task-2")

    @pytest.mark.asyncio
    async def test_unknown_task_cancels_nothing(self):
        mgr = IngestionJobManager(settings=mock.Mock())
        mgr._use_redis = False

        assert await mgr.cancel_jobs_for_task("no-such-task") == 0
