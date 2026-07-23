"""
Client registration and management APIs.

Exposes the endpoints that govern the lifecycle of forensic clients:

* ``POST   /api/clients/register``              - enroll a new client via a
  registration token (returns the client id + a long-lived client JWT)
* ``GET    /api/clients``                        - list clients (users, scoped
  by role/org; a client sees only itself)
* ``GET    /api/clients/{client_id}``            - client details
* ``DELETE /api/clients/{client_id}``            - remove a client
* ``POST   /api/clients/{client_id}/index-images`` - a client reports its local
  disk-image inventory (metadata only; raw images never leave the client)
* ``GET    /api/clients/{client_id}/images``     - list a client's indexed images

Access control
--------------
``register`` is unauthenticated but gated by a valid registration token.
``index-images`` is client-authenticated (``get_current_client``) and a client
may only index for itself. The remaining endpoints are user-authenticated
(``get_current_user``): ``super_admin`` sees all orgs, other roles are scoped to
their own ``org_id``.

Datetime note
-------------
All "now" computations use timezone-aware UTC (``datetime.now(timezone.utc)``),
matching ``server.services.auth_service`` and the registration-token expiry set
in ``server.api.organizations``. Token expiry is compared against an aware
timestamp; registration tokens store their expiry the same way.
"""
from datetime import datetime, timezone

import secrets
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.config import settings
from server.db.session import get_db
from server.middleware.auth import get_current_client, get_current_user
from server.models.database import (
    Client,
    DiskImage,
    RegistrationToken,
    User,
)
from server.models.schemas import (
    ClientCredentialResponse,
    ClientRegister,
    ClientResponse,
    DiskImageCreate,
    DiskImageResponse,
)
from server.services.auth_service import create_client_token

router = APIRouter(prefix="/api/clients", tags=["Clients"])


@router.post("/register", response_model=ClientCredentialResponse)
async def register_client(
    registration_data: ClientRegister,
    db: Session = Depends(get_db),
):
    """
    Register a new client using a registration token.

    Args:
        registration_data: Client registration data (token, hostname, capabilities)
        db: Database session

    Returns:
        Client credentials (ID and JWT token)

    Raises:
        HTTPException: If token invalid, expired, max clients reached, or
            hostname already registered in the org
    """
    # Find and validate registration token
    token = db.query(RegistrationToken).filter(
        RegistrationToken.token == registration_data.registration_token
    ).first()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid registration token",
        )

    # Check token expiration (aware UTC comparison; see module docstring)
    if token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration token has expired",
        )

    # Check max clients
    if token.used_count >= token.max_clients:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration token has reached maximum client limit",
        )

    # Check if client already exists in this org with this hostname
    existing = db.query(Client).filter(
        Client.org_id == token.org_id,
        Client.hostname == registration_data.hostname,
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client with this hostname already exists",
        )

    # Generate client secret
    jwt_secret = secrets.token_urlsafe(32)

    # Create client
    client = Client(
        id=uuid.uuid4(),
        org_id=token.org_id,
        hostname=registration_data.hostname,
        registration_token=registration_data.registration_token,
        jwt_secret=jwt_secret,
        capabilities=registration_data.capabilities.model_dump(),
        status="offline",  # Will be marked online after first poll
    )

    db.add(client)

    # Update token usage
    token.used_count += 1

    db.commit()
    db.refresh(client)

    # Create JWT token for client
    capabilities = registration_data.capabilities.model_dump()
    client_token = create_client_token(client.id, client.org_id, capabilities)

    server_url = (
        f"https://{settings.HOST}"
        if settings.ENVIRONMENT == "production"
        else f"http://{settings.HOST}:{settings.PORT}"
    )

    return ClientCredentialResponse(
        client_id=client.id,
        jwt_token=client_token,
        poll_interval=settings.DEFAULT_POLL_INTERVAL,
        server_url=server_url,
    )


@router.get("", response_model=List[ClientResponse])
async def list_clients(
    org_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List clients.

    A client requesting its own record sees only itself. Users see clients
    scoped by role: ``super_admin`` may optionally filter by org; all other
    roles see only their own organization's clients.

    Args:
        org_id: Filter by organization (super_admin only)
        status_filter: Filter by status (online/offline/error)
        current_user: Authenticated user or client
        db: Database session

    Returns:
        List of clients
    """

    # Client requesting - return only themselves
    if isinstance(current_user, Client):
        return [current_user]

    # User requesting - scope by role
    if current_user.role == "super_admin":
        query = db.query(Client)
        if org_id:
            query = query.filter(Client.org_id == org_id)
    else:
        # org_admin / analyst / auditor all scoped to own org
        query = db.query(Client).filter(Client.org_id == current_user.org_id)

    if status_filter:
        query = query.filter(Client.status == status_filter)

    return query.all()


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get client details.

    Args:
        client_id: Client UUID
        current_user: Authenticated user or client
        db: Database session

    Returns:
        Client details

    Raises:
        HTTPException: If client not found or access denied
    """

    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    # Check access
    if isinstance(current_user, Client):
        # A client can only see itself
        if current_user.id != client_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
    elif isinstance(current_user, User):
        if current_user.role != "super_admin" and current_user.org_id != client.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

    return client


@router.delete("/{client_id}")
async def delete_client(
    client_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a client. Requires org_admin or super_admin role.

    Args:
        client_id: Client UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If insufficient permissions, client not found, or
            cross-org access denied
    """
    # Require an admin role
    if current_user.role not in ("super_admin", "org_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    # Check cross-org access
    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    db.delete(client)
    db.commit()

    return {"message": "Client deleted successfully"}


@router.post("/{client_id}/index-images")
async def index_disk_images(
    client_id: uuid.UUID,
    images: List[DiskImageCreate],
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Client indexes its local disk images (metadata only; raw images never leave
    the client machine).

    Args:
        client_id: Client UUID
        images: List of disk image metadata
        current_client: Authenticated client
        db: Database session

    Returns:
        Indexing result (indexed/updated/total counts)

    Raises:
        HTTPException: If a client attempts to index for a different client
    """
    # A client may only index images for itself
    if current_client.id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clients can only index images for themselves",
        )

    indexed_count = 0
    updated_count = 0

    for image_data in images:
        # Check if image already exists for this client at this path
        existing = db.query(DiskImage).filter(
            DiskImage.client_id == client_id,
            DiskImage.path == image_data.path,
        ).first()

        if existing:
            # Update existing. NOTE: the ORM exposes the ``metadata`` DB column
            # as ``image_metadata`` (``metadata`` is reserved by SQLAlchemy).
            existing.size_bytes = image_data.size_bytes
            existing.format = image_data.format
            existing.md5_hash = image_data.md5_hash
            existing.image_metadata = image_data.image_metadata
            existing.indexed_at = datetime.now(timezone.utc)
            updated_count += 1
        else:
            # model_dump() emits ``image_metadata`` (matching the ORM attr), so
            # it spreads cleanly into the DiskImage constructor.
            image = DiskImage(
                client_id=client_id,
                **image_data.model_dump(),
            )
            db.add(image)
            indexed_count += 1

    db.commit()

    return {
        "indexed": indexed_count,
        "updated": updated_count,
        "total": len(images),
    }


@router.get("/{client_id}/images", response_model=List[DiskImageResponse])
async def list_client_images(
    client_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List disk images indexed for a client.

    Args:
        client_id: Client UUID
        current_user: Authenticated user (this endpoint is user-authenticated via
            ``get_current_user``; clients do not reach it)
        db: Database session

    Returns:
        List of disk images

    Raises:
        HTTPException: If client not found or cross-org access denied
    """

    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    # Check access (users scoped by org; a client is allowed by get_current_user
    # only if it's the same client, enforced upstream)
    if isinstance(current_user, User):
        if current_user.role != "super_admin" and current_user.org_id != client.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

    return db.query(DiskImage).filter(DiskImage.client_id == client_id).all()
