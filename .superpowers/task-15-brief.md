### Task 15: Implement Result Upload/Retrieval APIs (authored — plan gives title+scope only)

**Files:**
- Modify: `python_service/server/models/schemas.py` — add 4 schemas
- Create: `python_service/server/api/results.py` — 3 endpoints
- Modify: `python_service/server/main.py` — mount `results_router`
- Create: `python_service/tests/test_results_api.py`

**Interfaces:**
- Consumes: `ResultAggregator` (Task 14), `get_current_client` + `get_current_user`
  (auth), `get_db`, ORM `AnalysisTask` / `Client`.
- Produces: the result sub-resource API under `/api/tasks/{task_id}`.

This is the API companion to the Task 14 `ResultAggregator`, the way Task 13
wrapped the Task 12 orchestrator. It enforces the two different auth models:
**client-auth for upload** (a client posts only ITS OWN task's artifacts) and
**user-auth, org-scoped for retrieval** (the web UI reads results within its
org). Org isolation + ownership live here; the service trusts ids.

## Schemas (add to `schemas.py`)

```
class ResultArtifact(BaseModel):          # one artifact a client produced
    result_type: str = Field(..., pattern="^(database|file|metadata)$")
    file_path: Optional[str] = None
    file_size: Optional[int] = Field(None, ge=0)
    storage_location: Optional[str] = None
    result_metadata: Dict[str, Any] = {}

class ResultUploadRequest(BaseModel):
    artifacts: List[ResultArtifact]

class AnalysisResultResponse(BaseSchema):
    task_id: uuid.UUID
    client_id: Optional[uuid.UUID] = None
    result_type: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    storage_location: Optional[str] = None
    result_metadata: Dict[str, Any]

class LLMAnalysisResponse(BaseSchema):
    task_id: uuid.UUID
    file_id: Optional[uuid.UUID] = None
    file_path: Optional[str] = None
    input_text_hash: Optional[str] = None
    analysis_result: str
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    cost: Optional[Decimal] = None
```
(`Decimal` import needed; `Any`/`Dict`/`List`/`Optional`/`Field`/`uuid` already imported.)

## Endpoints (`api/results.py`, `APIRouter(prefix="/api/tasks", tags=["Results"])`)

1. `POST /api/tasks/{task_id}/results` — **client-auth** upload.
   - Fetch task → 404 if missing.
   - **Ownership (CRITICAL):** `task.client_id != current_client.id` → 403
     "Access denied". (A client posts only its own task's artifacts — stronger
     than org-scope and the correct check for a client principal.)
   - `ResultAggregator.store_results(task_id, current_client.id,
     [a.model_dump() for a in payload.artifacts], db)`. The service re-verifies
     ownership (defense in depth — the accepted double-query). Response
     `List[AnalysisResultResponse]`.

2. `GET /api/tasks/{task_id}/results` — **user-auth, org-scoped** retrieval.
   - `_get_task_owned_by_org`: fetch task → 404; super_admin bypass else
     `current_user.org_id != task.org_id` → 403. (Pattern identical to Task 13.)
   - `ResultAggregator.get_task_results(task_id, db)`. Response
     `List[AnalysisResultResponse]`.

3. `GET /api/tasks/{task_id}/llm-analyses` — **user-auth, org-scoped** retrieval.
   - Same `_get_task_owned_by_org` gate. `ResultAggregator.get_task_llm_analyses`.
     Response `List[LLMAnalysisResponse]`.

## PITFALLS (resolve when implementing)

1. **Two auth models (CRITICAL).** Upload uses `get_current_client`
   (client-token; ownership = `task.client_id == client.id`). Retrieval uses
   `get_current_user` (user-token; org-scope = `task.org_id == user.org_id`).
   Do NOT mix: a client must not read cross-org results via the user path, and a
   user must not upload as a client. Each endpoint depends on exactly one.

2. **Org isolation on retrieval is the endpoint's job (CRITICAL).** The service
   trusts `task_id`. Fetch the task and scope on `task.org_id` (super_admin
   bypass), 404 before 403 (no existence leak) — same as Task 13.

3. **Shared prefix `/api/tasks` with the Task 13 router.** Valid in FastAPI
   (routes match by full method+path); sub-paths `/results` and `/llm-analyses`
   do not collide with Task 13's `/`, `/{task_id}`, `/{task_id}/cancel`. Mount
   order in main.py is irrelevant (no same-path collisions). Document it in the
   module docstring so it isn't mistaken for a bug.

4. **Response schemas need `id` + `created_at` (BaseSchema).** Retrieval returns
   real ORM rows; in tests the factory rows MUST set both or serialization 422s.
   Upload relies on the service's `db.refresh` populating `created_at` — wire
   `_populate_defaults_on_refresh` onto `db.refresh` in tests.

5. **`store_results` takes `List[dict]`.** Convert each `ResultArtifact` via
   `.model_dump()` (keys: result_type, file_path, file_size, storage_location,
   result_metadata) — matches what the service reads.

6. **No datetime in endpoints** (service/models own timestamps). Keep it that
   way — no `utcnow` trap here.

7. **`cost` is `Decimal` (Numeric(10,4)).** Use `Optional[Decimal]` in the
   response; Pydantic v2 serializes it. Verify in the retrieval test.

8. **Mock wiring (per endpoint):**
   - upload: `chain.first.side_effect = [task, task]` (endpoint lookup + service
     re-check), then N `db.add` + 1 commit + N `db.refresh`.
   - retrieval: `chain.first.return_value = task` (endpoint gate) AND
     `chain.filter.return_value.order_by.return_value.all.return_value = rows`
     (service get) — two distinct terminal attrs (`.first` vs `.order_by().all`),
     no conflict.

## Forward notes (not Task 15 fixes)
- **Client→task progress wiring** (Tasks 12/13/14 forward note): still
  outstanding. The `task_id` soft link in command parameters should route
  `POST /api/commands/{id}/status` progress into
  `TaskOrchestrator.update_task_progress` and command-completion into
  `TaskOrchestrator.complete_task` — a small dedicated task re-opening
  `commands.py`.
- **Task-completion bridging on upload** is intentionally NOT done here: marking
  a task completed is tied to command completion, not artifact upload.
- **LLM text submission** (the server→LLM flow, `llm_analysis.py`) is a separate
  task / Cycle 2.
- `status_filter` / enum validation deferred to live-DB (consistent w/ prior tasks).

## Steps
1. Add the 4 schemas to `schemas.py`.
2. Write `results.py` (3 endpoints, the two auth models).
3. Mount `results_router` in `main.py`.
4. Write `test_results_api.py` (mock-DB + both `auth_as`/`client_as` overrides).
5. `cd python_service && python -m pytest tests/test_results_api.py -v` + full suite.
6. Commit: `feat: add result upload/retrieval API endpoints with tests`.
7. Dispatch reviewer; apply fixes; mark complete in `progress.md`.
