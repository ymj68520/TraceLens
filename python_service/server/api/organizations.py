"""
Organization and registration token management APIs.

Exposes endpoints for tenant (organization) lifecycle and for issuing the
registration tokens that forensic clients present to enroll themselves into an
organization.

Access control
--------------
Super admins can see and act across all organizations. Any other role is scoped
to its own organization (``current_user.org_id``): reads/writes that target a
different organization are rejected with ``403 Access denied``. Mutating
endpoints additionally require a permission via
:func:`server.middleware.auth.require_permission`:

* ``create_organizations`` - create an organization
* ``create_clients``        - issue a registration token
* ``manage_clients``        - delete a registration token
"""
from datetime import datetime, timedelta, timezone

import secrets
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.middleware.auth import get_current_user, require_permission
from server.models.database import Organization, RegistrationToken, User
from server.models.schemas import (
    OrganizationCreate,
    OrganizationResponse,
    RegistrationTokenCreate,
    RegistrationTokenResponse,
)

router = APIRouter(prefix="/api/organizations", tags=["Organizations"])


@router.post("", response_model=OrganizationResponse)
async def create_organization(
    org_data: OrganizationCreate,
    current_user: User = Depends(require_permission("create_organizations")),
    db: Session = Depends(get_db),
):
    """
    Create a new organization.

    Args:
        org_data: Organization creation data
        current_user: Authenticated user with create_organizations permission
        db: Database session

    Returns:
        Created organization

    Raises:
        HTTPException: If organization name already exists
    """
    # Check if organization exists
    existing = db.query(Organization).filter(
        Organization.name == org_data.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization with this name already exists",
        )

    # Create organization
    org = Organization(**org_data.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)

    return org


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all organizations.

    Super admins see every organization; all other roles see only their own.

    Args:
        current_user: Authenticated user
        db: Database session

    Returns:
        List of organizations
    """
    # Super admins see all, others see only their own
    if current_user.role == "super_admin":
        organizations = db.query(Organization).all()
    else:
        organizations = db.query(Organization).filter(
            Organization.id == current_user.org_id
        ).all()

    return organizations


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get organization by ID.

    Args:
        org_id: Organization UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        Organization details

    Raises:
        HTTPException: If organization not found or access denied
    """
    # Check access
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return org


@router.post(
    "/{org_id}/registration-tokens",
    response_model=RegistrationTokenResponse,
)
async def create_registration_token(
    org_id: uuid.UUID,
    token_data: RegistrationTokenCreate,
    current_user: User = Depends(require_permission("create_clients")),
    db: Session = Depends(get_db),
):
    """
    Create a registration token for an organization.

    The token is a URL-safe random string a client presents during enrollment.
    It carries a max-client cap and an expiry computed from
    ``token_data.expires_in_hours``.

    Args:
        org_id: Organization UUID
        token_data: Token creation data
        current_user: Authenticated user with create_clients permission
        db: Database session

    Returns:
        Created registration token

    Raises:
        HTTPException: If organization not found or access denied
    """
    # Check access
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Verify organization exists
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    # Generate unique token
    token = secrets.token_urlsafe(32)

    # Calculate expiration. Use a timezone-aware UTC timestamp for consistency
    # with the rest of the auth stack (see server.services.auth_service) and to
    # keep comparisons with other aware timestamps well-defined.
    expires_at = datetime.now(timezone.utc) + timedelta(hours=token_data.expires_in_hours)

    # Create registration token
    reg_token = RegistrationToken(
        org_id=org_id,
        token=token,
        max_clients=token_data.max_clients,
        expires_at=expires_at,
        created_by=current_user.id,
    )
    db.add(reg_token)
    db.commit()
    db.refresh(reg_token)

    return reg_token


@router.get(
    "/{org_id}/registration-tokens",
    response_model=List[RegistrationTokenResponse],
)
async def list_registration_tokens(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List registration tokens for an organization.

    Args:
        org_id: Organization UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        List of registration tokens

    Raises:
        HTTPException: If access denied
    """
    # Check access
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    tokens = db.query(RegistrationToken).filter(
        RegistrationToken.org_id == org_id
    ).all()

    return tokens


@router.delete("/registration-tokens/{token_id}")
async def delete_registration_token(
    token_id: uuid.UUID,
    current_user: User = Depends(require_permission("manage_clients")),
    db: Session = Depends(get_db),
):
    """
    Delete a registration token.

    Args:
        token_id: Token UUID
        current_user: Authenticated user with manage_clients permission
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If token not found
    """
    token = db.query(RegistrationToken).filter(
        RegistrationToken.id == token_id
    ).first()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration token not found",
        )

    # Check access
    if current_user.role != "super_admin" and current_user.org_id != token.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    db.delete(token)
    db.commit()

    return {"message": "Registration token deleted"}
