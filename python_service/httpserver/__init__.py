"""
HTTP Server Package for ForensicsProject Python Service.

This module provides a FastAPI-based HTTP server for:
- Graphiti knowledge graph integration
- LLM analysis services
- Database access and queries
- Health monitoring

The service is designed with extensibility in mind, allowing future
integration of other communication protocols (gRPC, WebSocket, etc.)
"""

from .config import Settings, get_settings

# Optional imports for test compatibility
try:
    from .main import create_app, get_app
    _has_main = True
except ImportError:
    _has_main = False

__version__ = "1.0.0"

if _has_main:
    __all__ = ["create_app", "get_app", "Settings", "get_settings"]
else:
    __all__ = ["Settings", "get_settings"]
