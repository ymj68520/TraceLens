"""ForensicGraphEpisodeV1 — the frozen Graphiti materialization input
(P6A §19-§23, §49, §52, §55).

Only candidates whose admission decision is ``admit`` may be frozen into
an episode. The episode is the COMPLETE materialization input: immutable,
content-hashed, backend-neutral, and self-contained — Graphiti never
receives DB paths, repository objects or live state callbacks, and the
P6B executor never re-reads a moving database at execution time.

Granularity (§20/§49): an episode is a set of independently
understandable semantic units (one per admitted candidate), each carrying
its own assertion → Evidence map so every assertion in the graph can be
hydrated back to real Evidence (§54: KG locates; Evidence Store proves).

After freezing, canonical state changes NEVER update an episode; a new
candidate/decision/episode supersedes the old one (§23).
"""

from __future__ import annotations

import hashlib
from typing import Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionDecisionV1,
)
from .agent_graph_candidate import GraphCandidateV1
from .agent_runtime import canonical_state_json

FORENSIC_GRAPH_EPISODE_VERSION = "forensic-graph-episode:v1"


class GraphSemanticUnit(BaseModel):
    """One independently explainable semantic unit (micro-batch seam).

    The unit's evidence_refs ARE the assertion → Evidence map: everything
    the unit asserts must be traceable to these refs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str  # = candidate_id
    candidate_kind: str
    semantic_summary: str
    evidence_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    occurrence_refs: tuple[str, ...] = ()
    review_status: Optional[str] = None
    verification_refs: tuple[str, ...] = ()

    def provenance_digest(self) -> str:
        return hashlib.sha256(
            canonical_state_json({
                "unit_id": self.unit_id,
                "semantic_summary": self.semantic_summary,
                "evidence_refs": list(self.evidence_refs),
                "finding_refs": list(self.finding_refs),
                "correlation_refs": list(self.correlation_refs),
            }).encode("utf-8")
        ).hexdigest()


class ForensicGraphEpisodeV1(BaseModel):
    """Frozen, hash-bound materialization input (backend-neutral)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_version: str = FORENSIC_GRAPH_EPISODE_VERSION

    episode_id: str
    task_id: str
    investigation_id: str

    candidate_ids: tuple[str, ...] = ()
    admission_decision_ids: tuple[str, ...] = ()

    semantic_units: tuple[GraphSemanticUnit, ...] = ()

    evidence_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    occurrence_refs: tuple[str, ...] = ()

    # per-unit review status map: unit_id -> review_status
    review_statuses: Mapping[str, str] = {}

    # §52 complete provenance: one envelope per semantic unit
    provenance_manifest: tuple[Mapping, ...] = ()

    source_revision: Optional[int] = None
    source_state_hash: Optional[str] = None

    policy_version: str
    policy_hash: str

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, data):
        if not isinstance(data, dict):
            return data
        units = tuple(
            unit if isinstance(unit, GraphSemanticUnit)
            else GraphSemanticUnit(**unit)
            for unit in (data.get("semantic_units") or ())
        )
        ordered_units = tuple(
            sorted(units, key=lambda unit: unit.unit_id)
        )
        candidate_ids = tuple(sorted(
            {str(v) for v in (data.get("candidate_ids") or ()) if v}
        ))
        decision_ids = tuple(sorted(
            {str(v) for v in (data.get("admission_decision_ids") or ())
             if v}
        ))
        payload = {
            "episode_version": FORENSIC_GRAPH_EPISODE_VERSION,
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "candidate_ids": candidate_ids,
            "admission_decision_ids": decision_ids,
            "unit_digests": [unit.provenance_digest()
                             for unit in ordered_units],
            "evidence_refs": sorted(
                {str(v) for v in (data.get("evidence_refs") or ()) if v}
            ),
            "finding_refs": sorted(
                {str(v) for v in (data.get("finding_refs") or ()) if v}
            ),
            "correlation_refs": sorted(
                {str(v) for v in (data.get("correlation_refs") or ())
                 if v}
            ),
            "occurrence_refs": sorted(
                {str(v) for v in (data.get("occurrence_refs") or ())
                 if v}
            ),
            "review_statuses": dict(
                sorted((data.get("review_statuses") or {}).items())
            ),
            "source_revision": data.get("source_revision"),
            "source_state_hash": data.get("source_state_hash"),
            "policy_version": data.get("policy_version"),
            "policy_hash": data.get("policy_hash"),
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data["semantic_units"] = [unit.model_dump() for unit in ordered_units]
        data["candidate_ids"] = candidate_ids
        data["admission_decision_ids"] = decision_ids
        data["input_hash"] = input_hash
        data["episode_id"] = "gepis:" + hashlib.sha256(
            canonical_state_json({**payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return data

    def to_row(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "episode_version": self.episode_version,
            "candidate_ids": tuple(self.candidate_ids),
            "admission_decision_ids": tuple(self.admission_decision_ids),
            "semantic_units": [unit.model_dump()
                               for unit in self.semantic_units],
            "evidence_refs": tuple(self.evidence_refs),
            "finding_refs": tuple(self.finding_refs),
            "correlation_refs": tuple(self.correlation_refs),
            "occurrence_refs": tuple(self.occurrence_refs),
            "review_statuses": dict(self.review_statuses),
            "provenance_manifest": [dict(item)
                                    for item in self.provenance_manifest],
            "source_revision": self.source_revision,
            "source_state_hash": self.source_state_hash,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "input_hash": self.input_hash,
        }


def freeze_episode(
    candidates: Sequence[GraphCandidateV1],
    decisions: Mapping[str, GraphAdmissionDecisionV1],
    *,
    task_id: str,
    investigation_id: str,
    source_revision: Optional[int],
    source_state_hash: Optional[str],
    policy_version: str,
    policy_hash: str,
) -> ForensicGraphEpisodeV1:
    """§19: freeze ONLY admitted candidates into one backend-neutral
    episode. Every candidate must carry its full admission decision; every
    decision must be ``admit`` (§27: defer/not_admitted never produce
    episodes)."""
    if not candidates:
        raise ValueError("cannot freeze an empty episode")
    units: list[GraphSemanticUnit] = []
    provenance: list[dict] = []
    review_statuses: dict[str, str] = {}
    for candidate in candidates:
        decision = decisions.get(candidate.candidate_id)
        if decision is None:
            raise ValueError(
                f"candidate {candidate.candidate_id!r} has no admission "
                "decision"
            )
        if decision.decision is not GraphAdmissionDecision.ADMIT:
            raise ValueError(
                f"candidate {candidate.candidate_id!r} was not admitted; "
                "only admitted candidates freeze into episodes"
            )
        unit = GraphSemanticUnit(
            unit_id=candidate.candidate_id,
            candidate_kind=candidate.candidate_kind,
            semantic_summary=candidate.semantic_summary,
            evidence_refs=tuple(candidate.evidence_refs),
            finding_refs=tuple(candidate.finding_refs),
            correlation_refs=tuple(candidate.correlation_refs),
            occurrence_refs=tuple(candidate.entity_occurrence_refs),
            review_status=candidate.review_status,
            verification_refs=tuple(candidate.verification_refs),
        )
        units.append(unit)
        review_statuses[unit.unit_id] = candidate.review_status or ""
        provenance.append({
            "unit_id": unit.unit_id,
            "candidate_id": candidate.candidate_id,
            "admission_decision_id": decision.decision_id,
            "evidence_refs": list(unit.evidence_refs),
            "finding_refs": list(unit.finding_refs),
            "correlation_refs": list(unit.correlation_refs),
            "review_status": candidate.review_status,
        })
    return ForensicGraphEpisodeV1(
        task_id=task_id,
        investigation_id=investigation_id,
        episode_id="",  # derived
        candidate_ids=tuple(c.candidate_id for c in candidates),
        admission_decision_ids=tuple(
            decisions[c.candidate_id].decision_id for c in candidates
        ),
        semantic_units=units,
        evidence_refs=tuple(sorted({
            ref for c in candidates for ref in c.evidence_refs
        })),
        finding_refs=tuple(sorted({
            ref for c in candidates for ref in c.finding_refs
        })),
        correlation_refs=tuple(sorted({
            ref for c in candidates for ref in c.correlation_refs
        })),
        occurrence_refs=tuple(sorted({
            ref for c in candidates for ref in c.entity_occurrence_refs
        })),
        review_statuses=review_statuses,
        provenance_manifest=provenance,
        source_revision=source_revision,
        source_state_hash=source_state_hash,
        policy_version=policy_version,
        policy_hash=policy_hash,
        input_hash="",  # derived
    )


__all__ = [
    "FORENSIC_GRAPH_EPISODE_VERSION",
    "ForensicGraphEpisodeV1",
    "GraphSemanticUnit",
    "freeze_episode",
]
