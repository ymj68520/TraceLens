# C/S Integration & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the new C/S layer (`src/http_agent` + `python_service/server`) from an unconnected, auth-broken island into a runnable, dual-stack deployment where the distributed mode coexists cleanly with the legacy local-mode C++ 8080 server.

**Architecture:** TraceLens runs as **two long-term coexisting deployment modes** (user decision: dual-stack, not deprecation):
- **Local mode (existing):** `forensic_analyzer --http-server 8080` serves the web UI and runs analysis in-process on a single workstation. Legacy `python_service/httpserver` (port 8090) is its LLM/graphiti proxy. Untouched by this plan except for port-bookkeeping.
- **Distributed mode (new):** `python_service/server` (port **8091**) is the multi-tenant backend; `tracelens_agent` clients poll it and run `forensic_analyzer` as a subprocess. The web UI gains a second API client to talk to 8091 for client/task/auth management.

The two modes share the `forensic_analyzer` binary and the web frontend, but not a process or port. This plan resolves the four P0 defects (server not wired in, 8090 collision, web/frontend not migrated, broken production auth) and the two P1 data-model defects (Task↔Command has no FK; DB-artifact naming not contracted), then sketches P2–P4 as follow-up plans.

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy / PyJWT / pytest (server); C++20 / CMake / GTest (client); React + Vite + axios (web); PostgreSQL (data model); raw SQL migrations under `migrations/postgresql/`.

## Global Constraints

- **No raw image bytes ever leave the client.** Only metadata/DB references cross the wire (existing invariant — do not regress).
- **Client never runs the LLM** — `--no-ai` stays unconditional in `src/http_agent/command_executor.cpp`.
- **Dual-stack:** do NOT remove or gut the C++ 8080 server or the legacy `httpserver`. New distributed server gets its own port (8091) and its own launch path.
- **Single source of truth for config:** every server module reads `server.config.settings`, never `os.getenv` directly (except inside `config.py` itself).
- **Python tests:** `cd python_service && pytest tests/ -v`. The C/S server tests use `fastapi.testclient.TestClient` against `server.main.app` (see `python_service/tests/conftest.py`, `test_auth_api.py`).
- **TDD:** every Python task writes the failing test first, runs it red, implements, runs it green, commits.
- **Commit messages** end with `Co-Authored-By: Claude <noreply@anthropic.com>` (repo convention).

## Dual-Stack Port & Responsibility Map (locked by this plan)

| Port | Process | Mode | Owns |
|---|---|---|---|
| 5173 | Vite dev server | both | web UI |
| 8080 | `forensic_analyzer --http-server` | **local** | in-process analysis + serves web UI (local mode) |
| 8090 | `python_service/httpserver` | **local** | LLM / graphiti proxy → 8080 |
| **8091** | `python_service/server` | **distributed** | auth, orgs, clients, command queue, tasks, results |

---

## File Structure

**Server (Python) — modified:**
- `python_service/server/services/auth_service.py` — drop dual config source + broken RS256 auto-select; read `settings`.
- `python_service/server/config.py` — default `PORT` 8090 → **8091**; document dual-stack.
- `python_service/server/models/database.py` — add `CommandQueue.task_id` FK column + relationship; add `AnalysisTask.commands` back-ref.
- `python_service/server/services/task_orchestrator.py` — set `command.task_id`; cancel via FK.
- `python_service/server/api/commands.py` — resolve task via `command.task_id` (move propagation into a service method — see Task 5).
- `python_service/server/services/result_aggregator.py` — persist `base_name` from artifact metadata; do not assume fixed DB names.

**Server (Python) — created:**
- `migrations/postgresql/002_command_task_fk.sql` — add `task_id` column + index + backfill from JSONB.
- `python_service/tests/test_auth_algorithm.py` — RS256 regression test.
- `python_service/tests/test_command_task_fk.py` — FK + cascade tests.

**Ops — modified:**
- `scripts/start_all_services.sh` — launch `python_service/server` on 8091 with a `/health` gate (additive, does not touch 8080/8090).
- `scripts/diagnose_services.sh` — probe 8091.
- `.env.example` — document `PORT`/`JWT_SECRET_KEY`/`JWT_ALGORITHM` for the distributed server.

**Web frontend — modified/created:**
- `web/src/services/api.js` — add `csApi` axios client → 8091.
- `web/src/services/csAuthService.js` — **create** — login/refresh/me against 8091.
- `web/src/services/csClientService.js` — **create** — list/register clients.
- `web/src/services/csTaskService.js` — **create** — distributed task create/list/status.
- `web/vite.config.js` — add `/csapi` proxy → `http://localhost:8091`.

---

## Phase 0 — 止血 (stop the bleeding)

### Task 1: Unify JWT config and fix the production RS256 breakage

**Why:** `auth_service.py:26-27` reads `JWT_SECRET_KEY`/`JWT_ALGORITHM` directly from env (ignoring `server.config.settings`) and hardcodes `JWT_ALGORITHM = "RS256"`. Lines 78/113/129 then select RS256 whenever `ENVIRONMENT != "development"`. No RSA key pair exists anywhere, so PyJWT cannot sign with RS256 using a symmetric secret — **production cannot issue a single token.**

**Files:**
- Modify: `python_service/server/services/auth_service.py:17-29, 78, 113, 129`
- Test: `python_service/tests/test_auth_algorithm.py` (create)

**Interfaces:**
- Consumes: `server.config.settings.JWT_SECRET_KEY`, `settings.JWT_ALGORITHM`, `settings.USER_TOKEN_EXPIRE_HOURS`, `settings.CLIENT_TOKEN_EXPIRE_DAYS` (all already defined at `config.py:44-47`).
- Produces: unchanged public functions `create_user_token`, `create_client_token`, `verify_token` — same signatures, now backed by a single config source.

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/test_auth_algorithm.py`:

```python
"""Regression tests for JWT algorithm/config handling (Task 1).

Guards against two prior defects:
  1. auth_service read JWT config from os.getenv, ignoring server.config.settings
     (two sources of truth with divergent defaults).
  2. ENVIRONMENT != "development" silently selected RS256 with no RSA key pair,
     making token issuance impossible in production.
"""
import jwt
from server.config import settings
from server.services import auth_service


def test_settings_is_the_single_source_of_truth():
    # auth_service must read the same values config.py exposes.
    assert auth_service.JWT_SECRET_KEY == settings.JWT_SECRET_KEY
    assert auth_service.JWT_ALGORITHM == settings.JWT_ALGORITHM


def test_user_token_round_trips():
    token = auth_service.create_user_token(
        user_id="00000000-0000-0000-0000-000000000001",
        org_id="00000000-0000-0000-0000-000000000002",
        role="analyst",
        permissions=["view_results"],
    )
    payload = auth_service.verify_token(token)
    assert payload is not None
    assert payload["type"] == "user"
    assert payload["role"] == "analyst"


def test_client_token_round_trips():
    token = auth_service.create_client_token(
        client_id="00000000-0000-0000-0000-000000000003",
        org_id="00000000-0000-0000-0000-000000000002",
        capabilities={"max_concurrent_tasks": 2},
    )
    payload = auth_service.verify_token(token)
    assert payload is not None
    assert payload["type"] == "client"


def test_token_uses_configured_algorithm():
    token = auth_service.create_user_token(
        user_id="00000000-0000-0000-0000-000000000001",
        org_id="00000000-0000-0000-0000-000000000002",
        role="analyst",
        permissions=[],
    )
    header = jwt.get_unverified_header(token)
    assert header["alg"] == settings.JWT_ALGORITHM
    # Default must be a symmetric alg that works with a shared secret.
    assert settings.JWT_ALGORITHM == "HS256"


def test_production_environment_still_issues_tokens(monkeypatch):
    # The exact bug: ENVIRONMENT != "development" used to pick RS256 and explode.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(auth_service, "settings", settings)
    token = auth_service.create_user_token(
        user_id="00000000-0000-0000-0000-000000000001",
        org_id="00000000-0000-0000-0000-000000000002",
        role="analyst",
        permissions=[],
    )
    assert auth_service.verify_token(token) is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python_service && pytest tests/test_auth_algorithm.py -v
```
Expected: FAIL — `auth_service.JWT_SECRET_KEY` is a random `os.urandom` value that will not equal `settings.JWT_SECRET_KEY`; `test_token_uses_configured_algorithm` fails because the header alg is `RS256`.

- [ ] **Step 3: Implement the fix**

Replace the config block at the top of `python_service/server/services/auth_service.py` (currently lines 17–29) with:

```python
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from passlib.context import CryptContext

from server.config import settings

# JWT configuration — SINGLE source of truth: server.config.settings.
# Do not re-read os.getenv here; that created a second source of truth whose
# defaults diverged from config.py (random key vs static string; RS256 vs HS256).
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM  # default "HS256"; see config.py
USER_TOKEN_EXPIRE_HOURS = settings.USER_TOKEN_EXPIRE_HOURS
CLIENT_TOKEN_EXPIRE_DAYS = settings.CLIENT_TOKEN_EXPIRE_DAYS

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

Then delete the ENVIRONMENT-based algorithm selection in all three functions. In `create_user_token`, `create_client_token`, and `verify_token`, replace:

```python
    algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=algorithm)
```

with:

```python
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
```

and in `verify_token` replace the matching `algorithm = ...` + `algorithms=[algorithm]` line with:

```python
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
```

Remove the now-unused `import os` at the top of the file if nothing else uses it (grep `os\.` in the file first).

Update the module docstring "Algorithm selection" section (lines 11–16) to:

```
Algorithm
---------
The signing algorithm is ``settings.JWT_ALGORITHM`` (default ``HS256``, a
symmetric algorithm keyed by ``settings.JWT_SECRET_KEY``). To use an
asymmetric algorithm such as RS256, set ``JWT_ALGORITHM=RS256`` and supply an
RSA key pair via configuration — this is intentionally NOT auto-selected, and
the previous ENVIRONMENT-based auto-switch to RS256 (which had no key pair and
broke token issuance) has been removed.
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python_service && pytest tests/test_auth_algorithm.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full auth suite to confirm no regression**

```bash
cd python_service && pytest tests/test_auth_api.py tests/test_auth_service.py tests/test_auth_middleware.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python_service/server/services/auth_service.py python_service/tests/test_auth_algorithm.py
git commit -m "$(cat <<'EOF'
fix(auth): unify JWT config and remove broken RS256 auto-selection

auth_service read JWT_SECRET_KEY/JWT_ALGORITHM directly from env, ignoring
server.config.settings (two sources of truth, divergent defaults), and
hardcoded RS256 whenever ENVIRONMENT != development — with no RSA key pair
configured, production could not issue any token. Algorithm now comes solely
from settings.JWT_ALGORITHM (default HS256).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Give the distributed C/S server a dedicated port (8091) and document the dual-stack boundary

**Why:** `python_service/server/config.py:35` defaults `PORT` to 8090, which collides with the legacy `python_service/httpserver` (`config.py:133`, also 8090). Dual-stack means both must be runnable at once.

**Files:**
- Modify: `python_service/server/config.py:33-35`
- Modify: `.env.example`
- Test: `python_service/tests/test_config_port.py` (create)

**Interfaces:**
- Produces: `settings.PORT == 8091` by default. Client `server_base_url` is configured per-deployment (`TRACELENS_SERVER_URL` / agent.conf), so no client code change is required — only docs.

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/test_config_port.py`:

```python
"""The distributed C/S server must not collide with the legacy httpserver
port (both defaulted to 8090). Dual-stack coexistence requires a dedicated port."""
from server.config import settings


def test_distributed_server_default_port_is_8091():
    assert settings.PORT == 8091


def test_port_overridable_by_env(monkeypatch):
    # Operators may still override; the default just must not be 8090.
    monkeypatch.setattr(settings, "PORT", 8099)
    assert settings.PORT == 8099
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python_service && pytest tests/test_config_port.py -v
```
Expected: FAIL — `settings.PORT == 8090`.

- [ ] **Step 3: Change the default port**

In `python_service/server/config.py`, replace lines 33–35:

```python
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8090"))
```

with:

```python
    # Server (distributed C/S backend).
    # Port 8091, NOT 8090: the legacy python_service/httpserver (LLM/graphiti
    # proxy for the local-mode C++ 8080 server) already owns 8090. Dual-stack
    # deployments run both simultaneously; see the port map in
    # docs/superpowers/plans/2026-07-27-cs-integration-hardening.md.
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8091"))
```

- [ ] **Step 4: Document in .env.example**

Append a clearly-labelled block to `.env.example`:

```env
# ── Distributed C/S server (python_service/server) ──────────────────────────
# Runs on its own port (8091) so it can coexist with the local-mode stack
# (C++ forensic_analyzer :8080 + legacy httpserver :8090).
PORT=8091
JWT_SECRET_KEY=change-this-in-production
JWT_ALGORITHM=HS256
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tracelens
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd python_service && pytest tests/test_config_port.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python_service/server/config.py .env.example python_service/tests/test_config_port.py
git commit -m "$(cat <<'EOF'
feat(server): default distributed C/S port to 8091 to avoid httpserver collision

The new python_service/server and the legacy python_service/httpserver both
defaulted to 8090. Dual-stack coexistence requires the distributed server to
use a dedicated port; documented the boundary in .env.example.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Wire the distributed server into the launch scripts with a health gate

**Why:** No launch script starts `python_service/server` — it is only imported by pytest. Distributed mode cannot run without it.

**Files:**
- Modify: `scripts/start_all_services.sh`
- Modify: `scripts/diagnose_services.sh`

**Interfaces:**
- Consumes: `settings.PORT` (8091), `GET /health` (defined at `server/main.py:126`).
- Produces: a running `python_service/server` on 8091 after `start_all_services.sh` succeeds, gated on `/health`.

> Note: this task has no unit test (it is shell orchestration). Verification is the manual health-check in Step 4.

- [ ] **Step 1: Read the existing launch structure**

```bash
grep -n 'httpserver\|CPP_PORT\|WEB_PORT\|python_service\|wait_for\|health' scripts/start_all_services.sh
```
Identify the function used to wait for a port / health endpoint (reuse the existing pattern rather than inventing one).

- [ ] **Step 2: Add the distributed-server launch block**

In `scripts/start_all_services.sh`, add a new block **after** the legacy httpserver block (keep that block intact — dual-stack). Mirror the existing httpserver launch style. The block must:
1. `cd` into `python_service` (so `python -m server.main` resolves the package, matching how `python -m httpserver.main` is launched at line 199).
2. Start `$PYTHON_EXEC -m server.main` on `PORT` (default 8091), redirecting logs to `$LOG_DIR/cs_server.log`.
3. Poll `http://localhost:${CS_PORT:-8091}/health` until it returns JSON containing `"healthy"` or a timeout (~30s) elapses.
4. On timeout, print the tail of `cs_server.log` and continue (do not abort the whole script — the local stack may still be useful).

Sketch (adapt variable names to match the existing script):

```bash
CS_PORT="${CS_PORT:-8091}"
log "Starting distributed C/S server on :${CS_PORT} ..."
( cd python_service && $PYTHON_EXEC -m server.main ) > "$LOG_DIR/cs_server.log" 2>&1 &

# Health gate
for i in $(seq 1 30); do
    if curl -fs "http://localhost:${CS_PORT}/health" | grep -q '"healthy"'; then
        log "C/S server healthy on :${CS_PORT}"
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        warn "C/S server did not become healthy; see $LOG_DIR/cs_server.log"
        tail -n 40 "$LOG_DIR/cs_server.log" || true
    fi
done
```

- [ ] **Step 3: Add a probe to diagnose_services.sh**

In `scripts/diagnose_services.sh`, add a check for 8091 alongside the existing 8080/8090 probes:

```bash
probe_http "distributed C/S server" "http://localhost:${CS_PORT:-8091}/health"
```
(Use the existing `probe_http`/echo helper already in that file; grep for it first.)

- [ ] **Step 4: Manual verification (requires PostgreSQL running)**

```bash
# Ensure a Postgres tracelens DB exists, then:
./scripts/start_all_services.sh
curl -s http://localhost:8091/health
# Expected: {"status":"healthy","app":"TraceLens Server","version":"1.0.0"}
curl -s http://localhost:8091/
# Expected: {"message":"TraceLens Server API","version":"1.0.0","docs":"/docs"}
```

- [ ] **Step 5: Commit**

```bash
git add scripts/start_all_services.sh scripts/diagnose_services.sh
git commit -m "$(cat <<'EOF'
feat(ops): launch distributed C/S server (:8091) with a health gate

start_all_services.sh previously started only the C++ 8080 server and the
legacy httpserver; python_service/server was unreachable outside pytest. It is
now started on 8091 (additive — local stack untouched) and gated on /health.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1 — 打通端到端 (close the loop)

### Task 4: Add a real `task_id` FK to `command_queue`

**Why:** `command_queue` has no `task_id` column; the link to `analysis_tasks` lives only inside the `parameters` JSONB (`task_orchestrator.py:125`). There is no referential integrity, and cancel has to filter on `parameters->>'task_id'`.

**Files:**
- Create: `migrations/postgresql/002_command_task_fk.sql`
- Modify: `python_service/server/models/database.py` (the `CommandQueue` class, ~lines 183–230) and `AnalysisTask` (add back-ref)
- Test: `python_service/tests/test_command_task_fk.py` (create)

**Interfaces:**
- Consumes: the existing `parameters["task_id"]` soft link to backfill.
- Produces: `CommandQueue.task_id` (nullable UUID FK → `analysis_tasks.id`, `ON DELETE CASCADE`), `CommandQueue.task` relationship, `AnalysisTask.commands` back-reference. Later tasks rely on `command.task_id` existing.

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/test_command_task_fk.py`:

```python
"""Task 4: command_queue.task_id is a real FK, not just a JSONB soft link."""
import uuid

from sqlalchemy import inspect

from server.models.database import AnalysisTask, CommandQueue


def test_command_queue_has_task_id_column():
    cols = {c.name for c in inspect(CommandQueue).columns}
    assert "task_id" in cols


def test_command_queue_has_task_relationship():
    rels = {r.key for r in inspect(CommandQueue).relationships}
    assert "task" in rels


def test_task_has_commands_backref():
    rels = {r.key for r in inspect(AnalysisTask).relationships}
    assert "commands" in rels


def test_deleting_a_task_cascades_to_its_command(db_session, org_and_client):
    """ON DELETE CASCADE must remove a command when its task is deleted.

    Tests the FK constraint at the DB level only — rows inserted directly, no
    orchestrator involved (the orchestrator wiring that sets task_id on create
    is Task 5). Requires the test DB to enforce foreign keys (PostgreSQL)."""
    org, client, disk_image, user = org_and_client
    task = AnalysisTask(
        id=uuid.uuid4(), org_id=org.id, client_id=client.id,
        disk_image_id=disk_image.id, task_name="cascade-test",
        analysis_type="full", status="in_progress",
    )
    db_session.add(task)
    db_session.flush()
    cmd = CommandQueue(
        id=uuid.uuid4(), client_id=client.id, user_id=user.id,
        command_type="analyze_disk", parameters={"image_path": "/tmp/x.raw"},
        priority=0, status="in_progress", task_id=task.id,
    )
    db_session.add(cmd)
    db_session.commit()
    cmd_id = cmd.id
    db_session.delete(task)
    db_session.commit()
    assert db_session.query(CommandQueue).filter_by(id=cmd_id).first() is None
```

> The `db_session` and `org_and_client` fixtures: check `python_service/tests/conftest.py` for an existing DB session fixture. **It must use PostgreSQL, not SQLite** — `parameters` is JSONB and the cascade test relies on a real `ON DELETE CASCADE` (SQLite does not enforce FKs by default, and JSONB ≠ JSON). The existing suite already runs against Postgres per migration 001. If a `db_session` fixture does not exist yet, add a minimal one to `conftest.py` that points `DATABASE_URL` at a throwaway Postgres DB, builds the schema via `Base.metadata.create_all`, and inserts an `Organization`, `Client`, `DiskImage`, and `User`. (This is a fixture, not the task's deliverable — keep it small.)

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python_service && pytest tests/test_command_task_fk.py -v
```
Expected: FAIL — `task_id` not in columns; relationships missing; the cascade test errors because the column does not yet exist. (The orchestrator's `create_analysis_task` setting `task_id` is verified in Task 5, not here.)

- [ ] **Step 3: Write the migration**

Create `migrations/postgresql/002_command_task_fk.sql`:

```sql
-- Migration 002: promote the task_id soft link (parameters->>'task_id') to a
-- real FK column with referential integrity and cascade delete.
-- Idempotent: safe to re-run.

ALTER TABLE command_queue
    ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE;

-- Backfill from the existing JSONB soft link for in-flight rows.
UPDATE command_queue
   SET task_id = (parameters->>'task_id')::uuid
 WHERE task_id IS NULL
   AND parameters ? 'task_id'
   AND parameters->>'task_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

CREATE INDEX IF NOT EXISTS idx_command_queue_task ON command_queue(task_id);
```

- [ ] **Step 4: Update the ORM model**

In `python_service/server/models/database.py`, inside the `CommandQueue` class, add the column + relationship (place the column near `client_id`/`user_id`):

```python
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_tasks.id", ondelete="CASCADE"),
        nullable=True,  # nullable: health_check / extract_file commands need no task
    )
```

and add the relationship:

```python
    client = relationship("Client", back_populates="commands")
    task = relationship("AnalysisTask", back_populates="commands")
```

In the `AnalysisTask` class, add the back-reference (place near its other relationships):

```python
    commands = relationship("CommandQueue", back_populates="task")
```

- [ ] **Step 5: Run the task-4 tests to verify they pass**

```bash
cd python_service && pytest tests/test_command_task_fk.py -v
```
Expected: PASS (4 tests: 3 model-introspection + 1 direct-insert cascade). The three introspection tests need no DB; the cascade test uses the `db_session` fixture.

- [ ] **Step 6: Commit the model/migration (orchestrator wiring is Task 5)**

```bash
git add migrations/postgresql/002_command_task_fk.sql python_service/server/models/database.py python_service/tests/test_command_task_fk.py
git commit -m "$(cat <<'EOF'
feat(db): add command_queue.task_id FK (migration 002)

The task↔command link previously lived only in parameters JSONB with no
referential integrity. Added a real task_id FK (ON DELETE CASCADE) plus an
index, and backfilled existing rows from the JSONB soft link.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Use the FK in the orchestrator and the command→task propagation

**Why:** Now that `task_id` is a column, stop parsing JSONB to find a command's task. Also move `_propagate_command_status_to_task` out of the route file (`api/commands.py:64`) into the service layer (P2 leak, but it touches the same code — fold it in here).

**Files:**
- Modify: `python_service/server/services/task_orchestrator.py` (~lines 125–144 create, ~390–394 cancel)
- Modify: `python_service/server/services/command_queue.py` (add a `propagate_command_status` method)
- Modify: `python_service/server/api/commands.py:64-141, 195` (call the service method)
- Test: extend `python_service/tests/test_command_task_fk.py` + `python_service/tests/test_task_orchestrator.py`

**Interfaces:**
- Consumes: `CommandQueue.task_id` (Task 4).
- Produces: `CommandQueueService.propagate_command_status(db, command) -> None` — the route calls this instead of inlining the logic.

- [ ] **Step 1: Write the failing tests**

Append to `python_service/tests/test_command_task_fk.py`:

```python
def test_command_inherits_task_id_when_created_via_orchestrator(db_session, org_and_client):
    """Creating a task must stamp the spawned command's task_id column."""
    from server.services.task_orchestrator import TaskOrchestrator

    org, client, disk_image, user = org_and_client
    task = TaskOrchestrator.create_analysis_task(
        db=db_session,
        org_id=org.id,
        client_id=client.id,
        user_id=user.id,
        disk_image_id=disk_image.id,
        task_name="fk-test",
        analysis_type="full",
    )
    cmd = db_session.query(CommandQueue).filter_by(task_id=task.id).one()
    assert cmd.task_id == task.id
    # JSONB soft link kept for one release as backward-compat; column is authoritative.
    assert cmd.parameters["task_id"] == str(task.id)


def test_cancel_task_fails_its_command_via_fk(db_session, org_and_client):
    from server.models.database import CommandStatus
    from server.services.task_orchestrator import TaskOrchestrator

    org, client, disk_image, user = org_and_client
    task = TaskOrchestrator.create_analysis_task(
        db=db_session, org_id=org.id, client_id=client.id, user_id=user.id,
        disk_image_id=disk_image.id, task_name="cancel-test", analysis_type="full",
    )
    TaskOrchestrator.cancel_task(db_session, task_id=task.id, org_id=org.id)
    cmd = db_session.query(CommandQueue).filter_by(task_id=task.id).one()
    assert cmd.status == "failed"


def test_propagate_uses_task_id_column_not_jsonb(db_session, org_and_client):
    """A command whose parameters lack task_id must still resolve its task
    via the task_id column."""
    from server.services.command_queue import CommandQueueService

    org, client, disk_image, user = org_and_client
    from server.services.task_orchestrator import TaskOrchestrator
    task = TaskOrchestrator.create_analysis_task(
        db=db_session, org_id=org.id, client_id=client.id, user_id=user.id,
        disk_image_id=disk_image.id, task_name="prop-test", analysis_type="full",
    )
    cmd = db_session.query(CommandQueue).filter_by(task_id=task.id).one()
    cmd.parameters = {k: v for k, v in cmd.parameters.items() if k != "task_id"}  # strip JSONB
    db_session.flush()
    CommandQueueService.propagate_command_status(db_session, cmd, "completed", 100, "ok")
    db_session.refresh(task)
    assert task.status == "completed"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd python_service && pytest tests/test_command_task_fk.py -v
```
Expected: the three new tests FAIL (orchestrator doesn't set `task_id` column on create; cancel still filters JSONB; `propagate_command_status` doesn't exist).

- [ ] **Step 3: Set `task_id` in the orchestrator on create**

In `python_service/server/services/task_orchestrator.py`, where the `CommandQueue` row is built (~line 125–144), add `task_id=task.id` to the constructor kwargs (keep `parameters["task_id"]` for one release as backward-compat for any in-flight client). After creation the command must have `cmd.task_id == task.id`.

- [ ] **Step 4: Cancel via FK**

In `TaskOrchestrator.cancel_task` (~line 390–394), replace the JSONB filter:

```python
    db.query(CommandQueue).filter(
        CommandQueue.parameters["task_id"].astext == str(task.id)
    )
```

with:

```python
    db.query(CommandQueue).filter(CommandQueue.task_id == task.id)
```

- [ ] **Step 5: Move propagation into the service**

Add to `python_service/server/services/command_queue.py` a method that resolves the task via `command.task_id` (falling back to JSONB only if the column is NULL, for rows older than the migration):

```python
    @staticmethod
    def propagate_command_status(db, command, status, progress=None, message=None):
        """Bridge a command status update to its owning analysis task.

        Resolves the task via the task_id FK column (authoritative); falls back
        to the legacy parameters->>'task_id' soft link only for pre-migration rows.
        Scopes the task lookup by command.client_id as defense-in-depth against
        a forged task_id planted in a command's parameters.
        """
        from server.models.database import AnalysisTask

        tid = command.task_id or command.parameters.get("task_id")
        if not tid:
            return  # health_check / extract_file have no owning task
        task = (
            db.query(AnalysisTask)
            .filter_by(id=tid, client_id=command.client_id)
            .first()
        )
        if task is None:
            return
        if status == "in_progress":
            TaskOrchestrator.update_task_progress(db, task_id=task.id, org_id=task.org_id, progress=progress or 0)
        elif status in ("completed", "failed"):
            TaskOrchestrator.complete_task(db, task_id=task.id, org_id=task.org_id, success=(status == "completed"), message=message)
```

(Adjust the `TaskOrchestrator.*` call signatures to match the real ones — `grep -n 'def update_task_progress\|def complete_task' python_service/server/services/task_orchestrator.py`.)

- [ ] **Step 6: Thin the route**

In `python_service/server/api/commands.py`, replace the body of `_propagate_command_status_to_task` (lines 64–141) and the call site (line ~195) with a single call:

```python
    CommandQueueService.propagate_command_status(db, command, body.status, body.progress, body.message)
```

Delete the now-unused module-level `_propagate_command_status_to_task` function entirely.

- [ ] **Step 7: Run all affected tests**

```bash
cd python_service && pytest tests/test_command_task_fk.py tests/test_task_orchestrator.py tests/test_commands_api.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add python_service/server/services/task_orchestrator.py python_service/server/services/command_queue.py python_service/server/api/commands.py python_service/tests/test_command_task_fk.py
git commit -m "$(cat <<'EOF'
refactor(server): resolve task via task_id FK, move propagation to service

Orchestrator now stamps command.task_id on create and cancels by FK instead of
filtering parameters JSONB. command→task propagation moved out of the commands
route into CommandQueueService.propagate_command_status (resolves via the FK,
falls back to JSONB only for pre-migration rows).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Web frontend — distributed-mode API client and services

**Why:** The web UI has zero calls into the new C/S server (`grep '/api/commands|/api/results|/api/clients|/api/auth' web/src` is empty). `taskService.js` targets the C++ 8080 server. Dual-stack needs a second client for 8091 without removing the local-mode one.

**Files:**
- Modify: `web/src/services/api.js`
- Modify: `web/vite.config.js`
- Create: `web/src/services/csAuthService.js`, `web/src/services/csClientService.js`, `web/src/services/csTaskService.js`

> No JS unit-test runner exists in this repo. Verification is the integration check in Step 5 (curl + browser). If a test harness is desired, it is a separate follow-up.

- [ ] **Step 1: Add the distributed-mode axios client**

In `web/src/services/api.js`, add alongside the existing `api`/`pythonApi`:

```js
// Distributed C/S server (python_service/server) — port 8091.
// Distinct from pythonApi (legacy httpserver :8090) and api (C++ :8080).
const CS_API_BASE_URL = import.meta.env.VITE_CS_API_URL || 'http://localhost:8091';

const csApi = axios.create({
  baseURL: CS_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

csApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('cs_auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
}, (error) => Promise.reject(error));

csApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('cs_auth_token');
    }
    return Promise.reject({
      message: error.message,
      status: error.response?.status,
      data: error.response?.data,
    });
  },
);

export { pythonApi, csApi };
export default api;
```

- [ ] **Step 2: Add the Vite proxy**

In `web/vite.config.js`, add a `/csapi` proxy entry mirroring the existing proxy block, targeting `http://localhost:8091`, rewriting `/csapi` → `''`.

- [ ] **Step 3: Create the distributed services**

`web/src/services/csAuthService.js`:

```js
import { csApi } from './api';

export const csLogin = (username, password) =>
  csApi.post('/api/auth/login', { username, password });

export const csRefresh = (token) =>
  csApi.post('/api/auth/refresh', {}, { headers: { Authorization: `Bearer ${token}` } });

export const csMe = () => csApi.get('/api/auth/me');
```

`web/src/services/csClientService.js`:

```js
import { csApi } from './api';

export const listClients = (params = {}) => csApi.get('/api/clients', { params });
export const getClient = (clientId) => csApi.get(`/api/clients/${clientId}`);
```

`web/src/services/csTaskService.js` (distributed task lifecycle — distinct from local `taskService.js`):

```js
import { csApi } from './api';

export const createDistributedTask = (taskData) => csApi.post('/api/tasks', taskData);
export const listDistributedTasks = (params = {}) => csApi.get('/api/tasks', { params });
export const getDistributedTask = (taskId) => csApi.get(`/api/tasks/${taskId}`);
export const cancelDistributedTask = (taskId) => csApi.post(`/api/tasks/${taskId}/cancel`);
```

> Confirm the exact distributed endpoints against `python_service/server/api/tasks.py` and `api/clients.py` before wiring UI pages (the agent report lists `POST /api/tasks/{id}/cancel`, `GET /api/clients`).

- [ ] **Step 4: Wire one smoke UI path (minimal)**

Add a "Distributed / 分布式" entry point (e.g., a new route or a button on the dashboard) that calls `csLogin` then `listClients`. Store the token under `cs_auth_token`. Keep it minimal — full page polish is out of scope for this task; the goal is to prove the 8091 path is reachable from the browser.

- [ ] **Step 5: Integration verification**

```bash
# 1. server up on 8091 (Task 3)
curl -s http://localhost:8091/health
# 2. proxy works through vite
cd web && npm run dev   # in another shell
curl -s http://localhost:5173/csapi/health   # proxied → 8091/health
# 3. login round-trip (create the seed super_admin first per migration 001)
curl -s -X POST http://localhost:8091/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"super_admin","password":"admin123"}'
```
Then in the browser at :5173, exercise the smoke path added in Step 4 and confirm a client list renders (or an empty list, not a network/CORS error).

- [ ] **Step 6: Commit**

```bash
git add web/src/services/api.js web/vite.config.js web/src/services/csAuthService.js web/src/services/csClientService.js web/src/services/csTaskService.js
git commit -m "$(cat <<'EOF'
feat(web): add distributed C/S API client and services (:8091)

The web frontend only talked to the local-mode C++ 8080 server and the legacy
httpserver. Added a dedicated csApi client for the distributed server on 8091
(auth/clients/tasks services), with a /csapi vite proxy. Local-mode services
are untouched (dual-stack).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: DB-artifact contract — server must not assume fixed DB filenames

**Why:** DB-output naming is triplicated. `PathManager::getTaskDbPaths` (`src/core/PathManager/PathManager.cpp:98`) expects fixed names (`raw.db`, `events.db`...), but `AnalysisOrchestrator.cpp:176` actually writes `<baseName>_raw.db`, and the client globs `<baseName>*.db` (`command_executor.cpp:101`). If the distributed server ever ingests client DBs by PathManager's fixed names, it will not find them. The client already sends `result_metadata.base_name` (`command_executor.cpp:121`) — make the server honor it and document the contract.

**Files:**
- Modify: `python_service/server/services/result_aggregator.py` (ensure `base_name` is stored in `AnalysisResult.result_metadata`)
- Modify: `docs/api_reference/Python_REST_API.md` (document the artifact contract)
- Test: `python_service/tests/test_result_aggregator.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `python_service/tests/test_result_aggregator.py` a test that uploads an artifact whose `file_path` is an arbitrary `<baseName>_files.db` and asserts the stored `AnalysisResult.result_metadata["base_name"]` equals that base, and that the row is accepted regardless of the DB's literal filename:

```python
def test_result_artifact_base_name_is_preserved(db_session, task_and_client):
    task, client = task_and_client
    from server.services.result_aggregator import ResultAggregator

    artifacts = [{
        "result_type": "database",
        "file_path": "/evidence/work/case7_files.db",   # arbitrary name
        "file_size": 4096,
        "storage_location": str(client.hostname),
        "result_metadata": {"base_name": "case7"},
    }]
    rows = ResultAggregator.store_results(
        db=db_session, task_id=task.id, client_id=client.id, artifacts=artifacts,
    )
    assert len(rows) == 1
    assert rows[0].result_metadata["base_name"] == "case7"
```

- [ ] **Step 2: Run to verify failure (or pass if already correct)**

```bash
cd python_service && pytest tests/test_result_aggregator.py -v
```
If it already passes, the contract holds — skip to documenting it (Step 3) and still commit the test.

- [ ] **Step 3: Document the contract**

In `docs/api_reference/Python_REST_API.md`, add a section "Artifact upload contract" stating: the server stores DB artifacts by reference only (`file_path`, `storage_location`, `result_metadata.base_name`); it MUST NOT assume PathManager's fixed filenames (`raw.db`/`events.db`/`files.db`); clients may name outputs `<baseName>_<kind>.db` and always send `base_name`. Note that PathManager's fixed-name convention is local-mode-only (C++ 8080 in-process) and does not apply to the distributed path.

- [ ] **Step 4: Commit**

```bash
git add python_service/server/services/result_aggregator.py python_service/tests/test_result_aggregator.py docs/api_reference/Python_REST_API.md
git commit -m "$(cat <<'EOF'
feat(server): preserve artifact base_name, document DB artifact contract

DB output naming is triplicated (PathManager fixed names vs analyzer
<baseName>_<kind>.db vs client glob). The distributed server stores artifacts
by reference only and now explicitly preserves base_name; documented that it
must not assume PathManager's local-mode fixed filenames.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2–4 — follow-up plan outlines (each becomes its own plan)

These are recorded here so the roadmap is complete, but each is an independent subsystem and should be expanded into a dedicated plan before execution (per the writing-plans scope rule).

### Phase 2 — client capability hardening (C++ / GTest)
- **2.1 Concurrency:** decouple poll from execute. Add a worker thread (bounded by `capabilities.max_concurrent_tasks`) so a multi-hour `analyze_disk` no longer blinds the poller. Touches `http_agent_service.cpp`, new `executor_pool`. GTest: two commands run concurrently; poll still advances during execution.
- **2.2 Progress reporting:** analyzer writes progress to a file the agent tails → `StatusReporter` POSTs `progress` periodically. GTest: at least one intermediate `in_progress` with `progress>0` for a long run.
- **2.3 `recover()` correctness:** verify the work dir's DB artifacts exist before reporting `failed`; only then report the prior status. Validate `reindex_interval_seconds > 0` in `ClientConfig::validate`.

### Phase 3 — server tidy-up (Python / pytest)
- **3.1 Route→service:** move `register_client` and `index_disk_images` (`api/clients.py:61,296`) into a `ClientService`; move presence stamping (`commands.py:189`) fully into `CommandQueueService`.
- **3.2 RBAC:** implement `require_permission` (`middleware/auth.py:144`); move `get_permissions_for_role` (`api/auth.py:134`) into `auth_service`.
- **3.3 Dead code:** wire or remove `ResultAggregator.store_llm_analysis` (`:182`); collapse `store_result` into `store_results`; make status enums (`CommandStatus` etc.) the actual column type instead of dead `String`; decide on `clients.jwt_secret` (use it for per-client signing, or drop the column + migration 003).
- **3.4 Config discipline:** audit for any remaining direct `os.getenv` reads outside `config.py`.

### Phase 4 — legacy/dual-stack boundary hardening (ops)
- **4.1** Make `start_all_services.sh` mode-aware (`--local` / `--distributed` / `--all`) so the two stacks can be started independently.
- **4.2** Decide `httpserver` (LLM/graphiti) fate: fold into the distributed server, or pin to 8090 permanently and document.
- **4.3** Add a top-level architecture note to `docs/architecture/Overview.md` describing the dual-stack port map and which features belong to which mode.

---

## Self-Review (run before handing off)

**1. Spec coverage (the review findings):**
- P0-1 server not wired → Task 3 ✓
- P0-2 8090 collision → Task 2 ✓
- P0-3 web frontend not migrated → Task 6 ✓
- P0-4 broken production auth → Task 1 ✓
- P1-1 single-threaded client → Phase 2.1 (outlined) ✓
- P1-2 Task↔Command no FK → Tasks 4 & 5 ✓
- P1-3 triplicated DB paths → Task 7 (contract) + documented ✓
- P2 route leaks / dead code → Phase 3 (outlined) ✓
- P3 client minors → Phase 2.3 (outlined) ✓

**2. Placeholder scan:** no TBD/TODO/"add error handling". Steps without inline code are shell edits (Task 3) or JS without a runner (Task 6), and each names exact files/lines + a concrete verification step. The one place signatures must be confirmed (`TaskOrchestrator.update_task_progress`/`complete_task`) gives the exact grep command to resolve them.

**3. Type/name consistency:** `CommandQueue.task_id` / `.task` and `AnalysisTask.commands` are used identically in Tasks 4, 5, and 7. `propagate_command_status(db, command, status, progress, message)` matches across Task 5's definition and call site. `csApi` / `cs_auth_token` / `VITE_CS_API_URL` are consistent across Task 6 steps.

**Caveat for the implementer:** Tasks 4–5 touch DB shape. Run `migrations/postgresql/002_command_task_fk.sql` against the `tracelens` database before the orchestrator tests (which rely on the column). The existing tests in `python_service/tests/test_*.py` import `server.main.app` and assume a live PostgreSQL — confirm `DATABASE_URL` points at a DB with migration 001 + 002 applied.
