"""Episode-gate hook registry (llm-throughput-hardening SPEC A).

The low-level GraphitiIngestor must stay free of httpserver imports, so the
upper layer registers one async "before episode" hook at service startup.
``GraphitiIngestor.batch_ingest`` awaits the hook before every add_episode;
raising :class:`GateAborted` from the hook stops the batch cleanly — remaining
episodes are reported as aborted through ``IngestionResult.errors``, never
silently skipped.

The hook is the enforcement point for both foreground gating (pause ingestion
while a pipeline analysis is consuming the LLM server) and per-job timeouts.
"""

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

BeforeEpisodeHook = Callable[[dict], Awaitable[None]]

_hook: Optional[BeforeEpisodeHook] = None


class GateAborted(RuntimeError):
    """Raised by the before-episode hook to abort the remaining episodes."""


def set_before_episode_hook(hook: Optional[BeforeEpisodeHook]) -> None:
    """Register (or clear with None) the before-episode hook."""
    global _hook
    _hook = hook


def has_before_episode_hook() -> bool:
    return _hook is not None


async def run_before_episode(meta: dict) -> None:
    """Await the registered hook before one add_episode call.

    ``meta`` carries ``{"index", "total", "group_id", "episode"}``. No-op when
    no hook is installed (library usage without the HTTP service).
    """
    if _hook is None:
        return
    await _hook(meta)
