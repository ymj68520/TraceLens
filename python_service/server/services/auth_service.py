"""
JWT Authentication service for token generation and validation.

Provides:
* bcrypt password hashing / verification
* JWT access-token creation for platform **users** (1-hour expiry)
* JWT access-token creation for forensic **clients** (30-day expiry)
* JWT verification and lookup helpers that resolve a token back to its
  ORM record via a database session.

Algorithm
---------
The signing algorithm is ``settings.JWT_ALGORITHM`` (default ``HS256``, a
symmetric algorithm keyed by ``settings.JWT_SECRET_KEY``). To use an
asymmetric algorithm such as RS256, set ``JWT_ALGORITHM=RS256`` and supply an
RSA key pair via configuration — this is intentionally NOT auto-selected, and
the previous ENVIRONMENT-based auto-switch to RS256 (which had no key pair and
broke token issuance) has been removed.
"""
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


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_user_token(
    user_id: uuid.UUID, org_id: uuid.UUID, role: str, permissions: list
) -> str:
    """
    Create JWT token for a user.

    Args:
        user_id: User's UUID
        org_id: Organization's UUID
        role: User's role
        permissions: List of user permissions

    Returns:
        JWT token string
    """
    # Timezone-aware UTC "now": calling .timestamp() on a naive datetime
    # (e.g. datetime.utcnow()) interprets it as local time, which produces an
    # epoch offset by the system's UTC offset and can make tokens expire
    # immediately on non-UTC hosts. datetime.now(timezone.utc) is correct.
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=USER_TOKEN_EXPIRE_HOURS)

    payload = {
        "user_id": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "permissions": permissions,
        "iat": now.timestamp(),
        "exp": expires.timestamp(),
        "type": "user",
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_client_token(
    client_id: uuid.UUID, org_id: uuid.UUID, capabilities: Dict[str, Any]
) -> str:
    """
    Create JWT token for a client.

    Args:
        client_id: Client's UUID
        org_id: Organization's UUID
        capabilities: Client capabilities dict

    Returns:
        JWT token string
    """
    # Timezone-aware UTC "now": calling .timestamp() on a naive datetime
    # (e.g. datetime.utcnow()) interprets it as local time, which produces an
    # epoch offset by the system's UTC offset and can make tokens expire
    # immediately on non-UTC hosts. datetime.now(timezone.utc) is correct.
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=CLIENT_TOKEN_EXPIRE_DAYS)

    payload = {
        "client_id": str(client_id),
        "org_id": str(org_id),
        "capabilities": capabilities,
        "iat": now.timestamp(),
        "exp": expires.timestamp(),
        "type": "client",
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_user_from_token(token: str, db) -> Optional[Any]:
    """
    Get user from JWT token.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        User object if valid, None otherwise
    """
    payload = verify_token(token)
    if not payload or payload.get("type") != "user":
        return None

    from server.models.database import User

    user = db.query(User).filter(User.id == uuid.UUID(payload["user_id"])).first()
    return user


def get_client_from_token(token: str, db) -> Optional[Any]:
    """
    Get client from JWT token.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        Client object if valid, None otherwise
    """
    payload = verify_token(token)
    if not payload or payload.get("type") != "client":
        return None

    from server.models.database import Client

    client = db.query(Client).filter(Client.id == uuid.UUID(payload["client_id"])).first()
    return client
