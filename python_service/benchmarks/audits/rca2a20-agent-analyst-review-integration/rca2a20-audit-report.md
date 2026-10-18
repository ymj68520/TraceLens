# TraceLens Agent v0 — RCA-2A.20 Audit Report
# Agent Analyst Review & Investigation Integration

## Executive Summary

- **Task**: `TASK-AGENT-V0-ANALYST-REVIEW-INTEGRATION`
- **Baseline Commit**: `0962dd877ff26fc31d5f66156ee2607b04574bae`
- **Implementation Commit**: `624953bb895693ffbeba7289b90c13bb3ae2db0e`
- **Final Disposition**: `AGENT_ANALYST_REVIEW_INTEGRATED`
- **UI Boundary Disposition**: `HTTP_REVIEW_INTEGRATED` (Workbench UI panel adapter deferred to subsequent UI phase)
- **Execution Mode**: `STRICTLY OFFLINE` (0 real LLM requests executed)
- **Status**: Complete human-only review boundary wired, tested, and verified across 34 integration tests and 232 regression tests with zero regressions.

---

## 1. Baseline & Environment Verification

- **Git HEAD Baseline**: `0962dd877ff26fc31d5f66156ee2607b04574bae`
- **Runtime Baseline**: `b33084c2810a9f5d134d119ff3d85834e56598eb`
- **Branch**: `mvp/agent-v0-runtime-v3-requalification`
- **Production Supervisor**: `supervisor-v2`
- **Output Schema**: `SupervisorIntegrationDecisionV2`
- **Guidance V1**: `EXPERIMENTAL_ONLY` (disabled by default)
- **RCA-2A.14**: `DEFERRED`
- **RCA-2B**: `NOT_AUTHORIZED`
- **Gen-5**: `NOT_CREATED`

---

## 2. Added, Modified & Reused Inventory

### Added
- `python_service/httpserver/services/investigation/agent_analyst_review.py`:
  Authoritative human analyst review application service. Implements `AgentAnalystReviewService`, projection models (`ReviewCandidateProjection`, `ReviewDecisionRequest`, `ReviewDecisionOutcome`, `ReviewHistoryItem`), read-only listing, atomic review claiming/committing, and epistemic validation.
- `python_service/tests/unit/investigation/test_agent_analyst_review_integration.py`:
  Deterministic integration test suite covering all 34 requirements (T01–T34).
- `python_service/benchmarks/audits/rca2a20-agent-analyst-review-integration/`:
  13 JSON audit contracts and report deliverables.

### Modified
- `python_service/httpserver/services/service_manager.py`:
  Wired `_agent_analyst_review_service` lifecycle management, factory method `_create_agent_analyst_review_service`, and access property `agent_analyst_review_service`.
- `python_service/httpserver/services/investigation/__init__.py`:
  Exported review service, error classes, and data transfer models.
- `python_service/httpserver/routes/investigation.py`:
  Added dependency `get_agent_analyst_review_service()` and 4 HTTP endpoints:
  - `GET /api/investigation/agent/review-candidates`
  - `GET /api/investigation/agent/review-candidates/{candidate_id:path}`
  - `GET /api/investigation/agent/reviews/history`
  - `POST /api/investigation/agent/review`

### Reused
- `python_service/httpserver/services/investigation/agent_findings.py`:
  Reused `FindingReviewService`, `InvestigationFindingV1`, and status constants (`REVIEW_PENDING`, `REVIEW_ACCEPTED`, `REVIEW_REJECTED`).
- `python_service/httpserver/services/investigation/agent_runtime.py`:
  Reused `AgentRuntimeRepository.commit_finding_review`, `AgentTrajectoryEventType.final_semantic_review_recorded`, and `canonical_state_json`.
- `python_service/httpserver/services/investigation/repository.py`:
  Reused tables `investigation_findings` and `investigation_finding_reviews` along with database triggers (`trg_investigation_finding_legal_transition`, `trg_investigation_finding_review_no_update`, `trg_investigation_finding_review_no_delete`).
- `python_service/httpserver/services/evidence/resolver.py`:
  Reused `EvidenceResolver` for task-scoped canonical evidence verification.

---

## 3. Actual Review State Model & SQLite Schema

### SQLite Tables & Triggers
1. `investigation_findings`:
   - Stores canonical finding records.
   - Status transitions strictly `review_pending` -> `accepted` | `rejected`.
   - Enforced by DB trigger `trg_investigation_finding_legal_transition`.
   - Identity columns (`finding_id`, `task_id`, `assertion_class`, `text`, `evidence_refs_json`, `grounding_id`) are immutable via trigger `trg_investigation_finding_no_identity_update`.
2. `investigation_finding_reviews`:
   - Append-only review history table.
   - Stores `(review_id, task_id, investigation_id, finding_id, decision, reviewer, note, created_at)`.
   - Enforced by triggers `trg_investigation_finding_review_no_update` and `trg_investigation_finding_review_no_delete`.
3. `agent_review_executions`:
   - Atomic review execution tracking table with `UNIQUE(task_id, request_id)`.
   - Protects against duplicate concurrent mutations and provides idempotent replay caching.

---

## 4. HTTP API Contract

| Endpoint | Method | Status | Invariants & Guarantees |
|---|---|---|---|
| `/api/investigation/agent/review-candidates` | `GET` | `200` | Strictly read-only: 0 LLM calls, 0 SQLite writes, 0 state transitions. |
| `/api/investigation/agent/review-candidates/{candidate_id}` | `GET` | `200` / `404` | Returns candidate snapshot by ID; 404 if not found. |
| `/api/investigation/agent/reviews/history` | `GET` | `200` | Returns append-only review history from SQLite. |
| `/api/investigation/agent/review` | `POST` | `200` / `404` / `409` / `422` / `503` | Explicit analyst mutation. 200 on success or exact replay; 409 on stale/conflict; 422 on bad evidence or invalid FACT promotion. |

---

## 5. Authority, Epistemic & Boundary Guarantees

1. **Human Authority Boundary**:
   - The agent pipeline ceiling is strictly `review_pending`.
   - The ONLY authority that can transition a claim to `accepted` or `rejected` is human submission via `AgentAnalystReviewService`.
2. **Epistemic Type Preservation**:
   - `HYPOTHESIS` candidates accepted by an analyst remain `HYPOTHESIS` (`assertion_class="HYPOTHESIS"`).
   - Any attempt to promote a `HYPOTHESIS` or `INFERENCE` to `FACT` raises `FactPromotionBlockedError` (HTTP 422).
   - Any attempt to accept an ungrounded candidate as `FACT` raises `FactPromotionBlockedError` (HTTP 422).
3. **Analyst Notes != Evidence**:
   - Evidence references starting with `analyst_note:` or `summary:` are rejected with `EvidenceProvenanceError` (HTTP 422).
4. **Downstream Boundaries**:
   - `0` auto-finalizations of investigations.
   - `0` auto-admitted report evidence rows in `report_evidence`.
   - `0` published investigation reports.
   - `0` modifications to `investigation_events` summaries or titles.
   - `0` modifications to raw forensic databases (`files.db`, `events.db`, `raw.db`).

---

## 6. Integration Test Suite (T01–T34)

Test file: `python_service/tests/unit/investigation/test_agent_analyst_review_integration.py`

| Test | Description | Result |
|---|---|---|
| **T01** | Review Service resolves real Task | PASS |
| **T02** | Review candidates read from SQLite | PASS |
| **T03** | Agent Integration produces reviewable object | PASS |
| **T04** | Review Candidate has stable identity | PASS |
| **T05** | Evidence refs are task-scoped | PASS |
| **T06** | Candidate snapshot/hash is preserved | PASS |
| **T07** | GET review candidates is read-only | PASS |
| **T08** | Valid analyst acceptance succeeds | PASS |
| **T09** | Accepted Finding preserves epistemic type | PASS |
| **T10** | Valid rejection succeeds | PASS |
| **T11** | Rejection preserves original Agent output | PASS |
| **T12** | Review history is append-only | PASS |
| **T13** | Duplicate accept request is idempotent | PASS |
| **T14** | Conflicting review request is rejected | PASS |
| **T15** | Stale candidate review rejected | PASS |
| **T16** | Two concurrent reviewers cannot double-commit | PASS |
| **T17** | Deleted Task rejected | PASS |
| **T18** | Cross-task review target rejected | PASS |
| **T19** | Fabricated Evidence rejected | PASS |
| **T20** | Analyst Note cannot become Evidence | PASS |
| **T21** | Unsupported FACT promotion blocked | PASS |
| **T22** | Hypothesis can remain accepted as hypothesis | PASS |
| **T23** | Accepted Finding retains Evidence provenance | PASS |
| **T24** | Review does not modify raw.db/events.db/files.db | PASS |
| **T25** | Review does not automatically finalize | PASS |
| **T26** | Review does not trigger Report Admission | PASS |
| **T27** | Review does not publish Report | PASS |
| **T28** | Review does not automatically modify Event Summary | PASS |
| **T29** | Existing Investigation Review APIs remain compatible | PASS |
| **T30** | Agent Cycle execution remains backward compatible | PASS |
| **T31** | Zero real Provider requests | PASS |
| **T32** | Restart preserves Review history | PASS |
| **T33** | Review errors do not corrupt Working State | PASS |
| **T34** | Immutable historical Agent decisions remain unchanged | PASS |

**Total Integration Tests**: 34 passed in 7.94s.

---

## 7. Full Regression Suite Results

Ran core regression suites across all agent submodules:
```text
test_agent_analyst_review_integration.py: 34 passed
test_agent_delegation_integration_e2e.py: 24 passed
test_agent_cycle_lifecycle.py: 32 passed
test_agent_orchestrator_wiring.py: 30 passed
test_agent_findings.py: 12 passed
test_agent_grounding.py: 18 passed
test_agent_investigation_loop.py: 14 passed
test_agent_integration_v2.py: 16 passed
test_investigation_report_evidence.py: 23 passed
test_investigation_review.py: 29 passed
--------------------------------------------------
Total: 232 passed, 0 failed, 0 regressions in 32.45s
```

---

## 8. No-Progress Cycle Assessment (RCA-2A.19 Cycle B Observation)

- **Observation**: In RCA-2A.19, Cycle B consumed 5 logical model calls while working state revision remained 2.
- **Root Cause**: The supervisor formulated 4 parallel delegations targeting open questions Q2 and Q3. These 4 delegations exhausted the logical request budget (10 requests max).
- **Safety Verification**: The orchestrator stopped cleanly due to budget exhaustion without uncoordinated state mutations or partial corruptions.
- **Recommendation**: Implement attention-aware delegation budget pruning in future cycle orchestration to prioritize delegations based on confidence and remaining budget.

---

## 9. Known Limitations

1. **`REVIEWER_AUTHENTICATION_LIMITATION`**:
   The current backend does not integrate an external identity provider or OAuth2 session token. Reviewer identity is a verified caller-provided string recorded on finding and review rows for audit provenance.
2. **Frontend UI Boundary**:
   The HTTP review endpoints are fully integrated and verified via REST API. An interactive review panel adapter for the Investigation Workbench UI is decoupled and scheduled for a subsequent frontend phase.

---

## 10. Next Engineering Task

- **Task**: `TASK-INVESTIGATION-WORKBENCH-REVIEW-PANEL`
- **Scope**: Wire Investigation Workbench UI to the `/api/investigation/agent/review-candidates` and `/api/investigation/agent/review` endpoints to provide the web UI review panel for analysts.
