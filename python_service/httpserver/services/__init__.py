"""
Services package for the HTTP server.

Contains business logic layer that abstracts:
- C++ backend communication
- Graphiti knowledge graph operations
- LLM analysis services

The architecture is designed for extensibility, allowing easy
addition of new communication protocols (gRPC, WebSocket, etc.)
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service_manager import ServiceManager, get_service_manager
    from .document_extractor import get_document_extractor_locator


def __getattr__(name):
    # Offline evidence verification imports this package too. Loading every
    # server/document extractor here makes a local verifier start the whole
    # service dependency graph (particularly slow on Windows/WSL filesystems).
    # Preserve the existing public exports, resolving them only when requested.
    if name in {"ServiceManager", "get_service_manager"}:
        from . import service_manager
        value = getattr(service_manager, name)
    elif name == "get_document_extractor_locator":
        from .document_extractor import get_document_extractor_locator
        value = get_document_extractor_locator
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value

__all__ = ["ServiceManager", "get_service_manager", "get_document_extractor_locator"]
