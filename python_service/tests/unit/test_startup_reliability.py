"""Reliability contracts for distributed server startup."""

import asyncio
from types import SimpleNamespace

import pytest

import server.main as server_main
from server.db.session import create_database_engine
from server.config import Settings


def test_database_engine_uses_bounded_postgres_timeouts(monkeypatch):
    captured = {}
    import server.db.session as session_module

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    config = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/tracelens",
        DB_CONNECT_TIMEOUT=3,
        DB_POOL_TIMEOUT=4,
    )
    engine = session_module.create_database_engine(config)
    assert captured["pool_timeout"] == 4
    assert captured["connect_args"]["connect_timeout"] == 3
    assert engine is not None


@pytest.mark.asyncio
async def test_database_startup_failure_keeps_liveness_and_marks_readiness(monkeypatch):
    monkeypatch.setattr(server_main.settings, "DB_STARTUP_TIMEOUT", 0.01)

    async def never_finishes():
        await asyncio.sleep(1)

    monkeypatch.setattr(server_main, "init_db", lambda: never_finishes())
    # The real init_db is synchronous; use a blocking callable to exercise the
    # timeout path without opening a database.
    monkeypatch.setattr(server_main, "init_db", lambda: __import__("time").sleep(1))
    assert await server_main.initialize_database() is False
    assert server_main._db_available is False
    assert server_main._db_error == "database initialization timed out"


@pytest.mark.asyncio
async def test_llm_client_initialization_does_not_make_network_request(monkeypatch):
    from httpserver.services.llm.llm_service import LLMService

    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def aclose(self):
            return None

    monkeypatch.setattr("httpserver.services.llm.llm_service.httpx.AsyncClient", Client)
    settings = SimpleNamespace(
        llm_text_base_url="http://192.168.31.170:1234",
        llm_vision_base_url="http://192.168.31.170:1234",
        llm_timeout_seconds=120,
    )
    service = LLMService(settings)
    await service.initialize()
    assert len(calls) == 2
    await service.shutdown()
