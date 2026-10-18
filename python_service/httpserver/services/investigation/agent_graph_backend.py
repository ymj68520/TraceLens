"""GraphMaterializationAdapter + backend boundary (P6B §5-§11, §66).

Graphiti ingest is TEXT + LLM EXTRACTION — it cannot consume a
structured forensic episode and it returns only counts, never object
ids.  This module is the explicit adapter boundary between TraceLens
and any graph backend:

    ForensicGraphEpisodeV1 (persisted, frozen)
        -> GraphMaterializationAdapter (deterministic, no LLM, no DB)
        -> GraphBackendEpisodeV1 (canonical payload + provenance token)
        -> GraphBackend.ingest (the ONLY backend touchpoint)
        -> BackendIngestOutcome

Because Graphiti returns no object ids, the backend episode NAME is
deterministic (``tracelens:materialization:{id}``), so the provenance
binding can be established by looking the episode back up by name
(§11 Strategy A/B hybrid).  A backend that cannot even confirm the
deterministic episode name yields GRAPH_PROVENANCE_UNRESOLVED -> the
materialization FAILS; results are then locator_only at best (§13).
Graphiti is a derived index executor, never a semantic authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_graph_episode import ForensicGraphEpisodeV1
from .agent_runtime import canonical_state_json

GRAPH_BACKEND_EPISODE_VERSION = "graph-backend-episode:v1"
ADAPTER_VERSION = "graph-materialization-adapter:v1"


def deterministic_episode_name(materialization_id: str) -> str:
    return f"tracelens:materialization:{materialization_id}"


class GraphBackendEpisodeV1(BaseModel):
    """§6 canonical backend payload (frozen, deterministic, hashed)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_version: str = GRAPH_BACKEND_EPISODE_VERSION

    materialization_id: str
    episode_id: str
    episode_hash: str

    group_id: str  # task-scoped namespace (§53)
    episode_name: str

    # per-unit canonical payload: name/body/source_description
    units: tuple[Mapping[str, Any], ...] = ()

    # machine-readable provenance token (never free-text only, §8)
    provenance_token: Mapping[str, Any] = {}

    adapter_version: str = ADAPTER_VERSION
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        payload = {
            "payload_version": GRAPH_BACKEND_EPISODE_VERSION,
            "materialization_id": data.get("materialization_id"),
            "episode_id": data.get("episode_id"),
            "episode_hash": data.get("episode_hash"),
            "group_id": data.get("group_id"),
            "episode_name": data.get("episode_name"),
            "unit_names": sorted(
                str(unit.get("unit_name", ""))
                for unit in (data.get("units") or [])
            ),
            "provenance_token": data.get("provenance_token") or {},
            "adapter_version": ADAPTER_VERSION,
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data["input_hash"] = input_hash
        return data


class GraphMaterializationAdapter:
    """§6 deterministic translation: frozen episode -> backend payload.

    Reads ONLY the persisted episode mapping given to it — no live DB
    reads, no LLM, no admission re-evaluation (§7 frozen input rule)."""

    VERSION = ADAPTER_VERSION

    def translate(
        self,
        episode: ForensicGraphEpisodeV1,
        *,
        materialization_id: str,
        group_id: str,
    ) -> GraphBackendEpisodeV1:
        units = []
        for unit in episode.semantic_units:
            units.append({
                "unit_name": (
                    f"{deterministic_episode_name(materialization_id)}"
                    f":unit:{unit.unit_id}"
                ),
                "unit_id": unit.unit_id,
                "episode_name": deterministic_episode_name(
                    materialization_id
                ),
                "body": json.dumps(
                    {
                        "assertion": unit.semantic_summary,
                        "candidate_kind": unit.candidate_kind,
                        "evidence_refs": list(unit.evidence_refs),
                        "finding_refs": list(unit.finding_refs),
                        "correlation_refs": list(unit.correlation_refs),
                        "occurrence_refs": list(unit.occurrence_refs),
                        "review_status": unit.review_status,
                        "verification_refs": list(unit.verification_refs),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "source_description": (
                    "TraceLens frozen forensic graph episode semantic unit"
                ),
            })
        provenance_token = {
            "adapter_version": self.VERSION,
            "episode_version": episode.episode_version,
            "episode_id": episode.episode_id,
            "episode_hash": episode.input_hash,
            "candidate_ids": list(episode.candidate_ids),
            "admission_decision_ids": list(episode.admission_decision_ids),
            "review_statuses": dict(episode.review_statuses),
            "finding_refs": list(episode.finding_refs),
            "correlation_refs": list(episode.correlation_refs),
            "evidence_refs": list(episode.evidence_refs),
            "source_revision": episode.source_revision,
            "source_state_hash": episode.source_state_hash,
            "policy_version": episode.policy_version,
            "policy_hash": episode.policy_hash,
        }
        return GraphBackendEpisodeV1(
            materialization_id=materialization_id,
            episode_id=episode.episode_id,
            episode_hash=episode.input_hash,
            group_id=group_id,
            episode_name=deterministic_episode_name(materialization_id),
            units=units,
            provenance_token=provenance_token,
            input_hash="",
        )


class BackendIngestOutcome(BaseModel):
    """Result of one backend ingest attempt (normalized, §21)."""

    model_config = ConfigDict(frozen=True)

    success: bool
    backend_episode_ref: Optional[str] = None
    failure_code: Optional[str] = None
    errors: tuple[str, ...] = ()


class GraphBackend(Protocol):
    """§6: the ONLY sanctioned backend touchpoint. A production
    implementation wraps GraphitiService lazily; agents/reports never
    touch it directly (§34)."""

    async def ingest(
        self, backend_episode: GraphBackendEpisodeV1
    ) -> BackendIngestOutcome: ...

    async def find_episode_ref(
        self, episode_name: str, group_id: str
    ) -> Optional[str]:
        """Resolve the backend's uuid for a deterministic episode name
        (the provenance binding anchor). None = unresolvable."""
        ...


class FakeGraphBackend:
    """Offline fixture backend (§63-safe: no Graphiti/Neo4j import)."""

    def __init__(self, *, fail_ingest: bool = False,
                 fail_lookup: bool = False):
        self.fail_ingest = fail_ingest
        self.fail_lookup = fail_lookup
        self.calls: list[str] = []
        self._refs: dict[str, str] = {}

    async def ingest(
        self, backend_episode: GraphBackendEpisodeV1
    ) -> BackendIngestOutcome:
        self.calls.append(backend_episode.episode_name)
        if self.fail_ingest:
            return BackendIngestOutcome(
                success=False,
                failure_code="GRAPH_BACKEND_INGEST_FAILED",
                errors=("fixture ingest failure",),
            )
        ref = "ep-" + hashlib.sha256(
            backend_episode.episode_name.encode("utf-8")
        ).hexdigest()[:20]
        self._refs[backend_episode.episode_name] = ref
        return BackendIngestOutcome(
            success=True, backend_episode_ref=ref
        )

    async def find_episode_ref(
        self, episode_name: str, group_id: str
    ) -> Optional[str]:
        if self.fail_lookup:
            return None
        return self._refs.get(episode_name)


def render_episode_text(backend_episode: GraphBackendEpisodeV1) -> str:
    """§8 deterministic textual rendering (audit/debug aid; provenance
    stays machine-readable in the provenance token/bindings)."""
    lines = [
        "TRACE_LENS_EPISODE",
        f"episode_id: {backend_episode.episode_id}",
        f"materialization_id: {backend_episode.materialization_id}",
        f"episode_hash: {backend_episode.episode_hash}",
    ]
    for unit in backend_episode.units:
        lines.append("SEMANTIC_UNIT")
        lines.append(f"unit_name: {unit.get('unit_name')}")
        body = unit.get("body", "")
        lines.append(f"body: {body}")
    return "\n".join(lines)


__all__ = [
    "ADAPTER_VERSION",
    "GRAPH_BACKEND_EPISODE_VERSION",
    "BackendIngestOutcome",
    "FakeGraphBackend",
    "GraphBackend",
    "GraphBackendEpisodeV1",
    "GraphMaterializationAdapter",
    "deterministic_episode_name",
    "render_episode_text",
]
