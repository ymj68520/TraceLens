"""
Services package for the HTTP server.

Contains business logic layer that abstracts:
- C++ backend communication
- Graphiti knowledge graph operations
- LLM analysis services

The architecture is designed for extensibility, allowing easy
addition of new communication protocols (gRPC, WebSocket, etc.)
"""

from .service_manager import ServiceManager, get_service_manager
from .document_extractor import get_document_extractor_locator

__all__ = ["ServiceManager", "get_service_manager", "get_document_extractor_locator"]
