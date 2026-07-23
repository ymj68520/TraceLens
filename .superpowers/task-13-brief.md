### Task 13: Implement Task Management API Endpoints (authored — plan gives title+scope only)

**Files:**
- Create: `python_service/server/api/tasks.py`
- Modify: `python_service/server/main.py` (mount `tasks_router`, existing style)
- Create: `python_service/tests/test_tasks_api.py`

**Interfaces:**
- Consumes: `TaskOrchestrator` (Task 12), `get_current_user` (auth), `get_db`
- Produces: 4 user-facing endpoints on `APIRouter(prefix="/api/tasks", tags=["Tasks"])`

This is the task-management analogue of Task 11's command API: it wraps the
Task 12 `TaskOrchestrator` and enforces org isolation + resource consistency at
the API boundary (the service trusts what it is handed — Task 12 reviewer
forward note).

## Endpoints

1. `POST /api/tasks` — create (user-auth, **org-scoped + disk-image consistency**)
   - Body: `AnalysisTaskCreate` (client_id, disk_image_id, task_name,
     analysis_type, priority, ttl_hours).
   - Derive `org_id` from `current_user.org_id` (NEVER the body).
   - Fetch client → 404 if missing; org-scope check (super_admin bypass, else
     `current_user.org_id == client.org_id` → 403).
   - Fetch disk_image → 404 if missing; verify `disk_image.client_id == client.id`
     → else 404 "Disk image not found" (prevents a cross-org disk image leaking
     into this org's command `image_path`; treat mismatch as not-found, no leak).
   - Call `TaskOrchestrator.create_analysis_task(org_id=current_user.org_id,
     user_id=current_user.id, client_id=..., disk_image_id=..., task_name=...,
     analysis_type=..., priority=..., ttl_hours=..., db=db)`.
   - Response: `AnalysisTaskResponse`.
2. `GET /api/tasks/{task_id}` — get (user-auth, org-scoped)
   - `TaskOrchestrator.get_task_status(task_id, db)` → 404 if None; org-scope on
     `task.org_id`; Response `AnalysisTaskResponse`.
3. `GET /api/tasks` — list (user-auth, org-scoped, optional `status_filter`)
   - Declare BEFORE `/{task_id}` (no real shadow — list is the empty path — but
     keep the ordering convention). `TaskOrchestrator.list_user_tasks(
     current_user.id, current_user.org_id, status_filter, db)` →
     `List[AnalysisTaskResponse]`. (Non-admin own-task filtering deferred.)
4. `POST /api/tasks/{task_id}/cancel` — cancel (user-auth, org-scoped)
   - `get_task_status` → 404; org-scope; `TaskOrchestrator.cancel_task(task_id,
     current_user.id, db)`; Response `AnalysisTaskResponse`. Wrap `ValueError`
     (cannot-cancel) → 409 "Conflict".

## PITFALLS (resolve when implementing)

1. **Org-scope is the endpoint's job (CRITICAL — Task 12 reviewer forward note).**
   The service trusts `org_id`. Derive from `current_user.org_id`; verify the
   client (and transitively the disk image) belongs to that org. Pattern from
   `commands.py` / `clients.py`: `if current_user.role != "super_admin" and
   current_user.org_id != <resource>.org_id: raise 403 "Access denied"`.

2. **Disk-image cross-org leak (CRITICAL).** Without `disk_image.client_id ==
   client.id`, a user can reference ANOTHER org's disk image; its `path` lands in
   the command's `image_path`. Verify membership; 404 on mismatch.

3. **`AnalysisTaskResponse` needs `created_at` + `progress` (Important).**
   `BaseSchema` requires `id` + `created_at`; `AnalysisTaskResponse.progress` is a
   required `int`. The service-created task relies on DB defaults for both
   (`func.now()`, `default=0`). Under mock, `db.refresh` is a no-op → both stay
   None → 422 serialization failure. Wire `_populate_defaults_on_refresh` onto
   `db.refresh` (Task 8/11 pattern) to set `created_at` and `progress` when None.

4. **Create does 4 `.first()` under mock** (endpoint client + disk_image, then
   the service's client + disk_image existence re-checks — the accepted Task 11
   double-query, doubled for two resources). Wire
   `chain.first.side_effect = [client, disk_image, client, disk_image]`.

5. **No datetime manipulation in the endpoints** (the service owns that) — so no
   `utcnow` pitfall here. Keep it that way.

6. **main.py wiring** — existing style:
   `from server.api.tasks import router as tasks_router` +
   `app.include_router(tasks_router)`. Routers declare own prefix/tags.

7. **Tests** — mock-DB + dependency-override (`auth_as`), real ORM `User`/
   `AnalysisTask`/`Client`/`DiskImage` instances, `_populate_defaults_on_refresh`
   on `db.refresh`. Cover: create (success / client-404 / cross-org-403 /
   same-org-allowed / disk-image-404 / disk-image-mismatch-404), get (success /
   404 / cross-org-403), list (success / status_filter), cancel (success /
   cannot-cancel-409 / 404 / cross-org-403). Negative tests assert no service
   write side-effects where applicable.

## Forward notes (not Task 13 fixes)
- Client→task progress wiring: the client reports via `POST /api/commands/{id}/status`
  (`TaskStatusUpdate.progress`). A follow-up should route that into
  `TaskOrchestrator.update_task_progress` via the `task_id` soft link stamped in
  Task 12 (re-opens Task 11's `commands.py` — defer to a small dedicated task).
- `status_filter` enum validation deferred to live-DB (consistent w/ Tasks 11-12).
- Non-admin own-task filtering in `list_user_tasks` deferred.

## Steps
1. Write `tasks.py` (4 endpoints, org-scoped).
2. Wire into `main.py`.
3. Write `test_tasks_api.py` (mock-DB).
4. `cd python_service && python -m pytest tests/test_tasks_api.py -v`.
5. Commit: `feat: add task management API endpoints with tests`.
