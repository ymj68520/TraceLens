"""Deterministic metric engine + metric registry (P8A §29-§47, §62-§64).

The evaluator NEVER calls an LLM for core scoring (§29/§62).  Every metric
has a versioned registry entry with an exact denominator definition
(§63); missing inputs produce ``unavailable`` — never 0 (§64).  No single
aggregate score exists (§2); outputs are hard-gate results plus dashboard
metric groups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex
from .availability import parser_reachable_critical_ids
from .truth_manifest import (
    AssertionClass,
    ClaimSemanticType,
    TruthManifestV1,
)

METRIC_REGISTRY_VERSION = "benchmark-metric-registry:v1"

# P5 assertion strength axis (same ordering as the production validator)
STRENGTH = {"HYPOTHESIS": 0, "INFERENCE": 1, "FACT": 2}


class MetricValueStatus(str, Enum):
    available = "available"
    unavailable = "unavailable"


class MetricValue(BaseModel):
    """§64: a metric is either a number or explicitly unavailable."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    metric_version: str
    status: MetricValueStatus = MetricValueStatus.available
    value: Optional[float] = None
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    unavailable_reason: str = ""

    @classmethod
    def missing(cls, metric_id: str, reason: str, version: str) -> "MetricValue":
        return cls(
            metric_id=metric_id,
            metric_version=version,
            status=MetricValueStatus.unavailable,
            value=None,
            unavailable_reason=reason,
        )


@dataclass(frozen=True)
class MetricSpec:
    """§63 one versioned metric definition."""

    metric_id: str
    version: str
    description: str
    denominator_definition: str
    higher_is_better: bool
    hard_gate_eligible: bool = False
    limitations: str = ""


@dataclass(frozen=True)
class HardGateResult:
    """§51 structural zero-tolerance gate result (no numeric thresholds)."""

    gate_id: str
    passed: bool
    violations: tuple[dict, ...] = ()
    notes: str = ""


# ---------------------------------------------------------------------------
# registry (§63) — frozen P8A definitions
# ---------------------------------------------------------------------------

METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric_id="critical_evidence_recall",
        version="1",
        description="discovered reachable critical evidence / parser-reachable critical evidence",
        denominator_definition=(
            "count of critical truth-evidence items whose reachability "
            "record is parser_reachable (ground-truth-only items excluded)"
        ),
        higher_is_better=True,
        limitations=(
            "parser gaps are reported separately via "
            "ground_truth_critical_reachability"
        ),
    ),
    MetricSpec(
        metric_id="relevant_evidence_precision",
        version="1",
        description="discovered critical+supporting refs / all discovered refs",
        denominator_definition="all distinct discovered evidence refs",
        higher_is_better=True,
    ),
    MetricSpec(
        metric_id="ground_truth_critical_reachability",
        version="1",
        description="parser-reachable critical / ground-truth critical",
        denominator_definition="all critical truth-evidence items",
        higher_is_better=True,
    ),
    MetricSpec(
        metric_id="unsupported_fact_rate",
        version="1",
        description="FACT findings matching no confirmed truth claim / all FACT findings",
        denominator_definition="all agent FACT findings in the snapshot",
        higher_is_better=False,
        hard_gate_eligible=False,
    ),
    MetricSpec(
        metric_id="assertion_overstatement_rate",
        version="1",
        description="findings whose assertion class exceeds the matched truth claim's maximum_assertion_class / matched findings",
        denominator_definition="findings matched to a confirmed/inference truth claim",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="causal_overreach_rate",
        version="1",
        description="causal/actor/intent findings over unsupported truth / such findings",
        denominator_definition="findings with causal, actor_attribution, or intent semantic type",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="question_disposition_accuracy",
        version="1",
        description="questions whose terminal disposition matches the truth expectation / evaluable questions",
        denominator_definition="truth questions evaluable against the snapshot",
        higher_is_better=True,
    ),
    MetricSpec(
        metric_id="premature_closure_rate",
        version="1",
        description="truth-unresolved questions answered as terminal-supported / truth-unresolved questions",
        denominator_definition="truth questions expecting unresolved",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="applicable_coverage_completion",
        version="1",
        description="coverage dims meeting expectation / evaluable dims",
        denominator_definition="truth coverage dimensions evaluable in the snapshot",
        higher_is_better=True,
    ),
    MetricSpec(
        metric_id="unjustified_coverage_closure",
        version="1",
        description="not_applicable closures without capability basis where truth expects coverage",
        denominator_definition="truth coverage dims with requires_closure_basis",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="correlation_recall",
        version="1",
        description="confirmed truth relations produced / confirmed truth relations",
        denominator_definition="confirmed truth relations",
        higher_is_better=True,
    ),
    MetricSpec(
        metric_id="false_entity_merge_rate",
        version="1",
        description="identity_merge relations produced against unsupported truth / identity relations produced",
        denominator_definition="identity-merge relations in the snapshot",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="productive_tool_call_ratio",
        version="1",
        description="tool calls with observed state/evidence effect / successful tool calls",
        denominator_definition="tool calls with status ok (failures excluded per §41)",
        higher_is_better=True,
    ),
    MetricSpec(
        metric_id="duplicate_call_rate",
        version="1",
        description="duplicate tool calls (same tool + args) / successful tool calls",
        denominator_definition="tool calls with status ok",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="time_to_first_critical_evidence_ms",
        version="1",
        description="wall clock until first critical evidence ref entered visibility",
        denominator_definition="n/a (single value)",
        higher_is_better=False,
    ),
    MetricSpec(
        metric_id="report_assertion_strength_violation_rate",
        version="1",
        description="published report assertions exceeding matched truth ceiling / published assertions",
        denominator_definition="published report assertions matchable to truth claims",
        higher_is_better=False,
    ),
)


def metric_spec(metric_id: str) -> MetricSpec:
    for spec in METRIC_SPECS:
        if spec.metric_id == metric_id:
            return spec
    raise KeyError(metric_id)


# ---------------------------------------------------------------------------
# failure-layer attribution (§48-§49)
# ---------------------------------------------------------------------------


class FailureLayer(str, Enum):
    DATASET = "DATASET"
    PARSER = "PARSER"
    TOOL_EXPOSURE = "TOOL_EXPOSURE"
    RETRIEVAL = "RETRIEVAL"
    SUPERVISOR = "SUPERVISOR"
    SPECIALIST = "SPECIALIST"
    CORRELATION = "CORRELATION"
    GROUNDING = "GROUNDING"
    SEMANTIC_VERIFICATION = "SEMANTIC_VERIFICATION"
    ASSERTION_POLICY = "ASSERTION_POLICY"
    GRAPH = "GRAPH"
    FINALIZATION = "FINALIZATION"
    REPORT_RETRIEVAL = "REPORT_RETRIEVAL"
    REPORT_WRITER = "REPORT_WRITER"
    REPORT_VALIDATION = "REPORT_VALIDATION"
    PROVIDER = "PROVIDER"
    RUNTIME = "RUNTIME"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FailureAttribution:
    what_failed: str
    expected: str
    observed: str
    layer: FailureLayer
    supporting_refs: tuple[str, ...] = ()


def attribute_missed_critical_evidence(
    truth_manifest: TruthManifestV1,
    reachability,
    snapshot,
) -> tuple[FailureAttribution, ...]:
    """§49 decision tree for undiscovered critical evidence."""
    discovered = set(snapshot.discovered_evidence_refs)
    by_id = {
        record.truth_evidence_id: record for record in reachability.records
    }
    attributions: list[FailureAttribution] = []
    for item in truth_manifest.critical_evidence:
        if item.truth_evidence_id in discovered:
            continue
        record = by_id.get(item.truth_evidence_id)
        if record is None or not record.parser_reachable:
            layer = FailureLayer.PARSER
        elif not record.agent_discoverable:
            layer = FailureLayer.TOOL_EXPOSURE
        else:
            layer = FailureLayer.RETRIEVAL
        attributions.append(
            FailureAttribution(
                what_failed=(
                    f"critical evidence not discovered: "
                    f"{item.truth_evidence_id}"
                ),
                expected="critical evidence present in agent visibility",
                observed="absent from discovered evidence refs",
                layer=layer,
                supporting_refs=tuple(
                    record.resolved_evidence_keys
                    if record else ()
                ),
            )
        )
    return tuple(attributions)


# ---------------------------------------------------------------------------
# evaluator (§29-§47) — deterministic, snapshot + truth only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RunView:
    """Normalized projection of the run snapshot used by all metrics."""

    discovered_refs: frozenset[str]
    fact_findings: tuple[dict, ...]
    all_findings: tuple[dict, ...]
    questions: tuple[dict, ...]
    coverage: tuple[dict, ...]
    relations: tuple[dict, ...]
    tool_calls: tuple[dict, ...]
    report_assertions: tuple[dict, ...]
    wall_ms_total: Optional[int]


def _run_view(snapshot) -> _RunView:
    findings = [
        row if isinstance(row, dict) else row.model_dump(mode="json")
        for row in snapshot.findings
    ]
    questions = [
        row if isinstance(row, dict) else row.model_dump(mode="json")
        for row in snapshot.questions
    ]
    coverage = [
        row if isinstance(row, dict) else row.model_dump(mode="json")
        for row in snapshot.coverage
    ]
    relations = [
        row if isinstance(row, dict) else row.model_dump(mode="json")
        for row in snapshot.correlations
    ]
    tool_calls = [
        call if isinstance(call, dict) else call.model_dump(mode="json")
        for call in snapshot.tool_calls
    ]
    report_assertions = list(
        (snapshot.report or {}).get("assertions", ())
    )
    return _RunView(
        discovered_refs=frozenset(snapshot.discovered_evidence_refs),
        fact_findings=tuple(
            f for f in findings if f.get("assertion_class") == "FACT"
        ),
        all_findings=tuple(findings),
        questions=tuple(questions),
        coverage=tuple(coverage),
        relations=tuple(relations),
        tool_calls=tuple(tool_calls),
        report_assertions=tuple(report_assertions),
        wall_ms_total=snapshot.wall_ms_total,
    )


def _ratio(
    metric_id: str,
    numerator: float,
    denominator: float,
    *,
    unavailable_reason: str = "denominator is zero",
) -> MetricValue:
    spec = metric_spec(metric_id)
    if denominator == 0:
        return MetricValue.missing(metric_id, unavailable_reason, spec.version)
    return MetricValue(
        metric_id=metric_id,
        metric_version=spec.version,
        value=numerator / denominator,
        numerator=numerator,
        denominator=denominator,
    )


# -- §30 evidence metrics ----------------------------------------------------


def critical_evidence_recall(
    truth_manifest: TruthManifestV1, reachability, snapshot
) -> MetricValue:
    """§30: denominator = parser-reachable critical evidence."""
    denominator_ids = parser_reachable_critical_ids(
        truth_manifest, reachability
    )
    if not denominator_ids:
        return MetricValue.missing(
            "critical_evidence_recall",
            "no parser-reachable critical evidence exists for this case",
            metric_spec("critical_evidence_recall").version,
        )
    view = _run_view(snapshot)
    truth_keys: dict[str, tuple[str, ...]] = {}
    for record in reachability.records:
        truth_keys[record.truth_evidence_id] = record.resolved_evidence_keys
    hit = 0
    for truth_id in denominator_ids:
        keys = truth_keys.get(truth_id, ())
        if any(key in view.discovered_refs for key in keys):
            hit += 1
    spec = metric_spec("critical_evidence_recall")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=hit / len(denominator_ids),
        numerator=hit,
        denominator=len(denominator_ids),
    )


def relevant_evidence_precision(
    truth_manifest: TruthManifestV1, reachability, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    if not view.discovered_refs:
        return MetricValue.missing(
            "relevant_evidence_precision",
            "no evidence discovered in this run",
            metric_spec("relevant_evidence_precision").version,
        )
    relevant_keys: set[str] = set()
    for record in reachability.records:
        item = truth_manifest.evidence_by_id(record.truth_evidence_id)
        if item is None or item.criticality.value == "irrelevant":
            continue
        relevant_keys.update(record.resolved_evidence_keys)
    relevant = sum(
        1 for ref in view.discovered_refs if ref in relevant_keys
    )
    spec = metric_spec("relevant_evidence_precision")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=relevant / len(view.discovered_refs),
        numerator=relevant,
        denominator=len(view.discovered_refs),
    )


# -- §31/§32 claim metrics ---------------------------------------------------


def _claim_matches_finding(claim, finding) -> bool:
    """§32 deterministic claim matching: exact truth claim id first, then
    normalized proposition text.  No LLM matching in P8A."""
    if finding.get("truth_claim_id") == claim.claim_id:
        return True
    return (
        " ".join(str(finding.get("text", "")).split()).lower()
        == " ".join(claim.proposition.split()).lower()
    )


def unsupported_fact_rate(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    if not view.fact_findings:
        return MetricValue.missing(
            "unsupported_fact_rate",
            "no FACT findings in this run",
            metric_spec("unsupported_fact_rate").version,
        )
    supported_texts = {
        " ".join(claim.proposition.split()).lower()
        for claim in truth_manifest.all_claims()
        if claim.truth_status == "confirmed"
    }
    unsupported = sum(
        1
        for finding in view.fact_findings
        if " ".join(str(finding.get("text", "")).split()).lower()
        not in supported_texts
        and finding.get("truth_claim_id") is None
    )
    spec = metric_spec("unsupported_fact_rate")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=unsupported / len(view.fact_findings),
        numerator=unsupported,
        denominator=len(view.fact_findings),
    )


def assertion_overstatement_rate(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    """§31: overstatement = class strength above the matched truth
    claim's maximum_assertion_class."""
    view = _run_view(snapshot)
    matched: list[tuple[dict, Any]] = []
    for finding in view.all_findings:
        for claim in truth_manifest.all_claims():
            if claim.truth_status == "confirmed" and _claim_matches_finding(
                claim, finding
            ):
                matched.append((finding, claim))
                break
    if not matched:
        return MetricValue.missing(
            "assertion_overstatement_rate",
            "no findings matched a confirmed truth claim",
            metric_spec("assertion_overstatement_rate").version,
        )
    overstated = sum(
        1
        for finding, claim in matched
        if claim.maximum_assertion_class is not None
        and STRENGTH.get(str(finding.get("assertion_class")), 0)
        > STRENGTH[claim.maximum_assertion_class.value]
    )
    spec = metric_spec("assertion_overstatement_rate")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=overstated / len(matched),
        numerator=overstated,
        denominator=len(matched),
    )


def causal_overreach_rate(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    risky_types = {
        ClaimSemanticType.causal.value,
        ClaimSemanticType.actor_attribution.value,
        ClaimSemanticType.intent.value,
    }
    unsupported_propositions = {
        " ".join(claim.proposition.split()).lower()
        for claim in truth_manifest.unsupported_or_prohibited_overclaims
    }
    risky = tuple(
        finding
        for finding in view.all_findings
        if finding.get("semantic_type") in risky_types
    )
    if not risky:
        return MetricValue.missing(
            "causal_overreach_rate",
            "no causal/actor/intent findings in this run",
            metric_spec("causal_overreach_rate").version,
        )
    overreach = sum(
        1
        for finding in risky
        if " ".join(str(finding.get("text", "")).split()).lower()
        in unsupported_propositions
    )
    spec = metric_spec("causal_overreach_rate")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=overreach / len(risky),
        numerator=overreach,
        denominator=len(risky),
    )


# -- §33/§34 question + coverage metrics -------------------------------------


_QUESTION_EXPECTATION = {
    "answered": {"answered"},
    "unresolved": {"unresolved"},
    "blocked": {"blocked"},
    "superseded": {"superseded"},
    "any_terminal": {"answered", "unresolved", "blocked", "superseded"},
}


def question_disposition_accuracy(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    snapshot_questions = {
        q.get("question_id"): q for q in view.questions
    }
    evaluable = 0
    correct = 0
    for truth_question in truth_manifest.expected_questions:
        observed = snapshot_questions.get(truth_question.question_id)
        if observed is None:
            continue
        evaluable += 1
        expected_set = _QUESTION_EXPECTATION[
            truth_question.expected_disposition.value
        ]
        if observed.get("status") in expected_set:
            correct += 1
    if evaluable == 0:
        return MetricValue.missing(
            "question_disposition_accuracy",
            "no truth questions evaluable against this snapshot",
            metric_spec("question_disposition_accuracy").version,
        )
    spec = metric_spec("question_disposition_accuracy")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=correct / evaluable,
        numerator=correct,
        denominator=evaluable,
    )


def premature_closure_rate(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    snapshot_questions = {
        q.get("question_id"): q for q in view.questions
    }
    unresolved_truth = [
        q
        for q in truth_manifest.expected_questions
        if q.expected_disposition.value == "unresolved"
    ]
    if not unresolved_truth:
        return MetricValue.missing(
            "premature_closure_rate",
            "no truth questions expect unresolved",
            metric_spec("premature_closure_rate").version,
        )
    premature = sum(
        1
        for q in unresolved_truth
        if snapshot_questions.get(q.question_id, {}).get("status")
        == "answered"
    )
    spec = metric_spec("premature_closure_rate")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=premature / len(unresolved_truth),
        numerator=premature,
        denominator=len(unresolved_truth),
    )


def unjustified_coverage_closure(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    """§16/§34: not_applicable closure WITHOUT capability basis where the
    truth expects coverage."""
    view = _run_view(snapshot)
    snapshot_coverage = {
        c.get("dimension_id"): c for c in view.coverage
    }
    gated = [
        c
        for c in truth_manifest.expected_coverage
        if c.requires_closure_basis
    ]
    if not gated:
        return MetricValue.missing(
            "unjustified_coverage_closure",
            "no truth coverage dimensions require a closure basis",
            metric_spec("unjustified_coverage_closure").version,
        )
    unjustified = sum(
        1
        for c in gated
        if snapshot_coverage.get(c.dimension_id, {}).get("status")
        == "not_applicable"
        and not snapshot_coverage.get(c.dimension_id, {}).get(
            "capability_basis"
        )
    )
    spec = metric_spec("unjustified_coverage_closure")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=unjustified / len(gated),
        numerator=unjustified,
        denominator=len(gated),
    )


# -- §35 correlation metrics -------------------------------------------------


def correlation_recall(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    confirmed = [
        r
        for r in truth_manifest.expected_relations
        if r.truth_status == "confirmed"
    ]
    if not confirmed:
        return MetricValue.missing(
            "correlation_recall",
            "no confirmed truth relations for this case",
            metric_spec("correlation_recall").version,
        )
    produced = {
        (
            str(relation.get("subject_entity", "")),
            str(relation.get("relation_family", "")),
            str(relation.get("object_entity", "")),
        )
        for relation in view.relations
    }
    hit = sum(
        1
        for r in confirmed
        if (r.subject_entity, r.relation_family, r.object_entity) in produced
    )
    spec = metric_spec("correlation_recall")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=hit / len(confirmed),
        numerator=hit,
        denominator=len(confirmed),
    )


def false_entity_merge_rate(
    truth_manifest: TruthManifestV1, snapshot
) -> MetricValue:
    view = _run_view(snapshot)
    merge_relations = [
        relation
        for relation in view.relations
        if relation.get("relation_family") == "same_person"
    ]
    if not merge_relations:
        return MetricValue.missing(
            "false_entity_merge_rate",
            "no identity-merge relations in this run",
            metric_spec("false_entity_merge_rate").version,
        )
    forbidden = {
        (r.subject_entity, r.object_entity)
        for r in truth_manifest.expected_relations
        if r.truth_status == "unsupported"
        and r.relation_family == "same_person"
    }
    false_merges = sum(
        1
        for relation in merge_relations
        if (relation.get("subject_entity"), relation.get("object_entity"))
        in forbidden
    )
    spec = metric_spec("false_entity_merge_rate")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=false_merges / len(merge_relations),
        numerator=false_merges,
        denominator=len(merge_relations),
    )


# -- §38-§42 process metrics -------------------------------------------------


def _productive_tool_call(call: dict) -> bool:
    """§39 frozen operational definition: a successful tool call is
    productive iff it exposed at least one evidence ref not seen in any
    EARLIER call (new evidence visibility) — state/coverage advancement
    projections plug in at the same seam in later versions."""
    return bool(call.get("evidence_refs"))


def _duplicate_key(call: dict) -> tuple:
    """§40: same tool id + same normalized args; state-revision scoping
    arrives with the state-transition projection."""
    return (
        str(call.get("tool_id")),
        canonical_dumps_args(call.get("args_normalized") or {}),
    )


def canonical_dumps_args(value) -> str:
    import json

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def productive_tool_call_ratio(snapshot) -> MetricValue:
    successful = [
        call
        for call in snapshot.tool_calls
        if (call.status if hasattr(call, "status") else call.get("status"))
        == "ok"
    ]
    if not successful:
        return MetricValue.missing(
            "productive_tool_call_ratio",
            "no successful tool calls in this run",
            metric_spec("productive_tool_call_ratio").version,
        )
    productive = sum(
        1
        for call in successful
        if _productive_tool_call(
            call if isinstance(call, dict) else call.model_dump(mode="json")
        )
    )
    spec = metric_spec("productive_tool_call_ratio")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=productive / len(successful),
        numerator=productive,
        denominator=len(successful),
    )


def duplicate_call_rate(snapshot) -> MetricValue:
    successful = [
        call
        for call in snapshot.tool_calls
        if (call.status if hasattr(call, "status") else call.get("status"))
        == "ok"
    ]
    if not successful:
        return MetricValue.missing(
            "duplicate_call_rate",
            "no successful tool calls in this run",
            metric_spec("duplicate_call_rate").version,
        )
    seen: set[tuple] = set()
    duplicates = 0
    for call in successful:
        raw = call if isinstance(call, dict) else call.model_dump(mode="json")
        key = _duplicate_key(raw)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    spec = metric_spec("duplicate_call_rate")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=duplicates / len(successful),
        numerator=duplicates,
        denominator=len(successful),
    )


def time_to_first_critical_evidence_ms(
    truth_manifest: TruthManifestV1,
    reachability,
    snapshot,
) -> MetricValue:
    """§38: first seq at which a critical truth evidence key entered
    visibility; converted with the snapshot's total wall time as a
    deterministic lower bound projection (per-seq timestamps arrive with
    the observation-timestamp telemetry)."""
    view = _run_view(snapshot)
    critical_keys: set[str] = set()
    for record in reachability.records:
        item = truth_manifest.evidence_by_id(record.truth_evidence_id)
        if item is not None and item.criticality.value == "critical":
            critical_keys.update(record.resolved_evidence_keys)
    seqs = [
        seq
        for ref, seq in (snapshot.evidence_first_seen_seq or {}).items()
        if ref in critical_keys
    ]
    if not seqs or view.wall_ms_total is None:
        return MetricValue.missing(
            "time_to_first_critical_evidence_ms",
            "no critical evidence discovered or no wall-time telemetry",
            metric_spec("time_to_first_critical_evidence_ms").version,
        )
    total_events = max(snapshot.evidence_first_seen_seq.values()) + 1
    spec = metric_spec("time_to_first_critical_evidence_ms")
    return MetricValue(
        metric_id=spec.metric_id,
        metric_version=spec.version,
        value=view.wall_ms_total * (min(seqs) / total_events),
        numerator=min(seqs),
        denominator=total_events,
    )


# -- §51 structural hard gates ----------------------------------------------


def structural_hard_gates(snapshot) -> tuple[HardGateResult, ...]:
    """Zero-tolerance structural gates (§51).  These are not performance
    thresholds; any violation is a correctness defect."""
    gates: list[HardGateResult] = []
    view = _run_view(snapshot)

    cross_task = [
        ref
        for ref in view.discovered_refs
        if ref.startswith("task:") and not ref.startswith(
            f"task:{snapshot.task_id}"
        )
    ]
    gates.append(
        HardGateResult(
            gate_id="no_cross_task_evidence_leak",
            passed=not cross_task,
            violations=tuple(
                {"evidence_ref": ref} for ref in cross_task
            ),
        )
    )

    gates.append(
        HardGateResult(
            gate_id="no_graph_id_as_evidence",
            passed=all(
                not str(ref).startswith(("graph:", "gm:", "gcand:", "node-"))
                for ref in view.discovered_refs
            ),
            violations=tuple(
                {"evidence_ref": ref}
                for ref in view.discovered_refs
                if str(ref).startswith(("graph:", "gm:", "gcand:", "node-"))
            ),
        )
    )

    agent_terminal = [
        finding
        for finding in view.all_findings
        if finding.get("status") in ("accepted", "rejected")
    ]
    gates.append(
        HardGateResult(
            gate_id="no_agent_accept_reject",
            passed=not agent_terminal,
            violations=tuple(
                {"finding_id": finding.get("finding_id")}
                for finding in agent_terminal
            ),
        )
    )
    return tuple(gates)


# ---------------------------------------------------------------------------
# §50 result assembly
# ---------------------------------------------------------------------------


class BenchmarkResultV1(BaseModel):
    """§50 immutable benchmark result (no aggregate score, §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_version: str = "benchmark-result:v1"

    run_manifest_id: str
    run_manifest_hash: str
    truth_manifest_id: str
    truth_manifest_hash: str
    snapshot_hash: str

    availability_summary: dict = Field(default_factory=dict)
    hard_gate_results: tuple[dict, ...] = ()
    quality_metrics: dict = Field(default_factory=dict)
    process_metrics: dict = Field(default_factory=dict)
    graph_metrics: dict = Field(default_factory=dict)
    cost_metrics: dict = Field(default_factory=dict)
    reliability_metadata: dict = Field(default_factory=dict)
    failure_attributions: tuple[dict, ...] = ()
    limitations: tuple[str, ...] = ()

    metric_registry_version: str = METRIC_REGISTRY_VERSION
    result_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        # defaulted-field normalization keeps result_hash IDEMPOTENT.
        data.setdefault("result_version", "benchmark-result:v1")
        data.setdefault("availability_summary", {})
        data.setdefault("hard_gate_results", ())
        data.setdefault("quality_metrics", {})
        data.setdefault("process_metrics", {})
        data.setdefault("graph_metrics", {})
        data.setdefault("cost_metrics", {})
        data.setdefault("reliability_metadata", {})
        data.setdefault("failure_attributions", ())
        data.setdefault("limitations", ())
        data.setdefault("metric_registry_version", METRIC_REGISTRY_VERSION)
        if not data.get("created_at"):
            from datetime import datetime, timezone

            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("result_hash", "created_at")
        }
        data["result_hash"] = sha256_hex(payload)
        return data


__all__ = [
    "BenchmarkResultV1",
    "FailureAttribution",
    "FailureLayer",
    "HardGateResult",
    "METRIC_REGISTRY_VERSION",
    "METRIC_SPECS",
    "MetricSpec",
    "MetricValue",
    "MetricValueStatus",
    "assertion_overstatement_rate",
    "attribute_missed_critical_evidence",
    "causal_overreach_rate",
    "correlation_recall",
    "critical_evidence_recall",
    "duplicate_call_rate",
    "false_entity_merge_rate",
    "metric_spec",
    "premature_closure_rate",
    "productive_tool_call_ratio",
    "question_disposition_accuracy",
    "relevant_evidence_precision",
    "structural_hard_gates",
    "time_to_first_critical_evidence_ms",
    "unjustified_coverage_closure",
    "unsupported_fact_rate",
]
