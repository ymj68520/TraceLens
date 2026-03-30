"""
Case Analysis Service — Main service class for LLM-driven forensic case analysis.

This is the main entry point that coordinates file filtering, analysis, and report generation.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings

from .file_filter import FileFilter
from .file_analyzer import FileAnalyzer
from .report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class CaseAnalysisService:
    """Service for end-to-end LLM case analysis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # Will be injected after ServiceManager init
        self._llm_service = None
        self._graphiti_service = None
        self._cpp_backend = None

        # Sub-modules (initialized after dependency injection)
        self._file_filter = None
        self._file_analyzer = None
        self._report_generator = None

    def set_llm_service(self, llm_service):
        """Inject the LLM service dependency."""
        self._llm_service = llm_service
        self._initialize_modules()

    def set_graphiti_service(self, graphiti_service):
        """Inject the Graphiti knowledge graph service (optional)."""
        self._graphiti_service = graphiti_service
        self._initialize_modules()

    def set_cpp_backend(self, cpp_backend):
        """Inject the C++ backend service dependency."""
        self._cpp_backend = cpp_backend
        self._initialize_modules()

    def _initialize_modules(self):
        """Initialize sub-modules after all dependencies are injected."""
        if self._llm_service and self._cpp_backend and not self._file_filter:
            self._file_filter = FileFilter(self.settings, self._llm_service, self._cpp_backend)
            self._file_analyzer = FileAnalyzer(self.settings, self._llm_service, self._graphiti_service)
            self._report_generator = ReportGenerator(self.settings, self._llm_service, self._graphiti_service)
            logger.info("Case analysis sub-modules initialized")

    # ------------------------------------------------------------------
    # Public API - delegated to sub-modules
    # ------------------------------------------------------------------

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
    ) -> bool:
        """Ingest case description and file descriptions into Graphiti."""
        if not self._file_analyzer:
            raise RuntimeError("FileAnalyzer module not initialized. Ensure all dependencies are injected.")
        return await self._file_analyzer.ingest_to_knowledge_graph(
            task_id, case_description, file_descriptions
        )

    async def generate_case_report(
        self,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        files_db_path: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a comprehensive case analysis report."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return await self._report_generator.generate_final_report(
            case_description, file_descriptions, files_db_path, task_id
        )

    def get_case_report(self, files_db_path: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a persisted case report from the database."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return self._report_generator.get_case_report(files_db_path, task_id)

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """Retrieve the list of case-relevant files."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return self._report_generator.get_filtered_files(files_db_path, task_id)

    # ------------------------------------------------------------------
    # File Extraction (handled by main service)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Full Pipeline — run all steps sequentially
    # ------------------------------------------------------------------
    async def run_full_analysis(
        self,
        task_id: str,
        files_db_path: str,
        case_description: str,
        max_filter_files: int = 200,
        run_filtering: bool = True,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run the complete case analysis pipeline.

        Steps:
            1. Filter files by case relevance (Optional)
            2. Generate per-file descriptions
            3. Generate final case report
        """
        result = {
            "task_id": task_id,
            "case_description": case_description,
            "steps": {},
        }

        filtered_files = []
        descriptions = []
        extraction_dir = ""
        extract_result = {"extracted_count": 0, "extraction_dir": ""}

        if run_filtering:
            # --- FULL PIPELINE MODE (Initial Task or Explicit Re-scan) ---

            # Step 1: Filter files via LLM
            if progress_callback:
                await progress_callback("filtering", "正在使用 LLM 自动筛选关键文件...")
            filter_result = await self.filter_files_by_case(
                files_db_path, case_description, max_filter_files, task_id=task_id
            )
            result["steps"]["filter"] = filter_result
            filtered_files = filter_result.get("filtered_files", [])

            # Persist the list so we can recover if subsequent steps fail
            self._file_filter._persist_filtered_files(files_db_path, task_id, filtered_files)

            if not filtered_files:
                msg = "LLM 未能在样本中筛选出与案情高度相关的文件。跳过文件提取和描述阶段。"
                logger.info(f"Task {task_id}: {msg}")
                result["steps"]["extraction"] = {"extraction_dir": "", "extracted_count": 0}
                result["steps"]["descriptions"] = []
            else:
                # Step 2: Extract filtered files to local disk
                if progress_callback:
                    await progress_callback("extracting", f"正在提取 {len(filtered_files)} 个文件到本地...")

                try:
                    extract_result = await self.extract_filtered_files(
                        task_id, filtered_files, progress_callback=progress_callback
                    )
                    result["steps"]["extraction"] = extract_result
                    extraction_dir = extract_result.get("extraction_dir", "")
                except Exception as e:
                    logger.error(f"Extraction step critical failure: {e}", exc_info=True)
                    result["steps"]["extraction"] = {"success": False, "error": str(e), "extracted_count": 0}

                # Step 3: Generate per-file descriptions
                if progress_callback:
                    await progress_callback("describing", f"正在分析 {len(filtered_files)} 个相关文件...")

                try:
                    descriptions = await self.generate_file_descriptions(
                        files_db_path, filtered_files, case_description, extraction_dir=extraction_dir,
                        progress_callback=progress_callback
                    )
                    result["steps"]["descriptions"] = descriptions
                except Exception as e:
                    logger.error(f"Description step failure: {e}", exc_info=True)

                # Step 3.6: Auto-analyze top event clusters for Timeline
                try:
                    if progress_callback:
                        await progress_callback("analyzing_clusters", "正在自动研判关键时间线事件簇...")

                    task_info = await self._cpp_backend.get_task(task_id)
                    events_db = task_info.get("output_events_db") or ""

                    if events_db and os.path.exists(events_db):
                        cluster_results = await self._file_analyzer.analyze_event_clusters(
                            events_db, case_description, limit=5
                        )
                        result["steps"]["event_clusters"] = {
                            "analyzed_count": len(cluster_results),
                            "success": True
                        }
                    else:
                        logger.warning(f"Task {task_id}: No events database found for cluster analysis")
                except Exception as e:
                    logger.error(f"Event cluster auto-analysis failed: {e}", exc_info=True)

                # Step 3.5: Ingest into knowledge graph
                if self._graphiti_service:
                    if progress_callback:
                        await progress_callback("ingesting", "正在将分析结果摄入知识图谱...")
                    try:
                        kg_ok = await self.ingest_to_knowledge_graph(
                            task_id, case_description, descriptions
                        )
                        result["steps"]["knowledge_graph"] = {"ingested": kg_ok, "episodes": len(descriptions) + 1}
                    except Exception as e:
                        logger.warning(f"KG ingestion failed (non-fatal): {e}")

        else:
            # --- FAST REPORTING MODE (Manual Review / Refinement) ---
            if progress_callback:
                await progress_callback("reporting_init", "跳过前置分析，正在根据当前研判结论生成报告...")

            # When run_filtering is False, we pass an empty descriptions list
            # generate_case_report will then automatically pull ALL 'relevant'
            # descriptions directly from the database.
            logger.info(f"Task {task_id}: Fast reporting mode. Skipping filter/extract/describe.")

        # Step 4: Final Case Report Generation (Common Path)
        if progress_callback:
            await progress_callback("reporting", "正在合成综合案情分析报告...")

        report = await self.generate_case_report(
            case_description, descriptions, files_db_path, task_id
        )
        result["steps"]["report"] = report

        logger.info(f"Task {task_id}: Full analysis pipeline completed.")
        logger.info(f"  - Files filtered: {len(filtered_files)}")
        logger.info(f"  - Files extracted: {extract_result.get('extracted_count', 0)}")
        logger.info(f"  - Files described: {len(descriptions)}")
        if self._graphiti_service:
            logger.info(f"  - KG ingestion: {result['steps'].get('knowledge_graph', {}).get('ingested', False)}")

        return result
