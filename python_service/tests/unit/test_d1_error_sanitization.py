"""Phase D1 regression: client-visible internal errors stay sanitized.

Every test drives one confirmed fix point with an exception whose message
carries filesystem paths / internal URLs, and asserts the original text
never reaches the response while the server-side log call still executes.
Domain errors (404/400/409 semantics) are intentionally NOT covered here —
D1 must not generalize them away.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from httpserver.config import Settings, mask_url_credentials
from httpserver.services.wechat_graph_parts._queries import (
    WeChatGraphQueriesMixin,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SECRET_PATH = "/secret/server/path/db.sqlite3"


def _selective_open_breaking(basename: str, message: str):
    """An ``open`` replacement that raises only for ``basename``."""
    real_open = open

    def fake_open(file, *args, **kwargs):
        if basename in str(file):
            raise OSError(message)
        return real_open(file, *args, **kwargs)

    return fake_open


# ---------------------------------------------------------------- helper


def test_mask_url_credentials():
    assert (
        mask_url_credentials("redis://:hunter2@localhost:6379")
        == "redis://:***@localhost:6379"
    )
    assert (
        mask_url_credentials("postgresql://postgres:hunter2@db:5432/x")
        == "postgresql://postgres:***@db:5432/x"
    )
    assert mask_url_credentials("redis://localhost:6379") == "redis://localhost:6379"
    assert mask_url_credentials("neo4j://127.0.0.1:7687") == "neo4j://127.0.0.1:7687"


# ---------------------------------------------------------------- system logs


@pytest.mark.asyncio
async def test_system_log_read_failure_is_sanitized(monkeypatch, tmp_path):
    from httpserver.routes import system as system_routes

    monkeypatch.setattr(system_routes.os.path, "exists", lambda p: True)
    monkeypatch.setattr(
        "builtins.open",
        _selective_open_breaking(
            "python_service.log", f"[Errno 13] Permission denied: '{SECRET_PATH}'"
        ),
    )

    response = await system_routes.get_service_logs("python", 10, Settings())
    messages = [entry["message"] for entry in response["logs"]]
    assert messages == ["log file read failed"]
    assert SECRET_PATH not in str(response)


# ---------------------------------------------------------------- health / readiness


class _RaisingService:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def health_check(self):
        raise self._exc


class _StubManager:
    def __init__(self):
        self.cpp_backend = _RaisingService(
            httpx.ConnectError("connection to http://10.0.0.9:8080 failed")
        )
        self.graphiti_service = _RaisingService(
            RuntimeError("bolt://neo4j-internal:7687 driver failed")
        )
        self.llm_service = _RaisingService(
            httpx.ReadTimeout("read timed out on http://llm-host:1234")
        )
        self.ingestion_job_manager = None


class _RaisingRedisManager(_StubManager):
    @property
    def ingestion_job_manager(self):
        raise ConnectionError("redis://:hunter2@redis-host:6379 ping failed")

    def __init__(self):
        # Skip _StubManager.__init__: assigning self.ingestion_job_manager
        # would collide with the raising property above.
        self.cpp_backend = _RaisingService(
            httpx.ConnectError("connection to http://10.0.0.9:8080 failed")
        )
        self.graphiti_service = _RaisingService(
            RuntimeError("bolt://neo4j-internal:7687 driver failed")
        )
        self.llm_service = _RaisingService(
            httpx.ReadTimeout("read timed out on http://llm-host:1234")
        )


@pytest.mark.asyncio
async def test_readiness_check_masks_urls_and_classifies_errors(monkeypatch):
    import httpserver.services as services_module
    from httpserver.routes import health as health_routes

    monkeypatch.setattr(
        services_module, "get_service_manager", lambda: _RaisingRedisManager()
    )
    settings = Settings(redis_url="redis://:hunter2@localhost:6379")

    response = await health_routes.readiness_check(settings)

    checks = response.checks
    assert checks["cpp_backend"]["error"] == "ConnectError"
    assert checks["neo4j"]["error"] == "RuntimeError"
    assert checks["llm"]["error"] == "ReadTimeout"
    # The raising ingestion_job_manager property lands in the redis except
    # branch: class name only, no redis URL in the payload.
    assert checks["redis"]["error"] == "ConnectionError"
    assert "url" not in checks["redis"]
    dumped = str(checks)
    for leaked in ("hunter2", "10.0.0.9", "neo4j-internal", "llm-host", "redis-host"):
        assert leaked not in dumped


@pytest.mark.asyncio
async def test_redis_status_endpoint_masks_url(monkeypatch):
    import httpserver.services as services_module
    from httpserver.routes import health as health_routes

    monkeypatch.setattr(
        services_module, "get_service_manager", lambda: _StubManager()
    )
    response = await health_routes.redis_status(
        Settings(redis_url="redis://:hunter2@localhost:6379")
    )
    # job_manager is None -> unavailable branch still returns the masked URL.
    assert response["url"] == "redis://:***@localhost:6379"
    assert "hunter2" not in str(response)


@pytest.mark.asyncio
async def test_service_manager_health_check_classifies_errors():
    from httpserver.services.service_manager import ServiceManager

    result = await ServiceManager.health_check(_StubManager())
    assert result["services"]["cpp_backend"]["error"] == "ConnectError"
    assert result["services"]["graphiti"]["error"] == "RuntimeError"
    assert result["services"]["llm"]["error"] == "ReadTimeout"
    dumped = str(result)
    assert "10.0.0.9" not in dumped
    assert "neo4j-internal" not in dumped


# ---------------------------------------------------------------- office parse


@pytest.mark.asyncio
async def test_office_parse_failure_error_is_fixed(monkeypatch, tmp_path):
    from httpserver.routes import office as office_routes

    xlsx = tmp_path / "sheet.xlsx"
    xlsx.write_bytes(b"PK")

    class BrokenService:
        async def parse_file(self, path):
            raise RuntimeError(
                f"provider endpoint http://llm-internal:1234 read {SECRET_PATH}"
            )

    monkeypatch.setattr(office_routes, "get_office_service", lambda: BrokenService())
    response = await office_routes.parse_office_file(
        office_routes.ParseRequest(file_path=str(xlsx))
    )
    assert response.error == "office parse failed"
    dumped = str(response)
    assert SECRET_PATH not in dumped
    assert "llm-internal" not in dumped


# ---------------------------------------------------------------- wechat queries


@pytest.mark.asyncio
async def test_wechat_query_operational_error_is_fixed(tmp_path):
    class Host(WeChatGraphQueriesMixin):
        pass

    # A valid sqlite file whose chat tables do not exist: the query raises
    # sqlite3.OperationalError, previously returned verbatim as "error".
    db = tmp_path / "wechat.db"
    sqlite3.connect(db).close()

    result = await Host().get_chat_history(str(db), "alice", "bob")
    assert result["error"] == "database query failed"
    assert str(tmp_path) not in str(result)


# ---------------------------------------------------------------- main.py global handler


def test_global_exception_handler_never_echoes_exception():
    from fastapi.testclient import TestClient

    from httpserver.main import create_app

    app = create_app()

    @app.get("/_d1_probe_boom")
    async def _probe_boom():  # pragma: no cover - test-only route
        raise RuntimeError(f"internal detail {SECRET_PATH}")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/_d1_probe_boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "An unexpected error occurred"
    assert SECRET_PATH not in response.text
    assert "internal detail" not in response.text


# ---------------------------------------------------------------- secret / config hygiene


def _hermetic_settings(monkeypatch) -> Settings:
    for var in (
        "NEO4J_PASSWORD", "OSS_ACCESS_KEY_SECRET", "REDIS_URL", "NEO4J_URI"
    ):
        monkeypatch.delenv(var, raising=False)
    return Settings(_env_file=None)


def test_settings_defaults_carry_no_credentials(monkeypatch):
    settings = _hermetic_settings(monkeypatch)
    assert settings.neo4j_password == ""
    assert settings.oss_access_key_secret == ""
    assert mask_url_credentials(settings.redis_url) == settings.redis_url


def test_settings_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://:fresh@localhost:6379/2")
    settings = Settings(_env_file=None)
    assert settings.redis_url == "redis://:fresh@localhost:6379/2"
    assert (
        mask_url_credentials(settings.redis_url) == "redis://:***@localhost:6379/2"
    )


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        not value
        or "change" in lowered
        or "your" in lowered
        or "placeholder" in lowered
        or "<" in value
    )


def test_env_example_has_no_real_credentials():
    example = REPO_ROOT / ".env.example"
    assert example.is_file(), ".env.example must exist at the repo root"
    sensitive_markers = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "AUTH")
    for raw in example.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        # "*TOKEN(S)" keys here are LLM token budgets/ratios, not credentials.
        if key.upper().endswith("TOKEN") or key.upper().endswith("TOKENS"):
            continue
        if any(marker in key.upper() for marker in sensitive_markers):
            assert _is_placeholder(value), (
                f".env.example key {key} must stay a placeholder, got {value!r}"
            )
        if "://" in value:
            password = urlsplit(value).password
            assert password is None or _is_placeholder(password), (
                f".env.example key {key} embeds a non-placeholder URL credential"
            )


def test_real_env_files_are_not_tracked():
    try:
        listed = subprocess.run(
            ["git", "ls-files", ".env", ".env.bak"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    except (subprocess.SubprocessError, OSError):
        pytest.skip("git unavailable")
    assert listed == [], f"tracked credential files: {listed}"
