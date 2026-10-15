"""IntegrationVocabularyGuidanceV1 (RCA-2A.6) — EXPERIMENTAL, OFFLINE.

Isolation guarantee (same doctrine as integration_proposal_v1): this
module lives in the benchmarks tree, OUTSIDE the production
``httpserver`` package.  No production import path reaches it; the
production agent factory's default behavior is unchanged.  It defines
no production behaviour and no new schema.

Design in one sentence: an INTEGRATE-only instructions SUFFIX that
explains the EXISTING frozen vocabularies (question status vs
delegation lifecycle status vs disposition) — every value it names is
rendered PROGRAMMATICALLY from the production enums, so no second,
drift-prone state definition exists.

What it deliberately does NOT do (RCA-2A.6 §2):
  - adds no QuestionStatus / disposition value;
  - maps nothing automatically (``completed`` is never mapped to
    ``answered``; ``no_evidence_found`` is never turned into a fact);
  - changes no pydantic enum, no server validation, no resolver, no
    StateTransitionPolicy, no retry/timeout;
  - never suggests fabricating evidence, basis handles or verification
    results.

Status: DRAFT candidate for the pre-registered controlled comparison
(RCA2A6ControlledComparisonProtocolV1).  Not wired to any production
path.  Offline contract tests can prove absence of CONFLICT with the
existing contract; nothing here proves model compliance.
"""

from __future__ import annotations

from httpserver.services.investigation.agent_working_state import (
    QuestionDisposition,
    QuestionStatus,
)

GUIDANCE_VERSION = "integration-vocabulary-guidance:v1"
GUIDANCE_HEADER = "Vocabulary guidance (clarifies the EXISTING contract; introduces no new values and changes no rule):"


def question_status_vocabulary() -> tuple[str, ...]:
    return tuple(m.value for m in QuestionStatus)


def question_disposition_vocabulary() -> tuple[str, ...]:
    return tuple(m.value for m in QuestionDisposition)


def build_vocabulary_guidance_text() -> str:
    """Render the guidance suffix.  Deterministic function of the
    production enums only — regenerate on any enum change, never
    hand-maintain the value lists."""
    statuses = ", ".join(repr(v) for v in question_status_vocabulary())
    dispositions = ", ".join(
        repr(v) for v in question_disposition_vocabulary())
    return (
        f"{GUIDANCE_HEADER}\n"
        "1. A fresh D* result shown with \"status\": \"completed\" means "
        "the specialist DELEGATION finished executing. It says nothing "
        "about the state of the Question it investigated. Delegation "
        "lifecycle status and Question status are DIFFERENT state "
        "machines.\n"
        "2. A question's to_status must be one of the frozen "
        f"QuestionStatus values: {statuses}. "
        "\"completed\" is NOT a Question status and will be rejected.\n"
        "3. to_status (where the question stands) and disposition (what "
        "the investigation concluded) are DIFFERENT semantic fields; "
        "one never substitutes for the other.\n"
        "4. \"not_supported\" is a QuestionDisposition value "
        f"({dispositions}), "
        "not a QuestionStatus; never emit it as a to_status.\n"
        "5. Absence of evidence does NOT by itself make a question "
        "closable: \"answered\" and \"unresolved\" remain subject to "
        "the existing closure policy (basis refs, limitations/summary, "
        "and for required questions a passed closure verification). "
        "Never fabricate evidence, never invent basis handles, and "
        "never imply verification results that do not exist.\n"
        "6. Every existing validation, binding and StateTransitionPolicy "
        "rule is unchanged by this note; this guidance only explains "
        "vocabulary that already exists in the schema."
    )


def guidance_violations() -> list[str]:
    """Self-verification: re-extract every value the rendered text
    claims to enumerate and require exact membership in the production
    enums (guards against a second, drifting state definition)."""
    text = build_vocabulary_guidance_text()
    violations = []
    for value in question_status_vocabulary():
        if repr(value) not in text:
            violations.append(f"missing QuestionStatus value: {value!r}")
    for value in question_disposition_vocabulary():
        if repr(value) not in text:
            violations.append(
                f"missing QuestionDisposition value: {value!r}")
    if '"completed"' not in text.replace("'completed'", '"completed"'):
        violations.append("text does not name 'completed' as illegal")
    # no fabricated vocabulary: every quoted status-like token in the
    # text must be a member of one of the two enums (or the delegation
    # lifecycle value being clarified)
    delegation_only = {"completed"}
    import re

    for quoted in set(re.findall(r'"([a-z_]+)"', text)):
        if quoted in ("status",):
            continue
        if quoted in question_status_vocabulary():
            continue
        if quoted in question_disposition_vocabulary():
            continue
        if quoted in delegation_only:
            continue
        violations.append(f"unrecognized quoted vocabulary: {quoted!r}")
    return violations


GUIDANCE_TEXT = build_vocabulary_guidance_text()
"""Frozen at import time from the production enums; the controlled
comparison protocol binds its SHA256, so any enum change invalidates
the pre-registration instead of silently re-basing the text."""


def guidance_sha256() -> str:
    import hashlib

    return hashlib.sha256(GUIDANCE_TEXT.encode("utf-8")).hexdigest()


class GuidanceIntegrationAgentFactory:
    """INTEGRATE-only experimental factory variant (RCA-2A.6 treatment
    arm).  Construction mirrors the production factory exactly — same
    model, same output_type, and the instruction TEXT is still produced
    by the production ``_integration_instructions_v2`` — with ONE
    difference: the frozen guidance suffix is appended.  PLAN and
    Specialist agents are NOT buildable from this class at all: an
    experiment physically cannot leak the guidance into another stage's
    prompt."""

    def __init__(self, *, model=None, settings=None):
        if model is not None:
            self._model = model
        elif settings is not None:
            from httpserver.services.investigation.agent_model_adapter import (
                build_chat_model,
            )

            self._model = build_chat_model(settings)
        else:
            raise ValueError(
                "GuidanceIntegrationAgentFactory requires an explicit "
                "model or settings")

    def build_integration_agent_v2(self, projection):
        from pydantic_ai import Agent

        from httpserver.services.investigation.agent_integration_v2 import (
            SupervisorIntegrationDecisionV2,
        )
        from httpserver.services.investigation.agent_supervisor import (
            _integration_instructions_v2,
        )

        return Agent(
            self._model,
            output_type=SupervisorIntegrationDecisionV2,
            instructions=[
                _integration_instructions_v2(projection)
                + "\n\n" + GUIDANCE_TEXT,
            ],
        )

    def __getattr__(self, name):
        # plan/specialist builders are intentionally NOT proxied: the
        # guidance variant only exists for the INTEGRATE stage
        raise AttributeError(
            f"GuidanceIntegrationAgentFactory is INTEGRATE-only "
            f"(attempted {name!r})")


__all__ = [
    "GUIDANCE_HEADER",
    "GUIDANCE_TEXT",
    "GUIDANCE_VERSION",
    "GuidanceIntegrationAgentFactory",
    "build_vocabulary_guidance_text",
    "guidance_sha256",
    "guidance_violations",
    "question_disposition_vocabulary",
    "question_status_vocabulary",
]
