"""Foreground gate + episode gate (llm-throughput-hardening SPEC A)."""

from __future__ import annotations

import asyncio
import time

import pytest

from graphiti_integration import episode_gate
from graphiti_integration.graphiti_ingestor import GraphitiIngestor
from httpserver.services.ingestion_gate import (
    ForegroundGate,
    GateJobContext,
    before_episode_hook,
    gate_context,
)


# ---------------------------------------------------------------- fakes

class _FakeSettings:
    def __init__(self, *, enabled=True, poll=0.01, timeout_hours=0):
        self.graphiti_foreground_gate = enabled
        self.graphiti_gate_poll_seconds = poll
        self.graphiti_job_timeout_hours = timeout_hours


class _FakeCppBackend:
    def __init__(self, tasks):
        self.tasks = tasks
        self.failures_left = 0
        self.calls = 0

    async def list_tasks(self, **kwargs):
        self.calls += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            raise RuntimeError("backend down")
        return {"tasks": self.tasks}


def _task(status: str, phase: str) -> dict:
    return {"id": "t", "status": status, "progress": {"current_phase": phase}}


# ---------------------------------------------------------------- busy detection

@pytest.mark.asyncio
async def test_llm_phase_is_busy():
    backend = _FakeCppBackend([_task("RUNNING", "LLM_ANALYSIS")])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    assert await gate.is_foreground_busy() is True


@pytest.mark.asyncio
async def test_platform_phase_is_busy():
    backend = _FakeCppBackend([_task("RUNNING", "PLATFORM_ANALYSIS")])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    assert await gate.is_foreground_busy() is True


@pytest.mark.asyncio
async def test_extraction_phase_is_not_busy():
    backend = _FakeCppBackend([_task("RUNNING", "EVENT_EXTRACTION")])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    assert await gate.is_foreground_busy() is False


@pytest.mark.asyncio
async def test_finalizing_is_not_busy_so_tail_trigger_passes():
    backend = _FakeCppBackend([_task("RUNNING", "FINALIZING")])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    assert await gate.is_foreground_busy() is False


@pytest.mark.asyncio
async def test_completed_task_is_not_busy():
    backend = _FakeCppBackend([_task("COMPLETED", "LLM_ANALYSIS")])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    assert await gate.is_foreground_busy() is False


# ---------------------------------------------------------------- failure semantics

@pytest.mark.asyncio
async def test_first_poll_failure_counts_as_busy():
    backend = _FakeCppBackend([])
    backend.failures_left = 1
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    assert await gate.is_foreground_busy() is True


@pytest.mark.asyncio
async def test_three_consecutive_failures_degrade_to_idle():
    backend = _FakeCppBackend([])
    backend.failures_left = 3
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    # Failures accumulate across polls: conservative-busy at first, idle after
    # three consecutive failures (a dead backend means an idle LLM server).
    assert await gate.is_foreground_busy() is True
    assert await gate.is_foreground_busy() is True
    assert await gate.is_foreground_busy() is False
    assert backend.calls == 3


# ---------------------------------------------------------------- wait / force / timeout

@pytest.mark.asyncio
async def test_wait_if_busy_returns_immediately_when_idle():
    backend = _FakeCppBackend([])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    await asyncio.wait_for(gate.wait_if_busy("task-x"), timeout=1.0)


@pytest.mark.asyncio
async def test_wait_if_busy_pauses_until_foreground_clears():
    backend = _FakeCppBackend([_task("RUNNING", "LLM_ANALYSIS")])
    gate = ForegroundGate(_FakeSettings(poll=0.01), backend.list_tasks)

    async def clear_soon():
        await asyncio.sleep(0.05)
        backend.tasks = [_task("COMPLETED", "FINALIZING")]

    asyncio.create_task(clear_soon())
    phases = []

    ctx = GateJobContext("j1", "task-x", set_phase=lambda p: phases.append(p) or asyncio.sleep(0))
    await asyncio.wait_for(gate.wait_if_busy("task-x", ctx), timeout=2.0)
    assert phases  # entered and left the waiting_idle phase


@pytest.mark.asyncio
async def test_force_context_skips_wait():
    backend = _FakeCppBackend([_task("RUNNING", "LLM_ANALYSIS")])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    gate_context.set(GateJobContext("j1", "task-x", force=True))
    try:
        await asyncio.wait_for(before_episode_hook({"group_id": "task-x"}), timeout=0.5)
    finally:
        gate_context.set(None)


@pytest.mark.asyncio
async def test_timeout_aborts_via_hook():
    backend = _FakeCppBackend([])
    gate = ForegroundGate(_FakeSettings(), backend.list_tasks)
    expired = GateJobContext("j1", "task-x", timeout_seconds=1.0)
    expired.started_at = time.monotonic() - 60.0  # budget exhausted long ago
    gate_context.set(expired)
    try:
        with pytest.raises(episode_gate.GateAborted):
            await before_episode_hook({"group_id": "task-x"})
        assert expired.timed_out is True
    finally:
        gate_context.set(None)


@pytest.mark.asyncio
async def test_disabled_gate_skips_wait():
    backend = _FakeCppBackend([_task("RUNNING", "LLM_ANALYSIS")])
    gate = ForegroundGate(_FakeSettings(enabled=False), backend.list_tasks)
    gate_context.set(GateJobContext("j1", "task-x"))
    try:
        await asyncio.wait_for(before_episode_hook({"group_id": "task-x"}), timeout=0.5)
    finally:
        gate_context.set(None)


# ---------------------------------------------------------------- batch abort

class _RecordingIngestor(GraphitiIngestor):
    """Ingestor stand-in that counts episodes instead of calling Graphiti."""

    def __init__(self, episodes_before_abort: int = 2):
        self.done = 0
        self._abort_after = episodes_before_abort
        self._initialized = True  # skip batch_ingest's initialize() call

    async def ingest_episode(self, episode, group_id=None):
        self.done += 1


class _Episode:
    def __init__(self, name: str):
        self.name = name
        self.file_path = f"/f/{name}"


@pytest.mark.asyncio
async def test_batch_ingest_aborts_and_reports_remaining():
    ingestor = _RecordingIngestor()
    episodes = [_Episode(f"ep{i}") for i in range(5)]
    calls = {"n": 0}

    async def hook(meta):
        calls["n"] += 1
        if meta["index"] == 2:
            raise episode_gate.GateAborted("foreground busy too long")

    episode_gate.set_before_episode_hook(hook)
    try:
        result = await ingestor.batch_ingest(episodes, group_id="g")
    finally:
        episode_gate.set_before_episode_hook(None)

    assert ingestor.done == 2  # episodes 0,1 ran; ep2's hook aborted before ingest
    assert result.failed == 3
    assert result.successful == 2  # the two episodes that ran before the abort
    assert any("aborted by episode gate" in e["error"] for e in result.errors)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_batch_ingest_without_hook_processes_all():
    ingestor = _RecordingIngestor()
    episodes = [_Episode(f"ep{i}") for i in range(3)]
    result = await ingestor.batch_ingest(episodes, group_id="g")
    assert result.successful == 3  # the fake ingest_episode never raises
    assert ingestor.done == 3
    assert result.failed == 0
