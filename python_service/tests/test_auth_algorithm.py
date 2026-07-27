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
