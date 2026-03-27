"""
LLM Service - AI analysis integration (Backward Compatibility Module).

This module maintains backward compatibility by re-exporting the LLMService
from the new modular structure.

New code should import from:
    from python_service.httpserver.services.llm import LLMService

Legacy imports continue to work:
    from python_service.httpserver.services.llm_service import LLMService
"""

# Re-export from new modular structure
from .llm import LLMService, FileAnalyzer, ModelManager, EventAnalyzer

__all__ = ["LLMService", "FileAnalyzer", "ModelManager", "EventAnalyzer"]
