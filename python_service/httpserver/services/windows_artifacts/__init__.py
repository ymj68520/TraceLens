"""
Windows Artifacts Analysis Package.

This package provides LLM-driven analysis of Windows forensic artifacts
including registry values, event logs, browser history, prefetch files,
and other Windows-specific traces.

Modules:
- windows_filter: Filter artifacts by case description using LLM
- windows_analyzer: Generate LLM descriptions for artifacts
- windows_toon_exporter: Export artifacts to TOON format
- windows_integration: Service coordinator for artifact processing
"""

from .windows_integration import WindowsArtifactsService

__all__ = [
    "WindowsArtifactsService",
]
