"""Graph materialization manifest + the atomic admission pipeline
(P6A §24-§32, §41, §59, §61, §66).

The manifest is the State Plane record that makes SQLite the logical
validity authority for graph content: ``admit`` only means "allowed to
materialize" (§18) — Graphiti/Neo4j availability lives in the manifest
lifecycle, never in the admission decision and never in Evidence or
Finding validity (§31).

``admit_graph_candidate`` is the §66 explicit entry (P6A never auto-
materializes Findings, and the PLAN→EXECUTE→INTEGRATE→EVALUATE loop is
untouched). One transaction persists the immutable admission decision,
the frozen episode (admit only) and the queued manifest — a half-written
admission unit is structurally impossible (§26). Identical replays
produce the same decision/episode/manifest ids and no duplicate queued
materialization (§28).

Graph manifest mutation is NOT a Working State semantic revision (§45):
these operations consume zero Working State revisions.
"""

from __future__ import annotations

import hashlib
import enum
from typing import Callable, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from .agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionDecisionV1,
    GraphAdmissionPolicy,
    GraphBudgetState,
)
from .agent_graph_candidate import (
    GraphCandidateV1,
    GraphCandidateValidator,
)
from .agent_graph_episode import freeze_episode
from .agent_runtime import AgentRuntimeRepository, canonical_state_json

MANIFEST_STATE_MACHINE_VERSION = "graph-materialization-manifest:v1"

DEFAULT_BACKEND_KIND = "graphiti"


class ManifestTransitionError(ValueError):
    """Illegal manifest lifecycle transition (also trigger-enforced)."""


_LEGAL_MANIFEST_TRANSITIONS = {
    "queued": {"running", "invalidated"},
    "running": {"active", "failed", "invalidated"},
    "active": {"stale", "invalidated", "superseded"},
    "failed": {"superseded"},
    "stale": {"superseded"},
    "invalidated": set(),
    "superseded": set(),
}


def manifest_status_recorded(
    manifest_id: str, backend_kind: str, investigation_id: str
) -> str:
    """Deterministic manifest id: identical admitted input replays to the
    same queued manifest instead of duplicating it (§28)."""
    digest = hashlib.sha256(
        canonical_state_json({
            "episode_id": manifest_id,
            "backend_kind": backend_kind,
            "investigation_id": investigation_id,
        }).encode("utf-8")
    ).hexdigest()
    return f"gm:{digest[:24]}"


def propose_graph_candidate(
    runtime: AgentRuntimeRepository,
    investigation_id: str,
    candidate: GraphCandidateV1,
    *,
    validator: Optional[GraphCandidateValidator] = None,
    evidence_ref_parser: Optional[Callable[[str], None]] = None,
    run_id: Optional[str] = None,
) -> dict:
    """§66 explicit candidate proposal: validate, then persist the
    immutable candidate row. Returns the durable row plus any validator
    violations (invalid candidates are still recorded - the admission
    pipeline will refuse them deterministically)."""
    validator = validator or GraphCandidateValidator()
    violations = validator.validate(
        candidate,
        task_id=candidate.task_id,
        investigation_id=investigation_id,
        evidence_ref_parser=evidence_ref_parser,
    )
    outcome = runtime.record_graph_candidates(
        investigation_id, [candidate.to_row()], run_id=run_id
    )
    return {
        "candidate": candidate,
        "recorded": outcome["inserted_count"] == 1,
        "violations": violations,
    }


def admit_graph_candidate(
    runtime: AgentRuntimeRepository,
    investigation_id: str,
    *,
    candidate_id: str,
    policy: Optional[GraphAdmissionPolicy] = None,
    finding_resolver: Optional[Callable[[str], Optional[Mapping]]] = None,
    budget_state: Optional[GraphBudgetState] = None,
    source_revision: Optional[int] = None,
    source_state_hash: Optional[str] = None,
    backend_kind: str = DEFAULT_BACKEND_KIND,
    run_id: Optional[str] = None,
) -> dict:
    """§26 atomic admission pipeline over a durably recorded candidate.

    ONE transaction: revalidate the candidate bindings, evaluate the
    policy, INSERT the immutable decision, and - for admit - INSERT the
    frozen episode plus the queued manifest, with trajectory events.
    defer/not_admitted persist ONLY the decision (§27)."""
    candidate_row = runtime.get_graph_candidate(investigation_id, candidate_id)
    if candidate_row is None:
        raise ValueError(
            f"unknown graph candidate for this task: {candidate_id!r}"
        )
    candidate = GraphCandidateV1.from_row(candidate_row)
    policy = policy or GraphAdmissionPolicy()

    decision = policy.evaluate(
        candidate,
        finding_resolver=finding_resolver,
        budget_state=budget_state,
    )

    episode_row = None
    if decision.decision is GraphAdmissionDecision.ADMIT:
        episode = freeze_episode(
            [candidate],
            {candidate.candidate_id: decision},
            task_id=candidate.task_id,
            investigation_id=candidate.investigation_id,
            source_revision=source_revision,
            source_state_hash=source_state_hash,
            policy_version=decision.policy_version,
            policy_hash=decision.policy_hash,
        )
        episode_row = episode.to_row()
        manifest_id = manifest_status_recorded(
            episode.episode_id, backend_kind, candidate.investigation_id
        )
        manifest_hash_input = {
            "episode_id": episode.episode_id,
            "episode_hash": episode.input_hash,
            "backend_kind": backend_kind,
        }
        manifest_input_hash = hashlib.sha256(
            canonical_state_json(manifest_hash_input).encode("utf-8")
        ).hexdigest()

    outcome = runtime.commit_graph_admission(
        investigation_id,
        decision_row=decision.to_row(),
        episode_row=episode_row,
        manifest=(
            {
                "materialization_id": manifest_id,
                "episode_id": episode_row["episode_id"],
                "episode_hash": episode_row["input_hash"],
                "backend_kind": backend_kind,
                "status": "queued",
                "input_hash": manifest_input_hash,
            }
            if episode_row is not None
            else None
        ),
        run_id=run_id,
    )
    return {
        "decision": decision,
        "episode": episode_row,
        "materialization_id": (
            manifest_id if episode_row is not None else None
        ),
        "commit": outcome,
    }


class ManifestStateMachine:
    """§29 lifecycle guard helpers (the DB triggers are the backstop).

    queued -> running; running -> active|failed; active ->
    stale|invalidated|superseded; failed/stale -> superseded. Terminal
    states never return to running - retries create NEW materialization
    attempts (P6B)."""

    LEGAL = _LEGAL_MANIFEST_TRANSITIONS

    @staticmethod
    def assert_transition(current: str, target: str) -> None:
        if target not in _LEGAL_MANIFEST_TRANSITIONS.get(current, set()):
            raise ManifestTransitionError(
                f"illegal manifest transition {current!r} -> {target!r}"
            )


__all__ = [
    "DEFAULT_BACKEND_KIND",
    "MANIFEST_STATE_MACHINE_VERSION",
    "ManifestStateMachine",
    "ManifestTransitionError",
    "admit_graph_candidate",
    "manifest_status_recorded",
    "propose_graph_candidate",
]
