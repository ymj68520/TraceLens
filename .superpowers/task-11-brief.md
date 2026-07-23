### Task 11: Implement Command Queue API Endpoints

**Files:**
- Create: `python_service/server/api/commands.py`
- Modify: `python_service/server/main.py` (mount router)
- Create: `python_service/tests/test_commands_api.py`

**Interfaces:**
- Consumes: Command queue service from Task 10
- Produces: Command queue API endpoints

---

## PITFALLS SPOTTED DURING EXTRACTION (resolve when implementing)

1. **`datetime.utcnow()` in `poll_commands`** (brief L3803: `current_client.last_poll = datetime.utcnow()`).
   → Must be `datetime.now(timezone.utc)`. NOTE: this *confirms* Task 10's forward
   observation — the poll endpoint DOES stamp `last_poll` before calling
   `get_commands_for_client`, so the online/offline coupling resolves here.

2. **`CommandQueue` NameError in `update_command_status` endpoint** (brief L3835 uses
   `db.query(CommandQueue)` but `CommandQueue` is only imported locally inside
   `get_command`/`list_client_commands`, NOT in `update_command_status`'s scope).
   → Import `CommandQueue` (and `Client`) at MODULE level; drop the redundant
   local imports.

3. **Cross-tenancy hole in `create_command` endpoint** (brief L3757-3784): the endpoint
   calls the service which only checks the client *exists* — any authenticated user can
   enqueue a command against ANOTHER org's client. No org-scope check.
   → Add an org-scope check before calling the service: fetch the client, require
   `current_user.role == "super_admin" or current_user.org_id == client.org_id`
   (else 403). Matches the pattern in `clients.py` get_client/delete_client.

4. **Brief tests use live DB (`SessionLocal`, real `/api/auth/login`)** — won't run
   (PostgreSQL-native JSONB/UUID, no DB in test env).
   → Convert to mock-DB + dependency-override pattern (auth_as/client_as) as in
   `tests/test_clients_api.py`. Override `get_current_user`/`get_current_client` and
   `get_db`.

5. **`main.py` wiring style** — brief uses `from server.api import ... commands` +
   `app.include_router(commands.router, tags=[...])`. Existing `main.py` uses
   `from server.api.X import router as X_router` + `app.include_router(X_router)`
   (routers declare own prefix/tags). → Follow EXISTING main.py style.

6. **`get_command`/`list_client_commands` org check** assumes `client` is non-None after
   the command lookup. For `get_command`, `command.client_id` is FK-constrained so the
   client should exist, but guard against None → 500. Minor.

7. **`update_command_status` double-query**: endpoint queries the command to check
   ownership, then the service queries it again. Acceptable (mock-friendly); keep.

---

## Step 1: commands API (brief verbatim)

Write to `python_service/server/api/commands.py`:

```python
"""
Command queue API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import datetime

from server.db.session import get_db
from server.models.database import User
from server.models.schemas import (
    CommandCreate, CommandResponse, CommandPollResponse,
    TaskStatusUpdate
)
from server.services.command_queue import CommandQueueService
from server.middleware.auth import get_current_user, get_current_client
from server.models.database import Client

router = APIRouter(prefix="/api/commands", tags=["Commands"])


@router.post("", response_model=CommandResponse)
async def create_command(
    command_data: CommandCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new command for a client."""
    try:
        command = CommandQueueService.create_command(command_data, current_user.id, db)
        return command
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/poll", response_model=CommandPollResponse)
async def poll_commands(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """Client endpoint to poll for pending commands."""
    current_client.last_poll = datetime.utcnow()       # PITFALL #1
    db.commit()
    response = CommandQueueService.get_commands_for_client(current_client.id, db)
    return response


@router.post("/{command_id}/status")
async def update_command_status(
    command_id: uuid.UUID,
    status_update: TaskStatusUpdate,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """Client endpoint to update command status."""
    command = db.query(CommandQueue).filter(           # PITFALL #2: CommandQueue not in scope
        CommandQueue.id == command_id
    ).first()
    if not command:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")
    if command.client_id != current_client.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    try:
        CommandQueueService.update_command_status(
            command_id, status_update.status, status_update.message, db
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"updated": True}


@router.get("/{command_id}", response_model=CommandResponse)
async def get_command(
    command_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get command details."""
    from server.models.database import CommandQueue, Client     # hoist (pitfall #2)
    command = db.query(CommandQueue).filter(CommandQueue.id == command_id).first()
    if not command:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")
    client = db.query(Client).filter(Client.id == command.client_id).first()
    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return command


@router.get("/client/{client_id}", response_model=List[CommandResponse])
async def list_client_commands(
    client_id: uuid.UUID,
    status_filter: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List commands for a client."""
    from server.models.database import CommandQueue, Client     # hoist (pitfall #2)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    query = db.query(CommandQueue).filter(CommandQueue.client_id == client_id)
    if status_filter:
        query = query.filter(CommandQueue.status == status_filter)
    commands = query.order_by(CommandQueue.created_at.desc()).all()
    return commands


@router.post("/expire")
async def trigger_expiration(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger command expiration check (admin only)."""
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    expired_count = CommandQueueService.expire_commands(db)
    return {"expired_commands": expired_count}
```

## Endpoints summary
- `POST /api/commands` — create command (user-auth) [ADD org-scope check — pitfall #3]
- `GET  /api/commands/poll` — client poll (client-auth); stamps last_poll, returns pending
- `POST /api/commands/{command_id}/status` — client reports status (client-auth, ownership-checked)
- `GET  /api/commands/{command_id}` — get command (user-auth, org-scoped)
- `GET  /api/commands/client/{client_id}` — list a client's commands (user-auth, org-scoped)
- `POST /api/commands/expire` — trigger expiration (super_admin only)

## Step 2: main.py — follow EXISTING style (pitfall #5)
```python
from server.api.commands import router as commands_router
# ...
app.include_router(commands_router)
```

## Step 3-5: tests (convert to mock-DB — pitfall #4), run, commit
