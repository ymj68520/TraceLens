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


class CaseAnalysisWindowsMixin:
    """Auto-extracted method group; see module docstring."""

    async def analyze_windows_artifacts(
        self,
        task_id: str,
        windows_db_path: str,
        case_description: str,
        max_artifacts: int = 200,
        artifact_types: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run full Windows artifacts analysis pipeline.

        Args:
            task_id: Task identifier
            windows_db_path: Path to _windows.db
            case_description: Case description for filtering/analysis
            max_artifacts: Maximum artifacts to analyze per type
            artifact_types: Artifact types to process (None = all)
            progress_callback: Optional progress callback

        Returns:
            Analysis results with statistics
        """
        if not self._windows_service:
            raise RuntimeError("Windows artifacts service not initialized")

        return await self._windows_service.run_full_analysis(
            task_id=task_id,
            windows_db_path=windows_db_path,
            case_description=case_description,
            max_artifacts=max_artifacts,
            artifact_types=artifact_types,
            progress_callback=progress_callback,
        )

    async def reanalyze_windows_artifacts(
        self,
        task_id: str,
        artifact_ids: List[tuple],  # List of (artifact_type, artifact_id)
        user_hint: str,
        windows_db_path: str,
        case_description: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Re-analyze specific Windows artifacts with additional user context.

        Args:
            task_id: Task identifier
            artifact_ids: List of (artifact_type, artifact_id) tuples
            user_hint: Additional user context
            windows_db_path: Path to _windows.db
            case_description: Original case description

        Returns:
            Analysis results for re-analyzed artifacts
        """
        if not self._windows_service:
            raise RuntimeError("Windows artifacts service not initialized")

        return await self._windows_service.reanalyze_artifacts(
            task_id=task_id,
            artifact_ids=artifact_ids,
            user_hint=user_hint,
            windows_db_path=windows_db_path,
            case_description=case_description,
        )

    def get_windows_report(
        self,
        windows_db_path: str,
        task_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve the persisted Windows artifact analysis report.

        Args:
            windows_db_path: Path to _windows.db
            task_id: Task identifier

        Returns:
            Report data or None if not found
        """
        if not self._windows_service:
            raise RuntimeError("Windows artifacts service not initialized")

        return self._windows_service.get_artifact_report(
            windows_db_path=windows_db_path,
            task_id=task_id
        )

    def get_filtered_windows_artifacts(
        self,
        windows_db_path: str,
        artifact_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get filtered Windows artifact descriptions from database."""
        if not self._windows_service:
            raise RuntimeError("Windows artifacts service not initialized")

        return self._windows_service.get_filtered_artifacts(
            windows_db_path=windows_db_path,
            artifact_type=artifact_type,
            severity=severity,
            limit=limit,
        )

    async def extract_filtered_files(
        self,
        task_id: str,
        file_paths: List[str],
        extraction_dir: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Extract filtered files to local disk.

        Calls C++ backend's file extraction API to extract selected files
        from the disk image so they can be analyzed by LLM.

        Args:
            task_id: Task ID
            file_paths: List of file paths to extract
            extraction_dir: Extraction directory (None = use default)
            progress_callback: Progress callback (current, total, file_path)

        Returns:
            Dict containing extraction results
        """
        if not file_paths:
            return {"success": True, "extracted_count": 0, "extraction_dir": ""}

        if not self._cpp_backend:
            raise RuntimeError("C++ backend service not initialized")

        try:
            # Get task info to determine extraction directory
            task_info = await self._cpp_backend.get_task(task_id)
            if not task_info:
                logger.error(f"Task {task_id} not found when trying to extract files.")
                raise RuntimeError(f"Task {task_id} not found")

            # Determine extraction directory
            # Priority: extraction_dir parameter > task's extraction_directory > default
            if not extraction_dir:
                extraction_dir = task_info.get("extraction_directory", "")

            # Make it absolute if it's not
            if extraction_dir and not os.path.isabs(extraction_dir):
                project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
                if not os.path.exists(os.path.join(project_root, "build")):
                    project_root = os.getcwd()
                extraction_dir = os.path.join(project_root, extraction_dir)

            if not extraction_dir:
                # Use task-specific directory under default extracted_files
                project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
                if not os.path.exists(os.path.join(project_root, "build")):
                    project_root = os.getcwd()
                extraction_dir = os.path.join(project_root, "build", "data", "tasks", task_id, "extracted_files")

            logger.info(f"Task {task_id}: Final determined extraction directory: {extraction_dir}")
            logger.info(f"Task {task_id}: Starting targeted extraction of {len(file_paths)} files")

            # Start extraction task
            extract_result = await self._cpp_backend.extract_files(
                task_id=task_id,
                file_paths=file_paths,
                output_dir=extraction_dir,
                overwrite=False,  # Don't overwrite existing files
            )

            job_id = extract_result.get("job_id")
            if not job_id:
                logger.error(f"Task {task_id}: Extraction API failed to return job_id. Result: {extract_result}")
                raise RuntimeError("Extract API did not return a job_id")

            logger.info(f"Task {task_id}: Extraction job {job_id} started. Waiting for completion...")

            # Poll for completion
            max_wait = 600  # 10 minutes timeout
            start_time = asyncio.get_event_loop().time()
            poll_interval = 2  # Check every 2 seconds

            while True:
                status = await self._cpp_backend.get_extraction_status(job_id)
                state = status.get("status", "unknown")

                # Log progress periodically
                if state == "running":
                    logger.info(f"Job {job_id} progress: {status.get('progress', 0)}% ({status.get('extracted_files', 0)}/{status.get('total_files', len(file_paths))})")

                if state == "completed":
                    logger.info(f"Task {task_id}: Extraction job {job_id} completed successfully.")
                    return {
                        "success": True,
                        "extracted_count": status.get("extracted_files", 0),
                        "extraction_dir": status.get("output_path", extraction_dir),
                    }
                elif state == "failed":
                    error_msg = status.get("error_details", "Unknown error")
                    raise RuntimeError(f"Extraction failed: {error_msg}")
                elif state == "cancelled":
                    raise RuntimeError("Extraction was cancelled")

                # Check timeout
                if asyncio.get_event_loop().time() - start_time > max_wait:
                    raise RuntimeError("Extraction timeout after 10 minutes")

                # Report progress
                if progress_callback:
                    extracted = status.get("extracted_files", 0)
                    total_files = status.get("total_files", len(file_paths))
                    await progress_callback(extracted, total_files, f"提取中... ({extracted}/{total_files})")

                await asyncio.sleep(poll_interval)

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"File extraction failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "extracted_count": 0,
                "extraction_dir": "",
            }

