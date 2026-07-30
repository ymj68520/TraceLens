"""Part of CaseAnalysisService (split for maintainability).

This mixin contributes a group of methods to the CaseAnalysisService class. It
is mixed into CaseAnalysisService in case_analysis_service.py and relies on the
instance attributes defined there (self.settings, self._llm_service,
self._graphiti_service, self._cpp_backend, self._file_filter, ...).
"""

import asyncio
import logging
import os
import httpx
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....config import Settings

from ..file_filter import FileFilter
from ..multi_image_filter import MultiImageFilter
from ..file_analyzer import FileAnalyzer
from ..report_generator import ReportGenerator
from ..cluster_analyzer import ClusterAnalyzer
from ...windows_artifacts import WindowsArtifactsService
from ..case_aggregation_manager import CaseAggregationManager
from ..db_utils import get_case_db_path, get_file_description_stats

logger = logging.getLogger(__name__)


class CaseAnalysisCoreMixin:
    """Auto-extracted method group; see module docstring."""

    def set_llm_service(self, llm_service):
        """Inject the LLM service dependency."""
        self._llm_service = llm_service
        self._initialize_modules()

    def set_graphiti_service(self, graphiti_service):
        """Inject the Graphiti knowledge graph service (optional)."""
        self._graphiti_service = graphiti_service
        # Re-initialize modules with updated graphiti service
        self._initialize_modules()

    def set_cpp_backend(self, cpp_backend):
        """Inject the C++ backend service dependency."""
        self._cpp_backend = cpp_backend
        self._initialize_modules()

    def set_windows_service(self, windows_service: WindowsArtifactsService):
        """Inject the Windows artifacts service dependency."""
        self._windows_service = windows_service
        if windows_service and self._llm_service:
            windows_service.set_llm_service(self._llm_service)
        if windows_service and self._graphiti_service:
            windows_service.set_graphiti_service(self._graphiti_service)
        logger.info("Windows artifacts service injected")

    def _initialize_modules(self):
        """Initialize sub-modules after all dependencies are injected."""
        if self._llm_service and self._cpp_backend:
            self._file_filter = FileFilter(self.settings, self._llm_service, self._cpp_backend)
            self._multi_filter = MultiImageFilter(self.settings, self._llm_service, self._cpp_backend)
            self._file_analyzer = FileAnalyzer(self.settings, self._llm_service, self._graphiti_service)
            self._report_generator = ReportGenerator(self.settings, self._llm_service, self._graphiti_service, self._cpp_backend)
            self._cluster_analyzer = ClusterAnalyzer(self.settings, self._llm_service, self._graphiti_service)
            self._case_aggregation = CaseAggregationManager(
                self.settings, self._cpp_backend, self._graphiti_service
            )
            logger.info("Case analysis sub-modules initialized")
            if self._graphiti_service:
                logger.info("Graphiti service is available for knowledge graph features")
            else:
                logger.info("Graphiti service not available - knowledge graph features will be disabled")

    async def filter_files_by_case(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int = 200,
        batch_size: int = 50,
        use_streaming: bool = True,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Let LLM select important files based on case description."""
        if not self._file_filter:
            raise RuntimeError("FileFilter module not initialized. Ensure all dependencies are injected.")
        return await self._file_filter.filter_files_by_case(
            files_db_path, case_description, max_files, batch_size, use_streaming, task_id
        )

    async def generate_file_descriptions(
        self,
        files_db_path: str,
        file_paths: List[str],
        case_description: str,
        extraction_dir: Optional[str] = None,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """Generate LLM description for each file in the list using concurrency."""
        if not self._file_analyzer:
            raise RuntimeError("FileAnalyzer module not initialized. Ensure all dependencies are injected.")
        return await self._file_analyzer.analyze_files(
            files_db_path, file_paths, case_description, extraction_dir, progress_callback
        )

    async def reanalyze_files(
        self,
        task_id: str,
        file_paths: List[str],
        user_hint: str,
        files_db_path: str,
        case_description: str = "",
    ) -> List[Dict[str, Any]]:
        """Re-analyze files with additional user context."""
        if not self._file_analyzer:
            raise RuntimeError("FileAnalyzer module not initialized. Ensure all dependencies are injected.")
        return await self._file_analyzer.reanalyze_files(
            task_id, file_paths, user_hint, files_db_path, case_description
        )

    async def ingest_to_knowledge_graph(
        self,
        task_id: str,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        cluster_descriptions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Ingest case description, file descriptions, and event clusters into Graphiti."""
        if not self._file_analyzer:
            raise RuntimeError("FileAnalyzer module not initialized. Ensure all dependencies are injected.")
        return await self._file_analyzer.ingest_to_knowledge_graph(
            task_id, case_description, file_descriptions, cluster_descriptions
        )

    async def generate_case_report(
        self,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        files_db_path: Optional[str] = None,
        task_id: Optional[str] = None,
        files_db_paths: Optional[List[str]] = None,
        task_ids: Optional[List[str]] = None,
        is_cross_image_report: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive case analysis report.

        For single-image reports: uses single database and task graph.
        For cross-image reports: aggregates from all databases and uses case-level graph.
        """
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return await self._report_generator.generate_final_report(
            case_description=case_description,
            file_descriptions=file_descriptions,
            files_db_path=files_db_path,
            task_id=task_id,
            files_db_paths=files_db_paths,
            task_ids=task_ids,
            is_cross_image_report=is_cross_image_report,
        )

    def get_case_report(self, files_db_path: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a persisted case report from the database."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return self._report_generator.get_case_report(files_db_path, task_id)

    def get_cross_image_report(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a persisted cross-image report from the case-level database."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return self._report_generator.get_cross_image_report(case_id)

    async def associate_tasks_to_case(self, case_id: str, task_ids: List[str]) -> Dict[str, Any]:
        """Associate already-completed tasks to a case, pre-populating analysis state.

        Delegates to the CaseAggregationManager so already-analyzed tasks are
        correctly reused (not re-analyzed) by a subsequent cross-image run.
        """
        if not self._case_aggregation:
            raise RuntimeError("CaseAggregationManager not initialized. Ensure all dependencies are injected.")
        return await self._case_aggregation.associate_tasks(case_id, task_ids)

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """Retrieve the list of case-relevant files."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return self._report_generator.get_filtered_files(files_db_path, task_id)

