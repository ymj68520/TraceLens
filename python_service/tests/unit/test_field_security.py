"""Synthetic field credentials only; never touch a real user or evidence file."""

import json
import secrets
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from passlib.context import CryptContext
from starlette.requests import Request

from httpserver.services.field_security import (
    AUDIENCE, ISSUER, FieldAuthenticationError, FieldConfigurationError,
    audit_actor, authorize, load_policy, login, principal, valid_internal,
)


@pytest.fixture
def field_env(tmp_path, monkeypatch):
    users = tmp_path / "field-users.json"
    users.write_text(json.dumps({"users": {
        "analyst": {"password_hash": CryptContext(schemes=["bcrypt"]).hash("synthetic-password"),
                    "role": "analyst", "active": True, "token_version": 1},
        "reviewer": {"password_hash": CryptContext(schemes=["bcrypt"]).hash("synthetic-review"),
                     "role": "reviewer", "active": True, "token_version": 1},
    }}), encoding="utf-8")
    users.chmod(0o600)
    values = {"TRACELENS_FIELD_AUTH": "enabled", "FIELD_USER_FILE": str(users),
              "FIELD_JWT_SECRET": secrets.token_urlsafe(48),
              "FIELD_CPP_TO_PYTHON_TOKEN": secrets.token_urlsafe(48),
              "FIELD_PYTHON_TO_CPP_TOKEN": secrets.token_urlsafe(48),
              "FIELD_OUTBOUND_POLICY": "disabled"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    return users


def test_field_tokens_are_signed_scoped_expiring_and_revocable(field_env):
    policy = load_policy()
    token = login(policy, "analyst", "synthetic-password")["access_token"]
    assert principal(policy, "Bearer " + token)["id"] == "analyst"
    authorize(principal(policy, "Bearer " + token), "GET", "/api/tasks")
    with pytest.raises(PermissionError):
        authorize(principal(policy, "Bearer " + token), "DELETE", "/api/tasks/id")
    with pytest.raises(PermissionError):
        authorize(principal(policy, "Bearer " + token), "POST", "/api/investigation/id/review")
    with pytest.raises(FieldAuthenticationError):
        principal(policy, "Bearer mock_jwt_token_123")
    with pytest.raises(FieldAuthenticationError):
        principal(policy, "Bearer " + jwt.encode({"sub": "analyst", "iss": ISSUER, "aud": AUDIENCE,
            "iat": int(time.time()) - 30, "nbf": int(time.time()) - 30,
            "exp": int(time.time()) - 1, "jti": "expired", "ver": 1}, policy.jwt_secret, algorithm="HS256"))
    data = json.loads(field_env.read_text())
    data["users"]["analyst"]["token_version"] = 2
    field_env.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FieldAuthenticationError):
        principal(policy, "Bearer " + token)
    assert valid_internal(policy, policy.cpp_to_python, direction="cpp_to_python", peer="127.0.0.1")
    assert not valid_internal(policy, policy.cpp_to_python, direction="cpp_to_python", peer="192.0.2.1")
    assert not valid_internal(policy, policy.python_to_cpp, direction="cpp_to_python", peer="127.0.0.1")


def test_field_mode_fails_closed_on_missing_or_weak_config(field_env, monkeypatch):
    monkeypatch.setenv("FIELD_JWT_SECRET", "weak")
    with pytest.raises(FieldConfigurationError):
        load_policy()
    monkeypatch.setenv("TRACELENS_REQUIRE_FIELD_AUTH", "1")
    monkeypatch.setenv("TRACELENS_FIELD_AUTH", "typo")
    with pytest.raises(FieldConfigurationError):
        load_policy()
    monkeypatch.setenv("TRACELENS_FIELD_AUTH", "enabled")
    monkeypatch.setenv("FIELD_JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9999")
    with pytest.raises(FieldConfigurationError):
        load_policy()
    monkeypatch.delenv("HTTP_PROXY")
    monkeypatch.setenv("FIELD_OUTBOUND_POLICY", "local_only")
    monkeypatch.setenv("FIELD_MODEL_ORIGINS", "https://api.example.com:443")
    with pytest.raises(FieldConfigurationError):
        load_policy()


def test_field_http_protects_old_routes_and_introspection(field_env):
    from httpserver.main import create_app

    client = TestClient(create_app(), client=("127.0.0.1", 12345))
    assert client.get("/api/system/health").status_code == 401
    assert client.get("/api/android-report/imports").status_code == 401
    assert client.get("/api/field-auth/me", headers={"X-User": "admin"}).status_code == 401
    assert client.get("/health/live").json() == {"status": "alive"}
    token = client.post("/api/field-auth/login", json={"username": "analyst", "password": "synthetic-password"}).json()["access_token"]
    assert client.get("/api/field-auth/me", headers={"Authorization": "Bearer " + token}).json()["role"] == "analyst"
    assert client.delete("/api/android-report/imports/00000000000000000000000000000000/tasks/x",
                         headers={"Authorization": "Bearer " + token}).status_code == 403
    endpoint = "/api/field-auth/introspect"
    body = {"authorization": "Bearer " + token, "method": "GET", "path": "/api/tasks"}
    assert client.post(endpoint, json=body).status_code == 401
    headers = {"X-TraceLens-Service-Token": load_policy().cpp_to_python}
    assert client.post(endpoint, json=body, headers=headers).json()["principal"]["id"] == "analyst"
    assert client.post(endpoint, json={**body, "method": "DELETE"}, headers=headers).status_code == 403


def test_review_audit_ignores_client_supplied_identity(field_env):
    app = FastAPI()
    app.state.field_policy = load_policy()
    request = Request({"type": "http", "app": app, "method": "POST", "path": "/review",
                       "headers": [], "query_string": b"", "client": ("127.0.0.1", 12345)})
    request.state.principal = {"id": "actual-reviewer", "role": "reviewer", "kind": "user"}
    assert audit_actor(request, "forged-name") == "actual-reviewer"


def test_field_release_layout_refuses_unfrozen_process(field_env, monkeypatch):
    from httpserver.main import create_app
    monkeypatch.setenv("TRACELENS_REQUIRE_RELEASE_LAYOUT", "1")
    monkeypatch.setenv("TRACELENS_RELEASE_ID", "UNFROZEN_WORKTREE")
    with pytest.raises(RuntimeError, match="release identity"):
        create_app()
