"""P8B corpus manifest + split integrity (B1, §13-§19, §88).

Four-way split: development / calibration / acceptance_holdout / stress.
The holdout is structurally sealed: the manifest records its hashes and
the corpus refuses to expose holdout case payloads before the
calibration profile is frozen (§14/§32/§51).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex
from .benchmark_case import BenchmarkCaseV1

CORPUS_MANIFEST_VERSION = "benchmark-corpus-manifest:v1"


class CorpusSplit(str, Enum):
    development = "development"
    calibration = "calibration"
    acceptance_holdout = "acceptance_holdout"
    stress = "stress"


class CorpusCaseRefV1(BaseModel):
    """One frozen case entry: hashes only — the holdout payload is NOT
    embedded here (§14)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    case_hash: str
    truth_manifest_id: str
    truth_manifest_hash: str
    dataset_hash: str
    tier: str
    negative_dimensions: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["negative_dimensions"] = tuple(
                dict.fromkeys(sorted(data.get("negative_dimensions", ())))
            )
        return data


class CoverageMatrixV1(BaseModel):
    """§16 coverage matrix over the frozen dimensions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    single_device_clear: bool = False
    single_device_noisy: bool = False
    multi_source_correlation: bool = False
    cross_device_relation: bool = False
    evidence_absent_indeterminate: bool = False
    analyst_note_misleading: bool = False
    case_context_misleading: bool = False
    same_username_identity_trap: bool = False
    same_ip_identity_trap: bool = False
    temporal_causality_trap: bool = False
    malicious_intent_trap: bool = False
    review_pending_vs_accepted: bool = False
    graph_optional_failure: bool = False
    report_citation_ceiling: bool = False
    provider_tool_failure: bool = False

    def covered_dimensions(self) -> tuple[str, ...]:
        return tuple(
            field
            for field in self.__class__.model_fields
            if getattr(self, field)
        )

    def missing_dimensions(self) -> tuple[str, ...]:
        return tuple(
            field
            for field in self.__class__.model_fields
            if not getattr(self, field)
        )


class BenchmarkCorpusManifestV1(BaseModel):
    """§15 content-addressed, versioned corpus freeze."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = CORPUS_MANIFEST_VERSION

    corpus_id: str
    version: str

    development_cases: tuple[CorpusCaseRefV1, ...] = ()
    calibration_cases: tuple[CorpusCaseRefV1, ...] = ()
    acceptance_cases: tuple[CorpusCaseRefV1, ...] = ()
    stress_cases: tuple[CorpusCaseRefV1, ...] = ()

    freeze_commit: str
    selection_rationale: str = ""
    coverage_matrix: CoverageMatrixV1 = Field(default_factory=CoverageMatrixV1)
    known_exclusions: tuple[str, ...] = ()
    # §19: recorded honestly — never claim inter-rater agreement without it
    truth_review_status: str = "single-reviewer"
    # B4/B6 gate: set when the calibration profile freezes; the corpus
    # refuses holdout exposure before that.
    calibration_profile_hash: Optional[str] = None

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        for key in (
            "development_cases",
            "calibration_cases",
            "acceptance_cases",
            "stress_cases",
        ):
            data[key] = tuple(
                sorted(
                    (
                        CorpusCaseRefV1.model_validate(item)
                        for item in data.get(key, ())
                    ),
                    key=lambda item: item.case_id,
                )
            )
        data["known_exclusions"] = tuple(
            dict.fromkeys(data.get("known_exclusions", ()))
        )
        # defaulted-field normalization keeps input_hash IDEMPOTENT (P7B
        # discipline): nested models validated pre-hash.
        data.setdefault("manifest_version", CORPUS_MANIFEST_VERSION)
        data.setdefault("selection_rationale", "")
        data.setdefault("truth_review_status", "single-reviewer")
        data.setdefault("calibration_profile_hash", None)
        data["coverage_matrix"] = CoverageMatrixV1.model_validate(
            data.get("coverage_matrix") or {}
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("corpus_id", "input_hash", "created_at")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("corpus_id"):
            data["corpus_id"] = "bcorpus:" + digest[:24]
        return data

    @model_validator(mode="after")
    def _validate_split_integrity(self):
        seen: dict[str, str] = {}
        for split in (
            "development_cases",
            "calibration_cases",
            "acceptance_cases",
            "stress_cases",
        ):
            for ref in getattr(self, split):
                owner = seen.get(ref.case_id)
                if owner is not None:
                    raise ValueError(
                        f"case {ref.case_id} appears in both {owner} "
                        f"and {split} (§88: no case in >1 split)"
                    )
                seen[ref.case_id] = split
        if not self.calibration_cases:
            raise ValueError("calibration split must not be empty")
        if not self.acceptance_cases:
            raise ValueError("acceptance_holdout split must not be empty")
        return self

    # -- holdout integrity (§14/§32/§51) ------------------------------------

    def release_holdout(self, *, calibration_profile_hash: str) -> "BenchmarkCorpusManifestV1":
        """Only a frozen calibration profile unlocks holdout exposure."""
        if not calibration_profile_hash:
            raise ValueError("calibration profile hash required")
        return self.model_copy(
            update={"calibration_profile_hash": calibration_profile_hash}
        )

    def holdout_released(self) -> bool:
        return self.calibration_profile_hash is not None

    def assert_holdout_released(self) -> None:
        if not self.holdout_released():
            raise ValueError(
                "acceptance holdout is sealed: calibration profile must "
                "freeze before any holdout execution (§32/§51)"
            )

    def case_refs(self, split: CorpusSplit) -> tuple[CorpusCaseRefV1, ...]:
        field_name = (
            "acceptance_cases"
            if split is CorpusSplit.acceptance_holdout
            else split.value + "_cases"
        )
        return tuple(getattr(self, field_name))

    def all_case_ids(self) -> tuple[str, ...]:
        return tuple(
            ref.case_id
            for split in CorpusSplit
            for ref in self.case_refs(split)
        )


def build_case_ref(case: BenchmarkCaseV1) -> CorpusCaseRefV1:
    from .truth_manifest import TruthManifestV1

    return CorpusCaseRefV1(
        case_id=case.case_id,
        case_hash=case.input_hash,
        truth_manifest_id=case.truth_manifest_id,
        truth_manifest_hash=case.truth_manifest_hash,
        dataset_hash=case.dataset.dataset_hash,
        tier=case.tier.value,
        negative_dimensions=tuple(
            field
            for field, value in case.negative_flags.model_dump().items()
            if value
        ),
    )


def verify_corpus_hashes(
    corpus: BenchmarkCorpusManifestV1,
    cases: dict[str, BenchmarkCaseV1],
) -> list[str]:
    """§88: every recorded hash must match the submitted case objects."""
    violations: list[str] = []
    for split in CorpusSplit:
        for ref in corpus.case_refs(split):
            case = cases.get(ref.case_id)
            if case is None:
                violations.append(f"{ref.case_id}: missing case object")
                continue
            if case.input_hash != ref.case_hash:
                violations.append(f"{ref.case_id}: case hash mismatch")
            if case.truth_manifest_hash != ref.truth_manifest_hash:
                violations.append(f"{ref.case_id}: truth hash mismatch")
            if case.dataset.dataset_hash != ref.dataset_hash:
                violations.append(f"{ref.case_id}: dataset hash mismatch")
    for case_id in cases:
        if case_id not in corpus.all_case_ids():
            violations.append(f"{case_id}: not recorded in the corpus")
    return violations


def check_minimum_independence(
    corpus: BenchmarkCorpusManifestV1, *,
    critical_negative_dimensions: tuple[str, ...],
) -> list[str]:
    """§18: every critical negative dimension needs >1 independent
    instance somewhere in the corpus; returns violations."""
    counts: dict[str, int] = {}
    for split in CorpusSplit:
        for ref in corpus.case_refs(split):
            for dimension in ref.negative_dimensions:
                counts[dimension] = counts.get(dimension, 0) + 1
    return [
        f"negative dimension {dimension!r} has "
        f"{counts.get(dimension, 0)} instances (needs >1)"
        for dimension in critical_negative_dimensions
        if counts.get(dimension, 0) < 2
    ]


__all__ = [
    "BenchmarkCorpusManifestV1",
    "CORPUS_MANIFEST_VERSION",
    "CorpusCaseRefV1",
    "CorpusSplit",
    "CoverageMatrixV1",
    "build_case_ref",
    "check_minimum_independence",
    "verify_corpus_hashes",
]
