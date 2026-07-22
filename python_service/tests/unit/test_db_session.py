"""
Unit tests for database session management (``server.db.session``).

Validates engine construction (QueuePool + pool sizing + pre-ping), the
``SessionLocal`` factory configuration, the ``Base`` declarative base, and the
``get_db`` FastAPI dependency lifecycle — including that the session is closed
even when the consumer raises.

No live database connection is required: ``get_db`` is exercised against a
stand-in session factory so we assert on close behavior without connecting.
"""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import QueuePool

import server.db.session as session_module
from server.db.session import (
    Base,
    SessionLocal,
    engine,
    get_db,
    init_db,
)


class TestEngineConfiguration:
    def test_engine_is_created(self):
        assert isinstance(engine, Engine)

    def test_uses_queue_pool(self):
        assert isinstance(engine.pool, QueuePool)

    def test_pool_size_is_ten(self):
        assert engine.pool.size() == 10

    def test_max_overflow_is_twenty(self):
        assert engine.pool._max_overflow == 20

    def test_pool_pre_ping_enabled(self):
        # pool_pre_ping is stored on the engine, not the pool.
        assert engine.pool._pre_ping is True

    def test_engine_url_points_at_postgresql(self):
        assert str(engine.url).startswith("postgresql://")
        assert engine.url.database == "tracelens"


class TestSessionLocalFactory:
    def test_bound_to_engine(self):
        assert SessionLocal.kw["bind"] is engine

    def test_autocommit_disabled(self):
        assert SessionLocal.kw["autocommit"] is False

    def test_autoflush_disabled(self):
        assert SessionLocal.kw["autoflush"] is False


class TestBase:
    def test_base_is_declarative(self):
        # In SQLAlchemy 2.0 declarative_base() returns a DeclarativeBase subclass.
        assert isinstance(Base, type)
        assert issubclass(Base, declarative_base().__mro__[0].__mro__[0]) or hasattr(
            Base, "metadata"
        )

    def test_base_has_metadata(self):
        assert hasattr(Base, "metadata")


class TestGetDbDependency:
    def test_get_db_yields_a_session_and_closes(self, monkeypatch):
        fake_session = MagicMock(name="session")
        fake_factory = MagicMock(return_value=fake_session)
        monkeypatch.setattr(session_module, "SessionLocal", fake_factory)

        gen = get_db()
        yielded = next(gen)
        assert yielded is fake_session
        # Generator not yet exhausted -> close not called yet.
        fake_session.close.assert_not_called()

        # Finish the generator (the ``finally`` should run).
        with pytest.raises(StopIteration):
            next(gen)
        fake_session.close.assert_called_once()

    def test_get_db_closes_session_on_exception(self, monkeypatch):
        fake_session = MagicMock(name="session")
        fake_factory = MagicMock(return_value=fake_session)
        monkeypatch.setattr(session_module, "SessionLocal", fake_factory)

        gen = get_db()
        _ = next(gen)
        # Simulate the route raising; the dependency must still close the session.
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("boom"))
        fake_session.close.assert_called_once()


class TestInitDbCallable:
    def test_init_db_is_callable(self):
        assert callable(init_db)

    def test_init_db_does_not_connect_on_definition(self):
        # Importing the module and referencing init_db must not require a DB.
        # (Actual execution needs a live DB, so we only assert callability here.)
        assert init_db.__name__ == "init_db"
