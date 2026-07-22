"""
Authentication API endpoints.

Exposes the login, token-refresh, and current-user-info endpoints consumed by
platform clients. Authentication is delegated to the auth service
(:mod:`server.services.auth_service`, Task 4) and route protection to the
middleware (:mod:`server.middleware.auth`, Task 5).

Endpoints
---------
``POST /api/auth/login``
    OAuth2 password flow. Accepts form-encoded ``username`` / ``password``,
    verifies credentials, and returns a JWT ``TokenResponse``.

``POST /api/auth/refresh``
    Returns a fresh JWT for the calling authenticated user.

``GET /api/auth/me``
    Returns the authenticated user's profile.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.middleware.auth import get_current_user
from server.models.database import User
from server.models.schemas import TokenResponse, UserResponse
from server.services.auth_service import create_user_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Authenticate user and return JWT token.

    Args:
        form_data: OAuth2 form with username and password
        db: Database session

    Returns:
        Token response with access token

    Raises:
        HTTPException: If credentials invalid
    """
    # Find user by username (or email)
    user = db.query(User).filter(
        (User.username == form_data.username) | (User.email == form_data.username)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()

    # Create token
    permissions = get_permissions_for_role(user.role)
    token = create_user_token(user.id, user.org_id, user.role, permissions)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=3600,  # 1 hour
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(current_user: User = Depends(get_current_user)):
    """
    Refresh JWT token.

    Args:
        current_user: Authenticated user

    Returns:
        New token response
    """
    permissions = get_permissions_for_role(current_user.role)
    token = create_user_token(
        current_user.id, current_user.org_id, current_user.role, permissions
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=3600,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current authenticated user information.

    Args:
        current_user: Authenticated user

    Returns:
        User response
    """
    return UserResponse(
        id=current_user.id,
        org_id=current_user.org_id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
        created_at=current_user.created_at,
        last_login=current_user.last_login,
    )


def get_permissions_for_role(role: str) -> list:
    """
    Get permissions for a given role.

    Args:
        role: User role

    Returns:
        List of permission names
    """
    role_permissions = {
        "super_admin": [
            "create_organizations",
            "manage_organizations",
            "create_users",
            "manage_users",
            "create_tasks",
            "manage_tasks",
            "view_results",
            "delete_results",
            "create_clients",
            "manage_clients",
            "delete_clients",
            "manage_system",
        ],
        "org_admin": [
            "create_users",
            "manage_users",
            "create_tasks",
            "manage_tasks",
            "view_results",
            "delete_results",
            "create_clients",
            "manage_clients",
            "delete_clients",
        ],
        "analyst": ["create_tasks", "view_results"],
        "auditor": ["view_results"],
    }

    return role_permissions.get(role, [])
