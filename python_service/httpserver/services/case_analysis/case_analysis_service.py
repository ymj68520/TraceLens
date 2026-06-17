"""
Case Analysis Service — Main service class for LLM-driven forensic case analysis.

This is the main entry point that coordinates file filtering, analysis, and report generation.
"""

import asyncio
import logging
import os
import httpx
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings

from .file_filter import FileFilter
from .multi_image_filter import MultiImageFilter
from .file_analyzer import FileAnalyzer
from .report_generator import ReportGenerator
from .cluster_analyzer import ClusterAnalyzer
from ..windows_artifacts import WindowsArtifactsService
from .case_aggregation_manager import CaseAggregationManager
from .db_utils import get_case_db_path, get_file_description_stats

logger = logging.getLogger(__name__)



from .case_analysis_parts import (
    CaseAnalysisCoreMixin,
    CaseAnalysisWindowsMixin,
    CaseAnalysisPipelinesMixin,
)


class CaseAnalysisService(
    CaseAnalysisCoreMixin,
    CaseAnalysisWindowsMixin,
    CaseAnalysisPipelinesMixin,
):
    """Service for end-to-end LLM case analysis.

    NOTE: The method implementations are split into mixins under the
    ``case_analysis_parts`` subpackage for maintainability:
      - CaseAnalysisCoreMixin     : dependency injection + file/report ops
      - CaseAnalysisWindowsMixin  : windows artifacts + extraction
      - CaseAnalysisPipelinesMixin: run_full / multi-image / smart / incremental
    The public surface (class name, all method signatures) is unchanged.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        # Will be injected after ServiceManager init
        self._llm_service = None
        self._graphiti_service = None
        self._cpp_backend = None

        # Sub-modules (initialized after dependency injection)
        self._file_filter = None
        self._multi_filter = None
        self._file_analyzer = None
        self._report_generator = None
        self._cluster_analyzer = None
        self._windows_service = None  # Windows artifacts service
        self._case_aggregation = None  # Case aggregation manager
