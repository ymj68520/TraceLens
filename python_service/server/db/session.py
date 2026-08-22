"""
Database session management with connection pooling.

The engine is built from the distributed server's Pydantic settings so the
shared .env file has one authoritative DATABASE_URL. Importing this module is
still lazy with respect to opening a database connection.
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from server.config import Settings, settings


def create_database_engine(config: Settings) -> Engine:
    """Build an engine with bounded driver and pool wait times."""
    connect_args = {}
    if config.DATABASE_URL.startswith(("postgresql://", "postgresql+")):
        connect_args["connect_timeout"] = config.DB_CONNECT_TIMEOUT
    return create_engine(
        config.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_timeout=config.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        connect_args=connect_args,
        echo=False,
    )


engine = create_database_engine(settings)
DATABASE_URL = settings.DATABASE_URL

# Create SessionLocal class.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models. All models in ``server.models.database`` derive
# from this so their tables are registered on a single ``Base.metadata``.
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Import ORM models and create any missing tables."""
    from server.models.database import (  # noqa: F401 (side effects)
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
