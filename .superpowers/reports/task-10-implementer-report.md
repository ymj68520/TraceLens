# Task 10 Implementer Report: Command Queue Service

## What was implemented

Task 10: the command queue management service.

**Files:**
- Created `python_service/server/services/command_queue.py` —
  `CommandQueueService` with 5 static methods:
  - `create_command(command_data, user_id, db)` — enqueue; verifies the client
    exists (ValueError otherwise); computes TTL (24h default, 1h for critical
    via `settings.CRITICAL_COMMAND_TTL_HOURS`); status set to `pending`.
  - `get_pending_commands(client_id, db)` — claims pending, unexpired commands
    ordered by priority (critical>high>normal>low) then `created_at`, and
    transitions each to `assigned` with `assigned_at`.
  - `update_command_status(command_id, status, result_message=None, db=None)` —
    `completed`/`failed` stamp `completed_at`; `failed` increments
    `retry_count`; unknown command raises ValueError.
  - `expire_commands(db=None)` — past-TTL `pending`/`assigned` → `expired`;
    returns count.
  - `get_commands_for_client(client_id, db)` — poll entry: refreshes client
    presence (`last_seen`; online iff `last_poll` within 60s), claims pending
    commands, returns `CommandPollResponse`.
- Created `python_service/tests/test_command_queue.py` — 15 tests.

Implemented directly by the controller (not a subagent) to avoid the
model-switch terminations that killed earlier implementers mid-flight; the
independent reviewer gate is still used.

## Deviations from the brief (all required for correctness/consistency)

1. **`datetime.utcnow()` → `datetime.now(timezone.utc)`** (9 occurrences in the
   brief's service). Two reasons: (a) consistency with the codebase standard
   (`auth_service`, `organizations`, `clients` all use aware UTC and warn
   against `utcnow()`); (b) `utcnow()` is deprecated on Python 3.12 and produces
   a naive datetime that would `TypeError` the moment it is compared against a
   DB-stored aware `ttl`. All "now" values now go through a centralized
   `_now()` helper.

2. **`Case` import hoisted + de-aliased.** The brief imports `from sqlalchemy
   import case as Case` at the *bottom* of the file (after the class) and uses
   `Case((cond, val), ...)`. The positional-tuple syntax is correct for
   SQLAlchemy 2.0; I moved `from sqlalchemy import and_, case` to the top
   imports and dropped the alias (used as `case(...)`). Added an `else_=5` so
   unknown priorities sort last rather than NULL.

3. **`.seconds` → `.total_seconds()`** in the online/offline check. A
   timedelta's `.seconds` attribute only holds the seconds component
   (0–86399), dropping any days; `.total_seconds()` measures the full interval.

4. **`status="pending"` set explicitly** in `create_command`. The brief relied
   on the DB column default (`default="pending"`), which only applies on
   flush/INSERT. Under the mock-DB test pattern there is no flush, so the
   returned object would have `status=None`. Setting it explicitly makes the
   object well-formed pre-flush and is harmless (matches the CHECK constraint).

5. **Tests use the mock-DB pattern**, not the brief's `SessionLocal`-based
   fixtures. The ORM models use PostgreSQL-native `JSONB`/`UUID`, so no live DB
   is available (consistent with Tasks 8/9). Query chains are terminal-stubbed
   (`.first()`/`.all()`) to return real ORM instances, so the status
   transitions, TTL math, retry accounting, and presence logic are all
   verified. The SQL filter/order predicates themselves are not asserted
   through a mock (they are never compiled) — that awaits a live DB.

## What was tested

Command: `python -m pytest tests/test_command_queue.py -v`
**Result: 15/15 passed.**

Coverage: create (normal TTL window, critical short-TTL override, unknown
client), get_pending (claim → assigned + assigned_at, empty path), update
(completed stamps completed_at, failed increments retry + stamps, in_progress
neither, unknown command raises), expire (past-TTL → expired + count, none
path), poll (online when last_poll recent, offline when stale/never-polled,
unknown client no-op).

**Full suite:** `464 passed, 3 skipped, 2 failed`. The 2 failures are the same
pre-existing, unrelated ones (missing `scipy` for a wechat PageRank test; a
graphiti base-URL env-config test) — not touched by this task.

## Forward observation (not a Task 10 fix)

`get_commands_for_client` derives online/offline from `client.last_poll`, which
is documented as "stamped by the poll endpoint" (Task 11). The intended call
sequence is therefore: poll endpoint sets `last_poll = now`, then calls this
method. If Task 11's poll endpoint does *not* set `last_poll` before calling
here, a mid-poll client would read as offline. Flagging so Task 11 wires
`last_poll` before invoking this service (or this method is revised to stamp
`last_poll` itself). Either is a Task 11 design choice.

## Files changed
- `python_service/server/services/command_queue.py` (created)
- `python_service/tests/test_command_queue.py` (created, 15 tests)

## Self-review findings
- All 5 brief methods implemented with documented behavior.
- Five deviations, all correctness/consistency-driven (datetime standard, import
  hygiene, timedelta math, well-formed returned object, test-environment reality).
- Business logic (TTL math, status transitions, retry accounting, presence) is
  directly verified; SQL predicate compilation is flagged for the live-DB phase.
