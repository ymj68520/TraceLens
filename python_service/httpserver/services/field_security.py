"""Small fail-closed identity/policy boundary for a controlled field deployment.

The legacy C/S token issuer has a development secret and incomplete role
enforcement, so field tokens use a separate issuer, secret and local user file.
No token, user identity or password is read from evidence content or headers
such as X-User/X-Forwarded-User.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from passlib.context import CryptContext

ISSUER = "tracelens-field"
FIELD_SECURITY_VERSION = "6a-v1"
AUDIENCE = "tracelens-api"
ALGORITHM = "HS256"
TOKEN_SECONDS = 900
_PASSWORDS = CryptContext(schemes=["bcrypt"], deprecated="auto")
ROLES = {
    "viewer": frozenset({"read"}),
    "analyst": frozenset({"read", "write"}),
    "reviewer": frozenset({"read", "write", "review"}),
    "admin": frozenset({"read", "write", "review", "admin"}),
}


class FieldConfigurationError(ValueError):
    pass


class FieldAuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class FieldPolicy:
    enabled: bool
    jwt_secret: str = ""
    cpp_to_python: str = ""
    python_to_cpp: str = ""
    user_file: Path | None = None
    outbound_mode: str = "disabled"
    allowed_model_origins: tuple[str, ...] = ()
    browser_origin: str = ""


def field_enabled() -> bool:
    return os.environ.get("TRACELENS_FIELD_AUTH", "").strip().lower() == "enabled"


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if (len(value.encode("utf-8")) < 32 or value.startswith("REPLACE_")
            or value == "change-this-in-production" or len(set(value)) < 16):
        raise FieldConfigurationError(f"{name} must be configured with at least 32 bytes")
    return value


def _file(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise FieldConfigurationError("field user file must be an explicit regular file")
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise FieldConfigurationError("field user file permissions must be owner-only")
    return path


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or not parsed.port:
        raise FieldConfigurationError("model origin requires scheme, host and port")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise FieldConfigurationError("model origin must not contain credentials, path or query")
    try:
        host_is_local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        # No DNS names in the application allowlist: a hostname can be
        # rebound after validation. Explicit address + network egress
        # enforcement are required for a field model service.
        host_is_local = False
    if not host_is_local:
        raise FieldConfigurationError("only numeric loopback model origins are currently supported")
    return f"{parsed.scheme}://{parsed.netloc}"


def load_policy() -> FieldPolicy:
    if not field_enabled():
        if os.environ.get("TRACELENS_REQUIRE_FIELD_AUTH") == "1":
            raise FieldConfigurationError("field authentication is required but not enabled")
        return FieldPolicy(enabled=False)
    jwt_secret = _secret("FIELD_JWT_SECRET")
    cpp_to_python = _secret("FIELD_CPP_TO_PYTHON_TOKEN")
    python_to_cpp = _secret("FIELD_PYTHON_TO_CPP_TOKEN")
    if len({jwt_secret, cpp_to_python, python_to_cpp}) != 3:
        raise FieldConfigurationError("field credentials must be independent")
    user_path = _file(Path(os.environ.get("FIELD_USER_FILE", "")))
    mode = os.environ.get("FIELD_OUTBOUND_POLICY", "disabled").strip().lower()
    if mode not in {"disabled", "local_only"}:
        raise FieldConfigurationError("FIELD_OUTBOUND_POLICY must be disabled or local_only")
    origins = tuple(_origin(item.strip()) for item in os.environ.get("FIELD_MODEL_ORIGINS", "").split(",") if item.strip())
    browser_origin = os.environ.get("FIELD_BROWSER_ORIGIN", "").strip()
    if browser_origin:
        parsed_browser = urlsplit(browser_origin)
        if (parsed_browser.scheme not in {"http", "https"} or not parsed_browser.hostname
                or parsed_browser.path not in {"", "/"} or parsed_browser.query or parsed_browser.fragment
                or parsed_browser.username or parsed_browser.password or "*" in browser_origin):
            raise FieldConfigurationError("FIELD_BROWSER_ORIGIN must be one exact origin")
        try:
            browser_loopback = ipaddress.ip_address(parsed_browser.hostname).is_loopback
        except ValueError:
            browser_loopback = False
        if parsed_browser.scheme != "https" and not browser_loopback:
            raise FieldConfigurationError("non-loopback field browser origin requires HTTPS")
    if mode == "local_only" and not origins:
        raise FieldConfigurationError("local_only requires explicit FIELD_MODEL_ORIGINS")
    if mode == "local_only":
        from ..config import get_settings
        settings = get_settings()
        configured = {
            "LLM_BASE_URL": settings.llm_base_url,
            "LLM_TEXT_BASE_URL": settings.llm_text_base_url,
            "LLM_VISION_BASE_URL": settings.llm_vision_base_url,
            "EMBEDDING_BASE_URL": os.environ.get("EMBEDDING_BASE_URL", ""),
        }
        for key, value in configured.items():
            if not value:
                continue
            parsed = urlsplit(value)
            if f"{parsed.scheme}://{parsed.netloc}" not in origins or parsed.username or parsed.password:
                raise FieldConfigurationError(f"{key} is not an explicitly allowed local model origin")
        if os.environ.get("GRAPHITI_USE_LOCAL_LLM", "true").lower() not in {"1", "true", "yes"}:
            raise FieldConfigurationError("Graphiti public-model fallback is forbidden")
    if any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")):
        raise FieldConfigurationError("proxy environment variables are forbidden in field mode")
    return FieldPolicy(True, jwt_secret, cpp_to_python, python_to_cpp, user_path, mode, origins, browser_origin)


def _users(policy: FieldPolicy) -> dict:
    path = _file(policy.user_file)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
        raise FieldConfigurationError("invalid field user file")
    return data["users"]


def login(policy: FieldPolicy, username: str, password: str) -> dict:
    if not policy.enabled or not isinstance(username, str) or not isinstance(password, str):
        raise FieldAuthenticationError("invalid credentials")
    if len(username) > 128 or len(password) > 1024:
        raise FieldAuthenticationError("invalid credentials")
    user = _users(policy).get(username)
    # Check an actual bcrypt hash even for unknown users to avoid an obvious
    # username-existence timing side channel.
    fallback = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO9aM3o8pSJa/Cj5HBcOOUqgHkjjQ2Zme"
    valid = _PASSWORDS.verify(password, user.get("password_hash", fallback) if isinstance(user, dict) else fallback)
    if not valid or not isinstance(user, dict) or not user.get("active") or user.get("role") not in ROLES:
        raise FieldAuthenticationError("invalid credentials")
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": username,
              "iat": now, "nbf": now, "exp": now + TOKEN_SECONDS,
              "jti": secrets.token_hex(16), "ver": user.get("token_version", 0)}
    return {"access_token": jwt.encode(claims, policy.jwt_secret, algorithm=ALGORITHM),
            "token_type": "bearer", "expires_in": TOKEN_SECONDS,
            "principal": {"id": username, "role": user["role"]}}


def principal(policy: FieldPolicy, authorization: str) -> dict:
    if not policy.enabled or not authorization.startswith("Bearer "):
        raise FieldAuthenticationError("bearer token required")
    token = authorization[7:]
    if not token or len(token) > 4096:
        raise FieldAuthenticationError("invalid bearer token")
    try:
        claims = jwt.decode(token, policy.jwt_secret, algorithms=[ALGORITHM],
                            audience=AUDIENCE, issuer=ISSUER,
                            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]})
        username = claims["sub"]
        user = _users(policy).get(username)
        if not isinstance(user, dict) or not user.get("active") or user.get("role") not in ROLES:
            raise FieldAuthenticationError("user is disabled")
        if claims.get("ver") != user.get("token_version", 0):
            raise FieldAuthenticationError("token was revoked")
        return {"id": username, "role": user["role"], "kind": "user"}
    except (jwt.PyJWTError, KeyError, TypeError, FieldConfigurationError) as exc:
        raise FieldAuthenticationError("invalid or expired bearer token") from exc


def required_permission(method: str, path: str) -> str:
    if method.upper() == "DELETE" or any(part in path for part in ("/delete", "/export", "/download", "/cleanup")):
        return "admin"
    if path.startswith("/api/reports/evidence") and method.upper() not in {"GET", "HEAD"}:
        return "review"
    if any(part in path for part in ("/review", "/accept", "/reject", "/report-evidence", "/publish")) and method.upper() != "GET":
        return "review"
    return "read" if method.upper() in {"GET", "HEAD"} else "write"


def authorize(subject: dict, method: str, path: str) -> None:
    role = subject.get("role")
    if required_permission(method, path) not in ROLES.get(role, frozenset()):
        raise PermissionError("insufficient permission")


def valid_internal(policy: FieldPolicy, token: str, *, direction: str, peer: str) -> bool:
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback = False
    expected = policy.cpp_to_python if direction == "cpp_to_python" else policy.python_to_cpp
    return bool(policy.enabled and loopback and token and hmac.compare_digest(token, expected))


def audit_actor(request, legacy_value: str | None = None) -> str:
    """Use authenticated server context for new decisions; preserve old-mode semantics."""
    policy = getattr(request.app.state, "field_policy", None)
    if policy is None or not policy.enabled:
        return legacy_value or "workbench"
    subject = getattr(request.state, "principal", None)
    if not subject or subject.get("kind") != "user" or not subject.get("id"):
        raise FieldAuthenticationError("trusted user principal required")
    return subject["id"]
