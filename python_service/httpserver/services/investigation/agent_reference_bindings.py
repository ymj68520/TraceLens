"""A1 supervisor integration contract v2 — trusted reference bindings.

The v1 contract made the supervisor LLM transcribe machine identity
strings (task/investigation/run UUIDs, 64-hex state/attention hashes,
delegation UUID + result-hash pairs, canonical evidence keys, question
ids, coverage dimension names).  P8B's ModelQualificationExperiment showed
four model families failing at exactly that interface with distinct
identity-plumbing signatures while evidence discovery itself succeeded.

v2 inverts the responsibility boundary (spec: "LLM chooses meaning;
TraceLens binds identity"):

    server owns canonical ids
    -> server derives a frozen ReferenceBindingTableV1 per invocation
    -> the model chooses semantic HANDLES (E1, Q2, D3, COV1, ...)
    -> the server resolves handles back to canonical refs (exact, no
       fuzzy repair) and injects every trusted identity field itself
    -> the existing StateTransitionPolicy stays the sole authority

Handles are ephemeral, model-facing reference labels: not Evidence ids,
not database identity, not citable, never valid across contexts.  They
are ordinals over canonically sorted refs, so the same frozen context
always produces the same table hash (deterministic, §5) — but they are
NOT array indices of any model-visible list; the table is server-owned.

This module is pure/deterministic: no I/O, no LLM, no clock.
"""

from __future__ import annotations

import enum
from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .agent_integration import (
    FreshResultEnvelope,
    IntegrationContextPack,
    context_state_question_ids,
)
from .agent_runtime import canonical_state_json, state_hash_of
from .agent_supervisor import SupervisorPlanningContextPack
from .agent_working_state import AgentWorkingStateV1

BINDING_TABLE_VERSION = "reference-binding-table:v1"

# Canonical handle prefixes.  Fixed-width per kind, ordinal over sorted
# canonical refs.  These strings are the ONLY identity tokens a v2 model
# may emit.
HANDLE_PREFIXES: Mapping[str, str] = {
    "evidence": "E",
    "question": "Q",
    "coverage": "COV",
    "delegation_result": "D",
    "finding": "F",
    "claim_proposal": "P",
    "hypothesis": "H",
    "contradiction": "X",
    "attention_item": "A",
}


class BindingKind(str, enum.Enum):
    evidence = "evidence"
    question = "question"
    coverage = "coverage"
    delegation_result = "delegation_result"
    finding = "finding"
    claim_proposal = "claim_proposal"
    hypothesis = "hypothesis"
    contradiction = "contradiction"
    attention_item = "attention_item"


class ReferenceBinding(BaseModel):
    """One handle -> canonical ref binding inside a frozen table."""

    model_config = ConfigDict(frozen=True)

    handle: str
    kind: BindingKind
    canonical_ref: str
    display_digest: str = ""


class ReferenceBindingTableV1(BaseModel):
    """Frozen per-invocation handle table (A1 §5).

    Valid ONLY inside the exact frozen context it was derived from
    (run-scoped per invocation; the supervisor is stateless across
    cycles and both context packs are rebuilt per cycle, so a per-
    invocation table is the only scope that never goes stale).
    """

    model_config = ConfigDict(frozen=True)

    table_version: str = BINDING_TABLE_VERSION
    binding_table_id: str = ""
    task_id: str
    investigation_id: str
    run_id: Optional[str] = None
    working_state_revision: int
    context_hash: str

    bindings: tuple[ReferenceBinding, ...] = ()

    created_at: str = "deterministic"  # never wall-clock; keeps hash stable

    input_hash: str = ""

    def __init__(self, **data: Any):
        super().__init__(**data)
        if not self.binding_table_id or not self.input_hash:
            derived = self._derive_hashes()
            object.__setattr__(
                self,
                "__dict__",
                {
                    **self.__dict__,
                    "binding_table_id": self.binding_table_id
                    or derived["binding_table_id"],
                    "input_hash": self.input_hash or derived["input_hash"],
                },
            )

    def _derive_hashes(self) -> dict[str, str]:
        payload = {
            "table_version": self.table_version,
            "task_id": self.task_id,
            "investigation_id": self.investigation_id,
            "run_id": self.run_id,
            "working_state_revision": self.working_state_revision,
            "context_hash": self.context_hash,
            "bindings": [b.model_dump() for b in self.bindings],
        }
        digest = state_hash_of(canonical_state_json(payload))
        return {"binding_table_id": f"rbt:{digest[:32]}", "input_hash": digest}

    def table_hash(self) -> str:
        return self.input_hash

    def by_handle(self, handle: str) -> Optional[ReferenceBinding]:
        for binding in self.bindings:
            if binding.handle == handle:
                return binding
        return None

    def canonical_refs_of_kind(self, kind: BindingKind) -> tuple[str, ...]:
        return tuple(
            b.canonical_ref for b in self.bindings if b.kind is kind
        )

    def handle_of(
        self, kind: BindingKind, canonical_ref: str
    ) -> Optional[str]:
        for binding in self.bindings:
            if binding.kind is kind and binding.canonical_ref == canonical_ref:
                return binding.handle
        return None


def _ordinal_handles(prefix: str, refs: Iterable[str]) -> list[tuple[str, str]]:
    return [
        (f"{prefix}{index}", ref)
        for index, ref in enumerate(sorted(refs), start=1)
    ]


def _display_digest(*content: Any) -> str:
    return state_hash_of(
        canonical_state_json(list(content))
    )[:16]


def _evidence_display(canonical_ref: str) -> str:
    """Human-reasonable, deterministic evidence display: path tail + short
    content digest.  The exact canonical key is deliberately NOT shown
    (A1 §17 default) — the model reasons about the file, the server
    binds the identity."""
    tail = "/".join(canonical_ref.replace("\\", "/").rstrip("/").split("/")[-2:])
    return f"{tail}#{_display_digest(canonical_ref)}"


def build_integration_binding_table(
    context: IntegrationContextPack,
    state: AgentWorkingStateV1,
) -> ReferenceBindingTableV1:
    """Derive the frozen handle table for ONE integration invocation.

    Deterministic function of (context, state): same inputs -> same
    binding_table_id (§5).  Domains mirror the v1 validator exactly:
    questions come from the context state slice (the same set the
    validator binds against), evidence from the fresh results' ref
    union, coverage/hypotheses/contradictions/findings/proposals from
    the frozen working state.
    """
    bindings: list[ReferenceBinding] = []

    question_ids = sorted(context_state_question_ids(context))
    for handle, qid in _ordinal_handles(
        HANDLE_PREFIXES["question"], question_ids
    ):
        q = state.question(qid)
        display = _display_digest(
            qid,
            (q.text or "")[:120] if q is not None else "",
            (q.status.value if q is not None else ""),
        )
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.question,
                canonical_ref=qid,
                display_digest=display,
            )
        )

    evidence_refs: set[str] = set(context.relevant_evidence_refs)
    for handle, ref in _ordinal_handles(
        HANDLE_PREFIXES["evidence"], evidence_refs
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.evidence,
                canonical_ref=ref,
                display_digest=_evidence_display(ref),
            )
        )

    for handle, env in (
        (f"D{index}", env)
        for index, env in enumerate(
            sorted(context.fresh_results, key=lambda e: e.delegation_id),
            start=1,
        )
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.delegation_result,
                canonical_ref=env.delegation_id,
                display_digest=_display_digest(
                    env.delegation_id, env.result_hash
                ),
            )
        )

    for handle, dim in (
        (f"COV{index}", dim)
        for index, dim in enumerate(
            sorted(state.coverage, key=lambda d: d.dimension_id), start=1
        )
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.coverage,
                canonical_ref=dim.dimension_id,
                display_digest=_display_digest(
                    dim.dimension_id, dim.status.value, dim.required
                ),
            )
        )

    for handle, ref in _ordinal_handles(
        HANDLE_PREFIXES["finding"], state.finding_refs
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.finding,
                canonical_ref=ref,
                display_digest=_display_digest(ref),
            )
        )

    for handle, ref in _ordinal_handles(
        HANDLE_PREFIXES["claim_proposal"], state.pending_proposal_refs
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.claim_proposal,
                canonical_ref=ref,
                display_digest=_display_digest(ref),
            )
        )

    for handle, hyp in (
        (f"H{index}", hyp)
        for index, hyp in enumerate(
            sorted(state.hypotheses, key=lambda h: h.hypothesis_id), start=1
        )
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.hypothesis,
                canonical_ref=hyp.hypothesis_id,
                display_digest=_display_digest(
                    hyp.hypothesis_id, hyp.status.value
                ),
            )
        )

    for handle, con in (
        (f"X{index}", con)
        for index, con in enumerate(
            sorted(
                state.contradictions, key=lambda c: c.contradiction_id
            ),
            start=1,
        )
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.contradiction,
                canonical_ref=con.contradiction_id,
                display_digest=_display_digest(
                    con.contradiction_id, con.status.value
                ),
            )
        )

    return ReferenceBindingTableV1(
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        working_state_revision=context.state_revision,
        context_hash=context.input_hash(),
        bindings=tuple(bindings),
    )


def build_plan_binding_table(
    pack: SupervisorPlanningContextPack,
) -> ReferenceBindingTableV1:
    """Derive the frozen handle table for ONE plan invocation.

    Domains: attention items (A*), active questions (Q*), source scopes
    (kept raw — a small closed semantic set; spec §4 design note).
    """
    bindings: list[ReferenceBinding] = []

    for handle, item in (
        (f"A{index}", item)
        for index, item in enumerate(
            sorted(pack.attention_items, key=lambda i: i.item_id), start=1
        )
    ):
        band = getattr(item.band, "value", item.band)
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.attention_item,
                canonical_ref=item.item_id,
                display_digest=_display_digest(
                    item.item_id, band, tuple(item.reason_codes)
                ),
            )
        )

    for handle, entry in (
        (f"Q{index}", entry)
        for index, entry in enumerate(
            sorted(pack.question_index, key=lambda q: q.question_id), start=1
        )
    ):
        bindings.append(
            ReferenceBinding(
                handle=handle,
                kind=BindingKind.question,
                canonical_ref=entry.question_id,
                display_digest=_display_digest(
                    entry.question_id, entry.status
                ),
            )
        )

    return ReferenceBindingTableV1(
        task_id=pack.task_id,
        investigation_id=pack.investigation_id,
        run_id=pack.run_id,
        working_state_revision=pack.state_revision,
        context_hash=state_hash_of(
            canonical_state_json(pack.model_dump())
        ),
        bindings=tuple(bindings),
    )


__all__ = [
    "BINDING_TABLE_VERSION",
    "BindingKind",
    "HANDLE_PREFIXES",
    "ReferenceBinding",
    "ReferenceBindingTableV1",
    "build_integration_binding_table",
    "build_plan_binding_table",
]
