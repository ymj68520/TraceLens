# Task 13 Implementer Report: Task Management API Endpoints

## What was implemented

Task 13: the user-facing task-management API — the analogue of Task 11's command
API, wrapping the Task 12 `TaskOrchestrator` and enforcing org isolation +
resource consistency at the API boundary.

**Files:**
- Created `python_service/server/api/tasks.py` — 4 endpoints on
  `APIRouter(prefix="/api/tasks", tags=["Tasks"])`:
  - `POST /api/tasks` — create (user-auth, **org-scoped + disk-image
    consistency**). `org_id` derived from `current_user.org_id` (never body);
    client existence + org-scope; disk-image existence **and** membership check
    (`disk_image.client_id == client.id`, else 404 to avoid leaking another
    org's image path); delegates to `TaskOrchestrator.create_analysis_task`;
    `ValueError` → 404 (defensive — both resources were just verified).
  - `GET /api/tasks` — list (org-scoped, optional `status_filter`), declared
    before `/{task_id}` per convention. Delegates to `list_user_tasks`.
  - `GET /api/tasks/{task_id}` — get (org-scoped). `get_task_status` →
    404 / org-scope 403.
  - `POST /api/tasks/{task_id}/cancel` — cancel (org-scoped). `get_task_status`
    → 404 / org-scope; `cancel_task`; `ValueError` (cannot-cancel terminal) →
    409 Conflict.
- Modified `python_service/server/main.py` — imported and mounted
  `tasks_router` (existing style).
- Created `python_service/tests/test_tasks_api.py` — 15 tests.

Implemented directly by the controller (subagents killed by model switches);
the independent reviewer gate is still used.

## Deviations from the brief (all required for correctness)

1. **Disk-image cross-org leak → 404 (not 403).** The brief said treat a
   membership mismatch as "404, no leak" — implemented exactly. Reporting it as
   403 would confirm the image exists under a different client; 404 gives no
   such signal. This closes the path where a caller references another org's
   disk image and its `path` would land in the command's `image_path`.

2. **`cancel` `ValueError` mapped to 409 (not a generic 500).** The orchestrator
   raises `ValueError` for both "Task not found" and "Cannot cancel task with
   status: …". Since existence + org are checked *before* `cancel_task` is
   called, the only reachable `ValueError` at that point is the cannot-cancel
   (terminal-state) one, so 409 Conflict is correct. A race that deletes the
   task between the two calls is the sole edge case and would surface as a
   misleading 409 rather than 404 — accepted (rare, non-correctness-critical).

3. **`_populate_defaults_on_refresh` populates `created_at` AND `progress`.**
   `create_analysis_task` calls `db.refresh(task)` twice and relies on DB
   server defaults (`func.now()` for `created_at`, `default=0` for `progress`)
   that the mock does not apply. `BaseSchema` requires a non-None `created_at`
   and `AnalysisTaskResponse` requires `progress: int`, so without populating
   them the create response would 422. The refresh side-effect sets both when
   None. (Only ever invoked with an `AnalysisTask` in this suite.)

4. **Create test wires 4 `.first()` (not 2).** The endpoint does client +
   disk-image existence lookups, then the service re-verifies both — the same
   accepted double-query pattern from Task 11, doubled across two resources.
   `side_effect = [cli, img, cli, img]`.

5. **`cancel` test wires 3 `.first()`.** Endpoint `get_task_status`, then
   `cancel_task`'s task lookup and command lookup (the soft-link match from
   Task 12). `side_effect = [task, task, command]`. The cannot-cancel path
   consumes only 2 (the command lookup is unreachable after the raise).

6. **List endpoint does no user-level filtering (deferred, as briefed).**
   `list_user_tasks` keeps the `user_id` param for future non-admin own-task
   filtering; the endpoint passes `current_user.id` but the service does not
   yet restrict by it. This matches the Task 12 forward note.

## What was tested

Command: `python -m pytest tests/test_tasks_api.py -v`
**Result: 15/15 passed.**

Coverage: create (success / client-404 / cross-org-403 / same-org-allowed /
disk-image-404 / disk-image-mismatch-404, asserting no `db.add` on the negative
paths), list (success / status_filter), get (success / 404 / cross-org-403),
cancel (success + command-failed / cannot-cancel-409 / 404 / cross-org-403).

**Full suite:** `525 passed, 3 skipped, 2 failed`. The 2 failures are the
pre-existing, unrelated ones (missing `scipy`; graphiti base-URL env) —
untouched by this task. (+15 over the prior 510.)

## Forward observations (not Task 13 fixes)

- **Client→task progress wiring.** The client reports progress via
  `POST /api/commands/{id}/status` (`TaskStatusUpdate.progress`). A follow-up
  should route that into `TaskOrchestrator.update_task_progress` via the
  `task_id` soft link stamped in Task 12 (re-opens Task 11's `commands.py`).
- **`status_filter` not enum-validated** — consistent with the Tasks 11-12
  deferral (live-DB concern).
- **Non-admin own-task filtering** in `list_user_tasks` still deferred.
- **`create_task`'s defensive `ValueError`→404 branch** is unreachable in the
  happy path (both resources are verified just above); retained for the rare
  delete-between-checks race.

## Self-review findings
- All 4 endpoints present, org-scoped identically to `commands.py`.
- The two CRITICAL pitfall points (org-scope + disk-image membership) each have
  dedicated negative tests asserting 403/404 AND `db.add.assert_not_called()`.
- No datetime manipulation in the endpoints (the service owns it) — so no
  `utcnow` pitfall here.
- Route ordering: `GET ""` (list) declared before `GET "/{task_id}"` (get);
  no shadowing.

## Reviewer fixes applied (commit f6983df)

Reviewer verdict: **Approved with minor fixes**. All CRITICAL invariants
verified correct against code (org isolation across all 4 endpoints, disk-image
cross-org leak genuinely blocked via membership check before the service call,
cancel ordering right, happy path really fails the command, mock query-chain
depths honest, no datetime in endpoints, main.py wiring correct,
`_populate_defaults_on_refresh` supplies the server defaults).

One **medium** test-fidelity finding fixed:

- **Cancel/get negative tests did not assert no-writes.** They checked only the
  status code, so a future reorder that moved the org/existence check *after*
  `cancel_task` could commit a cross-org cancellation (status set, command
  failed, history added, committed) while still returning 403 — and the test
  would stay green. Added `db.add.assert_not_called()` +
  `db.commit.assert_not_called()` to `test_cancel_task_cross_org_forbidden`,
  `test_cancel_task_not_found`, `test_get_task_cross_org_forbidden` (and
  `test_get_task_not_found` is read-only, covered by the cancel pair). Mirrors
  the create-flow negative tests. Tests: 15/15.

No code defects were found — the production code was correct on every invariant;
this was a gap in the safety net for the "authorization check before write"
ordering.
