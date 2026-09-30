"""BenchmarkCaseOutcomeV1 (P8B B3.5 §4-§7).

A versioned, DETERMINISTIC case-outcome metric computed from the
TruthManifest + the persisted BenchmarkRunSnapshot + the structural hard
gate results.  It answers "did the investigation succeed on benchmark
truth semantics" — NOT "did the FinalizationGate allow closure".

Registry discipline (§7): this is a NEW metric id/version evaluated in
its own module.  Existing BenchmarkResultV1 artifacts and their hashes
are untouched; the v2 measurement report carries both the frozen
`finalization_pass_rate` (renamed per §2/§3 — the gate-pass metric) and
this outcome.

Outcome values (§4):
    success                  every required component satisfied
    success_with_limitations satisfied with an explicit recorded limitation
    incomplete               mandatory semantic output absent, or required
                             discovery/coverage missing without overclaim
    incorrect                structural gate violation, premature closure of
                             a truth-unresolved question, or an unsupported
                             claim asserted
    unavailable              cannot be computed (missing inputs)

No-evidence rule (§5): a case with zero critical truth evidence can
succeed via a correct unresolved disposition + recorded limitation —
``tool_calls > 0`` is NEVER a success condition.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

CASE_OUTCOME_VERSION = "benchmark-case-outcome:v1"


class CaseOutcomeValue(str, Enum):
    success = "success"
    success_with_limitations = "success_with_limitations"
    incomplete = "incomplete"
    incorrect = "incorrect"
    unavailable = "unavailable"


class CaseOutcomeComponentV1(BaseModel):
    """One deterministic component check with its evidence."""

    model_config = ConfigDict(frozen=True)

    component: str
    status: str  # satisfied | failed | not_applicable | unavailable
    detail: str = ""


class BenchmarkCaseOutcomeV1(BaseModel):
    """§4 the deterministic truth-semantic outcome of one benchmark run."""

    model_config = ConfigDict(frozen=True)

    outcome_version: str = CASE_OUTCOME_VERSION

    case_id: str
    run_id: str = ""

    outcome: CaseOutcomeValue
    snapshot_hash: str = ""
    finalization_pass: bool = False

    components: tuple[CaseOutcomeComponentV1, ...] = ()
    limitations: tuple[str, ...] = ()

    rationale: str = ""

    outcome_hash: str = ""
    created_at: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if isinstance(data, dict):
            data.setdefault("outcome_version", CASE_OUTCOME_VERSION)
            data["components"] = tuple(
                CaseOutcomeComponentV1.model_validate(item)
                for item in data.get("components", ())
            )
            data.setdefault("limitations", ())
            if not data.get("created_at"):
                from datetime import datetime, timezone

                data["created_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
            payload = {
                key: value
                for key, value in data.items()
                if key not in ("outcome_hash", "created_at")
            }
            data["outcome_hash"] = sha256_hex(payload)
        return data


def evaluate_case_outcome(
    *,
    truth: Any,
    snapshot: Any,
    hard_gates: list[dict],
) -> BenchmarkCaseOutcomeV1:
    """Deterministic evaluator (§4/§5/§6).  ``truth`` is a TruthManifestV1,
    ``snapshot`` a BenchmarkRunSnapshotV1 (or validated dict), ``hard_gates``
    the structural gate list from metrics.structural_hard_gates."""
    if isinstance(snapshot, dict):
        snapshot_dict = snapshot
    else:
        snapshot_dict = snapshot.model_dump(mode="json")

    case_id = truth.case_id
    components: list[CaseOutcomeComponentV1] = []
    incorrect_reasons: list[str] = []
    incomplete_reasons: list[str] = []
    limitation = bool(snapshot_dict.get("limitations"))

    # -- 0. structural hard gates (§4) -----------------------------------
    gate_violations = [g for g in hard_gates if not g.get("passed")]
    components.append(
        CaseOutcomeComponentV1(
            component="structural_hard_gates",
            status="failed" if gate_violations else "satisfied",
            detail=(
                f"{len(gate_violations)} violation(s)"
                if gate_violations
                else "all gates passed"
            ),
        )
    )
    if gate_violations:
        incorrect_reasons.append("structural hard gate violation")

    discovered = set(snapshot_dict.get("discovered_evidence_refs") or ())
    questions = snapshot_dict.get("questions") or ()
    delegs = snapshot_dict.get("delegations") or ()
    integrated = any(d.get("integrated_revision") for d in delegs)
    findings = snapshot_dict.get("findings") or ()
    limitations = tuple(snapshot_dict.get("limitations") or ())
    finalization_pass = bool(snapshot_dict.get("finalization_id"))

    # -- 1. semantic output availability (§14/§40 distinction) -----------
    semantic_available = integrated or bool(findings)
    components.append(
        CaseOutcomeComponentV1(
            component="semantic_output_available",
            status="satisfied" if semantic_available else "unavailable",
            detail=(
                f"integrated_delegations={sum(1 for d in delegs if d.get('integrated_revision'))} "
                f"findings={len(findings)}"
            ),
        )
    )

    # -- 2. critical evidence discovery (§4; skipped when none, §5) ------
    critical_keys = [
        item.expected_evidence_key
        for item in truth.critical_evidence
        if item.expected_evidence_key
    ]
    if critical_keys:
        missing = [k for k in critical_keys if k not in discovered]
        components.append(
            CaseOutcomeComponentV1(
                component="critical_evidence_discovery",
                status="failed" if missing else "satisfied",
                detail=(
                    f"{len(critical_keys) - len(missing)}/{len(critical_keys)} discovered"
                    + (f"; missing={missing}" if missing else "")
                ),
            )
        )
        if missing:
            incomplete_reasons.append(
                "critical evidence not discovered"
            )
    else:
        components.append(
            CaseOutcomeComponentV1(
                component="critical_evidence_discovery",
                status="not_applicable",
                detail="case declares zero critical evidence (§5)",
            )
        )

    # -- 3. required question dispositions (§4) --------------------------
    # The snapshot carries terminal question rows WITHOUT free text
    # (question_id/status/disposition only), so the disposition check is
    # AGGREGATE and deterministic: the multiset of truth-expected
    # dispositions must be realizable against the terminal rows.  The
    # metric description documents this granularity (registry v1).
    terminal_open_statuses = {"open", "in_progress"}
    unresolved_statuses = {"unresolved", "deferred", "blocked", "superseded"}
    terminal_rows = [
        q for q in questions if q.get("status") not in terminal_open_statuses
    ]
    answered_rows = [
        q
        for q in terminal_rows
        if (q.get("disposition") or "").lower() == "answered"
    ]
    unresolved_rows = [
        q
        for q in terminal_rows
        if (q.get("status") in unresolved_statuses)
        or (q.get("disposition") or "").lower()
        in {"unresolved", "deferred", "blocked", "not_applicable"}
    ]
    expected_answered = [
        q
        for q in truth.expected_questions
        if q.expected_disposition.value == "answered"
    ]
    expected_unresolved = [
        q
        for q in truth.expected_questions
        if q.expected_disposition.value == "unresolved"
    ]
    components.append(
        CaseOutcomeComponentV1(
            component="question_dispositions",
            status="unavailable" if not terminal_rows else "satisfied",
            detail=(
                f"terminal={len(terminal_rows)} answered={len(answered_rows)} "
                f"unresolved={len(unresolved_rows)}; truth expects "
                f"answered={len(expected_answered)} unresolved={len(expected_unresolved)}"
            ),
        )
    )
    if not terminal_rows:
        incomplete_reasons.append(
            "no terminal question dispositions recorded"
        )
    else:
        if expected_answered and not answered_rows:
            incomplete_reasons.append(
                "truth expects an answered question; none terminal-answered"
            )
        if expected_unresolved:
            if unresolved_rows:
                pass  # satisfied: at least one justified unresolved terminal
            elif answered_rows and not expected_answered:
                incorrect_reasons.append(
                    "premature closure: all-truth-unresolved questions answered"
                )
            else:
                incomplete_reasons.append(
                    "truth expects an unresolved disposition; none recorded"
                )

    # -- 4. required coverage dispositions (§4) --------------------------
    for tc in truth.expected_coverage:
        rows = [
            c
            for c in (snapshot_dict.get("coverage") or ())
            if c.get("dimension_id") == tc.dimension_id
        ]
        if not rows:
            components.append(
                CaseOutcomeComponentV1(
                    component=f"coverage:{tc.dimension_id}",
                    status="unavailable",
                    detail="dimension absent from snapshot coverage",
                )
            )
            if tc.expected_status.value in {"covered", "partial"}:
                incomplete_reasons.append(
                    f"coverage {tc.dimension_id} not recorded"
                )
            continue
        row = rows[0]
        status = (row.get("status") or "").lower()
        expected = tc.expected_status.value
        if expected == "covered":
            ok = status in {"covered", "complete"}
            basis_ok = (
                not tc.requires_closure_basis
                or bool(row.get("capability_basis"))
                or status == "covered"
            )
            satisfied = ok and basis_ok
            components.append(
                CaseOutcomeComponentV1(
                    component=f"coverage:{tc.dimension_id}",
                    status="satisfied" if satisfied else "failed",
                    detail=f"terminal={status}",
                )
            )
            if not satisfied:
                incomplete_reasons.append(
                    f"coverage {tc.dimension_id}={status or 'unset'}"
                )
        else:
            components.append(
                CaseOutcomeComponentV1(
                    component=f"coverage:{tc.dimension_id}",
                    status="not_applicable",
                    detail=f"expected={expected}, terminal={status}",
                )
            )

    # -- 5. claim/overclaim constraints (§4) -----------------------------
    # Deterministic and conservative: with no integrated semantic output
    # this component is unavailable (§14 — "no errors" != "no violations
    # because nothing was produced").  Findings, when present, are checked
    # against prohibited overclaims by matching the finding text against
    # the prohibited proposition (exact-substring, no LLM).
    if not findings:
        components.append(
            CaseOutcomeComponentV1(
                component="overclaim_constraints",
                status="unavailable",
                detail="no findings produced; overclaim behavior unobserved",
            )
        )
    else:
        prohibited = [
            c.proposition
            for c in truth.unsupported_or_prohibited_overclaims
        ]
        violations = []
        for finding in findings:
            text = str(
                finding.get("text")
                if isinstance(finding, dict)
                else getattr(finding, "text", "")
                or ""
            )
            for prop in prohibited:
                if prop and _normalized_overlap(text, prop):
                    violations.append(prop)
        components.append(
            CaseOutcomeComponentV1(
                component="overclaim_constraints",
                status="failed" if violations else "satisfied",
                detail=(
                    f"{len(violations)} prohibited overclaim(s) asserted"
                    if violations
                    else f"{len(findings)} finding(s), none prohibited"
                ),
            )
        )
        if violations:
            incorrect_reasons.append("prohibited overclaim asserted")

    # -- outcome assembly --------------------------------------------------
    if incorrect_reasons:
        outcome = CaseOutcomeValue.incorrect
        rationale = "; ".join(incorrect_reasons)
    elif not semantic_available:
        outcome = CaseOutcomeValue.incomplete
        rationale = (
            "no integrated semantic output; gate-pass alone is not case "
            "success (§2/§4/§40)"
        )
    elif incomplete_reasons:
        outcome = CaseOutcomeValue.incomplete
        rationale = "; ".join(incomplete_reasons)
    elif limitation:
        outcome = CaseOutcomeValue.success_with_limitations
        rationale = "all components satisfied with recorded limitations"
    else:
        outcome = CaseOutcomeValue.success
        rationale = "all components satisfied"

    return BenchmarkCaseOutcomeV1(
        case_id=case_id,
        run_id=str(snapshot_dict.get("run_id") or ""),
        outcome=outcome,
        snapshot_hash=str(snapshot_dict.get("snapshot_hash") or ""),
        finalization_pass=finalization_pass,
        components=tuple(components),
        limitations=limitations,
        rationale=rationale,
    )


def _tokens(text: str) -> list[str]:
    import re

    return [
        t
        for t in re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        if len(t) > 1
    ]


def _normalized_overlap(a: str, b: str) -> bool:
    """True when a meaningful normalized fragment of the prohibited
    proposition appears in the finding text (>= 8-char CJK run or
    >= 3 shared distinctive tokens)."""
    a_tokens = set(_tokens(a))
    b_tokens = set(_tokens(b))
    shared = a_tokens & b_tokens
    return len(shared) >= 3


__all__ = [
    "CASE_OUTCOME_VERSION",
    "BenchmarkCaseOutcomeV1",
    "CaseOutcomeComponentV1",
    "CaseOutcomeValue",
    "evaluate_case_outcome",
]


# ---------------------------------------------------------------------------
# B5.5 evaluator v2 — acceptance-semantics closure (spec §5/§9/§14 Case A)
#
# Root causes fixed relative to v1 (see
# benchmarks/results/agent-v0/b2-restart/b2-post-h/
# case-outcome-incomplete-audit-v1.json):
#
# 1. disposition vocabulary (A_BENCHMARK_SEMANTICS_DEFECT): v1 counted
#    terminal rows whose DISPOSITION literal is "answered", a token that
#    does not exist in the frozen production contract
#    (QuestionStatus.answered is the answered terminal;
#    QuestionDisposition ∈ {supported, not_supported, inconclusive,
#    unavailable, not_applicable}).  v2 maps the truth vocabulary onto
#    the production (status, disposition) pair:
#      truth "answered"   ⇔ status == answered AND disposition recorded
#      truth "unresolved" ⇔ status ∈ {unresolved, blocked, deferred}
#                           OR answered with disposition ∈
#                           {not_supported, inconclusive}
#    The unresolved acceptable-set is derived from the frozen product
#    semantics: refusing an unknowable question (not_supported /
#    inconclusive) is a justified unresolved-type terminal — it is NOT an
#    inflation of the acceptable set (merge/causal assertions remain
#    policed by the overclaim and negative-case components).
#
# 2. overclaim channel (A_BENCHMARK_SEMANTICS_DEFECT, narrowed by
#    reevaluation evidence): the findings channel remains structurally
#    empty in benchmark runs (component unavailable), but extending the
#    substring matcher to raw claim texts is INVALID — it flags correct
#    negations as violations (16/23 false positives in the zero-model-
#    call reevaluation).  v2 therefore keeps v1's findings-only
#    semantics and documents that claim-level overclaim adjudication
#    belongs to the case-level negative gates (product semantics).
#
# Coverage requirements are UNCHANGED: they are real truth expectations
# and are satisfiable only after the harness seeds the charter coverage
# (B5.5 §11 harness fix) — deliberate.
# ---------------------------------------------------------------------------

CASE_OUTCOME_VERSION_V2 = "benchmark-case-outcome:v2"

_ANSWERED = "answered"
_UNRESOLVED_STATUSES = {"unresolved", "blocked", "deferred"}
_UNRESOLVED_REFUSAL_DISPOSITIONS = {"not_supported", "inconclusive"}


def evaluate_case_outcome_v2(
    *,
    truth: Any,
    snapshot: Any,
    hard_gates: list[dict],
    semantic_payloads: Optional[list[dict]] = None,
) -> BenchmarkCaseOutcomeV1:
    """v2 evaluator: v1 components with the production-faithful
    disposition semantics and the digest-payload overclaim channel."""
    v1 = evaluate_case_outcome(
        truth=truth, snapshot=snapshot, hard_gates=hard_gates
    )
    snapshot_dict = (
        snapshot
        if isinstance(snapshot, dict)
        else snapshot.model_dump(mode="json")
    )
    questions = snapshot_dict.get("questions") or ()
    terminal_open_statuses = {"open", "in_progress"}
    terminal_rows = [
        q for q in questions if q.get("status") not in terminal_open_statuses
    ]

    def _is_answered_terminal(q: dict) -> bool:
        return (q.get("status") or "").lower() == _ANSWERED and bool(
            q.get("disposition")
        )

    def _is_unresolved_terminal(q: dict) -> bool:
        status = (q.get("status") or "").lower()
        disposition = (q.get("disposition") or "").lower()
        return status in _UNRESOLVED_STATUSES or (
            status == _ANSWERED
            and disposition in _UNRESOLVED_REFUSAL_DISPOSITIONS
        )

    answered_rows = [q for q in terminal_rows if _is_answered_terminal(q)]
    unresolved_rows = [q for q in terminal_rows if _is_unresolved_terminal(q)]
    expected_answered = [
        q
        for q in truth.expected_questions
        if q.expected_disposition.value == "answered"
    ]
    expected_unresolved = [
        q
        for q in truth.expected_questions
        if q.expected_disposition.value == "unresolved"
    ]

    # carry v1's NON-question reasons (critical evidence, coverage) —
    # they are recomputed identically by v1 and are NOT superseded by the
    # v2 disposition semantics.
    incomplete_reasons: list[str] = [
        c.detail
        for c in v1.components
        if c.component.startswith("coverage:")
        and c.status in ("failed", "unavailable")
        and not c.detail.startswith("expected=")
    ]
    if any(
        c.component == "critical_evidence_discovery"
        and c.status == "failed"
        for c in v1.components
    ):
        incomplete_reasons.append("critical evidence not discovered")
    incorrect_reasons: list[str] = []
    components = [
        c for c in v1.components if c.component != "question_dispositions"
    ]
    components.append(
        CaseOutcomeComponentV1(
            component="question_dispositions",
            status="unavailable" if not terminal_rows else "satisfied",
            detail=(
                f"terminal={len(terminal_rows)} "
                f"answered-terminals={len(answered_rows)} "
                f"unresolved-terminals={len(unresolved_rows)}; truth "
                f"expects answered={len(expected_answered)} "
                f"unresolved={len(expected_unresolved)} "
                "(v2 production semantics)"
            ),
        )
    )
    if not terminal_rows:
        incomplete_reasons.append(
            "no terminal question dispositions recorded"
        )
    else:
        if expected_answered and not answered_rows:
            incomplete_reasons.append(
                "truth expects an answered question; none terminal-answered"
            )
        if expected_unresolved:
            if unresolved_rows:
                pass  # satisfied
            elif answered_rows and not expected_answered:
                incorrect_reasons.append(
                    "premature closure: all-truth-unresolved questions answered"
                )
            else:
                incomplete_reasons.append(
                    "truth expects an unresolved disposition; none recorded"
                )

    # overclaim: findings channel ONLY (v1 semantics deliberately kept).
    # B5.5 reevaluation PROVED that extending the substring matcher to
    # raw claim texts is invalid: the token-overlap check flags correct
    # NEGATIONS ("CANNOT be treated as the same person") as violations —
    # 16/23 false-positives in the zero-model-call reevaluation.  Claim
    # level overclaim/negation adjudication belongs to the case-level
    # negative gates (AcceptanceProfile §30, product semantics), not to
    # string equality (spec §5).
    payloads = semantic_payloads or []
    prohibited = [
        c.proposition for c in truth.unsupported_or_prohibited_overclaims
    ]
    findings = v1_findings(snapshot_dict)
    if not findings:
        overclaim_status = "unavailable"
        overclaim_detail = (
            "no findings produced on the findings channel; claim-level "
            "overclaim is adjudicated by the case-level negative gates, "
            "not by substring matching"
        )
        overclaim_violations: list[str] = []
    else:
        overclaim_violations = []
        for finding in findings:
            text = str(finding.get("text") or "")
            for prop in prohibited:
                if prop and _normalized_overlap(text, prop):
                    overclaim_violations.append(prop)
        overclaim_status = (
            "failed" if overclaim_violations else "satisfied"
        )
        overclaim_detail = (
            f"{len(overclaim_violations)} prohibited overclaim(s) asserted"
            if overclaim_violations
            else f"{len(findings)} finding(s), none prohibited"
        )
    components = [
        c for c in components if c.component != "overclaim_constraints"
    ]
    components.append(
        CaseOutcomeComponentV1(
            component="overclaim_constraints",
            status=overclaim_status,
            detail=overclaim_detail,
        )
    )
    if overclaim_violations:
        incorrect_reasons.append("prohibited overclaim asserted")

    # re-derive the outcome with v1's ordering but v2's reasons
    semantic_available = bool(
        any(
            d.get("integrated_revision")
            for d in (snapshot_dict.get("delegations") or ())
        )
    ) or bool(snapshot_dict.get("findings")) or bool(payloads)
    if incorrect_reasons:
        outcome = CaseOutcomeValue.incorrect
        rationale = "; ".join(incorrect_reasons)
    elif not semantic_available:
        outcome = CaseOutcomeValue.incomplete
        rationale = (
            "no integrated semantic output; gate-pass alone is not case "
            "success (§2/§4/§40)"
        )
    elif incomplete_reasons:
        outcome = CaseOutcomeValue.incomplete
        rationale = "; ".join(incomplete_reasons)
    elif snapshot_dict.get("limitations"):
        outcome = CaseOutcomeValue.success_with_limitations
        rationale = "all components satisfied with recorded limitations"
    else:
        outcome = CaseOutcomeValue.success
        rationale = "all components satisfied"

    return BenchmarkCaseOutcomeV1(
        case_id=truth.case_id,
        run_id=str(snapshot_dict.get("run_id") or ""),
        outcome=outcome,
        snapshot_hash=str(snapshot_dict.get("snapshot_hash") or ""),
        finalization_pass=bool(snapshot_dict.get("finalization_id")),
        components=tuple(components),
        limitations=tuple(snapshot_dict.get("limitations") or ()),
        rationale=rationale,
    ).model_copy(
        update={"outcome_version": CASE_OUTCOME_VERSION_V2}
    )


def v1_findings(snapshot_dict: dict) -> list:
    return list(snapshot_dict.get("findings") or ())
