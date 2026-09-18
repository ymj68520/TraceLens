"""Foreground gate for Graphiti episode ingestion (llm-throughput-hardening SPEC A).

A full ingestion can hold the single LM Studio server for hours (one
``add_episode`` ≈ 4–7 LLM calls; 79 episodes ≈ 6 h). When a pipeline analysis
runs concurrently, per-file LLM latency degrades from ~9 s to 8–26 min
(2026-09-16 measurements). This module gates ingestion at episode boundaries:

- **Busy** means: any task whose ``progress.current_phase`` is an LLM-consuming
  phase (``LLM_ANALYSIS`` / ``PLATFORM_ANALYSIS`` — verified to be the only two
  of eight TaskPhase values that touch the LLM server).
- The worker awaits :func:`wait_if_busy` between episodes; an in-flight episode
  is deliberately exempt (add_episode is an opaque multi-call black box).
- ``force`` jobs bypass the wait entirely (manual escape hatch).
- Poll failures: the first failed poll counts as busy (conservative); three or
  more consecutive failures count as idle — a dead C++ backend means an idle
  LLM server, and ingestion must not hang forever.
- Job timeout (``GRAPHITI_JOB_TIMEOUT_HOURS``) aborts the batch at the same
  episode boundary and surfaces as a FAILED job.

The hook is registered into ``graphiti_integration.episode_gate`` at app
startup (:func:`install_episode_gate`); the per-job context travels via a
``ContextVar`` set by the job worker / kg_sync runner.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from graphiti_integration import episode_gate

from ..config import Settings

logger = logging.getLogger(__name__)

# Serialized TaskPhase values that consume the LM Studio server. FINALIZING is
# deliberately absent: a task tail-triggers its own ingestion while still in
# FINALIZING, and that must not self-block.
LLM_CONSUMING_PHASES = {"LLM_ANALYSIS", "PLATFORM_ANALYSIS"}

RUNNING_TASK_STATUSES = {"RUNNING", "running"}


@dataclass
class GateJobContext:
    """Per-job gate state travelling through the ingestion call chain."""

    job_id: str
    label: str
    force: bool = False
    timeout_seconds: float = 0.0  # 0 = unlimited
    started_at: float = field(default_factory=time.monotonic)
    timed_out: bool = False

    #: async callable(phase: Optional[str]) -> None — None exits waiting state.
    set_phase: Optional[Callable[[str], Awaitable[None]]] = None

    def check_timeout(self) -> None:
        """Raise GateAborted when the job exceeded its time budget."""
        if self.timeout_seconds <= 0:
            return
        elapsed = time.monotonic() - self.started_at
        if elapsed >= self.timeout_seconds:
            self.timed_out = True
            raise episode_gate.GateAborted(
                f"job timeout after {elapsed / 3600.0:.2f}h "
                f"(GRAPHITI_JOB_TIMEOUT_HOURS budget)"
            )


gate_context: ContextVar[Optional[GateJobContext]] = ContextVar(
    "ingestion_gate_context", default=None
)


class ForegroundGate:
    """Polls the C++ task list and pauses episode ingestion while it's busy."""

    def __init__(self, settings: Settings, list_tasks: Callable[..., Awaitable[dict]]):
        self._settings = settings
        self._list_tasks = list_tasks
        self._consecutive_failures = 0
        self._logged_waiting = False

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._settings, "graphiti_foreground_gate", True))

    @property
    def poll_seconds(self) -> float:
        return float(getattr(self._settings, "graphiti_gate_poll_seconds", 30))

    async def is_foreground_busy(self) -> bool:
        """True when any task is in an LLM-consuming phase.

        Failure semantics (SPEC A4): the first failed poll is treated as busy
        (conservative — do not race the pipeline on a transient blip); three or
        more consecutive failures are treated as idle so a dead backend can
        never wedge ingestion permanently.
        """
        try:
            result = await self._list_tasks(page=1, page_size=200, timeout=5.0, max_retries=0)
            self._consecutive_failures = 0
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                logger.warning(
                    f"Foreground gate: {self._consecutive_failures} consecutive poll "
                    f"failures — treating foreground as idle ({e})"
                )
                return False
            logger.warning(f"Foreground gate: task poll failed ({e}) — treating as busy")
            return True

        tasks: Any = result
        if isinstance(result, dict):
            # Serializers wrap the list under different keys; scan known shapes.
            tasks = result.get("tasks") or result.get("items") or result.get("data") or []
        if not isinstance(tasks, list):
            tasks = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("status", "")).upper() not in RUNNING_TASK_STATUSES:
                continue
            phase = str((task.get("progress") or {}).get("current_phase", ""))
            if phase in LLM_CONSUMING_PHASES:
                return True
        return False

    async def wait_if_busy(self, label: str, ctx: Optional[GateJobContext] = None) -> None:
        """Block until the foreground is idle (or polling degrades to idle)."""
        if not self.enabled:
            return
        waited = False
        while True:
            if ctx is not None:
                ctx.check_timeout()
            if not await self.is_foreground_busy():
                break
            if not waited:
                waited = True
                logger.info(
                    f"Foreground gate: LLM analysis running — pausing ingestion "
                    f"of {label} (poll every {self.poll_seconds:.0f}s)"
                )
                if ctx is not None and ctx.set_phase is not None:
                    try:
                        await ctx.set_phase("waiting_idle")
                    except Exception as e:
                        logger.warning(f"Foreground gate: could not update job phase: {e}")
            await asyncio.sleep(self.poll_seconds)

        if waited:
            logger.info(f"Foreground gate: foreground idle — resuming ingestion of {label}")
            if ctx is not None and ctx.set_phase is not None:
                try:
                    await ctx.set_phase(None)
                except Exception as e:
                    logger.warning(f"Foreground gate: could not restore job phase: {e}")
        self._logged_waiting = False


_gate: Optional[ForegroundGate] = None


async def before_episode_hook(meta: dict) -> None:
    """Enforce timeout + foreground gate before one add_episode call."""
    gate = _gate
    ctx = gate_context.get()
    if ctx is not None:
        # Timeout applies regardless of the on/off switch — it is a runaway
        # guard, not a contention policy.
        ctx.check_timeout()
    if gate is None or not gate.enabled:
        return
    if ctx is not None and ctx.force:
        return
    label = ctx.label if ctx is not None else str(meta.get("group_id", ""))
    await gate.wait_if_busy(label, ctx)


def install_episode_gate(settings: Settings, list_tasks: Callable[..., Awaitable[dict]]) -> ForegroundGate:
    """Create the gate and register the before-episode hook."""
    global _gate
    _gate = ForegroundGate(settings, list_tasks)
    episode_gate.set_before_episode_hook(before_episode_hook)
    logger.info(
        f"Episode gate installed (enabled={_gate.enabled}, "
        f"poll={_gate.poll_seconds:.0f}s)"
    )
    return _gate


def uninstall_episode_gate() -> None:
    """Drop the gate and hook (app shutdown / test isolation).

    The registry is process-global; without this, a shut-down app's gate —
    holding its dead cpp_backend — keeps answering episode hooks in whatever
    runs next in the same process.
    """
    global _gate
    _gate = None
    episode_gate.set_before_episode_hook(None)


def get_gate() -> Optional[ForegroundGate]:
    return _gate


def make_job_context(
    settings: Settings,
    job_id: str,
    label: str,
    force: bool = False,
    set_phase: Optional[Callable[[str], Awaitable[None]]] = None,
) -> GateJobContext:
    """Build the per-job gate context from settings."""
    raw_timeout = getattr(settings, "graphiti_job_timeout_hours", 0)
    try:
        hours = float(raw_timeout)
    except (TypeError, ValueError):
        hours = 0.0
    return GateJobContext(
        job_id=job_id,
        label=label,
        force=force,
        timeout_seconds=hours * 3600.0 if hours > 0 else 0.0,
        set_phase=set_phase,
    )
