"""Truth Manifest contracts (P8A §6-§17, §87).

The Truth Manifest is a structured benchmark ORACLE, never a reference
report and never TraceLens Evidence.  The production Agent, Writer,
Verifier, Graph, and ReportContextPack must never see any part of it
(§54/§55 — enforced by the leakage tests).

Three-valued truth (§7): ``confirmed`` / ``unsupported`` /
``indeterminate``.  "Evidence 不足" is a legitimate truth answer; the
manifest never forces binary true/false.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

TRUTH_MANIFEST_VERSION = "truth-manifest:v1"
TRUTH_MANIFEST_ID_PREFIX = "tman:"


class TruthStatus(str, Enum):
    """§7 three-valued truth status."""

    confirmed = "confirmed"
    unsupported = "unsupported"
    indeterminate = "indeterminate"


class EvidenceCriticality(str, Enum):
    """§9 criticality axis (orthogonal to availability)."""

    critical = "critical"
    supporting = "supporting"
    irrelevant = "irrelevant"


class ParserExpectation(str, Enum):
    """§8/§9 parser-reachability expectation declared by the truth author."""

    reachable = "reachable"
    unavailable = "unavailable"
    conditional = "conditional"


class AssertionClass(str, Enum):
    """Maximum assertion class a confirmed claim may be stated at (§13)."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class ClaimSemanticType(str, Enum):
    """§12 semantic flags that drive overreach metrics."""

    factual = "factual"
    causal = "causal"
    actor_attribution = "actor_attribution"
    identity_merge = "identity_merge"
    intent = "intent"
    temporal = "temporal"


class QuestionDispositionExpectation(str, Enum):
    """§15 expected terminal disposition for one truth question."""

    answered = "answered"
    unresolved = "unresolved"
    blocked = "blocked"
    superseded = "superseded"
    any_terminal = "any_terminal"


class CoverageStatusExpectation(str, Enum):
    """§16 expected coverage terminal states."""

    covered = "covered"
    partial = "partial"
    unavailable = "unavailable"
    not_applicable = "not_applicable"


class TruthEvidenceItemV1(BaseModel):
    """§9 one ground-truth evidence item.

    The truth author describes identity in prose plus an optional
    ``expected_evidence_key``; the case-preparation reachability resolver
    (§10) binds real TraceLens evidence keys later.  Availability is
    always ``ground_truth`` here — the reachability layers are computed,
    not declared.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    truth_evidence_id: str
    evidence_identity_description: str
    expected_evidence_key: Optional[str] = None
    criticality: EvidenceCriticality
    parser_expectation: ParserExpectation
    source_kind: str = ""
    semantic_role: str = ""
    related_claim_ids: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            for key in ("related_claim_ids",):
                data[key] = tuple(dict.fromkeys(data.get(key, ())))
        return data


class ReachabilityStatus(str, Enum):
    """§10 resolver outcome per truth evidence item."""

    resolved = "resolved"
    parser_unavailable = "parser_unavailable"
    tool_not_exposed = "tool_not_exposed"
    unresolved = "unresolved"


class EvidenceReachabilityRecordV1(BaseModel):
    """§10/§11 one row of the Parser Reachability Manifest.

    ``parser_reachable`` / ``agent_discoverable`` are separate booleans:
    a parser-produced record no tool exposes is
    ``parser_reachable=True, agent_discoverable=False`` (a TOOL_EXPOSURE
    gap, not a reasoning-recall failure).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    truth_evidence_id: str
    resolved_evidence_keys: tuple[str, ...] = ()
    parser_reachable: bool
    agent_discoverable: bool
    status: ReachabilityStatus
    unavailable_reason: str = ""

    @model_validator(mode="after")
    def _validate_consistency(self):
        if self.parser_reachable and self.status == (
            ReachabilityStatus.parser_unavailable
        ):
            raise ValueError(
                "parser_reachable items cannot be parser_unavailable"
            )
        if self.agent_discoverable and not self.parser_reachable:
            raise ValueError(
                "agent_discoverable implies parser_reachable"
            )
        if self.status == ReachabilityStatus.resolved and (
            not self.resolved_evidence_keys or not self.agent_discoverable
        ):
            raise ValueError(
                "resolved reachability requires keys and discoverability"
            )
        if self.status != ReachabilityStatus.resolved and (
            not self.unavailable_reason
        ):
            raise ValueError("unresolved reachability requires a reason")
        return self


class ReachabilityManifestV1(BaseModel):
    """§10 output of the Parser Reachability Resolver for one case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reachability_version: str = "reachability-manifest:v1"
    case_id: str
    records: tuple[EvidenceReachabilityRecordV1, ...] = ()
    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        # defaulted-field normalization keeps input_hash IDEMPOTENT (P7B
        # discipline): a JSON replay must hash the same payload as the
        # first build.
        data.setdefault("reachability_version", "reachability-manifest:v1")
        data["records"] = tuple(
            sorted(
                (
                    EvidenceReachabilityRecordV1.model_validate(item)
                    for item in data.get("records", ())
                ),
                key=lambda item: item.truth_evidence_id,
            )
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("input_hash", "created_at")
        }
        data["input_hash"] = sha256_hex(payload)
        return data


class TruthClaimV1(BaseModel):
    """§12/§13/§14 one truth claim (proposition, not prose report)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    proposition: str
    truth_status: TruthStatus
    # §13: an acceptable inference carries an explicit ceiling so
    # "correct conclusion, too-strong assertion" is measurable.
    maximum_assertion_class: Optional[AssertionClass] = None
    required_evidence_ids: tuple[str, ...] = ()
    acceptable_evidence_sets: tuple[tuple[str, ...], ...] = ()
    forbidden_evidence_shortcuts: tuple[str, ...] = ()
    semantic_type: ClaimSemanticType = ClaimSemanticType.factual
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["required_evidence_ids"] = tuple(
                dict.fromkeys(data.get("required_evidence_ids", ()))
            )
            data["forbidden_evidence_shortcuts"] = tuple(
                dict.fromkeys(data.get("forbidden_evidence_shortcuts", ()))
            )
            data["acceptable_evidence_sets"] = tuple(
                tuple(dict.fromkeys(sorted(entry)))
                for entry in data.get("acceptable_evidence_sets", ())
            )
        return data

    @model_validator(mode="after")
    def _validate_contract(self):
        if self.truth_status == TruthStatus.confirmed and (
            self.maximum_assertion_class is None
        ):
            raise ValueError(
                "confirmed claims must declare maximum_assertion_class"
            )
        if self.truth_status != TruthStatus.confirmed and (
            self.maximum_assertion_class is not None
        ):
            raise ValueError(
                "non-confirmed claims carry no assertion ceiling"
            )
        if self.truth_status == TruthStatus.unsupported and (
            self.required_evidence_ids or self.acceptable_evidence_sets
        ):
            raise ValueError(
                "unsupported claims must not require evidence support"
            )
        return self


class TruthQuestionV1(BaseModel):
    """§15 one expected question.  ``unresolved`` can be the correct
    terminal state; the metrics never reward only "answered"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    text: str
    expected_disposition: QuestionDispositionExpectation
    required_evidence_ids: tuple[str, ...] = ()
    acceptable_answers: tuple[str, ...] = ()
    unacceptable_answers: tuple[str, ...] = ()
    priority: int = 0
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            for key in (
                "required_evidence_ids",
                "acceptable_answers",
                "unacceptable_answers",
            ):
                data[key] = tuple(dict.fromkeys(data.get(key, ())))
        return data


class TruthCoverageV1(BaseModel):
    """§16 one expected coverage dimension.

    ``requires_closure_basis`` marks dimensions where a terminal
    ``not_applicable`` WITHOUT a capability basis counts as an Unjustified
    Coverage Closure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension_id: str
    description: str = ""
    expected_status: CoverageStatusExpectation
    requires_closure_basis: bool = False
    required_evidence_ids: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["required_evidence_ids"] = tuple(
                dict.fromkeys(data.get("required_evidence_ids", ()))
            )
        return data


class TruthRelationV1(BaseModel):
    """§17 one expected relation (correlation / identity / causality)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relation_id: str
    subject_entity: str
    relation_family: str
    object_entity: str
    truth_status: TruthStatus
    maximum_assertion_class: Optional[AssertionClass] = None
    expected_evidence_ids: tuple[str, ...] = ()
    identity_merge_allowed: bool = False
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["expected_evidence_ids"] = tuple(
                dict.fromkeys(data.get("expected_evidence_ids", ()))
            )
        return data

    @model_validator(mode="after")
    def _validate_contract(self):
        if self.truth_status == TruthStatus.confirmed and (
            self.maximum_assertion_class is None
        ):
            raise ValueError(
                "confirmed relations must declare maximum_assertion_class"
            )
        return self


class TruthManifestV1(BaseModel):
    """§6 versioned structured truth oracle for one benchmark case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = TRUTH_MANIFEST_VERSION

    manifest_id: str
    case_id: str
    case_version: str

    critical_evidence: tuple[TruthEvidenceItemV1, ...] = ()
    supporting_evidence: tuple[TruthEvidenceItemV1, ...] = ()
    irrelevant_evidence: tuple[TruthEvidenceItemV1, ...] = ()

    expected_questions: tuple[TruthQuestionV1, ...] = ()
    confirmed_claims: tuple[TruthClaimV1, ...] = ()
    acceptable_inferences: tuple[TruthClaimV1, ...] = ()
    unsupported_or_prohibited_overclaims: tuple[TruthClaimV1, ...] = ()

    expected_relations: tuple[TruthRelationV1, ...] = ()
    expected_coverage: tuple[TruthCoverageV1, ...] = ()

    known_ambiguities: tuple[str, ...] = ()
    unavailable_truth: tuple[str, ...] = ()

    notes: str = ""

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("manifest_version", TRUTH_MANIFEST_VERSION)
        # Nested items are validated BEFORE hashing so the manifest payload
        # sees fully-normalized nested models on BOTH the first build and a
        # JSON reload (defaulted nested fields would otherwise differ).
        def _sorted(key, model, id_field):
            items = [
                model.model_validate(item) for item in data.get(key, ())
            ]
            return tuple(
                sorted(items, key=lambda item: getattr(item, id_field))
            )

        for key, model, id_field in (
            ("critical_evidence", TruthEvidenceItemV1, "truth_evidence_id"),
            ("supporting_evidence", TruthEvidenceItemV1, "truth_evidence_id"),
            ("irrelevant_evidence", TruthEvidenceItemV1, "truth_evidence_id"),
            ("expected_questions", TruthQuestionV1, "question_id"),
            ("confirmed_claims", TruthClaimV1, "claim_id"),
            ("acceptable_inferences", TruthClaimV1, "claim_id"),
            (
                "unsupported_or_prohibited_overclaims",
                TruthClaimV1,
                "claim_id",
            ),
            ("expected_relations", TruthRelationV1, "relation_id"),
            ("expected_coverage", TruthCoverageV1, "dimension_id"),
        ):
            data[key] = _sorted(key, model, id_field)
        data.setdefault("case_id", "")
        data.setdefault("case_version", "")
        for key in (
            "known_ambiguities",
            "unavailable_truth",
        ):
            data[key] = tuple(dict.fromkeys(data.get(key, ())))
        # defaulted-field normalization keeps input_hash IDEMPOTENT:
        # a JSON reload must hash the same payload as the first build.
        data.setdefault("notes", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("manifest_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("manifest_id"):
            data["manifest_id"] = TRUTH_MANIFEST_ID_PREFIX + digest[:24]
        return data

    @model_validator(mode="after")
    def _validate_id_uniqueness(self):
        evidence_items = (
            *self.critical_evidence,
            *self.supporting_evidence,
            *self.irrelevant_evidence,
        )
        evidence_ids = [item.truth_evidence_id for item in evidence_items]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("duplicate truth_evidence_id in manifest")
        critical_ids = {
            item.truth_evidence_id for item in self.critical_evidence
        }
        supporting_ids = {
            item.truth_evidence_id for item in self.supporting_evidence
        }
        if critical_ids & supporting_ids:
            raise ValueError(
                "truth evidence item cannot be both critical and supporting"
            )
        question_ids = [q.question_id for q in self.expected_questions]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("duplicate question_id in manifest")
        claim_ids = [
            c.claim_id
            for c in (
                *self.confirmed_claims,
                *self.acceptable_inferences,
                *self.unsupported_or_prohibited_overclaims,
            )
        ]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("duplicate claim_id across truth claim groups")
        relation_ids = [r.relation_id for r in self.expected_relations]
        if len(set(relation_ids)) != len(relation_ids):
            raise ValueError("duplicate relation_id in manifest")
        coverage_ids = [c.dimension_id for c in self.expected_coverage]
        if len(set(coverage_ids)) != len(coverage_ids):
            raise ValueError("duplicate coverage dimension_id in manifest")
        # every claim's evidence references must exist in the manifest
        known_evidence = set(evidence_ids)
        for claim in (
            *self.confirmed_claims,
            *self.acceptable_inferences,
        ):
            unknown = [
                ref
                for ref in claim.required_evidence_ids
                if ref not in known_evidence
            ]
            if unknown:
                raise ValueError(
                    f"claim {claim.claim_id} references unknown truth "
                    f"evidence: {sorted(unknown)}"
                )
        return self

    # -- derived accessors -------------------------------------------------

    def all_evidence_items(self) -> tuple[TruthEvidenceItemV1, ...]:
        return (
            *self.critical_evidence,
            *self.supporting_evidence,
            *self.irrelevant_evidence,
        )

    def evidence_by_id(self, truth_evidence_id: str):
        for item in self.all_evidence_items():
            if item.truth_evidence_id == truth_evidence_id:
                return item
        return None

    def all_claims(self) -> tuple[TruthClaimV1, ...]:
        return (
            *self.confirmed_claims,
            *self.acceptable_inferences,
            *self.unsupported_or_prohibited_overclaims,
        )


__all__ = [
    "AssertionClass",
    "ClaimSemanticType",
    "CoverageStatusExpectation",
    "EvidenceCriticality",
    "EvidenceReachabilityRecordV1",
    "ParserExpectation",
    "QuestionDispositionExpectation",
    "ReachabilityManifestV1",
    "ReachabilityStatus",
    "TRUTH_MANIFEST_VERSION",
    "TruthClaimV1",
    "TruthCoverageV1",
    "TruthEvidenceItemV1",
    "TruthManifestV1",
    "TruthQuestionV1",
    "TruthRelationV1",
    "TruthStatus",
]
