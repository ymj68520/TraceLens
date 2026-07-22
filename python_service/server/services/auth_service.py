"""
JWT Authentication service for token generation and validation.

Provides:
* bcrypt password hashing / verification
* JWT access-token creation for platform **users** (1-hour expiry)
* JWT access-token creation for forensic **clients** (30-day expiry)
* JWT verification and lookup helpers that resolve a token back to its
  ORM record via a database session.

Algorithm selection
-------------------
``HS256`` is used in development (``ENVIRONMENT == "development"``); ``RS256`` is
selected otherwise. Development uses a symmetric ``JWT_SECRET_KEY``; production
``RS256`` requires an RSA key pair supplied through environment configuration.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from passlib.context import CryptContext

# JWT configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.urandom(32).hex())
JWT_ALGORITHM = "RS256"  # Use RSA for production, HS256 for development
USER_TOKEN_EXPIRE_HOURS = 1
CLIENT_TOKEN_EXPIRE_DAYS = 30

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

    # For development, use HS256. For production, use RS256 with proper keys
    algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=algorithm)


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

    algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=algorithm)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[algorithm])
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
