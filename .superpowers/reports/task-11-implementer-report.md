# Task 11 Implementer Report: Command Queue API Endpoints

## What was implemented

Task 11: the command queue API endpoints that consume the Task 10 service.

**Files:**
- Created `python_service/server/api/commands.py` — 6 endpoints on an
  `APIRouter(prefix="/api/commands")`:
  - `POST /api/commands` — create a command (user-auth, **org-scoped**)
  - `GET  /api/commands/poll` — client poll (client-auth); stamps `last_poll`
    then claims pending commands
  - `POST /api/commands/{command_id}/status` — client reports status
    (client-auth, ownership-checked)
  - `GET  /api/commands/{command_id}` — command details (user-auth, org-scoped)
  - `GET  /api/commands/client/{client_id}` — list a client's commands
    (user-auth, org-scoped)
  - `POST /api/commands/expire` — manual TTL sweep (super_admin only)
- Modified `python_service/server/main.py` — mount `commands_router`.
- Created `python_service/tests/test_commands_api.py` — 17 tests.

Implemented directly by the controller (not a subagent) to avoid the
model-switch terminations that killed earlier implementers; the independent
reviewer gate is still used.

## Deviations from the brief (all required for correctness/security)

1. **CRITICAL — cross-tenancy hole in `create_command`.** The brief's endpoint
   called the service directly; the service only checks the client *exists*, so
   any authenticated user could enqueue a command against ANOTHER org's client.
   Added an org-scope check (fetch client; require `super_admin` or matching
   `org_id`, else 403) before calling the service. Matches the pattern in
   `clients.py` (get/delete). Added `test_create_command_cross_org_forbidden`
   and `test_create_command_same_org_allowed`.

2. **`CommandQueue` NameError.** The brief's `update_command_status` endpoint
   used `db.query(CommandQueue)` but `CommandQueue` was only imported locally
   inside `get_command`/`list_client_commands` — not in `update_command_status`'s
   scope → NameError at runtime. Consolidated `Client, CommandQueue, User` into
   the top-level import and removed the redundant local imports.

3. **`datetime.utcnow()` → `datetime.now(timezone.utc)`** in `poll_commands`
   (brief stamped `last_poll` with `utcnow()`). Consistency with the codebase
   standard and the aware-UTC values stored/compared in the service. This also
   confirms Task 10's forward note: the poll endpoint sets `last_poll` *before*
   calling `get_commands_for_client`, so an actively-polling client reads online.

4. **`get_command` None-guard.** After fetching the owning client, the brief
   dereferenced `client.org_id` unconditionally; an orphaned command (client
   gone) would 500 with AttributeError. Added a `client is None` → 404 guard.

5. **`main.py` wiring** follows the EXISTING style (`from server.api.commands
   import router as commands_router` + `app.include_router(commands_router)`),
   not the brief's `from server.api import ... commands` form. Routers declare
   their own prefix/tags, so no extra args.

6. **Route ordering preserved**: `GET /poll` is declared before `GET
   /{command_id}` so the literal `poll` segment is not captured by the
   `{command_id}` path parameter. (The brief already had this order; called out
   in the module docstring.)

7. **Tests use the mock-DB + dependency-override pattern**, not the brief's
   live-`SessionLocal`/real-login fixtures (no DB in the test env). Auth
   identities are real ORM `User`/`Client`; `get_current_user`/
   `get_current_client` overridden via `auth_as`/`client_as`. A
   `_populate_defaults_on_refresh` side-effect on `db.refresh` simulates the DB
   applying server defaults (`created_at`, `retry_count`) on commit+refresh —
   the established Task 8 pattern — so a freshly-created command serializes into
   `CommandResponse`.

## What was tested

Command: `python -m pytest tests/test_commands_api.py -v`
**Result: 17/17 passed.**

Coverage: create (success / 404 / cross-org 403 / same-org allowed), poll
(claims pending → assigned, stamps last_poll, online; empty), status (success /
404 / wrong-client 403), get (success / 404 / cross-org 403), list (success /
404 / cross-org 403), expire (success / non-admin 403). Negative tests assert
no DB writes (`add.assert_not_called()`, `query.assert_not_called()`).

**Full suite:** `487 passed, 3 skipped, 2 failed`. The 2 failures are the same
pre-existing, unrelated ones (missing `scipy`; graphiti base-URL env) — not
touched by this task.

## Forward observations (not Task 11 fixes)

- The `status_filter` query param on `list_client_commands` adds another
  `.filter()` to the chain; under the mock-DB pattern the extra predicate is
  not asserted (SQL is never compiled), consistent with how Task 10's
  filter/ordering predicates are deferred to the live-DB phase.
- `update_command_status` endpoint queries the command once for the ownership
  check, then the service queries it again. Acceptable (mock-friendly); a
  single-query refactor is possible later.
- `trigger_expiration` is user-triggered only; the background TTL sweeper
  (needed for automatic expiry) is a later task — it can call
  `CommandQueueService.expire_commands()` directly (the Task 10 session-leak
  fix makes that safe).

## Files changed
- `python_service/server/api/commands.py` (created)
- `python_service/server/main.py` (mount commands router)
- `python_service/tests/test_commands_api.py` (created, 17 tests)

## Self-review findings
- All 6 brief endpoints implemented with documented access control.
- One critical security deviation (cross-tenancy) + three correctness deviations
  (NameError, datetime, None-guard) + wiring/style — all required.
- Tests verify real HTTP behavior across success and all documented error paths.
- The Task 10 ↔ Task 11 `last_poll` coupling is confirmed resolved (poll stamps
  before claiming).
