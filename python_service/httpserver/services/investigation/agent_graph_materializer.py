"""GraphMaterializationExecutor (P6B §12-§32, §58-§62, §80-§87).

Executes ONE queued manifest at a time through the frozen pipeline:

    load queued manifest (trusted store revalidated)
    -> atomic queued->running claim (CAS; second worker is a no-op)
    -> load the persisted frozen episode, verify identity/hash
    -> deterministic adapter translation
    -> backend ingest (the ONLY backend touchpoint)
    -> backend provenance binding by deterministic episode-name lookup
    -> completion-time canonical revalidation (§17-§19)
    -> activate (atomic bindings+active) or explicit failed/
       invalidated/stale - never a bare "Graphiti said ok"

Explicit dispatch only (§15): initialization performs recovery (running
-> failed(runtime_restart); queued stays queued) and NEVER auto-ingests.
Graph is an optional enhancement: every failure here is a manifest
failure - Evidence, Findings, review, Working State and Finalization are
untouched (§29/§87), and zero Working State revisions are consumed (§86).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Optional

from .agent_graph_admission import GraphAdmissionPolicy
from .agent_graph_backend import (
    FakeGraphBackend,
    GraphBackend,
    GraphMaterializationAdapter,
)
from .agent_runtime import AgentRuntimeRepository

EXECUTOR_VERSION = "graph-materialization-executor:v1"

# §21 normalized failure codes
GRAPH_BACKEND_UNAVAILABLE = "GRAPH_BACKEND_UNAVAILABLE"
GRAPH_BACKEND_TIMEOUT = "GRAPH_BACKEND_TIMEOUT"
GRAPH_BACKEND_INGEST_FAILED = "GRAPH_BACKEND_INGEST_FAILED"
GRAPH_INPUT_INVALID = "GRAPH_INPUT_INVALID"
GRAPH_EPISODE_HASH_MISMATCH = "GRAPH_EPISODE_HASH_MISMATCH"
GRAPH_PROVENANCE_UNRESOLVED = "GRAPH_PROVENANCE_UNRESOLVED"
GRAPH_TASK_GONE = "GRAPH_TASK_GONE"
GRAPH_INTERNAL_FAILURE = "GRAPH_INTERNAL_FAILURE"


class GraphMaterializationExecutor:
    """Explicit-dispatch executor over the frozen P6A state machine."""

    VERSION = EXECUTOR_VERSION

    def __init__(
        self,
        *,
        runtime: AgentRuntimeRepository,
        backend: Optional[GraphBackend] = None,
        backend_factory: Optional[Callable[[], GraphBackend]] = None,
        finding_resolver: Optional[Callable[[str], Optional[Mapping]]] = None,
        evidence_resolver: Optional[Callable[[str], bool]] = None,
        max_parallel: int = 2,
    ):
        self._runtime = runtime
        self._backend = backend
        self._backend_factory = backend_factory
        self._finding_resolver = finding_resolver
        self._evidence_resolver = evidence_resolver
        self.max_parallel = max_parallel
        self._adapter = GraphMaterializationAdapter()
        self._dispatching = False

    # -- backend (lazy, §28) ---------------------------------------------

    def _get_backend(self) -> GraphBackend:
        if self._backend is None:
            if self._backend_factory is None:
                self._backend = FakeGraphBackend()
            else:
                self._backend = self._backend_factory()
        return self._backend

    # -- lifecycle (§26/§27/§62) -----------------------------------------

    def initialize(self) -> dict:
        """Recovery ONLY: running -> failed(runtime_restart); queued stays
        queued. No backend client is constructed, nothing auto-ingests."""
        expired = self._runtime.fail_running_graph_materializations(
            failure_code="GRAPH_RUNTIME_RESTART"
        )
        return {"running_failed": expired, "ingested": 0}

    async def shutdown(self) -> None:
        """Stop dispatching; owned local state is dropped. No graph
        deletion, no Evidence invalidation (§62)."""
        self._dispatching = False

    # -- dispatch (§15) ---------------------------------------------------

    async def execute_batch(
        self, pairs
    ) -> list[dict]:
        """pairs: (investigation_id, materialization_id)."""
        self._dispatching = True
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def _one(pair):
            investigation_id, mid = pair
            async with semaphore:
                return await self.execute_materialization(
                    investigation_id, mid
                )

        try:
            return list(
                await asyncio.gather(
                    *(_one(pair) for pair in materialization_ids)
                )
            )
        finally:
            self._dispatching = False

    async def execute_materialization(
        self, investigation_id: str, materialization_id: str
    ) -> dict:
        runtime = self._runtime
        # §20 task lifecycle: the trusted task-owned store must still hold
        # this investigation before ANY execution step
        if runtime.get_investigation(investigation_id) is None:
            return {
                "materialization_id": materialization_id,
                "outcome": "skipped",
                "failure_code": GRAPH_TASK_GONE,
            }

        # §59 atomic claim: queued -> running; a second worker is a no-op
        if not runtime.claim_graph_materialization(
            investigation_id, materialization_id
        ):
            return {
                "materialization_id": materialization_id,
                "outcome": "conflict",
                "failure_code": None,
            }

        # §7 frozen input rule: only persisted rows from here on
        manifest = runtime.get_graph_materialization(
            investigation_id, materialization_id
        )
        episode = runtime.get_graph_episode(
            investigation_id, manifest["episode_id"]
        )
        if episode is None:
            return await self._fail(
                investigation_id, materialization_id,
                expected_status="running",
                code=GRAPH_INPUT_INVALID,
                detail="episode row missing",
            )
        if episode["input_hash"] != manifest["episode_hash"]:
            return await self._fail(
                investigation_id, materialization_id,
                expected_status="running",
                code=GRAPH_EPISODE_HASH_MISMATCH,
                detail="frozen episode hash mismatch",
            )

        # deterministic translation (§6): frozen slice only
        backend_episode = self._adapter.translate(
            _episode_model_shim(episode),
            materialization_id=materialization_id,
            group_id=runtime.task_id,
        )

        try:
            backend = self._get_backend()
            outcome = await backend.ingest(backend_episode)
        except Exception as exc:
            return await self._fail(
                investigation_id, materialization_id,
                expected_status="running",
                code=GRAPH_BACKEND_UNAVAILABLE,
                detail=f"{type(exc).__name__}: {exc}"[:300],
            )
        if not outcome.success:
            return await self._fail(
                investigation_id, materialization_id,
                expected_status="running",
                code=outcome.failure_code or GRAPH_BACKEND_INGEST_FAILED,
                detail="; ".join(outcome.errors)[:300],
            )

        # §10/§13 provenance binding: deterministic episode-name lookup
        backend_ref = await backend.find_episode_ref(
            backend_episode.episode_name, backend_episode.group_id
        )
        if not backend_ref:
            return await self._fail(
                investigation_id, materialization_id,
                expected_status="running",
                code=GRAPH_PROVENANCE_UNRESOLVED,
                detail="backend episode ref unresolvable",
            )

        # §17-§19 completion-time canonical revalidation
        invalidation = self._revalidate_canonical(episode)
        if invalidation is not None:
            target, reason = invalidation
            runtime.advance_graph_materialization(
                investigation_id, materialization_id,
                to_status=target,
                failure_code=reason if target == "invalidated" else None,
                failure_summary=reason,
            )
            return {
                "materialization_id": materialization_id,
                "outcome": target,
                "failure_code": reason,
            }

        # §81 atomic activation: bindings + active + trajectory
        bindings = [
            {
                "binding_id": f"gbind:{materialization_id}:episode",
                "backend_kind": manifest["backend_kind"],
                "backend_group_ref": backend_episode.group_id,
                "backend_episode_ref": backend_ref,
                "backend_episode_name": backend_episode.episode_name,
                "backend_object_kind": "episode",
                "semantic_unit_id": None,
                "provenance": dict(backend_episode.provenance_token),
            }
        ]
        runtime.activate_graph_materialization(
            investigation_id, materialization_id,
            expected_episode_hash=manifest["episode_hash"],
            bindings=bindings,
            backend_episode_ref=backend_ref,
        )
        return {
            "materialization_id": materialization_id,
            "outcome": "active",
            "backend_episode_ref": backend_ref,
        }

    # -- internals --------------------------------------------------------

    def _revalidate_canonical(self, episode: Mapping) -> Optional[tuple]:
        """§17-§19: returns (target_status, reason) when completion-time
        canonical state forbids activation; None when still eligible."""
        findings = {
            ref: self._finding_resolver(ref)
            for ref in episode["finding_refs"]
        } if self._finding_resolver else {}
        for ref, finding in findings.items():
            if finding is None:
                return ("invalidated", "FINDING_MISSING")
            if finding["status"] == "rejected":
                return ("invalidated", "FINDING_REJECTED")
        if self._evidence_resolver is not None:
            for ref in episode["evidence_refs"]:
                try:
                    if not self._evidence_resolver(
                        self._runtime.task_id, ref
                    ):
                        return ("invalidated", "EVIDENCE_MISSING")
                except Exception:
                    return ("invalidated", "EVIDENCE_MISSING")
        for ref, finding in findings.items():
            if finding["status"] == "accepted" and (
                episode["review_statuses"].get(_unit_for(episode, ref))
                == "review_pending"
            ):
                return ("stale", "REVIEW_STATUS_CHANGED")
        return None

    async def _fail(
        self,
        investigation_id: str,
        materialization_id: str,
        *,
        expected_status: str,
        code: str,
        detail: str,
    ) -> dict:
        self._runtime.fail_graph_materialization(
            investigation_id, materialization_id,
            expected_status=expected_status,
            failure_code=code,
            failure_summary=detail,
        )
        return {
            "materialization_id": materialization_id,
            "outcome": "failed",
            "failure_code": code,
        }


def _episode_model_shim(episode: Mapping) -> ForensicEpisodeShim:
    return ForensicEpisodeShim(episode)


class ForensicEpisodeShim:
    """Read-side adapter over the persisted episode row exposing the
    attribute surface the deterministic translator expects."""

    def __init__(self, row: Mapping):
        self.episode_version = row["episode_version"]
        self.episode_id = row["episode_id"]
        self.input_hash = row["input_hash"]
        self.candidate_ids = row["candidate_ids"]
        self.admission_decision_ids = row["admission_decision_ids"]
        self.review_statuses = row["review_statuses"]
        self.finding_refs = row["finding_refs"]
        self.correlation_refs = row["correlation_refs"]
        self.evidence_refs = row["evidence_refs"]
        self.source_revision = row["source_revision"]
        self.source_state_hash = row["source_state_hash"]
        self.policy_version = row["policy_version"]
        self.policy_hash = row["policy_hash"]
        from .agent_graph_episode import GraphSemanticUnit

        self.semantic_units = [
            GraphSemanticUnit(**unit) for unit in row["semantic_units"]
        ]


def _unit_for(episode: Mapping, finding_ref: str) -> Optional[str]:
    for unit in episode["semantic_units"]:
        if finding_ref in (unit.get("finding_refs") or []):
            return unit.get("unit_id")
    return None


__all__ = [
    "EXECUTOR_VERSION",
    "GraphMaterializationExecutor",
]
