### Task 14: Implement Result Aggregator Service (authored — plan gives title+scope only)

**Files:**
- Create: `python_service/server/services/result_aggregator.py`
- Create: `python_service/tests/test_result_aggregator.py`

**Interfaces:**
- Consumes: ORM models `AnalysisResult`, `LLMAnalysis`, `AnalysisTask`,
  `Client` (`server.models.database`); `SessionLocal` (`server.db.session`).
- Produces: a `ResultAggregator` class with granular store/retrieve methods.
  Task 15 (`api/results.py`) will compose these + enforce org isolation, exactly
  as Task 13 composed Task 12's `TaskOrchestrator`.

**Position in the architecture:** When a client finishes an `analyze_disk`
command it produces artifacts (a forensic SQLite database, carved files,
metadata) plus LLM-analyzable text. The result aggregator persists those as
`analysis_results` / `llm_analysis` rows attached to the originating task. It is
the result-side analogue of `task_orchestrator.py` (Task 12).

## Methods

All public methods use `owns_session = db is None` + `try`/`finally` +
`db.close()` (the pool-leak guard established by `command_queue.py` /
`task_orchestrator.py` — Task 15 will pass its request session, but background
aggregation callers may not).

1. `store_result(task_id, client_id, result_type, file_path=None,
   file_size=None, storage_location=None, result_metadata=None, db=None)
   -> AnalysisResult`
   - Validate `result_type` in `("database", "file", "metadata")` → else
     `ValueError` (mirrors the DB CHECK constraint; defense before insert).
   - Fetch the task (`AnalysisTask.id == task_id`); `ValueError("Task not
     found")` if missing.
   - **Client consistency (Important):** verify `client_id == task.client_id`,
     else `ValueError("Client does not own this task")`. Prevents a client from
     injecting results into another client's task. (`client_id` is the
     authenticated client's id, passed by Task 15.)
   - Create the `AnalysisResult` row using the **`result_metadata=`** kwarg
     (NOT `metadata=` — reserved), commit, refresh, return.

2. `store_results(task_id, client_id, results: List[dict], db=None)
   -> List[AnalysisResult]`
   - Bulk path: fetch + validate the task ONCE, validate each result's
     `result_type`, build all rows, single commit, refresh each. Same
     client-consistency check. Returns the created rows in order.

3. `store_llm_analysis(task_id, analysis_result, file_path=None,
   input_text_hash=None, model_used=None, tokens_used=None, cost=None,
   file_id=None, db=None) -> LLMAnalysis`
   - `analysis_result` is the non-nullable LLM output text.
   - Fetch + validate task existence (client consistency optional here — LLM
     analysis rows have no `client_id` column; enforce task existence only).
   - Create the `LLMAnalysis` row, commit, refresh, return.

4. `get_task_results(task_id, db=None) -> List[AnalysisResult]`
   - `query(AnalysisResult).filter(AnalysisResult.task_id ==
     task_id).order_by(created_at.desc()).all()` (newest first).

5. `get_task_llm_analyses(task_id, db=None) -> List[LLMAnalysis]`
   - Same shape against `LLMAnalysis`.

## PITFALLS (resolve when implementing)

1. **`metadata` reserved → `result_metadata` (CRITICAL).** The `AnalysisResult`
   column `metadata` is mapped to the `result_metadata` attribute
   (`database.py`). Use `result_metadata=` in the constructor and
   `.result_metadata` for access — same trap as Task 12's `task_metadata` /
   Task 9's `image_metadata`.

2. **`result_type` CHECK constraint (Important).** Validate against
   `("database", "file", "metadata")` in the service and raise `ValueError`.
   Under the mock the DB never rejects a bad value, so without the check the
   service would happily store `"nonsense"`. Keep the validation BEFORE any
   `db.add` (and, for `owns_session`, BEFORE opening the session is fine since
   it raises inside `try`).

3. **Client consistency = data integrity, NOT org isolation (Important).**
   `task.client_id == client_id` stops a client injecting results into a
   sibling task. **Org isolation itself is the API layer's job (Task 15)** —
   this service trusts the ids it is handed (mirroring how the orchestrator
   trusts `org_id`). Do NOT re-derive org here.

4. **No datetime manipulation (the models own timestamps).** Both models use
   `created_at = Column(DateTime, server_default=func.now())` — a server
   default, so the service sets NO timestamps. This means **no `utcnow` trap
   here** — keep it that way. Tests populate `created_at` via
   `_populate_defaults_on_refresh` on `db.refresh`.

5. **`owns_session` + `try`/`finally` on ALL 5 public methods (Important).**
   Same class of leak as Task 10/12. Validation that raises (bad result_type,
   missing task) must happen INSIDE the `try` so `finally` still closes an owned
   session — the `update_task_progress` ordering lesson from Task 12.

6. **`store_results` single transaction.** One task fetch, one validation pass,
   one commit, then refresh each row. Do not commit per-row (would leave
   partial writes if one fails).

7. **JSONB `result_metadata`.** Set once at creation (a fresh dict) — no
   in-place mutation, so the plain-`Column(JSONB)`/no-`MutableDict` caveat does
   not bite. (Forward note: a later update path that mutates it must reassign.)

8. **Tests: mock-DB, pure service methods.** Pass a `MagicMock` session
   directly (no FastAPI DI). Wire `_populate_defaults_on_refresh` onto
   `db.refresh` to supply `created_at`. Query chains:
   - `store_result`: one `.first()` (task lookup) + `db.add` + commit + refresh.
   - `store_results`: one `.first()` (task) + N `db.add` + one commit + N refresh.
   - `store_llm_analysis`: one `.first()` (task) + add + commit + refresh.
   - `get_task_results` / `get_task_llm_analyses`: `.filter().order_by().all()`.
   Cover: store_result success / invalid result_type (ValueError before add) /
   task-not-found / client-mismatch; store_results bulk; store_llm_analysis;
   get methods; and the owns-session/leak contract (owned closed on success +
   on the validation-error path; provided never closed).

## Forward notes (not Task 14 fixes)
- Task 15 (`api/results.py`) MUST derive + verify ownership: the authenticated
  client (client-token) may only post results for tasks whose `client_id` is
  its own; user-token callers fetching results must be org-scoped to the task's
  `org_id`. The service does neither.
- Wiring client→task progress: still outstanding from Tasks 12/13 (the
  `task_id` soft link in command parameters). A small dedicated task should
  route `POST /api/commands/{id}/status` progress into
  `TaskOrchestrator.update_task_progress` and task completion into the
  aggregator.
- `result_type` / `status` enum validation is deferred to live-DB CHECK
  constraints where it isn't enforced in code (consistent with Tasks 11-13).

## Steps
1. Write `result_aggregator.py` (5 methods, owns_session each).
2. Write `test_result_aggregator.py` (mock-DB).
3. `cd python_service && python -m pytest tests/test_result_aggregator.py -v`.
4. Full suite to confirm no regression.
5. Commit: `feat: add result aggregator service with tests`.
6. Dispatch reviewer; apply fixes; mark complete in `progress.md`.
