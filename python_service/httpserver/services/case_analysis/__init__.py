"""
Case Analysis Package — LLM-driven forensic case analysis.

This package provides modular case analysis capabilities:
- File filtering (streaming and legacy methods)
- File analysis (text and vision)
- Report generation (graph-enhanced and fallback)
- Event cluster analysis with Graphiti integration
- Main service orchestration

Backward compatibility: The main CaseAnalysisService class is exported
from this package for existing code that imports from the parent module.
"""

from .case_analysis_service import CaseAnalysisService
from .file_filter import FileFilter
from .file_analyzer import FileAnalyzer
from .report_generator import ReportGenerator
from .cluster_analyzer import ClusterAnalyzer
from . import db_utils
from .llm_response_parser import LLMResponseParser, ParseResult

__all__ = [
    "CaseAnalysisService",
    "FileFilter",
    "FileAnalyzer",
    "ReportGenerator",
    "ClusterAnalyzer",
    "db_utils",
    "LLMResponseParser",
    "ParseResult",
]
