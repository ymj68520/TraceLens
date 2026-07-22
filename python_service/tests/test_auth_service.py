"""
Tests for authentication service (``server.services.auth_service``).

These tests exercise:
* bcrypt password hashing and verification
* user JWT token creation and round-trip verification
* client JWT token creation and round-trip verification
* rejection of expired tokens
* rejection of malformed / invalid tokens

Environment note
----------------
The auth service selects ``HS256`` only when ``ENVIRONMENT == "development"`` and
``RS256`` otherwise. ``RS256`` requires an asymmetric RSA key pair, while the
service's ``JWT_SECRET_KEY`` is symmetric key material. Unit tests therefore run
under the development algorithm by setting ``ENVIRONMENT=development`` before
importing the service. ``setdefault`` preserves any externally-configured value
(e.g. an integration environment that intentionally exercises ``RS256``).
"""
import os

# Select the HS256 development path for unit tests. Must happen before the
# service module is imported so the algorithm is resolved consistently at call
# time (the service reads the env var on every call).
os.environ.setdefault("ENVIRONMENT", "development")

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from server.services.auth_service import (
    JWT_SECRET_KEY,
    create_client_token,
    create_user_token,
    hash_password,
    verify_password,
    verify_token,
)


def test_password_hashing():
    """Test password hashing and verification."""
    password = "test_password_123"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_user_token_creation():
    """Test user JWT token creation."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    role = "analyst"
    permissions = ["create_tasks", "view_results"]

    token = create_user_token(user_id, org_id, role, permissions)

    assert token is not None
    assert isinstance(token, str)


def test_user_token_verification():
    """Test user JWT token verification."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    role = "analyst"
    permissions = ["create_tasks", "view_results"]

    token = create_user_token(user_id, org_id, role, permissions)
    payload = verify_token(token)

    assert payload is not None
    assert payload["user_id"] == str(user_id)
    assert payload["org_id"] == str(org_id)
    assert payload["role"] == role
    assert payload["permissions"] == permissions
    assert payload["type"] == "user"


def test_client_token_creation():
    """Test client JWT token creation."""
    client_id = uuid.uuid4()
    org_id = uuid.uuid4()
    capabilities = {"max_concurrent_tasks": 2, "supported_formats": ["E01", "DD"]}

    token = create_client_token(client_id, org_id, capabilities)

    assert token is not None
    assert isinstance(token, str)


def test_client_token_verification():
    """Test client JWT token verification."""
    client_id = uuid.uuid4()
    org_id = uuid.uuid4()
    capabilities = {"max_concurrent_tasks": 2}

    token = create_client_token(client_id, org_id, capabilities)
    payload = verify_token(token)

    assert payload is not None
    assert payload["client_id"] == str(client_id)
    assert payload["org_id"] == str(org_id)
    assert payload["capabilities"] == capabilities
    assert payload["type"] == "client"


def test_expired_token():
    """Test that expired tokens are rejected."""
    # Build a token whose expiry is already in the past so that verify_token
    # rejects it as expired. Uses the same HS256 algorithm the service uses in
    # development so verification keys/algorithms match.
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": str(uuid.uuid4()),
        "org_id": str(uuid.uuid4()),
        "role": "analyst",
        "permissions": [],
        "iat": (now - timedelta(hours=2)).timestamp(),
        "exp": (now - timedelta(hours=1)).timestamp(),
        "type": "user",
    }
    expired_token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

    assert verify_token(expired_token) is None


def test_invalid_token():
    """Test that invalid tokens are rejected."""
    payload = verify_token("invalid_token_string")
    assert payload is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
