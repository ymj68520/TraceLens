"""Benchmark case contract (P8A §18-§20, §76-§77).

``BenchmarkCaseV1`` binds dataset identity (per-file cryptographic hashes,
order-stable — never a directory path), the TruthManifest ref, the frozen
five-tier taxonomy, and negative-case flags.  Case files live under
``benchmarks/cases/<case_id>/`` (§53); nothing here enters
investigation.db or reports.db.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

BENCHMARK_CASE_VERSION = "benchmark-case:v1"
BENCHMARK_CASE_ID_PREFIX = "bcase:"


class BenchmarkTier(str, Enum):
    """§19 frozen five-tier taxonomy."""

    T0 = "T0"  # deterministic contract tests
    T1 = "T1"  # single device + clear Goal
    T2 = "T2"  # complex single-device reasoning / noise
    T3 = "T3"  # multi-device / cross-source / Graph / Report
    T4 = "T4"  # large real-world performance acceptance


class DatasetFileRefV1(BaseModel):
    """§56 one dataset member: logical id + size + cryptographic hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_id: str
    relative_path: str
    size_bytes: int
    sha256: str

    @model_validator(mode="after")
    def _validate(self):
        if len(self.sha256) != 64:
            raise ValueError("dataset file sha256 must be a hex digest")
        return self


class DatasetManifestV1(BaseModel):
    """§56 order-stable multi-mirror dataset identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str = "benchmark-dataset:v1"
    dataset_id: str
    files: tuple[DatasetFileRefV1, ...] = ()
    dataset_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("dataset_version", "benchmark-dataset:v1")
        data["files"] = tuple(
            sorted(
                (
                    DatasetFileRefV1.model_validate(item)
                    for item in data.get("files", ())
                ),
                key=lambda item: item.logical_id,
            )
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("dataset_hash", "created_at")
        }
        data["dataset_hash"] = sha256_hex(payload)
        return data


class NegativeCaseFlagsV1(BaseModel):
    """§20 negative-case dimensions a case exercises."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    no_incriminating_evidence: bool = False
    ambiguous_evidence: bool = False
    misleading_case_context: bool = False
    incorrect_analyst_hypothesis: bool = False
    same_username_different_person: bool = False
    temporal_proximity_not_causality: bool = False
    review_pending_tempting_conclusion: bool = False
    graph_hallucinated_relation: bool = False
    missing_critical_parser_support: bool = False
    provider_failure: bool = False


class BenchmarkCaseV1(BaseModel):
    """§18 one benchmark case contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_contract_version: str = BENCHMARK_CASE_VERSION

    case_id: str
    case_version: str
    title: str

    dataset: DatasetManifestV1

    truth_manifest_id: str
    truth_manifest_hash: str

    goal: str
    case_context: str

    platform_composition: tuple[str, ...] = ()

    tier: BenchmarkTier
    negative_flags: NegativeCaseFlagsV1 = Field(
        default_factory=NegativeCaseFlagsV1
    )
    expected_parser_profile: str = ""

    benchmark_tags: tuple[str, ...] = ()

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("case_contract_version", BENCHMARK_CASE_VERSION)
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        # defaulted-field normalization keeps input_hash IDEMPOTENT:
        # a JSON reload must hash the same payload as the first build.
        # Nested defaulted models are validated pre-hash so the payload
        # sees the full normalized form on both build and reload.
        data.setdefault("platform_composition", ())
        data.setdefault("benchmark_tags", ())
        data.setdefault("expected_parser_profile", "")
        data.setdefault("case_context", "")
        data.setdefault("title", "")
        data["dataset"] = DatasetManifestV1.model_validate(
            data.get("dataset")
        )
        data["negative_flags"] = NegativeCaseFlagsV1.model_validate(
            data.get("negative_flags") or {}
        )
        data["platform_composition"] = tuple(
            sorted(set(data.get("platform_composition", ())))
        )
        data["benchmark_tags"] = tuple(
            dict.fromkeys(sorted(data.get("benchmark_tags", ())))
        )
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("case_id", "input_hash", "created_at")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("case_id"):
            data["case_id"] = BENCHMARK_CASE_ID_PREFIX + digest[:24]
        return data

    @model_validator(mode="after")
    def _validate_binding(self):
        if not self.goal.strip():
            raise ValueError("benchmark case requires a Goal")
        return self


def verify_dataset_files(
    dataset: DatasetManifestV1, base_dir
) -> list[str]:
    """§56/§85 dry-run verification: every file must exist with the exact
    recorded size + sha256.  Returns the list of violations (empty = OK)."""
    import hashlib
    from pathlib import Path

    base = Path(base_dir)
    violations: list[str] = []
    for file_ref in dataset.files:
        path = base / file_ref.relative_path
        if not path.is_file():
            violations.append(
                f"{file_ref.logical_id}: missing file {file_ref.relative_path}"
            )
            continue
        size = path.stat().st_size
        if size != file_ref.size_bytes:
            violations.append(
                f"{file_ref.logical_id}: size mismatch "
                f"({size} != {file_ref.size_bytes})"
            )
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != file_ref.sha256:
            violations.append(
                f"{file_ref.logical_id}: sha256 mismatch"
            )
    known_ids = {ref.logical_id for ref in dataset.files}
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.name not in {"case.json", "truth_manifest.json"}:
            rel = path.relative_to(base).as_posix()
            if not any(
                ref.relative_path == rel for ref in dataset.files
            ) and rel not in {"run_configs", "results"}:
                violations.append(f"undeclared dataset file: {rel}")
    del known_ids
    return violations


__all__ = [
    "BENCHMARK_CASE_VERSION",
    "BenchmarkCaseV1",
    "BenchmarkTier",
    "DatasetFileRefV1",
    "DatasetManifestV1",
    "NegativeCaseFlagsV1",
    "verify_dataset_files",
]
