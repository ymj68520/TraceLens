"""B7/B8 final acceptance artifacts (P8B §65-§80, §100-§102).

Contracts for the final Agent v0 closure:

- SupportedResourceEnvelopeV1 (§67) — validated host assumptions, never
  auto-promoted from the dev machine;
- ModelSupportTier (§70) — validated/provisional/unsupported per
  provider+model+config;
- BenchmarkAcceptanceReportV1 (§71/§72) — the final report contract with
  the four §74 dispositions and NO aggregate score (§73);
- KnownLimitationsV1 (§80) — honest limitation inventory.

P8B discipline (§104): code complete != phase PASS.  When the holdout
has not run, the disposition is ACCEPTANCE PENDING, never PASS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

RESOURCE_ENVELOPE_VERSION = "supported-resource-envelope:v1"
ACCEPTANCE_REPORT_VERSION = "benchmark-acceptance-report:v1"
KNOWN_LIMITATIONS_VERSION = "known-limitations:v1"


class ModelSupportTier(str, Enum):
    """§70: per provider/model/config, never generalized."""

    validated = "validated"
    provisional = "provisional"
    unsupported = "unsupported"


class ModelSupportEntryV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model_id: str
    config_digest: str = ""
    tier: ModelSupportTier
    evidence_run_ids: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["evidence_run_ids"] = tuple(
                sorted(set(data.get("evidence_run_ids", ())))
            )
        return data


class SupportedResourceEnvelopeV1(BaseModel):
    """§67: measured envelope.  Dev-machine specs are recorded as
    ``measured_on`` context, NEVER as minimum requirements."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_version: str = RESOURCE_ENVELOPE_VERSION
    cpu_assumption: str = "x86_64 multi-core; no specific model required"
    ram_min_gb: Optional[float] = None
    ram_recommended_gb: Optional[float] = None
    gpu_required: bool = False
    gpu_note: str = ""
    context_window_min_tokens: Optional[int] = None
    graph_backend_required: bool = False
    measured_on: str = ""
    notes: str = ""


class ExternalValidationItemV1(BaseModel):
    """§77: one pending external validation, honestly recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: str
    reason: str
    blocking: bool = False  # True blocks PASS; False allows
    # PASS_WITH_LIMITATIONS per §76


class KnownLimitationsV1(BaseModel):
    """§80 machine-readable limitation inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limitations_version: str = KNOWN_LIMITATIONS_VERSION
    items: tuple[str, ...] = ()
    external_validations: tuple[ExternalValidationItemV1, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["items"] = tuple(dict.fromkeys(data.get("items", ())))
            data["external_validations"] = tuple(
                ExternalValidationItemV1.model_validate(item)
                for item in data.get("external_validations", ())
            )
        return data


class BenchmarkAcceptanceReportV1(BaseModel):
    """§71/§72 final acceptance report (machine-readable; human summary
    is generated from it).  §73: NO aggregate score field exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = ACCEPTANCE_REPORT_VERSION

    git_baseline: str
    freeze_chain: dict = Field(default_factory=dict)
    corpus_id: str
    corpus_hash: str
    calibration_profile_id: str = ""
    acceptance_profile_id: str = ""

    model_support: tuple[ModelSupportEntryV1, ...] = ()

    hard_gate_results: tuple[dict, ...] = ()
    quality_dashboard: dict = Field(default_factory=dict)
    cost_dashboard: dict = Field(default_factory=dict)
    reliability_dashboard: dict = Field(default_factory=dict)
    ablation_summary: dict = Field(default_factory=dict)
    calibration_changes: dict = Field(default_factory=dict)
    negative_case_results: dict = Field(default_factory=dict)
    graph_utility: dict = Field(default_factory=dict)
    report_correctness: dict = Field(default_factory=dict)
    large_case_status: str = "EXTERNAL_VALIDATION_PENDING"

    limitations: KnownLimitationsV1 = Field(
        default_factory=KnownLimitationsV1
    )

    disposition: str  # §74 exact disposition value
    disposition_reason: str = ""

    report_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data["model_support"] = tuple(
            sorted(
                (
                    ModelSupportEntryV1.model_validate(item)
                    for item in data.get("model_support", ())
                ),
                key=lambda item: (item.provider, item.model_id),
            )
        )
        data["limitations"] = KnownLimitationsV1.model_validate(
            data.get("limitations") or {}
        )
        for key in (
            "freeze_chain",
            "quality_dashboard",
            "cost_dashboard",
            "reliability_dashboard",
            "ablation_summary",
            "calibration_changes",
            "negative_case_results",
            "graph_utility",
            "report_correctness",
        ):
            data[key] = dict(sorted((data.get(key) or {}).items()))
        # defaulted-field normalization keeps report_hash IDEMPOTENT.
        data.setdefault("report_version", ACCEPTANCE_REPORT_VERSION)
        data.setdefault("calibration_profile_id", "")
        data.setdefault("acceptance_profile_id", "")
        data.setdefault("large_case_status", "EXTERNAL_VALIDATION_PENDING")
        data.setdefault("disposition_reason", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("report_hash", "created_at")
        }
        data["report_hash"] = sha256_hex(payload)
        return data

    @model_validator(mode="after")
    def _validate_disposition(self):
        from .acceptance import AcceptanceDisposition

        allowed = {item.value for item in AcceptanceDisposition}
        if self.disposition not in allowed:
            raise ValueError(
                f"disposition must be one of {sorted(allowed)}; "
                f"got {self.disposition!r} (§74)"
            )
        if self.disposition == "PASS" and any(
            item.blocking for item in self.limitations.external_validations
        ):
            raise ValueError(
                "a blocking external validation forbids PASS (§77)"
            )
        return self

    def human_summary(self) -> str:
        """§71: human-readable summary generated FROM the machine
        report — no separate hand-maintained numbers."""
        lines = [
            f"Agent v0 acceptance report {self.report_hash[:16]}",
            f"git baseline: {self.git_baseline}",
            f"corpus: {self.corpus_id} ({self.corpus_hash[:16]})",
            f"disposition: {self.disposition}",
        ]
        if self.disposition_reason:
            lines.append(f"reason: {self.disposition_reason}")
        failed_gates = [
            gate.get("gate_id")
            for gate in self.hard_gate_results
            if not gate.get("passed")
        ]
        lines.append(
            "hard gates: PASS" if not failed_gates
            else f"hard gates: FAIL {failed_gates}"
        )
        for entry in self.model_support:
            lines.append(
                f"model {entry.provider}/{entry.model_id}: {entry.tier.value}"
            )
        if self.limitations.items:
            lines.append(f"limitations: {len(self.limitations.items)} recorded")
        pending = [
            item.item
            for item in self.limitations.external_validations
        ]
        if pending:
            lines.append(f"external validations pending: {pending}")
        return "\n".join(lines)


__all__ = [
    "ACCEPTANCE_REPORT_VERSION",
    "BenchmarkAcceptanceReportV1",
    "KnownLimitationsV1",
    "ModelSupportEntryV1",
    "ModelSupportTier",
    "RESOURCE_ENVELOPE_VERSION",
    "SupportedResourceEnvelopeV1",
]
