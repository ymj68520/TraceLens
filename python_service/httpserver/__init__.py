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

from .main import create_app, get_app
from .config import Settings, get_settings

__version__ = "1.0.0"
__all__ = ["create_app", "get_app", "Settings", "get_settings"]
