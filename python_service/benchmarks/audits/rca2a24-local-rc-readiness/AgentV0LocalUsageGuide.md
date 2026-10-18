# TraceLens Agent v0 — Local Single-User Developer Usage Guide

## 1. Overview
TraceLens Agent v0 provides an offline-first, task-scoped investigation assistant integrated into the Investigation Workbench.
It assists digital forensics analysts by executing evidence-grounded investigation cycles, formulating hypotheses, delegating queries to read-only tool registries, and presenting review candidates for explicit human analyst disposition.

---

## 2. Configuration & Startup

### Step 1: Environment Variables
By default, Agent execution is disabled (`AGENT_EXECUTION_ENABLED=false`).
To enable local Agent functionality, configure `.env` or set environment variables:

```bash
# Enable Agent cycle execution (Default: false)
AGENT_EXECUTION_ENABLED=true

# Enforce local caller mutation boundary (Default: true)
AGENT_REVIEW_LOCAL_ONLY=true

# Configure LLM Provider (Example: local vLLM or Ollama endpoint)
LLM_TEXT_BASE_URL=http://127.0.0.1:8000/v1
LLM_TEXT_MODEL=qwen2.5-14b-instruct
LLM_TEXT_API_KEY=your_api_key_here
```

> [!NOTE]
> When `AGENT_EXECUTION_ENABLED=false`, existing review candidates and historical review decisions remain fully accessible in read-only mode.

### Step 2: Starting Services
```bash
# Terminal 1: Python HTTP Service
cd python_service
python3 -m uvicorn httpserver.main:app --host 127.0.0.1 --port 8090

# Terminal 2: Web Frontend Dev Server
cd web
npm run dev -- --host 127.0.0.1 --port 3000
```

---

## 3. Investigation Workflow

### Step 1: Open Investigation Workbench
1. Navigate to `http://127.0.0.1:3000/investigation?task_id=<YOUR_TASK_ID>`.
2. The Investigation Workbench layout consists of three columns:
   - **Column 1: Evidence Workspace** (File tree and primary artifacts)
   - **Column 2: Investigation Timeline** (Temporal event sequence)
   - **Column 3: Analysis Workspace** (Agent Execution Control + Agent Review Panel)

### Step 2: Start an Agent Cycle
1. In Column 3, inspect the **Agent Execution Control**:
   - Current Working State Revision (e.g. `Rev 1`)
   - Execution Status (`idle`)
   - Objective & Metric counters (Questions, Findings, Hypotheses)
2. Click **Start Agent Cycle** (`data-testid="btn-start-agent-cycle"`).
3. The button enters the busy state (`执行中...`) with duplicate-click protection.
4. The Agent executes a single bounded cycle:
   - Supervisor v2 generates delegation plan.
   - Specialists query read-only SQLite forensic evidence databases.
   - Supervisor v2 integrates findings and commits new working state (`Rev 1 -> Rev 2`).
5. When complete, the revision badge updates to `Rev 2` and the candidate queue automatically refreshes.

### Step 3: Inspect Review Candidates & Evidence Provenance
1. In the **Agent Analyst Review Panel** below the execution control:
   - Inspect the candidate list (showing claim type, target ID, and status `review_pending`).
2. Click a candidate to view its full text, assertion class, and grounded evidence references.
3. Click an evidence reference (e.g. `file:C/Windows/System32/config/SAM`) to cross-reference the raw evidence in Column 1.

### Step 4: Submit Explicit Accept / Reject Review
1. Click **Accept** or **Reject**.
2. A confirmation modal appears (`data-testid="review-confirmation-dialog"`).
3. Enter an analyst review note (e.g., *"Analyst verified SAM hive credential access."*).
4. Click **Confirm Decision**.
5. The decision is committed authoritatively to SQLite `investigation_finding_reviews`.
6. The candidate status updates to `accepted` or `rejected`, and the decision appears in the **Authoritative Review History**.

---

## 4. Epistemic Safety Rules & Integrity Guarantees

1. **Raw Evidence Immutability**: Evidence databases (`raw.db`, `files.db`, `events.db`) are strictly read-only and will never be modified.
2. **Epistemic Class Separation**:
   - Findings produced by the agent are `INFERENCE` or `HYPOTHESIS`.
   - Explicit Analyst Acceptance accepts the finding as a secondary claim, but **never** auto-promotes it to `FACT`.
   - Attempting to promote an inference directly to `FACT` is rejected by the backend with `422 Unprocessable Entity`.
3. **No Automatic Report Admission**: Accepted findings do not automatically appear in published reports; explicit analyst report admission is required.
4. **Idempotency & Crash Recovery**:
   - If an HTTP timeout occurs, the frontend retains the stable `request_id`.
   - Retrying with the same `request_id` safely returns the completed cycle outcome without duplicate re-execution.
   - If the backend crashes during execution, `recover_interrupted_agent_runtime()` automatically clears stale claims on restart.

---

## 5. Known Operational Limitations

1. **Reviewer Identity**: Reviewer identity is caller-declared (`CALLER_DECLARED`). In single-user development mode, no RBAC or password authentication is enforced.
2. **Local Security Boundary**: Review and cycle mutation endpoints are strictly restricted to trusted local development callers (`127.0.0.1`, `::1`, `localhost`). Untrusted origins, null origins, and cross-site requests are rejected with `403 Forbidden`.
3. **Single-User Only**: Not designed for concurrent multi-tenant team collaboration.
