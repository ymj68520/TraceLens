"""
Database package initialization.

Re-exports the engine, declarative base, session dependency, and all ORM models
so callers can do ``from server.db import Organization, get_db`` etc.

The ORM models are exposed lazily via module ``__getattr__`` (PEP 562). This
deliberately avoids an eager ``from server.models.database import ...`` at
package import time, which would create a circular import:
``server.db`` -> ``server.models.database`` -> ``server.db.session`` ->
(partially initialized) ``server.db``. Importing ``server.models.database``
directly (before ``server.db``) must not fail, and lazy re-export guarantees
that. The public API is unchanged: every name listed in ``__all__`` is
reachable from ``server.db`` exactly as the task brief specifies.
"""
from server.db.session import Base, engine, get_db, init_db

__all__ = [
    "engine",
    "Base",
    "get_db",
    "init_db",
    "Organization",
    "User",
    "Client",
    "DiskImage",
    "CommandQueue",
    "AnalysisTask",
    "AnalysisResult",
    "LLMAnalysis",
    "TaskHistory",
    "RegistrationToken",
]

# Model names that are re-exported from ``server.models.database`` on demand.
_LAZY_MODELS = {
    "Organization",
    "User",
    "Client",
    "DiskImage",
    "CommandQueue",
    "AnalysisTask",
    "AnalysisResult",
    "LLMAnalysis",
    "TaskHistory",
    "RegistrationToken",
}


def __getattr__(name):
    """Lazily import ORM models to avoid a package-load-time circular import."""
    if name in _LAZY_MODELS:
        from server.models import database

        value = getattr(database, name)
        globals()[name] = value  # cache for subsequent direct lookups
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(_LAZY_MODELS))
