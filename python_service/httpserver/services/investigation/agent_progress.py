"""Deterministic NoProgressDetector (P2).

Progress is computed from semantic state changes only — never an LLM score,
never trajectory noise.  ``progress_state`` / ``budget_state`` bookkeeping is
deliberately excluded from the diff so a bookkeeping-only commit can never
masquerade as progress.

The consecutive-no-progress threshold is a calibration input supplied through
``NoProgressPolicyConfig``; no specific N is claimed as a v0 canonical value.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_working_state import (
    AgentWorkingStateV1,
    NO_PROGRESS_POLICY_VERSION,
)

NEW_RELEVANT_EVIDENCE = "NEW_RELEVANT_EVIDENCE"
QUESTION_ADVANCED = "QUESTION_ADVANCED"
COVERAGE_ADVANCED = "COVERAGE_ADVANCED"
CONTRADICTION_CHANGED = "CONTRADICTION_CHANGED"
NEW_FINDING_REF = "NEW_FINDING_REF"
HYPOTHESIS_CHANGED = "HYPOTHESIS_CHANGED"

_RELEVANCE_ORDER = {"candidate": 0, "irrelevant": 0, "relevant": 1, "high_value": 2}


class ProgressSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    productive: bool
    reason_codes: tuple[str, ...] = ()
    counts: dict[str, int] = {}
    previous_revision: Optional[int] = None
    current_revision: Optional[int] = None
    policy_version: str = NO_PROGRESS_POLICY_VERSION


class NoProgressVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    no_progress_detected: bool
    consecutive_no_progress_cycles: int
    threshold: int
    policy_version: str = NO_PROGRESS_POLICY_VERSION


class NoProgressPolicyConfig(BaseModel):
    """Calibration surface (P2 §26): the threshold comes from policy config,
    tests may pin 1/2/N, and no value is an architecture constant."""

    model_config = ConfigDict(frozen=True)

    threshold: int = 2

    @model_validator(mode="after")
    def _validate_threshold(self) -> "NoProgressPolicyConfig":
        if self.threshold < 1:
            raise ValueError("no-progress threshold must be >= 1")
        return self


class NoProgressDetector:
    """Compares two committed Working State revisions semantically."""

    def __init__(self, *, policy_version: str = NO_PROGRESS_POLICY_VERSION):
        self.policy_version = policy_version

    def evaluate(
        self,
        previous_state: Optional[AgentWorkingStateV1],
        current_state: AgentWorkingStateV1,
        *,
        previous_revision: Optional[int] = None,
        current_revision: Optional[int] = None,
    ) -> ProgressSnapshot:
        counts: dict[str, int] = {
            NEW_RELEVANT_EVIDENCE: 0,
            QUESTION_ADVANCED: 0,
            COVERAGE_ADVANCED: 0,
            CONTRADICTION_CHANGED: 0,
            NEW_FINDING_REF: 0,
            HYPOTHESIS_CHANGED: 0,
        }
        if previous_state is not None:
            counts[NEW_RELEVANT_EVIDENCE] = self._evidence_progress(
                previous_state, current_state
            )
            counts[QUESTION_ADVANCED] = self._question_progress(
                previous_state, current_state
            )
            counts[COVERAGE_ADVANCED] = self._coverage_progress(
                previous_state, current_state
            )
            counts[CONTRADICTION_CHANGED] = self._contradiction_progress(
                previous_state, current_state
            )
            counts[NEW_FINDING_REF] = len(
                set(current_state.finding_refs) - set(previous_state.finding_refs)
            )
            counts[HYPOTHESIS_CHANGED] = self._hypothesis_progress(
                previous_state, current_state
            )
        else:
            # first committed revision of an investigation is the baseline,
            # not evidence of progress
            pass
        reason_codes = tuple(code for code, count in counts.items() if count > 0)
        return ProgressSnapshot(
            productive=bool(reason_codes),
            reason_codes=reason_codes,
            counts=counts,
            previous_revision=previous_revision,
            current_revision=current_revision,
            policy_version=self.policy_version,
        )

    def verdict(
        self,
        snapshot: ProgressSnapshot,
        config: NoProgressPolicyConfig,
        *,
        consecutive_no_progress_cycles: int,
    ) -> NoProgressVerdict:
        consecutive = (
            0
            if snapshot.productive
            else consecutive_no_progress_cycles + 1
        )
        return NoProgressVerdict(
            no_progress_detected=consecutive >= config.threshold,
            consecutive_no_progress_cycles=consecutive,
            threshold=config.threshold,
            policy_version=self.policy_version,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _evidence_progress(previous: AgentWorkingStateV1, current: AgentWorkingStateV1) -> int:
        previous_items = {i.evidence_key: i for i in previous.evidence_working_set}
        progressed = 0
        for item in current.evidence_working_set:
            before = previous_items.get(item.evidence_key)
            if before is None:
                if item.status.value in ("relevant", "high_value"):
                    progressed += 1
                continue
            if _RELEVANCE_ORDER.get(item.status.value, 0) > _RELEVANCE_ORDER.get(
                before.status.value, 0
            ):
                progressed += 1
        return progressed

    @staticmethod
    def _question_progress(previous: AgentWorkingStateV1, current: AgentWorkingStateV1) -> int:
        previous_questions = {q.question_id: q for q in previous.questions}
        progressed = 0
        for question in current.questions:
            before = previous_questions.get(question.question_id)
            if before is None or before.status != question.status:
                progressed += 1
        return progressed

    @staticmethod
    def _coverage_progress(previous: AgentWorkingStateV1, current: AgentWorkingStateV1) -> int:
        previous_dims = {c.dimension_id: c for c in previous.coverage}
        progressed = 0
        for dimension in current.coverage:
            before = previous_dims.get(dimension.dimension_id)
            if before is None or before.status != dimension.status:
                progressed += 1
        return progressed

    @staticmethod
    def _contradiction_progress(previous: AgentWorkingStateV1, current: AgentWorkingStateV1) -> int:
        previous_items = {c.contradiction_id: c for c in previous.contradictions}
        changed = 0
        for contradiction in current.contradictions:
            before = previous_items.get(contradiction.contradiction_id)
            if before is None or before.status != contradiction.status:
                changed += 1
        return changed

    @staticmethod
    def _hypothesis_progress(previous: AgentWorkingStateV1, current: AgentWorkingStateV1) -> int:
        previous_items = {h.hypothesis_id: h for h in previous.hypotheses}
        changed = 0
        for hypothesis in current.hypotheses:
            before = previous_items.get(hypothesis.hypothesis_id)
            if before is None or before.status != hypothesis.status:
                changed += 1
        return changed
