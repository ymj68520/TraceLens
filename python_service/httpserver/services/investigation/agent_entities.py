"""Evidence-backed entity occurrences (P5A §7-§8, §13-§16).

Every ``EntityOccurrenceV1`` is Evidence-backed: its ``evidence_ref`` must
parse as a real Evidence key and resolve inside the task before the
occurrence is built (§14).  Analyst notes, Case Context, LLM text,
ToolObservation summaries and Graph nodes never become verified occurrences
— they are simply never accepted by this builder.

Deterministic identity (§8): the occurrence_id is a content hash over the
extraction inputs, so the same extraction always yields the same id and
input order never changes it.  No array indexes, no model-generated UUIDs.

Resolved entities (§16): P5A does NOT build an aggressive canonical entity
store.  ``derive_entity_auto_links`` forms links only where the
IdentityPolicy marks the identifier deterministic-safe (cryptographic
hashes); the links are pure derivations over the immutable occurrence rows
and are recomputable after restart, so they need no table of their own.
"""

from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from .agent_identity import IdentityNormalizationError, IdentityPolicy
from .agent_runtime import canonical_state_json, state_hash_of
from .agent_specialist_result import SpecialistResultV1

ENTITY_OCCURRENCE_VERSION = "entity-occurrence:v1"

EXTRACTION_METHOD = "specialist_candidate_mapping:v1"


def derive_occurrence_id(
    *,
    task_id: str,
    evidence_ref: str,
    entity_type: str,
    source_field: str,
    raw_value: str,
    normalized_value: str,
    role: str,
) -> str:
    """Deterministic content-addressed occurrence id (§8).

    Covers exactly the frozen input set; input ordering cannot change it."""
    payload = {
        "task_id": task_id,
        "evidence_ref": evidence_ref,
        "entity_type": entity_type,
        "source_field": source_field,
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "role": role,
    }
    digest = hashlib.sha256(
        canonical_state_json(payload).encode("utf-8")
    ).hexdigest()
    return f"entocc:{digest[:24]}"


class EntityTemporalRef(BaseModel):
    """Bounded temporal anchor derived from the Evidence itself."""

    model_config = ConfigDict(frozen=True)

    kind: str  # e.g. "evidence_mtime" | "cluster_window"
    start: Optional[int] = None
    end: Optional[int] = None


class EntityOccurrenceV1(BaseModel):
    """One evidence-backed observation of an entity value (version-frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    occurrence_version: str = ENTITY_OCCURRENCE_VERSION
    occurrence_id: str

    task_id: str
    investigation_id: str

    source_scope_id: str
    evidence_ref: str

    entity_type: str

    raw_value: str
    normalized_value: str
    match_key: str
    namespace: str
    role: str

    temporal: Optional[EntityTemporalRef] = None

    source_field: str
    extraction_method: str = EXTRACTION_METHOD

    verification_status: str = "verified"

    provenance: dict = {}

    def extraction_hash(self) -> str:
        """Hash over exactly the §8 identity inputs (policy-independent)."""
        return hashlib.sha256(
            canonical_state_json(
                {
                    "task_id": self.task_id,
                    "evidence_ref": self.evidence_ref,
                    "entity_type": self.entity_type,
                    "source_field": self.source_field,
                    "raw_value": self.raw_value,
                    "normalized_value": self.normalized_value,
                    "role": self.role,
                }
            ).encode("utf-8")
        ).hexdigest()

    def to_row(self) -> dict:
        """Repository-shaped mapping for ``record_entity_occurrences``."""
        return {
            "occurrence_id": self.occurrence_id,
            "source_scope_id": self.source_scope_id,
            "evidence_ref": self.evidence_ref,
            "entity_type": self.entity_type,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "match_key": self.match_key,
            "namespace": self.namespace,
            "role": self.role,
            "temporal": self.temporal.model_dump() if self.temporal else None,
            "source_field": self.source_field,
            "extraction_method": self.extraction_method,
            "verification_status": self.verification_status,
            "provenance": dict(self.provenance),
            "input_hash": self.extraction_hash(),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "EntityOccurrenceV1":
        temporal = row.get("temporal")
        return cls(
            occurrence_id=row["occurrence_id"],
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            source_scope_id=row["source_scope_id"],
            evidence_ref=row["evidence_ref"],
            entity_type=row["entity_type"],
            raw_value=row["raw_value"],
            normalized_value=row["normalized_value"],
            match_key=row["match_key"],
            namespace=row["namespace"],
            role=row["role"],
            temporal=EntityTemporalRef(**temporal) if temporal else None,
            source_field=row["source_field"],
            extraction_method=row["extraction_method"],
            verification_status=row["verification_status"],
            provenance=dict(row.get("provenance") or {}),
        )


class ExtractionLimitation(BaseModel):
    """Why one candidate (or candidate/ref pair) produced no occurrence."""

    model_config = ConfigDict(frozen=True)

    code: str
    detail: str


class EntityExtractionReport(BaseModel):
    """Deterministic extraction outcome over one specialist result."""

    model_config = ConfigDict(frozen=True)

    occurrences: tuple[EntityOccurrenceV1, ...] = ()
    limitations: tuple[ExtractionLimitation, ...] = ()

    def sorted(self) -> "EntityExtractionReport":
        return EntityExtractionReport(
            occurrences=tuple(
                sorted(self.occurrences, key=lambda item: item.occurrence_id)
            ),
            limitations=tuple(
                sorted(
                    self.limitations,
                    key=lambda item: (item.code, item.detail),
                )
            ),
        )


EvidenceLookup = Callable[[str, str], Awaitable[Optional[Mapping[str, Any]]]]


def _temporal_from_metadata(
    metadata: Mapping[str, Any],
) -> Optional[EntityTemporalRef]:
    source_mtime = metadata.get("source_mtime")
    if source_mtime:
        return EntityTemporalRef(
            kind="evidence_mtime", start=int(source_mtime), end=int(source_mtime)
        )
    cluster_start = metadata.get("cluster_start")
    cluster_end = metadata.get("cluster_end")
    if cluster_start and cluster_end:
        return EntityTemporalRef(
            kind="cluster_window",
            start=int(cluster_start),
            end=int(cluster_end),
        )
    return None


async def build_occurrences_from_specialist_result(
    result: SpecialistResultV1,
    *,
    task_id: str,
    investigation_id: str,
    source_scope_id: str,
    identity_policy: IdentityPolicy,
    evidence_lookup: EvidenceLookup,
    allowed_evidence_ids: Optional[frozenset[str]] = None,
    role: str = "mention",
) -> EntityExtractionReport:
    """Map ``SpecialistResultV1.entity_candidates`` to verified occurrences.

    One occurrence is built per (candidate, evidence_ref) pair; every pair
    must resolve to real, task-scoped Evidence (and be inside the optional
    visibility set) or it is skipped with a limitation — never silently
    upgraded, never backed by LLM text (§13/§14)."""
    limitations: list[ExtractionLimitation] = []
    occurrences: list[EntityOccurrenceV1] = []
    source_field = f"specialist_result.entity_candidates[{result.delegation_id}]"

    for candidate in result.entity_candidates:
        definition = identity_policy.registry.get(
            candidate.entity_type_candidate or ""
        )
        if definition is None:
            limitations.append(
                ExtractionLimitation(
                    code="OCCURRENCE_UNKNOWN_ENTITY_TYPE",
                    detail=(
                        f"candidate {candidate.candidate_id!r}: "
                        f"entity_type_candidate="
                        f"{candidate.entity_type_candidate!r} not in registry"
                    ),
                )
            )
            continue
        try:
            resolution = identity_policy.resolve(
                candidate.entity_type_candidate,
                candidate.raw_value,
                qualifiers={"source_scope_id": source_scope_id},
            )
        except IdentityNormalizationError as exc:
            limitations.append(
                ExtractionLimitation(
                    code="OCCURRENCE_NORMALIZATION_REJECTED",
                    detail=(
                        f"candidate {candidate.candidate_id!r}: {exc}"
                    ),
                )
            )
            continue

        refs = tuple(dict.fromkeys(candidate.evidence_refs))
        if not refs:
            limitations.append(
                ExtractionLimitation(
                    code="OCCURRENCE_NO_EVIDENCE_REF",
                    detail=(
                        f"candidate {candidate.candidate_id!r} carries no "
                        "evidence ref; never a verified occurrence"
                    ),
                )
            )
            continue
        for evidence_ref in refs:
            if (
                allowed_evidence_ids is not None
                and evidence_ref not in allowed_evidence_ids
            ):
                limitations.append(
                    ExtractionLimitation(
                        code="OCCURRENCE_EVIDENCE_NOT_VISIBLE",
                        detail=(
                            f"candidate {candidate.candidate_id!r}: "
                            f"{evidence_ref!r} not in the delegation's "
                            "visible Evidence set"
                        ),
                    )
                )
                continue
            try:
                metadata = await evidence_lookup(task_id, evidence_ref)
            except Exception as exc:  # resolver fail-closed -> skip
                limitations.append(
                    ExtractionLimitation(
                        code="OCCURRENCE_EVIDENCE_UNRESOLVED",
                        detail=(
                            f"candidate {candidate.candidate_id!r}: "
                            f"{evidence_ref!r} did not resolve ({exc})"
                        ),
                    )
                )
                continue
            if metadata is None:
                limitations.append(
                    ExtractionLimitation(
                        code="OCCURRENCE_EVIDENCE_UNRESOLVED",
                        detail=(
                            f"candidate {candidate.candidate_id!r}: "
                            f"{evidence_ref!r} not found in task"
                        ),
                    )
                )
                continue
            occurrences.append(
                EntityOccurrenceV1(
                    occurrence_id=derive_occurrence_id(
                        task_id=task_id,
                        evidence_ref=evidence_ref,
                        entity_type=definition.entity_type,
                        source_field=source_field,
                        raw_value=candidate.raw_value,
                        normalized_value=resolution.normalized_value,
                        role=role,
                    ),
                    task_id=task_id,
                    investigation_id=investigation_id,
                    source_scope_id=source_scope_id,
                    evidence_ref=evidence_ref,
                    entity_type=definition.entity_type,
                    raw_value=candidate.raw_value,
                    normalized_value=resolution.normalized_value,
                    match_key=resolution.match_key,
                    namespace=resolution.namespace,
                    role=role,
                    temporal=_temporal_from_metadata(metadata),
                    source_field=source_field,
                    extraction_method=EXTRACTION_METHOD,
                    verification_status="verified",
                    provenance={
                        "source_candidate_id": candidate.candidate_id,
                        "source_result_hash": result.result_hash(),
                        "identity_class": resolution.identity_class.value,
                        "auto_link_allowed": resolution.auto_link_allowed,
                        "normalized_candidate_declared":
                            candidate.normalized_candidate or "",
                    },
                )
            )

    return EntityExtractionReport(
        occurrences=tuple(occurrences), limitations=tuple(limitations)
    ).sorted()


class EntityAutoLink(BaseModel):
    """A deterministic-safe identity link over strong occurrences (§16)."""

    model_config = ConfigDict(frozen=True)

    link_id: str
    task_id: str
    investigation_id: str
    entity_type: str
    match_key: str
    namespace: str
    member_occurrence_ids: tuple[str, ...]
    input_hash: str


def derive_entity_auto_links(
    occurrences: Iterable[EntityOccurrenceV1],
) -> tuple[EntityAutoLink, ...]:
    """Group occurrences into links only where auto-link is sanctioned.

    Same SHA256 -> linked.  Same IP / same username text / same display
    name / temporal neighborhood -> NEVER linked here; those occurrences
    carry ``auto_link_allowed=False`` and are skipped entirely (§16)."""
    buckets: dict[tuple[str, str, str, str], list[EntityOccurrenceV1]] = {}
    for occurrence in occurrences:
        if occurrence.provenance.get("auto_link_allowed") is not True:
            continue
        key = (
            occurrence.task_id,
            occurrence.investigation_id,
            occurrence.entity_type,
            occurrence.match_key,
        )
        buckets.setdefault(key, []).append(occurrence)

    links: list[EntityAutoLink] = []
    for key, members in buckets.items():
        task_id, investigation_id, entity_type, match_key = key
        ordered = sorted(members, key=lambda item: item.occurrence_id)
        if len({item.match_key for item in ordered}) != 1:
            continue
        member_ids = tuple(item.occurrence_id for item in ordered)
        namespaces = {item.namespace for item in ordered}
        if len(namespaces) != 1:
            continue
        payload = {
            "task_id": task_id,
            "investigation_id": investigation_id,
            "entity_type": entity_type,
            "match_key": match_key,
            "member_occurrence_ids": list(member_ids),
        }
        digest = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        links.append(
            EntityAutoLink(
                link_id=f"entlink:{digest[:24]}",
                task_id=task_id,
                investigation_id=investigation_id,
                entity_type=entity_type,
                match_key=match_key,
                namespace=next(iter(namespaces)),
                member_occurrence_ids=member_ids,
                input_hash=state_hash_of(payload),
            )
        )
    return tuple(sorted(links, key=lambda link: link.link_id))


__all__ = [
    "ENTITY_OCCURRENCE_VERSION",
    "EXTRACTION_METHOD",
    "EntityAutoLink",
    "EntityExtractionReport",
    "EntityOccurrenceV1",
    "EntityTemporalRef",
    "ExtractionLimitation",
    "build_occurrences_from_specialist_result",
    "derive_entity_auto_links",
    "derive_occurrence_id",
]
