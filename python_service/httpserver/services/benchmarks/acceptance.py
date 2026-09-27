"""B2–B6 measurement/calibration/acceptance policy (P8B §20-§64, §89-§91).

Deterministic, fixture-testable policy modules:

- PreCalibrationProfileV1 — frozen baseline before ANY tuning (§20);
- CalibrationExperimentV1 — one controlled parameter experiment (§44);
- select_calibration_variant — constrained selection: hard gates first,
  then quality floors, then cost/reliability Pareto (§33; §89 tests);
- CalibrationComparisonReportV1 — improvements AND regressions (§49);
- AgentV0CalibrationProfileV1 — candidate profile after calibration (§45);
- AgentV0AcceptanceProfileV1 + evaluate_acceptance — holdout policy with
  case-level ceilings, zero-tolerance gates, and the four §74 dispositions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

PRE_CALIBRATION_PROFILE_VERSION = "pre-calibration-profile:v1"
CALIBRATION_EXPERIMENT_VERSION = "calibration-experiment:v1"
CALIBRATION_PROFILE_VERSION = "agent-v0-calibration-profile:v1"
ACCEPTANCE_PROFILE_VERSION = "agent-v0-acceptance-profile:v1"


class PreCalibrationProfileV1(BaseModel):
    """§20: frozen BEFORE any numeric production change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_version: str = PRE_CALIBRATION_PROFILE_VERSION
    git_commit: str
    parameter_values: dict = Field(default_factory=dict)
    model_config_id: str = ""
    prompt_versions: dict = Field(default_factory=dict)
    policy_versions: dict = Field(default_factory=dict)
    tool_registry_hash: str = ""
    graph_policy_version: str = ""
    report_policy_versions: dict = Field(default_factory=dict)
    inventory_hash: str = ""

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("profile_version", PRE_CALIBRATION_PROFILE_VERSION)
        for key in ("parameter_values", "prompt_versions",
                    "policy_versions", "report_policy_versions"):
            data[key] = dict(sorted((data.get(key) or {}).items()))
        data.setdefault("model_config_id", "")
        data.setdefault("tool_registry_hash", "")
        data.setdefault("graph_policy_version", "")
        data.setdefault("inventory_hash", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("input_hash", "created_at")
        }
        data["input_hash"] = sha256_hex(payload)
        return data


class ExperimentDecision(str, Enum):
    adopt = "adopt"
    reject = "reject"
    inconclusive = "inconclusive"


class CalibrationExperimentV1(BaseModel):
    """§44: ONE controlled experiment — changed parameters only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_version: str = CALIBRATION_EXPERIMENT_VERSION
    experiment_id: str
    baseline_profile_hash: str
    corpus_id: str
    changed_parameters: dict = Field(default_factory=dict)
    run_ids: tuple[str, ...] = ()
    metric_summaries: dict = Field(default_factory=dict)
    hard_gates_passed: bool
    tradeoffs: str = ""
    decision: ExperimentDecision
    rationale: str = ""

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("experiment_version", CALIBRATION_EXPERIMENT_VERSION)
        data.setdefault("tradeoffs", "")
        data.setdefault("rationale", "")
        data["changed_parameters"] = dict(
            sorted((data.get("changed_parameters") or {}).items())
        )
        data["metric_summaries"] = dict(
            sorted((data.get("metric_summaries") or {}).items())
        )
        data["run_ids"] = tuple(sorted(set(data.get("run_ids", ()))))
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("experiment_id", "input_hash", "created_at")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("experiment_id"):
            data["experiment_id"] = "bexp:" + digest[:24]
        return data


def select_calibration_variant(
    *,
    baseline: dict,
    variants: list[dict],
) -> dict:
    """§33/§89 constrained selection over ONE parameter group.

    Each entry: {name, hard_gates_passed, quality: {metric: value},
    cost: {metric: value}}.  Selection rule:

    1. a variant with any failed structural hard gate is NEVER selected;
    2. a variant that regresses any quality metric beyond its baseline
       floor is rejected;
    3. among survivors, prefer strict Pareto improvements (equal-or-
       better quality AND cost), then lower cost at equal quality;
    4. if nothing dominates, the decision is inconclusive → the baseline
       stands (zero parameter change is a valid outcome, §50).
    """
    if not baseline.get("hard_gates_passed"):
        return {"decision": "reject_all", "selected": None}
    survivors = [
        v for v in variants if v.get("hard_gates_passed")
    ]
    if not survivors:
        return {"decision": "reject_all", "selected": None}
    baseline_quality = baseline.get("quality", {})
    # quality floors: no regression on any baseline-known metric
    eligible = []
    for variant in survivors:
        quality = variant.get("quality", {})
        regression = [
            metric
            for metric, floor in baseline_quality.items()
            if metric in quality and quality[metric] < floor
        ]
        if regression:
            continue
        eligible.append(variant)
    if not eligible:
        return {"decision": "reject_all", "selected": None}
    baseline_cost = baseline.get("cost", {})
    pareto = []
    for variant in eligible:
        quality = variant.get("quality", {})
        cost = variant.get("cost", {})
        no_quality_regression = all(
            quality.get(metric, floor) >= floor
            for metric, floor in baseline_quality.items()
        )
        quality_improved = any(
            quality.get(metric, floor) > floor
            for metric, floor in baseline_quality.items()
        )
        cost_values = {
            metric: cost.get(metric, baseline_value)
            for metric, baseline_value in baseline_cost.items()
        }
        no_cost_regression = all(
            value <= baseline_value
            for metric, value in cost_values.items()
            for baseline_value in [baseline_cost.get(metric, value)]
        )
        cost_improved = any(
            value < baseline_cost.get(metric, value)
            for metric, value in cost_values.items()
        )
        if no_quality_regression and no_cost_regression and (
            quality_improved or cost_improved
        ):
            pareto.append(variant)
    if pareto:
        return {"decision": "adopt", "selected": pareto[0]["name"]}
    # no strict dominance → inconclusive; baseline stands (§50)
    return {"decision": "inconclusive", "selected": None}


class CalibrationComparisonReportV1(BaseModel):
    """§49: post-calibration comparison — every metric classified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = "calibration-comparison:v1"
    corpus_id: str
    baseline_profile_hash: str
    calibrated_profile_hash: str
    improvements: tuple[str, ...] = ()
    regressions: tuple[str, ...] = ()
    neutral: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    notes: str = ""

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("report_version", "calibration-comparison:v1")
        for key in ("improvements", "regressions", "neutral", "unavailable"):
            data[key] = tuple(sorted(set(data.get(key, ())))
                             ) if data.get(key) else ()
        data.setdefault("notes", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("input_hash", "created_at")
        }
        data["input_hash"] = sha256_hex(payload)
        return data


class AgentV0CalibrationProfileV1(BaseModel):
    """§45: candidate profile — final only after holdout acceptance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_version: str = CALIBRATION_PROFILE_VERSION
    profile_id: str
    status: str = "candidate"  # candidate | frozen
    baseline_commit: str
    tuned_parameters: dict = Field(default_factory=dict)
    unchanged_parameters: dict = Field(default_factory=dict)
    model_assumptions: dict = Field(default_factory=dict)
    policy_versions: dict = Field(default_factory=dict)
    expected_resource_class: str = ""
    calibration_corpus_hash: str = ""
    supporting_experiment_ids: tuple[str, ...] = ()

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        for key in ("tuned_parameters", "unchanged_parameters",
                    "model_assumptions", "policy_versions"):
            data[key] = dict(sorted((data.get(key) or {}).items()))
        data["supporting_experiment_ids"] = tuple(
            sorted(set(data.get("supporting_experiment_ids", ())))
        )
        data.setdefault("profile_version", CALIBRATION_PROFILE_VERSION)
        data.setdefault("status", "candidate")
        data.setdefault("expected_resource_class", "")
        data.setdefault("calibration_corpus_hash", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("profile_id", "input_hash", "created_at")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("profile_id"):
            data["profile_id"] = "acal:" + digest[:24]
        return data


class ThresholdType(str, Enum):
    case_level_ceiling = "case_level_ceiling"  # per-case hard max (§57)
    case_level_floor = "case_level_floor"  # per-case hard min
    aggregate = "aggregate"
    observational_only = "observational_only"


class AcceptanceThresholdV1(BaseModel):
    """§55 one threshold entry.  No threshold is invented for metrics the
    telemetry cannot support (§56)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str
    threshold_type: ThresholdType
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    rationale: str = ""
    supporting_experiment_ids: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["supporting_experiment_ids"] = tuple(
                sorted(set(data.get("supporting_experiment_ids", ())))
            )
        return data

    @model_validator(mode="after")
    def _validate(self):
        if self.threshold_type is ThresholdType.observational_only:
            return self
        if self.minimum is None and self.maximum is None:
            raise ValueError(
                f"threshold {self.metric_id} needs minimum or maximum"
            )
        if not self.rationale:
            raise ValueError(
                f"threshold {self.metric_id} needs recorded rationale"
            )
        return self


class AgentV0AcceptanceProfileV1(BaseModel):
    """§54/§55 frozen acceptance profile (content-addressed)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_version: str = ACCEPTANCE_PROFILE_VERSION
    profile_id: str
    status: str = "frozen"
    corpus_hash: str
    calibration_profile_hash: str
    model_provider: str
    model_id: str
    thresholds: tuple[AcceptanceThresholdV1, ...] = ()
    zero_tolerance_gate_ids: tuple[str, ...] = ()
    notes: str = ""

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data["thresholds"] = tuple(
            sorted(
                (
                    AcceptanceThresholdV1.model_validate(item)
                    for item in data.get("thresholds", ())
                ),
                key=lambda item: item.metric_id,
            )
        )
        data["zero_tolerance_gate_ids"] = tuple(
            sorted(set(data.get("zero_tolerance_gate_ids", ())))
        )
        # defaulted-field normalization keeps input_hash IDEMPOTENT.
        data.setdefault("profile_version", ACCEPTANCE_PROFILE_VERSION)
        data.setdefault("status", "frozen")
        data.setdefault("notes", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("profile_id", "input_hash", "created_at")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("profile_id"):
            data["profile_id"] = "aacc:" + digest[:24]
        return data


class AcceptanceDisposition(str, Enum):
    """§74 precise dispositions — never 'looks good'."""

    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS_WITH_LIMITATIONS"
    FAIL = "FAIL"
    EXTERNAL_VALIDATION_PENDING = "EXTERNAL_VALIDATION_PENDING"


def evaluate_acceptance(
    *,
    acceptance_profile: AgentV0AcceptanceProfileV1,
    hard_gate_results: list[dict],
    case_metrics: list[dict],
    corpus_aggregate_metrics: dict,
    unavailable_required_metrics: tuple[str, ...] = (),
    optional_capability_gaps: tuple[str, ...] = (),
) -> dict:
    """§53/§57/§91 acceptance policy.

    - ANY failed structural hard gate → FAIL (§53: never averaged);
    - a REQUIRED metric being unavailable → cannot PASS (§91);
    - case-level ceilings/floors apply per case (aggregate masking is
      impossible, §57);
    - observational-only metrics may be unavailable with a limitation;
    - optional non-safety capability gaps (T4, GPU telemetry) →
      PASS_WITH_LIMITATIONS, never for correctness failures (§76).
    """
    failed_gates = [g for g in hard_gate_results if not g.get("passed")]
    if failed_gates:
        return {
            "disposition": AcceptanceDisposition.FAIL.value,
            "reason": "structural zero-tolerance gate violation",
            "failed_gates": [g.get("gate_id") for g in failed_gates],
        }
    if unavailable_required_metrics:
        return {
            "disposition": AcceptanceDisposition.FAIL.value,
            "reason": "required metric unavailable (§91)",
            "unavailable": list(unavailable_required_metrics),
        }
    violations: list[dict] = []
    for threshold in acceptance_profile.thresholds:
        if threshold.threshold_type is ThresholdType.observational_only:
            continue
        if threshold.threshold_type in (
            ThresholdType.case_level_ceiling,
            ThresholdType.case_level_floor,
        ):
            for case_entry in case_metrics:
                value = case_entry.get("metrics", {}).get(threshold.metric_id)
                if value is None:
                    continue  # handled by unavailable-required logic
                if (
                    threshold.threshold_type
                    is ThresholdType.case_level_ceiling
                    and threshold.maximum is not None
                    and value > threshold.maximum
                ):
                    violations.append(
                        {
                            "metric": threshold.metric_id,
                            "case": case_entry.get("case_id"),
                            "value": value,
                            "ceiling": threshold.maximum,
                        }
                    )
                if (
                    threshold.threshold_type
                    is ThresholdType.case_level_floor
                    and threshold.minimum is not None
                    and value < threshold.minimum
                ):
                    violations.append(
                        {
                            "metric": threshold.metric_id,
                            "case": case_entry.get("case_id"),
                            "value": value,
                            "floor": threshold.minimum,
                        }
                    )
        else:  # aggregate
            value = corpus_aggregate_metrics.get(threshold.metric_id)
            if value is None:
                continue
            if threshold.maximum is not None and value > threshold.maximum:
                violations.append(
                    {
                        "metric": threshold.metric_id,
                        "aggregate": True,
                        "value": value,
                        "ceiling": threshold.maximum,
                    }
                )
            if threshold.minimum is not None and value < threshold.minimum:
                violations.append(
                    {
                        "metric": threshold.metric_id,
                        "aggregate": True,
                        "value": value,
                        "floor": threshold.minimum,
                    }
                )
    if violations:
        return {
            "disposition": AcceptanceDisposition.FAIL.value,
            "reason": "acceptance threshold violation (case-level where defined)",
            "violations": violations,
        }
    if optional_capability_gaps:
        return {
            "disposition": (
                AcceptanceDisposition.PASS_WITH_LIMITATIONS.value
            ),
            "reason": "optional non-safety capability unavailable (§76)",
            "gaps": list(optional_capability_gaps),
        }
    return {"disposition": AcceptanceDisposition.PASS.value, "reason": ""}


__all__ = [
    "AcceptanceDisposition",
    "AcceptanceThresholdV1",
    "AgentV0AcceptanceProfileV1",
    "AgentV0CalibrationProfileV1",
    "CALIBRATION_EXPERIMENT_VERSION",
    "CALIBRATION_PROFILE_VERSION",
    "ACCEPTANCE_PROFILE_VERSION",
    "CalibrationComparisonReportV1",
    "CalibrationExperimentV1",
    "ExperimentDecision",
    "PRE_CALIBRATION_PROFILE_VERSION",
    "PreCalibrationProfileV1",
    "ThresholdType",
    "evaluate_acceptance",
    "select_calibration_variant",
]
