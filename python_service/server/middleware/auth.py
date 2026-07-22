"""
JWT Authentication middleware for FastAPI.

Provides FastAPI dependency-injection callables that protect routes behind JWT
authentication. Two token types are supported:

* **user** tokens  -> resolved by :func:`get_current_user`
* **client** tokens -> resolved by :func:`get_current_client`

Token type is enforced strictly: a client token presented to a user-protected
route (and vice versa) is rejected with ``401 Unauthorized``. The underlying
JWT verification and ORM lookup are delegated to
:mod:`server.services.auth_service` (Task 4).
"""
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.services.auth_service import (
    get_client_from_token,
    get_user_from_token,
    verify_token,
)

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db=None,
):
    """
    Get current authenticated user from JWT token.

    Raises:
        HTTPException: If token is invalid or user not found

    Returns:
        User object
    """
    from server.db.session import get_db

    # Use dependency injection for db if not provided
    if db is None:
        db_gen = get_db()
        db = next(db_gen)

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "user":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_from_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_client(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db=None,
):
    """
    Get current authenticated client from JWT token.

    Raises:
        HTTPException: If token is invalid or client not found

    Returns:
        Client object
    """
    from server.db.session import get_db

    if db is None:
        db_gen = get_db()
        db = next(db_gen)

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "client":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client = get_client_from_token(token, db)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return client


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db=None,
):
    """
    Optionally get authenticated user.

    Returns None if no token provided or invalid.
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def require_permission(*permissions: str):
    """
    Dependency factory that requires specific permissions.

    Args:
        *permissions: Required permission names

    Returns:
        Dependency function
    """
    async def permission_dependency(current_user=Depends(get_current_user)):
        # Check if user has required permissions
        # For now, super_admin has all permissions
        if current_user.role == "super_admin":
            return current_user

        # TODO: Implement proper permission checking based on role
        # For now, just check if user is authenticated
        return current_user

    return permission_dependency
