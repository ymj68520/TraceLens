# A1-S Repository Audit — Deterministic Evidence Snapshot Admission Boundary

Status: AUDIT COMPLETE (S1, pre-implementation, spec §2)
Branch: `mvp/agent-v0-evidence-snapshot-admission` (from `43283a31`)
Scope: answer Q1–Q13 from code; freeze the §3 invariant and the §4/§5 design.
No production behaviour changed by this document.

## Q1 — do tool results resolve through resolve_evidence()?

NO.  The read-only tool adapters list/emit evidence keys directly from the
task's own stores; successful observations persist those keys verbatim
(`ToolObservation.evidence_refs`).  `EvidenceResolver.resolve_evidence()`
(`httpserver/services/evidence/resolver.py:115`) is only on the capture-
service path (`investigation/service.py:33`).  The agent discovery path and
the canonical resolution path never meet today.

## Q2 — is allowed_evidence_ids visibility-only?

YES.  `reconstruct_allowed_evidence_ids`
(`agent_tools/visibility.py:24`) is a pure function over durable records
(frozen ContextPack initial refs ∪ successful ToolObservation refs), built
exactly so grounding can distinguish "Evidence exists" from "Evidence was
exposed to this run".  It has no relationship to EvidenceSnapshot admission;
the two concepts are fully independent (confirmed at Q3/Q10).

## Q3 — what does SpecialistResultV1.evidence_refs validation check?

`SpecialistResultValidator._check_evidence_ref`
(`agent_specialist_result.py:317`):
- syntax: `parse_evidence_key` ✓
- cross-task seam: `SpecialistResultValidator()` is constructed BARE
  (`agent_specialist_executor.py:665`) → `_cross_task_ref_validator is None`
  → **task scope is NOT checked at the specialist stage**
- visibility membership ✓ (`RESULT_EVIDENCE_NOT_VISIBLE`)
- canonical resolver: ✗ not consulted
- snapshot existence: ✗ not consulted

A tool-visible ref can therefore enter a completed result without ever
having been canonically resolved or admitted — the audited gap.

## Q4 — specialist terminal transaction

`AgentRuntimeRepository.complete_delegation_with_result`
(`agent_runtime.py:5235`): single `BEGIN IMMEDIATE` — valid result row +
delegation `running → completed` transition + completion trajectory event +
COMMIT.  This is the transaction boundary S extends.

## Q5 — does the invariant already exist?

NO (verified): `capture_if_absent` has exactly three callers — the manual
HTTP capture API (`routes/investigation.py:76`), the investigation event
flow (`event.py:186`) and secondary-analysis execution
(`execution.py:168,181`).  Nothing in the agent path captures; a completed
SpecialistResult can cite snapshot-less refs.

## Q6 — why does integration grounding query evidence_snapshots?

Intended provenance freeze, not accidental coupling.  EvidenceSnapshot is
the immutable investigation-side provenance anchor: grounding must answer
"was this Evidence admitted into THIS investigation" (frozen payload at
capture time), which the live task store cannot answer.  The capture service
even performs a deliberate second task-liveness lookup separate from
resolution (`service.py:35-40`).  The P5A defect is not the anchor's
semantics — it is that the agent path never feeds the anchor (Q5).

## Q7 — is EVIDENCE_REF_CROSS_TASK dual-used?

YES.  `StateTransitionPolicy._refute_evidence_refs`
(`agent_transitions.py:351`) maps resolver `not_found` to
`EVIDENCE_REF_CROSS_TASK` regardless of whether the ref is foreign-task or
same-task-but-unsnapshotted.  Additive correction (§14): new resolver status
`snapshot_missing` + new violation code `EVIDENCE_SNAPSHOT_MISSING`,
emitted only when the ref is agent-visible but has no snapshot.  No
existing code removed; the code is never used to relax validation.

## Q8 — capture_if_absent semantics

`InvestigationRepository.capture_if_absent` (`repository.py:4414`):
task-guard (`ValueError` on foreign task) / insert-only with
`ON CONFLICT(task_id, evidence_key) DO NOTHING` (first-write-wins,
idempotent, existing snapshot wins and the source DB is not touched) /
candidate built fully OUTSIDE the write transaction from the resolved
Evidence (S5 read-only mode, no LLM).  All four required properties hold.

## Q9 — conn-aware capture?

NOT present: `capture_if_absent` opens its own `BEGIN IMMEDIATE`.  S adds
the minimal adapter `capture_if_absent_conn(conn, candidates)` inserting
pre-built candidates into the EXISTING investigation transaction; the
Snapshot subsystem is not refactored.

## Q10 — when do snapshots trigger today?

Manual capture API, investigation event flow, secondary-analysis execution
(Q5).  "Evidence enters Investigation" today means exactly those; S extends
the admission boundary to "a completed SpecialistResult explicitly cited
it" (§13) — a lifecycle completion, not an identity change.

## Q11 — admission target

The promotion boundary: `SpecialistResult.evidence_refs` (the refs the
agent promotes as investigation-relevant output).  ToolObservation refs
stay discovery-only (§6): capture-per-search-hit would make search results
semantic admissions and write-amplify massively.  Decision: result refs
only.

## Q12 — unresolvable ref at completion

Fail closed: the delegation terminalises as `failed` with the new code
`EVIDENCE_RESOLUTION_FAILED`, an invalid-status result row is persisted for
audit, and NO completed result / NO snapshot is written (mirrors the
existing invalid-output branch at `agent_specialist_executor.py:687`).

## Q13 — task deletion / lifecycle guard

Resolution (Phase A) re-validates task existence via `get_task` (resolver
R1/R2/R3 — DB paths come only from `get_task`); the capture service's
two-lookup pattern (resolution vs task liveness) is preserved; Phase B's
existing transaction already revalidates delegation state
(`queued/running → completed` only from `running`).  Snapshot admission
inherits all of these guards by living inside the same transaction.

## Frozen invariant (§3)

    Delegation.status == completed
    AND E ∈ SpecialistResult.evidence_refs
    ⇒ EvidenceSnapshot(task_id, E) exists

Deterministic, runtime-owned, transactional — never a model duty.

## Design (§4/§5)

Phase A (no locks): for each deduped `result.evidence_ref` →
`parse_evidence_key` → `EvidenceResolver.resolve_evidence(task_id, ref)` →
`build_snapshot_candidate(resolved)` (source-DB reads only).  Any failure ⇒
delegation failed (`EVIDENCE_RESOLUTION_FAILED`), nothing written.
Phase B: the existing `complete_delegation_with_result` transaction —
revalidate lifecycle, `capture_if_absent_conn(...)` for every candidate,
persist result, transition `running → completed`, trajectory, COMMIT.
Atomicity (§10), idempotency (§11), source-truth payloads (§12),
Tool-boundary purity (§6), allowed_evidence_ids untouched (§8).
