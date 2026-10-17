# RCA-2A.16 — Agent Service Wiring & Minimal HTTP Integration Audit Report

- **Phase**: RCA-2A.16
- **Task ID**: `TASK-AGENT-V0-SERVICE-WIRING`
- **Timestamp UTC**: 2026-10-17T06:15:00Z
- **Baseline Commit**: `c143895bbcaf1a9f8c291f325941822b06d14b67` (RCA-2A.15)
- **Candidate ID**: `supervisor-v2-vocabulary-guidance-v1`
- **Candidate Guidance SHA-256**: `e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29`
- **Output Schema Hash**: `a214ec4f5e81fcbb` (`SupervisorIntegrationDecisionV2`)
- **Execution Mode**: `OFFLINE_BOUNDED_IMPLEMENTATION`
- **Final Disposition**: `AGENT_SERVICE_WIRING_COMPLETED`
- **Architectural Policy**: `HARD_STOP_ENFORCED`

---

## 1. Executive Summary

Phase **RCA-2A.16** successfully implements the service layer integration and minimal HTTP API routes for TraceLens Agent v0, directly addressing the core architectural gaps identified in RCA-2A.15. 

Prior to this phase, while all 12 core Agent v0 domain components (supervisor, specialist delegation, registry, working state transition, and hard safety gates) were thoroughly unit-tested, the application service container `ServiceManager` maintained uninitialized wiring (`supervisor=None`, `delegation_dispatcher=None`), and no HTTP endpoints existed to trigger an investigation cycle or inspect agent state.

In accordance with the bounded offline authorization:
1. **Historical Metric Reconciliation**: Reconciled the raw metric accounting differences between RCA-2A.12 and RCA-2A.15. Explicitly corrected the Semantic Adequacy baseline (3/8 Control -> 5/8 Treatment) and the F3 identity overreach attribution (Seat 6 Treatment, not Seat 10).
2. **Orchestrator Wiring in `ServiceManager`**: Implemented `ServiceManager._create_agent_orchestrator()` to wire a concrete `InvestigationSupervisor`, a registered `SpecialistDelegationDispatcher`, a SQLite-backed `AgentStateStore`, and a `SupervisorEvaluationGate`.
3. **Developer-Only Experimental Opt-in**: Added `agent_execution_enabled` (default `False`) and `agent_experimental_guidance_enabled` (default `False`) to configuration settings. Production supervisor defaults strictly use `supervisor-v2`. When experimental guidance is enabled, `GuidanceIntegrationAgentFactory` is plugged in dynamically without modifying `agent_supervisor.py` or production prompt files.
4. **Minimal Agent HTTP Endpoints**: Added `POST /api/investigation/agent/cycle` and `GET /api/investigation/agent/state` with task-scoped concurrency locks (`_agent_task_locks`), execution sets (`_agent_task_running`), revision conflict handling (HTTP 409), and trusted database path resolution via `cpp_backend.get_task(task_id)`.
5. **Deterministic Verification**: Developed 30 comprehensive integration tests (`T01`–`T30` in `test_agent_orchestrator_wiring.py`) verifying dependency injection, state persistence, step execution, concurrency locks, and error propagation.
6. **Zero Real LLM Requests & Zero Production Regression**: 100% offline execution with 0 real provider calls. Passed 1297 tests across RCA-2A.8 through RCA-2A.16 without a single failure.

---

## 2. Baseline Verification & Historical Lineage

### 2.1 Git and Lineage Integrity
- **Verified Baseline Commit**: `c143895bbcaf1a9f8c291f325941822b06d14b67` (RCA-2A.15 solo engineering validation).
- **Lineage Chain**:
  - `0419e111520e1460ff65bac7fb540f9b07745ec0` (RCA-2A.12 — 8/8 Paired Cross-Case Completed)
  - `82227677a4ce4f68bde393c3e22c677bb411fb66` (RCA-2A.13 — Qualification Readiness With Limitations)
  - `ce5649e37f5791d250dc87e23910aec2c75464e6` (RCA-2A.14a — Holdout Readiness, Custody Blocked)
  - `167093e70d2639e692ce52cb0aa7fa6ee5425fa7` (RCA-2A.14b — External Custody Not Available, Deferred)
  - `c143895bbcaf1a9f8c291f325941822b06d14b67` (RCA-2A.15 — Solo Engineering Validation & Critical Path Report)
- **Runtime Invariant**: Real LLM/provider calls count = 0. All audits conducted strictly offline.

### 2.2 Frozen Candidate Integrity
- **Candidate ID**: `supervisor-v2-vocabulary-guidance-v1`
- **Candidate Guidance SHA-256**: `e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29`
- **Output Schema Hash**: `a214ec4f5e81fcbb` (`SupervisorIntegrationDecisionV2`)
- **Status**: Preserved invariant with exact match to RCA-2A.12 through RCA-2A.15.

---

## 3. Historical Metric Amendment (RCA-2A.12 vs RCA-2A.15)

An in-depth code and audit file review reconciled the historical metric discrepancies noted between RCA-2A.12 and RCA-2A.15 (`rca2a16-historical-metric-amendment-v1.json`):

| Evaluation Dimension | RCA-2A.12 Ground Truth | RCA-2A.15 Documented | Reconciled Audit Status |
| :--- | :--- | :--- | :--- |
| **Canonical Integration Validity** | Control: 4/8 (50.0%)<br>Treatment: 7/8 (87.5%)<br>Delta: +37.5 pp | Control: 4/8 (50.0%)<br>Treatment: 7/8 (87.5%)<br>Delta: +37.5 pp | **CONSISTENT**: Gain of +37.5 pp confirmed. |
| **Semantic Adequacy** | Control: 3/8 (37.5%)<br>Treatment: 5/8 (62.5%)<br>Delta: +25.0 pp | Control: 5/8 (62.5%)<br>Treatment: 7/8 (87.5%)<br>Delta: +25.0 pp | **AMENDED**: RCA-2A.15 mistakenly shifted both Control and Treatment baselines upward by 2 seats (conflating Canonical Validity 7/8 with Semantic Adequacy 5/8). The true gain is 3/8 (37.5%) to 5/8 (62.5%), preserving the +25.0 pp delta. |
| **Investigative Information Value** | Treatment Wins: 4/8<br>Control Wins: 2/8<br>Ties: 2/8<br>Positive Discovery: 3/8<br>Non-degraded: 5/8 | Reported as 87.5% (7/8) | **AMENDED**: RCA-2A.15 grouped valid/non-degraded cases together as 7/8. True raw win rate is 4/8 (50.0%) wins, 2/8 ties, 2/8 losses. |
| **F3 Cross-System Identity Overreach** | Observed in Seat 6 (`t2-identity-trap_A` Treatment) | Documented as Seat 10 | **CORRECTED**: The actual overreach occurred in Seat 6 (Treatment). Seat 10 was the Control run for `t2-no-evidence_B`. |

---

## 4. Architectural & Dependency Reuse Assessment

The wiring design adheres to strict architectural boundaries evaluated across 10 core dimensions:

1. **Concrete Orchestrator Class**: Reused existing `AgentOrchestrator` (`python_service/httpserver/services/investigation/agent_orchestrator.py`).
2. **Supervisor Injection**: Injected a concrete `InvestigationSupervisor` with default production `ProductionSupervisor` (using `SupervisorAgentFactory`).
3. **Specialist Dispatcher Injection**: Injected `SpecialistDelegationDispatcher` pre-registered with `LogSpecialist`, `MetricsSpecialist`, `ConfigSpecialist`, and `TimelineSpecialist`.
4. **Guidance Opt-In Mechanics**: Experimental Vocabulary Guidance V1 is accessed exclusively through `agent_experimental_guidance_enabled=True`. When active, `ExperimentalGuidanceSupervisor` dynamically injects `GuidanceIntegrationAgentFactory` without altering production prompts or `agent_supervisor.py`.
5. **State Store Sharing**: Persistence uses SQLite via `SqliteAgentStateStore(db_path)`.
6. **Safety Gates Injected**: Evaluated using `SupervisorEvaluationGate` verifying schema, transitions, and grounding invariants.
7. **Task Lock Isolation**: In-memory asyncio locks (`_agent_task_locks[task_id]`) and active execution sets (`_agent_task_running`) prevent concurrent cycle overlaps per task.
8. **Analyst Review Boundaries**: Supervisor conclusions remain uncommitted drafts until explicitly approved by human analysts; the agent cannot self-approve findings.
9. **Revision Guard**: `expected_revision` checks prevent race conditions or silent overwrites between concurrent HTTP clients.
10. **Zero Production Modification**: `agent_supervisor.py` and `SupervisorIntegrationDecisionV2` remain untouched.

---

## 5. Service Layer & HTTP Integration Implementation

```mermaid
flowchart TD
    Client["HTTP Client"] -->|POST /api/investigation/agent/cycle| RouteCycle["routes/investigation.py: run_investigation_cycle"]
    Client -->|GET /api/investigation/agent/state| RouteState["routes/investigation.py: get_agent_state"]
    
    subgraph RouteGuards["Route Safety & Concurrency Guards"]
        Lock["Task Concurrency Lock (_agent_task_locks)"]
        RunSet["Running Task Guard (_agent_task_running)"]
        RevGuard["Revision Check (HTTP 409 on conflict)"]
    end
    
    RouteCycle --> Lock
    Lock --> RunSet
    RunSet --> RevGuard
    
    subgraph ServiceLayer["ServiceManager"]
        SM["ServiceManager._create_agent_orchestrator()"]
        ConfigCheck{"agent_experimental_guidance_enabled?"}
        ProdSup["ProductionSupervisor (supervisor-v2)"]
        ExpSup["ExperimentalGuidanceSupervisor (+ Guidance V1)"]
        Disp["SpecialistDelegationDispatcher (4 Specialists)"]
        Store["SqliteAgentStateStore"]
    end
    
    RevGuard --> SM
    SM --> ConfigCheck
    ConfigCheck -->|False (Default)| ProdSup
    ConfigCheck -->|True (Opt-in)| ExpSup
    SM --> Disp
    SM --> Store
    
    subgraph Execution["Agent Execution Loop"]
        Orch["AgentOrchestrator.step()"]
        Gate["SupervisorEvaluationGate"]
    end
    
    ProdSup --> Orch
    ExpSup --> Orch
    Disp --> Orch
    Store --> Orch
    Orch --> Gate
```

### 5.1 Configuration Additions (`httpserver/config.py`)
- `agent_execution_enabled: bool = False`: Master switch gating the execution of agent cycles via API.
- `agent_experimental_guidance_enabled: bool = False`: Experimental opt-in switch enabling Vocabulary Guidance V1.
- Enabled `populate_by_name=True` on `SettingsConfigDict` to allow programmatic overrides with camelCase and snake_case aliases.

### 5.2 ServiceManager Wiring (`httpserver/services/service_manager.py`)
- Implemented `_create_agent_orchestrator(task_id, db_path)`:
  - Validates `agent_execution_enabled` is `True`.
  - Instantiates `SpecialistDelegationDispatcher` with standard specialists.
  - Constructs `InvestigationSupervisor` with production defaults or experimental guidance wrapper.
  - Returns fully bound `AgentOrchestrator`.

### 5.3 HTTP Route Endpoints (`httpserver/routes/investigation.py`)
- `POST /api/investigation/agent/cycle`:
  - Validates request body (`task_id`, `max_steps`, `expected_revision`).
  - Acquires task-scoped async lock.
  - Rejects overlapping executions on same task with HTTP 409.
  - Fetches task metadata from `cpp_backend.get_task(task_id)` to resolve trusted SQLite database path.
  - Calls `orchestrator.step()` and returns execution trajectory and updated state.
- `GET /api/investigation/agent/state`:
  - Retrieves current working state, revision, and draft findings.

---

## 6. Deterministic Integration Test Matrix (T01–T30)

All 30 deterministic test cases in `tests/unit/investigation/test_agent_orchestrator_wiring.py` passed with 100% success (execution duration: 9.88s):

| Test ID | Category | Description | Status |
| :--- | :--- | :--- | :--- |
| **T01** | Configuration | `agent_execution_enabled` defaults to `False` | **PASS** |
| **T02** | Configuration | `agent_experimental_guidance_enabled` defaults to `False` | **PASS** |
| **T03** | Configuration | Settings parse env variables correctly | **PASS** |
| **T04** | Wiring | `_create_agent_orchestrator` raises if execution disabled | **PASS** |
| **T05** | Wiring | `_create_agent_orchestrator` returns `AgentOrchestrator` when enabled | **PASS** |
| **T06** | Wiring | Injects non-null `InvestigationSupervisor` | **PASS** |
| **T07** | Wiring | Injects non-null `SpecialistDelegationDispatcher` | **PASS** |
| **T08** | Wiring | Injects non-null `AgentStateStore` | **PASS** |
| **T09** | Wiring | Specialist dispatcher contains all 4 default specialists | **PASS** |
| **T10** | Guidance Opt-in | Default wiring uses production supervisor (`supervisor-v2`) | **PASS** |
| **T11** | Guidance Opt-in | Experimental opt-in uses `GuidanceIntegrationAgentFactory` | **PASS** |
| **T12** | Guidance Opt-in | `agent_supervisor.py` has zero uncommitted changes | **PASS** |
| **T13** | HTTP Cycle | Missing task returns 404 Not Found | **PASS** |
| **T14** | HTTP Cycle | Execution disabled returns 503 Service Unavailable | **PASS** |
| **T15** | HTTP Cycle | Revision conflict returns 409 Conflict | **PASS** |
| **T16** | HTTP Cycle | Concurrent cycle execution on same task returns 409 Conflict | **PASS** |
| **T17** | HTTP Cycle | Valid cycle execution advances revision and returns state | **PASS** |
| **T18** | HTTP Cycle | Max steps parameter is respected | **PASS** |
| **T19** | HTTP State | Missing task returns 404 Not Found | **PASS** |
| **T20** | HTTP State | Valid state retrieval returns current revision and hypotheses | **PASS** |
| **T21** | Persistence | State transitions persist correctly across multiple cycles | **PASS** |
| **T22** | Persistence | SQLite store maintains history and trajectory events | **PASS** |
| **T23** | Evidence Boundary | Ungrounded hypotheses fail validation gate | **PASS** |
| **T24** | Evidence Boundary | Grounded hypotheses pass validation gate | **PASS** |
| **T25** | Analyst Boundary | Agent cannot self-approve conclusions | **PASS** |
| **T26** | Error Handling | Specialist failure propagates cleanly without crashing cycle | **PASS** |
| **T27** | Error Handling | Supervisor exception aborts cycle cleanly and records error | **PASS** |
| **T28** | Path Security | Path resolution rejects relative and directory traversal attempts | **PASS** |
| **T29** | Concurrency | Parallel requests on different tasks execute independently | **PASS** |
| **T30** | Regression | Full end-to-end multi-step cycle completes without mock leaks | **PASS** |

---

## 7. Multi-Phase Regression Summary

A complete offline regression suite verified zero collateral breakage across previous milestone gates:

```text
======================= 1297 passed, 1 skipped in 39.51s =======================
```

- **RCA-2A.8 Semantic Validity Suite**: 12/12 passed (including production path immutability and guidance default checks).
- **RCA-2A.9a Specialist Evidence Grounding Suite**: 17/17 passed.
- **RCA-2A.11b Benchmark Semantics Hardening Suite**: 24/24 passed.
- **RCA-2A.12 Cross-Case Regression Suite**: 28/28 passed.
- **RCA-2A.13 Qualification Protocol Readiness Suite**: 16/16 passed.
- **RCA-2A.14a Holdout Construction Suite**: 20/20 passed.
- **RCA-2A.14b Custody Verification Suite**: 20/20 passed.
- **RCA-2A.15 Solo Engineering Validation Suite**: 21/21 passed.
- **RCA-2A.16 Service Wiring Suite**: 30/30 passed.
- **Investigation Unit Test Suite**: 1097/1098 passed (1 skipped, 0 failed).

---

## 8. Final Engineering Disposition & Hard Stop

### Final Disposition: `AGENT_SERVICE_WIRING_COMPLETED`

TraceLens Agent v0 service layer wiring and minimal HTTP API integration are complete, fully verified, and mathematically auditable. 

- **Production Prompt**: UNCHANGED (`supervisor-v2`).
- **Production Schema**: UNCHANGED (`SupervisorIntegrationDecisionV2`).
- **Real LLM Requests**: STRICTLY ZERO.
- **Independent Qualification (Tier 3)**: DEFERRED.
- **RCA-2B & Gen-5**: NOT AUTHORIZED / NOT CREATED.

**HARD STOP ENFORCED.** No further unprompted executions or production modifications are permitted.
