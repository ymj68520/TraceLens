"""DeterministicCorrelationEngine (P5A §17-§22).

This is NOT an agent and calls no model.  It consumes durable
EntityOccurrences plus their evidence metadata and emits bounded
``CorrelationCandidateV1`` proposals — never canonical facts, never graph
writes, never identity assertions.

Candidate production is bucketed (§21): candidates arise only from

    same match bucket (entity_type + match_key, weak namespaces excluded)
    known structural relations (url host vs domain)
    structured co-occurrence inside one Evidence
    bounded temporal overlap

Never from an unbounded entity-x-entity pairwise sweep.  Bounds
(max_candidates, temporal window) are provisional runtime defaults, left
configurable for P8 calibration.

Assertion boundary (§19/§20): the engine only emits ``observed``,
``inference`` and ``hypothesis`` assertion hints, and ``causal_status`` is
one of ``not_assessed`` / ``non_causal`` / ``causal_hypothesis``.
Temporal-only proximity NEVER becomes causal (E7).  ``causal_confirmed``
does not exist in this phase.  ``semantic_inference`` derivation belongs to
the P5B CorrelationAgent and is unreachable here.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict

from .agent_entities import EntityOccurrenceV1

CORRELATION_CANDIDATE_VERSION = "correlation-candidate:v1"
DETERMINISTIC_CORRELATION_VERSION = "deterministic-correlation:v1"

# Provisional runtime defaults — P8 calibration (§21).
DEFAULT_MAX_CANDIDATES = 200
DEFAULT_TEMPORAL_WINDOW_SECONDS = 3600

# Namespaces whose match keys are weak (IdentityPolicy WEAK_MATCH_KEY):
# sharing them is never bucketed into deterministic identifier matches.
_WEAK_NAMESPACES = frozenset({
    "ip:network",
    "account:bare",
    "process:bare",
    "process:host_temporal",
})


class CorrelationDerivation(str, Enum):
    """§18: how a candidate was derived. Semantic inference is P5B-only."""

    ARTIFACT_EXPLICIT = "artifact_explicit"
    DETERMINISTIC_MATCH = "deterministic_match"


class CorrelationAssertionHint(str, Enum):
    """§19 safe levels only."""

    OBSERVED = "observed"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"


class CausalStatus(str, Enum):
    """§20: causal_confirmed does not exist in P5A."""

    NOT_ASSESSED = "not_assessed"
    NON_CAUSAL = "non_causal"
    CAUSAL_HYPOTHESIS = "causal_hypothesis"


class TemporalRelation(BaseModel):
    """Bounded temporal observation between two occurrences."""

    model_config = ConfigDict(frozen=True)

    kind: str  # "overlap" | "within_window"
    gap_seconds: int = 0
    window_seconds: int


class CorrelationCandidateV1(BaseModel):
    """One bounded, non-canonical correlation proposal (version-frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_version: str = CORRELATION_CANDIDATE_VERSION
    correlation_id: str

    relation_family: str

    subject_ref: str  # occurrence id
    object_ref: str   # occurrence id

    derivation: CorrelationDerivation
    assertion_hint: CorrelationAssertionHint

    evidence_refs: tuple[str, ...]
    support_types: tuple[str, ...]

    temporal_relation: Optional[TemporalRelation] = None

    limitations: tuple[str, ...] = ()

    causal_status: CausalStatus = CausalStatus.NOT_ASSESSED

    input_hash: str

    def to_row(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "relation_family": self.relation_family,
            "subject_ref": self.subject_ref,
            "object_ref": self.object_ref,
            "derivation": self.derivation.value,
            "assertion_hint": self.assertion_hint.value,
            "evidence_refs": tuple(self.evidence_refs),
            "support_types": tuple(self.support_types),
            "temporal_relation": (
                self.temporal_relation.model_dump()
                if self.temporal_relation else None
            ),
            "limitations": tuple(self.limitations),
            "causal_status": self.causal_status.value,
            "input_hash": self.input_hash,
        }

    @classmethod
    def from_row(cls, row: dict) -> "CorrelationCandidateV1":
        temporal = row.get("temporal_relation")
        return cls(
            correlation_id=row["correlation_id"],
            relation_family=row["relation_family"],
            subject_ref=row["subject_ref"],
            object_ref=row["object_ref"],
            derivation=CorrelationDerivation(row["derivation"]),
            assertion_hint=CorrelationAssertionHint(row["assertion_hint"]),
            evidence_refs=tuple(row["evidence_refs"]),
            support_types=tuple(row["support_types"]),
            temporal_relation=(
                TemporalRelation(**temporal) if temporal else None
            ),
            limitations=tuple(row["limitations"]),
            causal_status=CausalStatus(row["causal_status"]),
            input_hash=row["input_hash"],
        )


class CorrelationBounds(BaseModel):
    """§21 bounded generation. Provisional defaults; P8 calibrates."""

    model_config = ConfigDict(frozen=True)

    max_candidates: int = DEFAULT_MAX_CANDIDATES
    temporal_window_seconds: int = DEFAULT_TEMPORAL_WINDOW_SECONDS


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


class _CandidateFactory:
    """Builds deterministic, deduplicated candidates for one relation rule."""

    def __init__(
        self,
        *,
        task_id: str,
        investigation_id: str,
        relation_family: str,
        derivation: CorrelationDerivation,
        assertion_hint: CorrelationAssertionHint,
        support_types: tuple[str, ...],
        limitations: tuple[str, ...] = (),
        temporal_window: Optional[int] = None,
    ):
        self.task_id = task_id
        self.investigation_id = investigation_id
        self.relation_family = relation_family
        self.derivation = derivation
        self.assertion_hint = assertion_hint
        self.support_types = support_types
        self.limitations = limitations
        self.temporal_window = temporal_window
        self._seen: set[tuple[str, str]] = set()

    def pair(
        self,
        subject: EntityOccurrenceV1,
        object_: EntityOccurrenceV1,
        *,
        temporal_relation: Optional[TemporalRelation] = None,
    ) -> Optional[CorrelationCandidateV1]:
        left, right = sorted(
            (subject, object_), key=lambda item: item.occurrence_id
        )
        key = (left.occurrence_id, right.occurrence_id)
        if key in self._seen:
            return None
        self._seen.add(key)
        evidence_refs = sorted({
            left.evidence_ref,
            right.evidence_ref,
            *(left.provenance.get("additional_refs") or ()),
            *(right.provenance.get("additional_refs") or ()),
        })
        input_payload = {
            "engine_version": DETERMINISTIC_CORRELATION_VERSION,
            "task_id": self.task_id,
            "investigation_id": self.investigation_id,
            "relation_family": self.relation_family,
            "subject_ref": left.occurrence_id,
            "object_ref": right.occurrence_id,
            "evidence_refs": evidence_refs,
            "support_types": list(self.support_types),
        }
        input_hash = hashlib.sha256(
            _canonical(input_payload).encode("utf-8")
        ).hexdigest()
        return CorrelationCandidateV1(
            correlation_id=f"corr:{input_hash[:24]}",
            relation_family=self.relation_family,
            subject_ref=left.occurrence_id,
            object_ref=right.occurrence_id,
            derivation=self.derivation,
            assertion_hint=self.assertion_hint,
            evidence_refs=tuple(evidence_refs),
            support_types=self.support_types,
            temporal_relation=temporal_relation,
            limitations=self.limitations,
            causal_status=CausalStatus.NOT_ASSESSED,
            input_hash=input_hash,
        )


class DeterministicCorrelationEngine:
    """Bounded deterministic candidate generation over durable occurrences."""

    VERSION = DETERMINISTIC_CORRELATION_VERSION

    def __init__(
        self,
        *,
        bounds: Optional[CorrelationBounds] = None,
    ):
        self.bounds = bounds or CorrelationBounds()

    # -- public API ------------------------------------------------------

    def generate(
        self,
        occurrences: Sequence[EntityOccurrenceV1],
    ) -> tuple[CorrelationCandidateV1, ...]:
        if not occurrences:
            return ()
        task_ids = {item.task_id for item in occurrences}
        investigation_ids = {item.investigation_id for item in occurrences}
        if len(task_ids) != 1 or len(investigation_ids) != 1:
            raise ValueError(
                "correlation engine requires occurrences of exactly one "
                "task/investigation"
            )
        candidates: list[CorrelationCandidateV1] = []

        # 1-3. same match bucket: exact hash / normalized identifier /
        #       composite account (distinct evidence refs only)
        candidates.extend(self._identifier_bucket_candidates(occurrences))
        # 4. url host vs domain structural relation
        candidates.extend(self._url_domain_candidates(occurrences))
        # 5. structured co-occurrence inside one Evidence
        candidates.extend(self._co_occurrence_candidates(occurrences))
        # 6. bounded temporal overlap (hypothesis at most, never causal)
        candidates.extend(self._temporal_candidates(occurrences))

        # deterministic order: family/rule priority is generation order;
        # inside one rule, correlation_id order. Truncation is deterministic.
        unique: dict[str, CorrelationCandidateV1] = {}
        for candidate in candidates:
            unique.setdefault(candidate.correlation_id, candidate)
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                _RULE_PRIORITY[item.relation_family], item.correlation_id
            ),
        )
        return tuple(ordered[: self.bounds.max_candidates])

    # -- rules ------------------------------------------------------------

    def _bucketable(self, occurrence: EntityOccurrenceV1) -> bool:
        return occurrence.namespace not in _WEAK_NAMESPACES

    def _identifier_bucket_candidates(
        self, occurrences: Sequence[EntityOccurrenceV1]
    ) -> list[CorrelationCandidateV1]:
        buckets: dict[tuple[str, str], list[EntityOccurrenceV1]] = {}
        for occurrence in occurrences:
            if not self._bucketable(occurrence):
                continue
            buckets.setdefault(
                (occurrence.entity_type, occurrence.match_key), []
            ).append(occurrence)

        candidates: list[CorrelationCandidateV1] = []
        for (entity_type, _match_key), members in sorted(buckets.items()):
            distinct = self._distinct_evidence(members)
            if len(distinct) < 2:
                continue
            if entity_type == "file_hash":
                factory = _CandidateFactory(
                    task_id=distinct[0].task_id,
                    investigation_id=distinct[0].investigation_id,
                    relation_family="same_content_hash",
                    derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
                    assertion_hint=CorrelationAssertionHint.INFERENCE,
                    support_types=("exact_hash",),
                    limitations=(
                        "deterministic cross-artifact digest match; no "
                        "transfer/copy action is asserted",
                    ),
                )
            elif entity_type == "user_account":
                factory = _CandidateFactory(
                    task_id=distinct[0].task_id,
                    investigation_id=distinct[0].investigation_id,
                    relation_family="composite_account_match",
                    derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
                    assertion_hint=CorrelationAssertionHint.INFERENCE,
                    support_types=("composite_account",),
                    limitations=(
                        "same realm-qualified account string; not a proof "
                        "of the same natural person",
                    ),
                )
            else:
                factory = _CandidateFactory(
                    task_id=distinct[0].task_id,
                    investigation_id=distinct[0].investigation_id,
                    relation_family="normalized_identifier_match",
                    derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
                    assertion_hint=CorrelationAssertionHint.INFERENCE,
                    support_types=("normalized_identifier",),
                )
            for left, right in self._pairs(distinct):
                candidate = factory.pair(left, right)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _url_domain_candidates(
        self, occurrences: Sequence[EntityOccurrenceV1]
    ) -> list[CorrelationCandidateV1]:
        domains = {
            item.normalized_value: item
            for item in occurrences
            if item.entity_type == "domain"
        }
        if not domains:
            return []
        factory: Optional[_CandidateFactory] = None
        candidates: list[CorrelationCandidateV1] = []
        for occurrence in occurrences:
            if occurrence.entity_type != "url":
                continue
            host = occurrence.normalized_value.split("://", 1)[-1].split(
                "/", 1
            )[0].split(":", 1)[0].rstrip(".")
            target = domains.get(host)
            if target is None:
                continue
            if factory is None:
                factory = _CandidateFactory(
                    task_id=occurrence.task_id,
                    investigation_id=occurrence.investigation_id,
                    relation_family="url_domain_structure",
                    derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
                    assertion_hint=CorrelationAssertionHint.INFERENCE,
                    support_types=("url_domain_structure",),
                )
            candidate = factory.pair(occurrence, target)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _co_occurrence_candidates(
        self, occurrences: Sequence[EntityOccurrenceV1]
    ) -> list[CorrelationCandidateV1]:
        by_evidence: dict[str, list[EntityOccurrenceV1]] = {}
        for occurrence in occurrences:
            by_evidence.setdefault(occurrence.evidence_ref, []).append(
                occurrence
            )
        candidates: list[CorrelationCandidateV1] = []
        for evidence_ref, members in sorted(by_evidence.items()):
            distinct_values = {
                (item.entity_type, item.normalized_value)
                for item in members
            }
            if len(distinct_values) < 2:
                continue  # one distinct entity value is no co-occurrence
            ordered_members = sorted(members, key=lambda i: i.occurrence_id)
            factory = _CandidateFactory(
                task_id=ordered_members[0].task_id,
                investigation_id=ordered_members[0].investigation_id,
                relation_family="structured_co_occurrence",
                derivation=CorrelationDerivation.ARTIFACT_EXPLICIT,
                assertion_hint=CorrelationAssertionHint.OBSERVED,
                support_types=("co_occurrence",),
                limitations=(
                    f"both values are recorded inside {evidence_ref!r}; "
                    "the artifact records no relation between them",
                ),
            )
            for left, right in self._pairs(ordered_members):
                if (left.entity_type, left.normalized_value) == (
                    right.entity_type, right.normalized_value
                ):
                    continue
                candidate = factory.pair(left, right)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _temporal_candidates(
        self, occurrences: Sequence[EntityOccurrenceV1]
    ) -> list[CorrelationCandidateV1]:
        timed = [
            item for item in occurrences
            if item.temporal is not None
            and item.temporal.start is not None
            and item.temporal.end is not None
        ]
        if len(timed) < 2:
            return []
        factory = _CandidateFactory(
            task_id=timed[0].task_id,
            investigation_id=timed[0].investigation_id,
            relation_family="temporal_overlap",
            derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
            assertion_hint=CorrelationAssertionHint.HYPOTHESIS,
            support_types=("temporal_overlap",),
            limitations=(
                "temporal proximity only — never causal (P5A §19/§20)",
            ),
        )
        window = self.bounds.temporal_window_seconds
        candidates: list[CorrelationCandidateV1] = []
        for left, right in self._pairs(sorted(timed, key=lambda i: i.occurrence_id)):
            gap = max(
                0,
                right.temporal.start - left.temporal.end,
                left.temporal.start - right.temporal.end,
            )
            if gap > window:
                continue
            overlap = (
                left.temporal.start <= right.temporal.end
                and right.temporal.start <= left.temporal.end
            )
            candidate = factory.pair(
                left,
                right,
                temporal_relation=TemporalRelation(
                    kind="overlap" if overlap else "within_window",
                    gap_seconds=int(gap),
                    window_seconds=window,
                ),
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _distinct_evidence(
        members: Sequence[EntityOccurrenceV1],
    ) -> list[EntityOccurrenceV1]:
        """First occurrence per evidence ref, deterministic order."""
        seen: dict[str, EntityOccurrenceV1] = {}
        for item in sorted(members, key=lambda i: i.occurrence_id):
            seen.setdefault(item.evidence_ref, item)
        return sorted(seen.values(), key=lambda i: i.occurrence_id)

    @staticmethod
    def _pairs(items: Sequence[EntityOccurrenceV1]):
        for index in range(len(items)):
            for other in range(index + 1, len(items)):
                yield items[index], items[other]


_RULE_PRIORITY = {
    "same_content_hash": 0,
    "normalized_identifier_match": 1,
    "composite_account_match": 2,
    "url_domain_structure": 3,
    "structured_co_occurrence": 4,
    "temporal_overlap": 5,
}


__all__ = [
    "CORRELATION_CANDIDATE_VERSION",
    "DETERMINISTIC_CORRELATION_VERSION",
    "CausalStatus",
    "CorrelationAssertionHint",
    "CorrelationBounds",
    "CorrelationCandidateV1",
    "CorrelationDerivation",
    "DeterministicCorrelationEngine",
    "TemporalRelation",
]
