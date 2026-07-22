"""
Database session management with connection pooling.

Creates a module-level SQLAlchemy ``engine`` backed by a :class:`QueuePool` and a
``SessionLocal`` factory. The ``get_db`` generator is the FastAPI dependency used
to hand a request-scoped session to route handlers and ensure it is closed.

The engine is created lazily: importing this module does not open a connection,
so it is safe to import in environments where the database is not reachable.
Connections are only established on first use (and verified at checkout time
because ``pool_pre_ping=True``).
"""
import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

# Database URL from environment. Default points at a local PostgreSQL instance.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tracelens",
)

# Create engine with connection pooling.
#   pool_size     - baseline number of persistent connections kept open
#   max_overflow  - additional connections allowed beyond pool_size under load
#   pool_pre_ping - issue a lightweight SELECT 1 to liven-check a connection
#                   before handing it out, so stale/broken connections are
#                   replaced transparently instead of raising on use
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=os.getenv("DB_ECHO", "false").lower() == "true",
)

# Create SessionLocal class.
# autocommit=False keeps transaction control explicit (commit/rollback by hand);
# autoflush=False prevents implicit flushes before queries, which is safer for
# multi-step request workflows.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models. All models in ``server.models.database`` derive
# from this so their tables are registered on a single ``Base.metadata``.
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency injection for FastAPI routes.

    Yields a database session and ensures it is returned to the pool (closed)
    even if the route raises.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.

    Imports every ORM model so it is registered on ``Base.metadata``, then
    issues ``CREATE TABLE`` for any that do not yet exist. Call this on
    application startup. For first-time provisioning prefer running the raw
    migration (``server.db.init_db``) so CHECK constraints and indexes match
    the schema exactly.
    """
    from server.models.database import (  # noqa: F401 (import for side effect)
        AnalysisResult,
        AnalysisTask,
        Client,
        CommandQueue,
        DiskImage,
        LLMAnalysis,
        Organization,
        RegistrationToken,
        TaskHistory,
        User,
    )

    Base.metadata.create_all(bind=engine)
