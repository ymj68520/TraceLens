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
from .multi_image_filter import MultiImageFilter
from .file_analyzer import FileAnalyzer
from .report_generator import ReportGenerator
from .cluster_analyzer import ClusterAnalyzer
from ..windows_artifacts import WindowsArtifactsService

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
        self._multi_filter = None
        self._file_analyzer = None
        self._report_generator = None
        self._cluster_analyzer = None
        self._windows_service = None  # Windows artifacts service

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
            self._report_generator = ReportGenerator(self.settings, self._llm_service, self._graphiti_service)
            self._cluster_analyzer = ClusterAnalyzer(self.settings, self._llm_service, self._graphiti_service)
            logger.info("Case analysis sub-modules initialized")
            if self._graphiti_service:
                logger.info("Graphiti service is available for knowledge graph features")
            else:
                logger.info("Graphiti service not available - knowledge graph features will be disabled")

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

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """Retrieve the list of case-relevant files."""
        if not self._report_generator:
            raise RuntimeError("ReportGenerator module not initialized. Ensure all dependencies are injected.")
        return self._report_generator.get_filtered_files(files_db_path, task_id)

    # ------------------------------------------------------------------
    # Windows Artifacts Analysis
    # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Smart detection: Auto-enable filtering if no filtered files exist
        # ------------------------------------------------------------------
        has_existing_filtered = False
        if not run_filtering:
            from .db_utils import get_filtered_files_from_db
            existing_filtered = get_filtered_files_from_db(files_db_path, task_id)
            if not existing_filtered:
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: No filtered files found in database, auto-enabling filtering")
                run_filtering = True
            else:
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: Found {len(existing_filtered)} existing filtered files, skipping filter step")
                filtered_files = existing_filtered
                has_existing_filtered = True

        if run_filtering:
            # --- FULL PIPELINE MODE (Initial Task or Explicit Re-scan) ---

            # Step 1: Filter files via LLM
            if progress_callback:
                await progress_callback("filtering", "正在使用 LLM 自动筛选关键文件...")
            logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting LLM file filtering...")
            logger.info(f"[CASE_ANALYSIS] files_db_path: {files_db_path}")
            logger.info(f"[CASE_ANALYSIS] case_description length: {len(case_description)}")
            logger.info(f"[CASE_ANALYSIS] max_filter_files: {max_filter_files}")

            filter_result = await self.filter_files_by_case(
                files_db_path, case_description, max_filter_files, task_id=task_id
            )
            result["steps"]["filter"] = filter_result
            filtered_files = filter_result.get("filtered_files", [])

            logger.info(f"[CASE_ANALYSIS] Task {task_id}: LLM filtering complete.")
            logger.info(f"[CASE_ANALYSIS]   - filtered_files count: {len(filtered_files)}")
            logger.info(f"[CASE_ANALYSIS]   - total_files: {filter_result.get('total_files', 0)}")
            logger.info(f"[CASE_ANALYSIS]   - reasoning: {filter_result.get('reasoning', '')[:200]}")

            # Persist the list so we can recover if subsequent steps fail
            self._file_filter._persist_filtered_files(files_db_path, task_id, filtered_files)

            if not filtered_files:
                msg = "LLM 未能在样本中筛选出与案情高度相关的文件。跳过文件提取和描述阶段。"
                logger.warning(f"[CASE_ANALYSIS] Task {task_id}: {msg}")
                logger.warning(f"[CASE_ANALYSIS] Task {task_id}: This will skip file extraction, AI analysis, and Graphiti ingestion!")
                result["steps"]["extraction"] = {"extraction_dir": "", "extracted_count": 0}
                result["steps"]["descriptions"] = []
            else:
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: Proceeding with {len(filtered_files)} filtered files for extraction")
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: Sample files to extract: {filtered_files[:5]}")

                # Step 2: Extract filtered files to local disk
                if progress_callback:
                    await progress_callback("extracting", f"正在提取 {len(filtered_files)} 个文件到本地...")

                try:
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting file extraction...")
                    extract_result = await self.extract_filtered_files(
                        task_id, filtered_files, progress_callback=progress_callback
                    )
                    result["steps"]["extraction"] = extract_result
                    extraction_dir = extract_result.get("extraction_dir", "")
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: Extraction completed - dir: {extraction_dir}, count: {extract_result.get('extracted_count', 0)}")
                except Exception as e:
                    logger.error(f"[CASE_ANALYSIS] Task {task_id}: Extraction step critical failure: {e}", exc_info=True)
                    result["steps"]["extraction"] = {"success": False, "error": str(e), "extracted_count": 0}
                    extraction_dir = ""

                # Step 3: Parallel execution of file analysis and event cluster analysis
                if progress_callback:
                    await progress_callback("analyzing", "正在并行分析文件和事件簇...")

                logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting file description generation...")
                # Prepare parallel tasks
                file_task = asyncio.create_task(self.generate_file_descriptions(
                    files_db_path, filtered_files, case_description, extraction_dir=extraction_dir,
                    progress_callback=progress_callback
                ))

                # Get events_db path for cluster analysis
                task_info = await self._cpp_backend.get_task(task_id)
                events_db = task_info.get("output_events_db") or ""

                cluster_task = None
                if events_db and os.path.exists(events_db):
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting event cluster analysis...")
                    cluster_task = asyncio.create_task(self._cluster_analyzer.analyze_and_ingest_clusters(
                        events_db, case_description, task_id, progress_callback
                    ))

                # Wait for file analysis
                try:
                    descriptions = await file_task
                    result["steps"]["descriptions"] = descriptions
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: File descriptions completed - {len(descriptions)} files analyzed")
                except Exception as e:
                    logger.error(f"[CASE_ANALYSIS] Task {task_id}: Description step failure: {e}", exc_info=True)
                    descriptions = []

                # Wait for cluster analysis (if started)
                cluster_results = []
                if cluster_task:
                    try:
                        cluster_results = await cluster_task
                        result["steps"]["event_clusters"] = {
                            "analyzed_count": len(cluster_results),
                            "success": True
                        }
                        logger.info(f"[CASE_ANALYSIS] Task {task_id}: Event cluster analysis completed - {len(cluster_results)} clusters")
                    except Exception as e:
                        logger.error(f"[CASE_ANALYSIS] Task {task_id}: Event cluster analysis failed: {e}", exc_info=True)

                # Step 4: Ingest to knowledge graph (files + clusters)
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: Checking graphiti_service for ingestion...")
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: _graphiti_service is None: {self._graphiti_service is None}")
                if self._graphiti_service:
                    if progress_callback:
                        await progress_callback("ingesting", "正在将分析结果摄入知识图谱...")
                    try:
                        logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting KG ingestion with {len(descriptions)} file descriptions and {len(cluster_results)} cluster descriptions")
                        kg_ok = await self.ingest_to_knowledge_graph(
                            task_id, case_description, descriptions, cluster_descriptions=cluster_results
                        )
                        logger.info(f"[CASE_ANALYSIS] Task {task_id}: KG ingestion completed, result: {kg_ok}")
                        result["steps"]["knowledge_graph"] = {
                            "ingested": kg_ok,
                            "file_episodes": len(descriptions),
                            "cluster_episodes": len(cluster_results)
                        }
                    except Exception as e:
                        logger.error(f"[CASE_ANALYSIS] Task {task_id}: KG ingestion failed (non-fatal): {e}", exc_info=True)
                        result["steps"]["knowledge_graph"] = {
                            "ingested": False,
                            "error": str(e),
                            "file_episodes": len(descriptions),
                            "cluster_episodes": len(cluster_results)
                        }
                else:
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: graphiti_service not available, skipping KG ingestion")
                    result["steps"]["knowledge_graph"] = {
                        "skipped": True,
                        "reason": "graphiti_service not available"
                    }

        else:
            # --- REUSE EXISTING FILTERED FILES MODE ---
            if has_existing_filtered:
                # We have filtered files but didn't just run filtering
                # Still need to extract and describe if not done yet
                if progress_callback:
                    await progress_callback("reusing", f"使用已筛选的 {len(filtered_files)} 个文件，继续执行提取和分析...")

                logger.info(f"Task {task_id}: Reusing {len(filtered_files)} existing filtered files")

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

                # Step 3: File analysis and event cluster analysis
                if progress_callback:
                    await progress_callback("analyzing", "正在并行分析文件和事件簇...")

                # Prepare parallel tasks
                file_task = asyncio.create_task(self.generate_file_descriptions(
                    files_db_path, filtered_files, case_description, extraction_dir=extraction_dir,
                    progress_callback=progress_callback
                ))

                # Get events_db path for cluster analysis
                task_info = await self._cpp_backend.get_task(task_id)
                events_db = task_info.get("output_events_db") or ""

                cluster_task = None
                if events_db and os.path.exists(events_db):
                    cluster_task = asyncio.create_task(self._cluster_analyzer.analyze_and_ingest_clusters(
                        events_db, case_description, task_id, progress_callback
                    ))

                # Wait for file analysis
                try:
                    descriptions = await file_task
                    result["steps"]["descriptions"] = descriptions
                except Exception as e:
                    logger.error(f"Description step failure: {e}", exc_info=True)
                    descriptions = []

                # Wait for cluster analysis (if started)
                cluster_results = []
                if cluster_task:
                    try:
                        cluster_results = await cluster_task
                        result["steps"]["event_clusters"] = {
                            "analyzed_count": len(cluster_results),
                            "success": True
                        }
                    except Exception as e:
                        logger.error(f"Event cluster analysis failed: {e}", exc_info=True)

                # Step 4: Ingest to knowledge graph (files + clusters)
                logger.info(f"[CASE_ANALYSIS] Task {task_id}: [REUSE MODE] Checking graphiti_service for ingestion...")
                if self._graphiti_service:
                    if progress_callback:
                        await progress_callback("ingesting", "正在将分析结果摄入知识图谱...")
                    try:
                        logger.info(f"[CASE_ANALYSIS] Task {task_id}: [REUSE MODE] Starting KG ingestion with {len(descriptions)} file descriptions and {len(cluster_results)} cluster descriptions")
                        kg_ok = await self.ingest_to_knowledge_graph(
                            task_id, case_description, descriptions, cluster_descriptions=cluster_results
                        )
                        logger.info(f"[CASE_ANALYSIS] Task {task_id}: [REUSE MODE] KG ingestion completed, result: {kg_ok}")
                        result["steps"]["knowledge_graph"] = {
                            "ingested": kg_ok,
                            "file_episodes": len(descriptions),
                            "cluster_episodes": len(cluster_results)
                        }
                    except Exception as e:
                        logger.error(f"[CASE_ANALYSIS] Task {task_id}: [REUSE MODE] KG ingestion failed (non-fatal): {e}", exc_info=True)
                        result["steps"]["knowledge_graph"] = {
                            "ingested": False,
                            "error": str(e),
                            "file_episodes": len(descriptions),
                            "cluster_episodes": len(cluster_results)
                        }
                else:
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: [REUSE MODE] graphiti_service not available, skipping KG ingestion")
                    result["steps"]["knowledge_graph"] = {
                        "skipped": True,
                        "reason": "graphiti_service not available"
                    }
            else:
                # --- FAST REPORTING MODE (Manual Review / Refinement) ---
                if progress_callback:
                    await progress_callback("reporting_init", "跳过前置分析，正在根据当前研判结论生成报告...")

                # When run_filtering is False and no existing filtered files,
                # generate_case_report will pull ALL 'relevant' descriptions from database.
                logger.info(f"Task {task_id}: Fast reporting mode. Skipping filter/extract/describe.")

        # Step 5: Final Case Report Generation (Common Path)
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

    # ------------------------------------------------------------------
    # Multi-Image Pipeline (Case-level analysis)
    # ------------------------------------------------------------------

    async def run_multi_image_analysis(
        self,
        case_id: str,
        task_ids: List[str],
        files_db_paths: List[str],
        case_description: str,
        max_filter_files: int = 400,
        events_db_paths: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run cross-image analysis for a ForensicCase.

        Steps:
          1. Aggregate + deduplicate files across all _files.db databases
          2. LLM-filter relevant files (cross-image aware)
          3. Extract + describe files per image (reuses run_full_analysis pipeline)
          4. Ingest all data into case-level knowledge graph
          5. Generate combined case report using case-level graph

        Key changes:
          - Case-level Graphiti graph for cross-image semantic search
          - Report generation uses case_id instead of task_id
          - Report aggregates data from all images
        """
        if not self._multi_filter:
            raise RuntimeError("MultiImageFilter not initialized. Ensure all dependencies are injected.")

        if not events_db_paths:
            events_db_paths = []

        result: Dict[str, Any] = {
            "case_id": case_id,
            "task_ids": task_ids,
            "case_description": case_description,
            "steps": {},
        }

        if progress_callback:
            await progress_callback("filtering", f"正在跨 {len(files_db_paths)} 个镜像筛选关键文件...")

        # Step 1 — Cross-image LLM filter
        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: starting multi-image filter "
                    f"({len(files_db_paths)} images)")
        filter_result = await self._multi_filter.filter_files_multi(
            files_db_paths=files_db_paths,
            case_description=case_description,
            max_files=max_filter_files,
            task_ids=task_ids,
        )
        result["steps"]["filter"] = {
            "total_files":     filter_result.get("total_files", 0),
            "selected_count":  filter_result.get("selected_count", 0),
            "dedup_removed":   filter_result.get("dedup_removed", 0),
            "source_counts":   filter_result.get("source_counts", {}),
        }
        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: filter done — "
                    f"{filter_result.get('selected_count', 0)} files selected")

        # Step 2 — Per-image extraction + description (run single-image pipelines)
        all_descriptions: List[Dict[str, Any]] = []

        for idx, (task_id, db_path) in enumerate(zip(task_ids, files_db_paths)):
            if progress_callback:
                await progress_callback(
                    "analyzing",
                    f"正在分析镜像 {idx+1}/{len(task_ids)}（task {task_id[:8]}）..."
                )
            logger.info(f"[MULTI_ANALYSIS] Case {case_id}: running per-image pipeline "
                        f"for task {task_id} (db: {db_path})")
            try:
                img_result = await self.run_full_analysis(
                    task_id=task_id,
                    files_db_path=db_path,
                    case_description=case_description,
                    max_filter_files=max_filter_files,
                    run_filtering=False,   # filtered files already persisted in Step 1
                    progress_callback=None,
                )
                descs = img_result.get("steps", {}).get("descriptions", [])
                all_descriptions.extend(descs)
                result["steps"][f"image_{idx+1}"] = {
                    "task_id": task_id,
                    "described": len(descs),
                }
            except Exception as e:
                logger.error(f"[MULTI_ANALYSIS] Image {idx+1} pipeline failed: {e}", exc_info=True)
                result["steps"][f"image_{idx+1}"] = {"task_id": task_id, "error": str(e)}

        # Step 3 — Ingest all data into case-level knowledge graph
        if self._graphiti_service:
            if progress_callback:
                await progress_callback("ingesting_case", "正在将所有镜像的分析结果摄入案例级知识图谱...")

            logger.info(f"[MULTI_ANALYSIS] Case {case_id}: starting case-level graph ingestion")
            try:
                kg_success = await self._graphiti_service.ingest_case_data(
                    case_id=case_id,
                    task_ids=task_ids,
                    files_db_paths=files_db_paths,
                    events_db_paths=events_db_paths,
                    progress_callback=progress_callback,
                )
                result["steps"]["knowledge_graph"] = {
                    "ingested": kg_success,
                    "case_id": case_id,
                    "task_count": len(task_ids),
                }
                logger.info(f"[MULTI_ANALYSIS] Case {case_id}: case-level graph ingestion completed: {kg_success}")
            except Exception as e:
                logger.error(f"[MULTI_ANALYSIS] Case {case_id}: case-level graph ingestion failed: {e}", exc_info=True)
                result["steps"]["knowledge_graph"] = {
                    "ingested": False,
                    "error": str(e),
                }
        else:
            logger.info(f"[MULTI_ANALYSIS] Case {case_id}: graphiti_service not available, skipping case-level graph ingestion")
            result["steps"]["knowledge_graph"] = {
                "skipped": True,
                "reason": "graphiti_service not available"
            }

        # Step 4 — Combined report using case-level graph
        if progress_callback:
            await progress_callback("reporting", "正在生成跨镜像综合报告（使用案例级知识图谱）...")

        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: generating cross-image report using case-level graph")
        try:
            combined_report = await self.generate_case_report(
                case_description=case_description,
                file_descriptions=all_descriptions,
                files_db_paths=files_db_paths,  # Pass all databases for aggregation
                task_id=case_id,
                task_ids=task_ids,  # Pass all task IDs for graph search
                is_cross_image_report=True,
            )
            result["steps"]["report"] = combined_report
        except Exception as e:
            logger.error(f"[MULTI_ANALYSIS] Case {case_id}: report generation failed: {e}", exc_info=True)
            result["steps"]["report"] = {
                "error": str(e),
                "report": "报告生成失败：" + str(e)
            }

        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: complete — "
                    f"{len(all_descriptions)} total files described across {len(task_ids)} images")
        return result
