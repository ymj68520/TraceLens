"""Production calibration inventory (P8B §3-§5).

Records every production tunable with its owner phase, current value,
config source, semantic-vs-numeric classification, P8 calibratability,
and safety floor.  Semantic/architecture invariants (§4) are listed and
marked NOT calibratable so calibration can never quietly touch them.
The inventory is data derived from the repository at the P8A frozen
baseline; P8B must not invent new knobs (§5).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

CALIBRATION_INVENTORY_VERSION = "production-calibration-inventory:v1"


class CalibratableInP8(str, Enum):
    yes = "yes"
    no = "no"


class ParameterKind(str, Enum):
    semantic = "semantic"
    numeric = "numeric"


class CalibrationParameterV1(BaseModel):
    """§3 one calibratable (or explicitly non-calibratable) parameter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter_id: str
    owner_phase: str  # P1..P7
    description: str

    current_value: Optional[str] = None
    config_source: str = ""
    runtime_override_source: str = ""

    kind: ParameterKind
    calibratable_in_p8: CalibratableInP8
    safety_floor: str = ""
    invariant: str = ""
    observed_metric_dependencies: tuple[str, ...] = ()
    restart_required: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if isinstance(data, dict):
            data["observed_metric_dependencies"] = tuple(
                dict.fromkeys(data.get("observed_metric_dependencies", ()))
            )
        return data

    @model_validator(mode="after")
    def _validate_kind_gate(self):
        if self.kind is ParameterKind.semantic and (
            self.calibratable_in_p8 is CalibratableInP8.yes
        ):
            raise ValueError(
                f"semantic parameter {self.parameter_id} is an architecture "
                "invariant and cannot be calibrated in P8 (§4)"
            )
        if self.calibratable_in_p8 is CalibratableInP8.no and not (
            self.safety_floor or self.invariant
        ):
            raise ValueError(
                f"non-calibratable parameter {self.parameter_id} must state "
                "its safety floor or invariant"
            )
        return self


class ProductionCalibrationInventoryV1(BaseModel):
    """§3 content-addressed inventory over the frozen baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inventory_version: str = CALIBRATION_INVENTORY_VERSION

    baseline_commit: str
    parameters: tuple[CalibrationParameterV1, ...] = ()

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data["parameters"] = tuple(
            sorted(
                (
                    CalibrationParameterV1.model_validate(item)
                    for item in data.get("parameters", ())
                ),
                key=lambda item: item.parameter_id,
            )
        )
        if not data.get("created_at"):
            from datetime import datetime, timezone

            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("input_hash", "created_at")
        }
        data["input_hash"] = sha256_hex(payload)
        return data

    def calibratable_parameters(self) -> tuple[CalibrationParameterV1, ...]:
        return tuple(
            p
            for p in self.parameters
            if p.calibratable_in_p8 is CalibratableInP8.yes
        )

    def invariants(self) -> tuple[CalibrationParameterV1, ...]:
        return tuple(
            p
            for p in self.parameters
            if p.calibratable_in_p8 is CalibratableInP8.no
        )


def build_default_inventory(*, baseline_commit: str) -> ProductionCalibrationInventoryV1:
    """§3/§5 inventory taken from the real repository at the P8A baseline.

    Values recorded verbatim from the code; P8B never invents knobs.
    """
    return ProductionCalibrationInventoryV1(
        baseline_commit=baseline_commit,
        parameters=(
            # -- §5 numeric / operational knobs (calibratable) ------------
            CalibrationParameterV1(
                parameter_id="supervisor.max_cycles_per_invocation",
                owner_phase="P4B",
                description="cycle budget for one orchestrator run_loop invocation",
                current_value="1",
                config_source="SupervisorCyclePolicy default (agent_orchestrator.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor=">= 1 (ge=1); must not force premature closure",
                observed_metric_dependencies=(
                    "premature_closure_rate",
                    "budget exhaustion",
                    "wall time",
                ),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="supervisor.max_cycles_per_run",
                owner_phase="P4B",
                description="cycle budget across one run lifetime",
                current_value="20",
                config_source="SupervisorCyclePolicy default (agent_orchestrator.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor=">= 1; no mass budget-exhausted terminations (§36)",
                observed_metric_dependencies=("premature_closure_rate", "wall time"),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="attention.window_size",
                owner_phase="P4",
                description="AttentionSet window capacity (None = unbounded default)",
                current_value="None",
                config_source="AttentionPolicyConfig default (agent_attention.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="critical obligations must not be dropped (§35)",
                observed_metric_dependencies=(
                    "critical_evidence_recall",
                    "no-progress episodes",
                    "token growth",
                ),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="attention.exploration_allowance",
                owner_phase="P4",
                description="exploratory attention allowance",
                current_value="None",
                config_source="AttentionPolicyConfig default (agent_attention.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="exploration suppression only when budget exhausted",
                observed_metric_dependencies=(
                    "critical_evidence_recall",
                    "productive_tool_call_ratio",
                ),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="specialist.max_output_retries",
                owner_phase="P4A",
                description="structured-output retries per specialist attempt",
                current_value="2",
                config_source="AgentRunPolicy default (agent_specialist_executor.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor=">= 0; ceiling violations are never retried blindly",
                observed_metric_dependencies=("wall time", "provider calls"),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="correlation.max_candidates",
                owner_phase="P5",
                description="correlation candidate cap (explicitly provisional per P5)",
                current_value="200",
                config_source="CorrelationBounds default (agent_correlation.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="False Entity Merge rate has priority over recall (§40)",
                observed_metric_dependencies=(
                    "correlation_recall",
                    "false_entity_merge_rate",
                ),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="correlation.temporal_window_seconds",
                owner_phase="P5",
                description="bounded temporal window (explicitly provisional per P5)",
                current_value="3600",
                config_source="CorrelationBounds default (agent_correlation.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="temporal proximity must not imply causality (§73)",
                observed_metric_dependencies=("causal_overreach_rate",),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="graph.max_candidates_per_cycle",
                owner_phase="P6A",
                description="graph candidate admission budget per cycle",
                current_value="32",
                config_source="DEFAULT_MAX_CANDIDATES_PER_CYCLE (agent_graph_admission.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="graph utility must justify cost (§41)",
                observed_metric_dependencies=(
                    "graph utility",
                    "materialization count",
                    "wall time",
                ),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="graph.max_parallel_materializations",
                owner_phase="P6B",
                description="graph materialization concurrency",
                current_value="2",
                config_source="GraphMaterializer max_parallel default",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="backend rate limits; admission policy untouched",
                observed_metric_dependencies=("wall time", "graph cost"),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="report.max_evidence_items",
                owner_phase="P7A",
                description="report pack evidence item budget",
                current_value="24",
                config_source="RetrievalBudgetV1 default (report_hydration.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="citation completeness/semantic sufficiency targets (§42)",
                observed_metric_dependencies=(
                    "citation completeness",
                    "context compression",
                ),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="report.max_detailed_items",
                owner_phase="P7A",
                description="detailed hydration count per pack",
                current_value="4",
                config_source="RetrievalBudgetV1 default (report_hydration.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="semantic citation sufficiency target",
                observed_metric_dependencies=("semantic citation sufficiency",),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="report.max_context_chars",
                owner_phase="P7A",
                description="ContextPack character budget",
                current_value="48000",
                config_source="RetrievalBudgetV1 default (report_hydration.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="no citation/starvation failures (§42)",
                observed_metric_dependencies=("context compression", "writer tokens"),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="report.max_graph_expansion",
                owner_phase="P7A",
                description="graph expansion budget per pack",
                current_value="8",
                config_source="RetrievalBudgetV1 default (report_hydration.py)",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="graph provenance rules untouched",
                observed_metric_dependencies=("report retrieval recall",),
                restart_required=False,
            ),
            CalibrationParameterV1(
                parameter_id="provider.timeout_seconds",
                owner_phase="P3",
                description="LLM provider timeout",
                current_value="120",
                config_source="settings.llm_timeout_seconds (config.py LLM_TIMEOUT_SECONDS)",
                runtime_override_source="env LLM_TIMEOUT_SECONDS",
                kind=ParameterKind.numeric,
                calibratable_in_p8=CalibratableInP8.yes,
                safety_floor="timeout failure = failed run, never silent pass (§11)",
                observed_metric_dependencies=("provider failures", "wall time"),
                restart_required=True,
            ),
            # -- §4 semantic invariants (NOT calibratable) -----------------
            CalibrationParameterV1(
                parameter_id="invariant.evidence_identity_and_task_isolation",
                owner_phase="P1/P2",
                description="evidence identity + task isolation",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="cross-task leak is zero tolerance (§53)",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.grounding_validity",
                owner_phase="P5A",
                description="grounding validity/visibility authority",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="fabricated grounding is a correctness defect",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.assertion_semantics",
                owner_phase="P5",
                description=(
                    "FACT/INFERENCE/HYPOTHESIS semantics, ceiling direction, "
                    "review_pending automatic ceiling"
                ),
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="assertion ceiling direction can never be relaxed (§4)",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.analyst_only_accept_reject",
                owner_phase="P5B",
                description="analyst-only accepted/rejected transitions",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="agent terminal review writes are zero tolerance",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.mandatory_verification",
                owner_phase="P5B",
                description="mandatory verification for high-risk semantics",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="semantic_required verification cannot be disabled (§39)",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.graph_provenance",
                owner_phase="P6",
                description="graph provenance requirement; graph id != evidence",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="graph ids never enter evidence positions",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.report_citation_allowlist",
                owner_phase="P7A",
                description="report citation allowlist derivation",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="published citations stay inside the frozen allowlist",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.writer_tools_zero",
                owner_phase="P7B",
                description="ChapterWriter tools=0 boundary",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="writer never gains retrieval",
            ),
            CalibrationParameterV1(
                parameter_id="invariant.finalization_hard_blockers",
                owner_phase="P2",
                description="FinalizationGate hard blockers",
                kind=ParameterKind.semantic,
                calibratable_in_p8=CalibratableInP8.no,
                invariant="finalization bypass is zero tolerance",
            ),
        ),
    )


__all__ = [
    "CALIBRATION_INVENTORY_VERSION",
    "CalibratableInP8",
    "CalibrationParameterV1",
    "ParameterKind",
    "ProductionCalibrationInventoryV1",
    "build_default_inventory",
]
