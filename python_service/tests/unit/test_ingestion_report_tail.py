"""Ingestion completion fires the pipeline-tail report callback (and only then).

Covers both completion paths: the self-running kg_sync job and the worker
loop's FULL ingestion (the initial analysis pipeline's own tail).
"""

from __future__ import annotations

import asyncio

import pytest

from httpserver.config import get_settings
from httpserver.services.ingestion_job_manager import IngestionJobManager


class _Rec:
    def __init__(self):
        self.tasks: list[str] = []

    async def __call__(self, task_id: str) -> None:
        self.tasks.append(task_id)


def _make_manager(monkeypatch) -> IngestionJobManager:
    manager = IngestionJobManager(get_settings())

    async def _save_job(job):
        pass

    async def _update_job_status(job_id, status, current_phase=None,
                                 progress=None, error=None, result=None):
        return None

    monkeypatch.setattr(manager, "_save_job", _save_job)
    monkeypatch.setattr(manager, "_update_job_status", _update_job_status)
    return manager


@pytest.mark.asyncio
async def test_tail_callback_fires_on_completed(monkeypatch):
    manager = _make_manager(monkeypatch)
    rec = _Rec()
    manager.on_ingestion_completed = rec

    async def runner(progress):
        await progress("ingesting_episodes", "...")
        return {"episodes_successful": 2}

    await manager._run_kg_sync_job("job-1", runner, "task-A")
    # fire-and-forget tail task needs a loop tick to run
    await asyncio.sleep(0.05)
    assert rec.tasks == ["task-A"]


@pytest.mark.asyncio
async def test_tail_callback_not_fired_on_failure(monkeypatch):
    manager = _make_manager(monkeypatch)
    rec = _Rec()
    manager.on_ingestion_completed = rec

    async def runner(progress):
        raise RuntimeError("ingestion boom")

    await manager._run_kg_sync_job("job-2", runner, "task-B")
    await asyncio.sleep(0.05)
    assert rec.tasks == []


@pytest.mark.asyncio
async def test_tail_callback_error_does_not_break_job(monkeypatch):
    manager = _make_manager(monkeypatch)

    async def broken(task_id):
        raise RuntimeError("report tail boom")

    manager.on_ingestion_completed = broken
    statuses = []

    async def runner(progress):
        return {"ok": True}

    async def _update(job_id, status, current_phase=None,
                      progress=None, error=None, result=None):
        statuses.append((status, current_phase))

    monkeypatch.setattr(manager, "_update_job_status", _update)
    await manager._run_kg_sync_job("job-3", runner, "task-C")
    await asyncio.sleep(0.05)
    # the job itself still completed
    assert any(s.name == "COMPLETED" for s, _p in statuses)


@pytest.mark.asyncio
async def test_worker_full_ingestion_fires_tail(monkeypatch):
    manager = _make_manager(monkeypatch)
    rec = _Rec()
    manager.on_ingestion_completed = rec

    async def _force(job_id):
        return False

    async def _full(job_id, task_id):
        return None

    monkeypatch.setattr(manager, "_job_force_flag", _force)
    monkeypatch.setattr(manager, "_process_full_ingestion", _full)
    await manager._process_job({
        "job_id": "job-4", "task_id": "task-D", "mode": "full",
    })
    await asyncio.sleep(0.05)
    assert rec.tasks == ["task-D"]


@pytest.mark.asyncio
async def test_worker_non_full_mode_does_not_fire_tail(monkeypatch):
    manager = _make_manager(monkeypatch)
    rec = _Rec()
    manager.on_ingestion_completed = rec

    async def _force(job_id):
        return False

    async def _analyzed_only(job_id, task_id):
        return None

    monkeypatch.setattr(manager, "_job_force_flag", _force)
    monkeypatch.setattr(manager, "_process_analyzed_only", _analyzed_only)
    await manager._process_job({
        "job_id": "job-5", "task_id": "task-E", "mode": "analyzed_only",
    })
    await asyncio.sleep(0.05)
    assert rec.tasks == []
