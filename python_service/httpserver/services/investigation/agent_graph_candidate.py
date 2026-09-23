"""GraphCandidateV1 — proposal to enter the Investigation Context Graph
(P6A §6-§12, §37-§42).

A GraphCandidate is a PROPOSAL, never an admission and never authority
(§6/§64): only the deterministic GraphAdmissionPolicy decides, only an
``admit`` decision may freeze an episode, and only the queued
materialization manifest records the lifecycle.

Evidence boundary (§9): every candidate must trace to real Evidence refs,
or to a canonical semantic object (Finding / validated correlation) that
itself carries evidence refs. Natural-language summaries, LLM reasoning,
Graph nodes, Analyst Notes and Case Context are NEVER sufficient
provenance (§11) — they may only appear as the pointed-to objects.

Candidate kinds are a versioned starter set (§7): the architecture's
permanent taxonomy is TBD; the registry below covers exactly the three
admissible layers plus their natural aliases.
"""

from __future__ import annotations

import hashlib
import enum
from typing import Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_runtime import canonical_state_json

GRAPH_CANDIDATE_VERSION = "graph-candidate:v1"
CANDIDATE_KIND_REGISTRY_VERSION = "graph-candidate-kind-registry:v1"


class GraphCandidateKind(str, enum.Enum):
    """§7/§10 starter set — the three architecture-admissible layers."""

    EVIDENCE_DERIVED_CONTEXT = "evidence_derived_context"
    VERIFIED_FINDING = "verified_finding"
    VALIDATED_CORRELATION = "validated_correlation"


class GraphCandidateKindRegistry(BaseModel):
    """Versioned registry: the kinds this policy version understands."""

    model_config = ConfigDict(frozen=True)

    registry_version: str = CANDIDATE_KIND_REGISTRY_VERSION
    kinds: tuple[str, ...] = tuple(
        kind.value for kind in GraphCandidateKind
    )

    def knows(self, kind: str) -> bool:
        return kind in self.kinds

    def registry_hash(self) -> str:
        return hashlib.sha256(
            canonical_state_json({
                "registry_version": self.registry_version,
                "kinds": sorted(self.kinds),
            }).encode("utf-8")
        ).hexdigest()


class GraphCandidateV1(BaseModel):
    """One proposed semantic graph unit (version-frozen, §6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_version: str = GRAPH_CANDIDATE_VERSION
    candidate_id: str

    task_id: str
    investigation_id: str

    candidate_kind: str

    subject_refs: tuple[str, ...] = ()
    relation_refs: tuple[str, ...] = ()
    object_refs: tuple[str, ...] = ()

    # §9 provenance: at least one of these must be non-empty and every
    # ref must resolve inside the task.
    evidence_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    entity_occurrence_refs: tuple[str, ...] = ()

    semantic_summary: str

    review_status: Optional[str] = None  # accepted/review_pending/rejected
    verification_refs: tuple[str, ...] = ()

    source_reason: str = ""
    source_component: str = ""

    priority_band: Optional[str] = None
    limitations: tuple[str, ...] = ()

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, data):
        if not isinstance(data, dict):
            return data

        def _sorted(values) -> list:
            return sorted({str(v) for v in (values or ()) if v})

        payload = {
            "candidate_version": GRAPH_CANDIDATE_VERSION,
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "candidate_kind": data.get("candidate_kind"),
            "subject_refs": _sorted(data.get("subject_refs")),
            "relation_refs": _sorted(data.get("relation_refs")),
            "object_refs": _sorted(data.get("object_refs")),
            "evidence_refs": _sorted(data.get("evidence_refs")),
            "finding_refs": _sorted(data.get("finding_refs")),
            "correlation_refs": _sorted(data.get("correlation_refs")),
            "entity_occurrence_refs": _sorted(
                data.get("entity_occurrence_refs")
            ),
            "semantic_summary": " ".join(
                str(data.get("semantic_summary") or "").split()
            ),
            "review_status": data.get("review_status"),
            "verification_refs": _sorted(data.get("verification_refs")),
            "source_reason": str(data.get("source_reason") or ""),
            "source_component": str(data.get("source_component") or ""),
            "priority_band": data.get("priority_band"),
            "limitations": _sorted(data.get("limitations")),
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data.update(payload)
        data["input_hash"] = input_hash
        data["candidate_id"] = "gcand:" + hashlib.sha256(
            canonical_state_json({**payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return data

    def to_row(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "candidate_kind": self.candidate_kind,
            "subject_refs": tuple(self.subject_refs),
            "relation_refs": tuple(self.relation_refs),
            "object_refs": tuple(self.object_refs),
            "evidence_refs": tuple(self.evidence_refs),
            "finding_refs": tuple(self.finding_refs),
            "correlation_refs": tuple(self.correlation_refs),
            "entity_occurrence_refs": tuple(self.entity_occurrence_refs),
            "semantic_summary": self.semantic_summary,
            "review_status": self.review_status,
            "verification_refs": tuple(self.verification_refs),
            "source_reason": self.source_reason,
            "source_component": self.source_component,
            "limitations": tuple(self.limitations),
            "input_hash": self.input_hash,
        }

    @classmethod
    def from_row(cls, row: Mapping) -> "GraphCandidateV1":
        return cls(
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            candidate_id=row["candidate_id"],
            candidate_version=row["candidate_version"],
            candidate_kind=row["candidate_kind"],
            subject_refs=tuple(row["subject_refs"]),
            relation_refs=tuple(row["relation_refs"]),
            object_refs=tuple(row["object_refs"]),
            evidence_refs=tuple(row["evidence_refs"]),
            finding_refs=tuple(row["finding_refs"]),
            correlation_refs=tuple(row["correlation_refs"]),
            entity_occurrence_refs=tuple(row["entity_occurrence_refs"]),
            semantic_summary=row["semantic_summary"],
            review_status=row.get("review_status"),
            verification_refs=tuple(row["verification_refs"]),
            source_reason=row.get("source_reason") or "",
            source_component=row.get("source_component") or "",
            limitations=tuple(row["limitations"]),
            input_hash=row["input_hash"],
        )


class CandidateViolationCode(str, enum.Enum):
    """§42 deterministic candidate validator codes."""

    CANDIDATE_VERSION_UNSUPPORTED = "CANDIDATE_VERSION_UNSUPPORTED"
    CANDIDATE_IDENTITY_MISMATCH = "CANDIDATE_IDENTITY_MISMATCH"
    CANDIDATE_KIND_UNKNOWN = "CANDIDATE_KIND_UNKNOWN"
    CANDIDATE_PROVENANCE_MISSING = "CANDIDATE_PROVENANCE_MISSING"
    CANDIDATE_EVIDENCE_REF_MALFORMED = "CANDIDATE_EVIDENCE_REF_MALFORMED"
    CANDIDATE_SUMMARY_EMPTY = "CANDIDATE_SUMMARY_EMPTY"
    CANDIDATE_FORBIDDEN_SOURCE = "CANDIDATE_FORBIDDEN_SOURCE"


_FORBIDDEN_SOURCE_COMPONENTS = (
    "analyst_note",
    "case_context",
    "agent_reasoning",
    "llm_chain_of_thought",
    "provider_response",
    "supervisor_summary",
    "tool_observation_summary",
    "verifier_prose",
)


class GraphCandidateValidator:
    """§42 structural gate: invalid candidates never reach the policy."""

    def __init__(self, registry: Optional[GraphCandidateKindRegistry] = None):
        self._registry = registry or GraphCandidateKindRegistry()

    def validate(
        self,
        candidate: GraphCandidateV1,
        *,
        task_id: str,
        investigation_id: str,
        evidence_ref_parser=None,
    ) -> tuple[CandidateViolationCode, ...]:
        violations: list[CandidateViolationCode] = []
        if candidate.candidate_version != GRAPH_CANDIDATE_VERSION:
            violations.append(
                CandidateViolationCode.CANDIDATE_VERSION_UNSUPPORTED
            )
        if (
            candidate.task_id != task_id
            or candidate.investigation_id != investigation_id
        ):
            violations.append(
                CandidateViolationCode.CANDIDATE_IDENTITY_MISMATCH
            )
        if not self._registry.knows(candidate.candidate_kind):
            violations.append(CandidateViolationCode.CANDIDATE_KIND_UNKNOWN)
        if not (
            candidate.evidence_refs
            or candidate.finding_refs
            or candidate.correlation_refs
        ):
            violations.append(
                CandidateViolationCode.CANDIDATE_PROVENANCE_MISSING
            )
        if not candidate.semantic_summary.strip():
            violations.append(CandidateViolationCode.CANDIDATE_SUMMARY_EMPTY)
        if evidence_ref_parser is not None:
            for ref in candidate.evidence_refs:
                try:
                    evidence_ref_parser(ref)
                except Exception:
                    violations.append(
                        CandidateViolationCode.
                        CANDIDATE_EVIDENCE_REF_MALFORMED
                    )
        source = candidate.source_component.lower()
        if source in _FORBIDDEN_SOURCE_COMPONENTS:
            violations.append(CandidateViolationCode.CANDIDATE_FORBIDDEN_SOURCE)
        return tuple(violations)


class GraphCandidateBuilder:
    """§41 deterministic builders over canonical objects (no LLM)."""

    VERSION = GRAPH_CANDIDATE_VERSION

    def candidate_from_finding(
        self,
        finding: Mapping,
        *,
        task_id: str,
        investigation_id: str,
        verification_refs: Sequence[str] = (),
        source_reason: str = "",
    ) -> GraphCandidateV1:
        """§38: a P5 canonical Finding (review_pending or accepted)
        becomes a verified_finding candidate carrying its exact status."""
        review_status = finding["status"]
        if review_status not in ("review_pending", "accepted"):
            raise ValueError(
                f"finding status {review_status!r} cannot be proposed; "
                "rejected findings are never candidates"
            )
        kind = GraphCandidateKind.VERIFIED_FINDING.value
        return GraphCandidateV1(
            task_id=task_id,
            investigation_id=investigation_id,
            candidate_id="",  # derived
            candidate_kind=kind,
            evidence_refs=tuple(finding["evidence_refs"]),
            finding_refs=(finding["finding_id"],),
            semantic_summary=finding["text"],
            review_status=review_status,
            verification_refs=tuple(
                [finding["semantic_verification_id"]]
                if finding.get("semantic_verification_id") else []
            ) or tuple(verification_refs),
            source_reason=source_reason or "canonical_finding",
            source_component="graph_candidate_builder",
            limitations=tuple(finding["limitations"]),
            input_hash="",
        )

    def candidate_from_evidence_context(
        self,
        *,
        task_id: str,
        investigation_id: str,
        summary: str,
        evidence_refs: Sequence[str],
        occurrence_refs: Sequence[str] = (),
        subject_refs: Sequence[str] = (),
        object_refs: Sequence[str] = (),
        source_reason: str = "deterministic_evidence_context",
    ) -> GraphCandidateV1:
        """§37: fully deterministic, LLM-free evidence-derived context
        (e.g. Evidence <-> file-hash occurrence from typed P5 data)."""
        return GraphCandidateV1(
            task_id=task_id,
            investigation_id=investigation_id,
            candidate_id="",  # derived
            candidate_kind=GraphCandidateKind.EVIDENCE_DERIVED_CONTEXT.value,
            evidence_refs=tuple(evidence_refs),
            entity_occurrence_refs=tuple(occurrence_refs),
            subject_refs=tuple(subject_refs),
            object_refs=tuple(object_refs),
            semantic_summary=summary,
            review_status="not_applicable",
            source_reason=source_reason,
            source_component="graph_candidate_builder",
        )


__all__ = [
    "CANDIDATE_KIND_REGISTRY_VERSION",
    "GRAPH_CANDIDATE_VERSION",
    "CandidateViolationCode",
    "GraphCandidateBuilder",
    "GraphCandidateKind",
    "GraphCandidateKindRegistry",
    "GraphCandidateValidator",
    "GraphCandidateV1",
]
