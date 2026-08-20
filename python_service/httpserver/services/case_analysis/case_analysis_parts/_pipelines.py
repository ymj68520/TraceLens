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


class CaseAnalysisPipelinesMixin:
    """Auto-extracted method group; see module docstring."""

    async def run_full_analysis(
        self,
        task_id: str,
        files_db_path: str,
        case_description: str,
        max_filter_files: int = 200,
        run_filtering: bool = True,
        report_only: bool = False,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run the complete case analysis pipeline.

        Steps:
            1. Filter files by case relevance (Optional)
            2. Generate per-file descriptions
            3. Generate final case report

        Args:
            report_only: If True, skip all pipeline steps (filter/extract/describe/ingest)
                and only regenerate the report from existing evidence in the database.
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
        # Report-only mode: skip entire pipeline, go straight to report
        # ------------------------------------------------------------------
        if report_only:
            logger.info(f"[CASE_ANALYSIS] Task {task_id}: Report-only mode. Skipping filter/extract/describe/ingest.")
            if progress_callback:
                await progress_callback("reporting_init", "仅重新生成报告，使用已有证据数据...")

        else:
            # ------------------------------------------------------------------
            # Smart detection: Auto-enable filtering if no filtered files exist
            # ------------------------------------------------------------------
            has_existing_filtered = False
            if not run_filtering:
                from ..db_utils import get_filtered_files_from_db
                existing_filtered = get_filtered_files_from_db(files_db_path, task_id)
                if not existing_filtered:
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: No filtered files found in database, auto-enabling filtering")
                    run_filtering = True
                else:
                    logger.info(f"[CASE_ANALYSIS] Task {task_id}: Found {len(existing_filtered)} existing filtered files, skipping filter step")
                    filtered_files = existing_filtered
                    has_existing_filtered = True

        if not report_only and run_filtering:
            # --- FULL PIPELINE MODE (Initial Task or Explicit Re-scan) ---

            # Step 1: Filter files (deterministic by default; reuses C++ profile)
            filter_mode = getattr(self.settings, "file_filter_mode", "deterministic")
            if progress_callback:
                if filter_mode == "llm":
                    await progress_callback("filtering", "正在使用 LLM 自动筛选关键文件...")
                else:
                    await progress_callback("filtering", "正在使用确定性分类筛选（复用 C++ profile）...")
            logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting file filtering (mode={filter_mode})...")
            logger.info(f"[CASE_ANALYSIS] files_db_path: {files_db_path}")
            logger.info(f"[CASE_ANALYSIS] case_description length: {len(case_description)}")
            logger.info(f"[CASE_ANALYSIS] max_filter_files: {max_filter_files} "
                        f"(ignored in deterministic mode; cap=settings.filter_max_files)")

            filter_result = await self.filter_files_by_case(
                files_db_path, case_description, max_filter_files, task_id=task_id
            )
            result["steps"]["filter"] = filter_result
            filtered_files = filter_result.get("filtered_files", [])

            logger.info(f"[CASE_ANALYSIS] Task {task_id}: File filtering complete.")
            logger.info(f"[CASE_ANALYSIS]   - filtered_files count: {len(filtered_files)}")
            logger.info(f"[CASE_ANALYSIS]   - total_files: {filter_result.get('total_files', 0)}")
            logger.info(f"[CASE_ANALYSIS]   - reasoning: {filter_result.get('reasoning', '')[:200]}")

            # Persist the list so we can recover if subsequent steps fail
            self._file_filter._persist_filtered_files(files_db_path, task_id, filtered_files)

            if not filtered_files:
                msg = "未能在样本中筛选出符合要求的文件。跳过文件提取和描述阶段。"
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
            if not report_only and has_existing_filtered:
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
                # NOTE: files_db_path is still needed for report persistence and DB aggregation

        # Step 5: Final Case Report Generation (Common Path)
        if progress_callback:
            await progress_callback("reporting", "正在合成综合案情分析报告...")

        # Ensure files_db_path is resolved for report persistence
        if not files_db_path and task_id and self._cpp_backend:
            try:
                task_info = await self._cpp_backend.get_task(task_id)
                if task_info:
                    files_db_path = task_info.get("output_files_db") or task_info.get("output_files_db_path", "")
                    if files_db_path:
                        logger.info(f"Task {task_id}: Resolved files_db_path from task info: {files_db_path}")
            except Exception as e:
                logger.warning(f"Task {task_id}: Could not resolve files_db_path: {e}")

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

        # Step 1 — Cross-image filter (deterministic by default)
        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: starting multi-image filter "
                    f"({len(files_db_paths)} images, mode={getattr(self.settings, 'file_filter_mode', 'deterministic')})")
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

    async def run_smart_case_analysis(
        self,
        case_name: str,
        case_description: str,
        auto_associate: bool = True,
        auto_analyze: bool = True,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        智能案件分析 - 自动发现并关联已完成任务

        Flow:
        1. Create case via C++ backend
        2. Scan and auto-associate completed tasks
        3. Execute incremental analysis (skip already-analyzed tasks)
        4. Generate case-level report

        Args:
            case_name: Case name
            case_description: Case description for LLM analysis
            auto_associate: Auto-associate completed tasks to case
            auto_analyze: Automatically execute analysis after association
            progress_callback: Optional progress callback (stage, message)

        Returns:
            Dict with analysis results including case_id, tasks analyzed, etc.
        """
        result = {
            "case_name": case_name,
            "case_description": case_description,
            "steps": {},
        }

        # Step 1: Create case via C++ backend API
        if progress_callback:
            await progress_callback("creating_case", "正在创建案件...")

        logger.info(f"[SMART_CASE] Creating case: {case_name}")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.settings.cpp_backend_url}/api/cases",
                    json={
                        "name": case_name,
                        "description": case_description,
                        "task_ids": [],  # Start empty, will auto-associate
                    },
                )
                if response.status_code not in (200, 201):
                    raise RuntimeError(f"C++ backend returned {response.status_code}: {response.text}")

                case_response = response.json()
                case_id = case_response.get("id")
                if not case_id:
                    raise RuntimeError("Failed to create case - no ID returned")

                result["case_id"] = case_id
                result["steps"]["create_case"] = {"success": True, "case_id": case_id}

        except Exception as e:
            logger.error(f"[SMART_CASE] Failed to create case: {e}", exc_info=True)
            result["steps"]["create_case"] = {"success": False, "error": str(e)}
            return result

        # Step 2: Scan and associate completed tasks
        if progress_callback:
            await progress_callback("scanning_tasks", "正在扫描已完成任务...")

        try:
            association_result = await self._case_aggregation.scan_and_associate_completed_tasks(
                case_id=case_id,
                auto_associate=auto_associate,
                progress_callback=progress_callback,
            )
            result["steps"]["scan_tasks"] = association_result

            # Check if we have tasks to analyze
            total_tasks = (
                len(association_result.get("already_analyzed", [])) +
                len(association_result.get("pending_analysis", []))
            )

            if total_tasks == 0:
                result["steps"]["analysis"] = {
                    "skipped": True,
                    "reason": "No completed tasks found to analyze"
                }
                return result

        except Exception as e:
            logger.error(f"[SMART_CASE] Failed to scan tasks: {e}", exc_info=True)
            result["steps"]["scan_tasks"] = {"error": str(e)}
            return result

        # Step 3: Execute incremental analysis
        if auto_analyze:
            analysis_result = await self.run_incremental_analysis(
                case_id=case_id,
                progress_callback=progress_callback,
            )
            result["steps"]["analysis"] = analysis_result
        else:
            result["steps"]["analysis"] = {"skipped": True, "reason": "auto_analyze=False"}

        return result

    async def run_incremental_analysis(
        self,
        case_id: str,
        new_task_ids: List[str] = None,
        force_reanalyze: bool = False,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        增量分析 - 仅分析新增或变更的任务

        Flow:
        1. Plan incremental analysis (determine which tasks need analysis)
        2. Skip already-analyzed tasks, reuse their file_descriptions
        3. Execute full analysis only on new/pending tasks
        4. Incrementally update case-level knowledge graph
        5. Generate updated case report

        Args:
            case_id: Case identifier
            new_task_ids: Optional list of new task IDs to add
            force_reanalyze: If True, reanalyze all tasks
            progress_callback: Optional progress callback (stage, message)

        Returns:
            Dict with analysis results
        """
        result = {
            "case_id": case_id,
            "new_task_ids": new_task_ids or [],
            "force_reanalyze": force_reanalyze,
            "steps": {},
        }

        if not self._case_aggregation:
            raise RuntimeError("CaseAggregationManager not initialized")

        # Step 1: Plan incremental analysis
        if progress_callback:
            await progress_callback("planning", "正在规划增量分析...")

        try:
            plan = await self._case_aggregation.plan_incremental_analysis(
                case_id=case_id,
                new_task_ids=new_task_ids,
            )
            result["steps"]["plan"] = plan

            if force_reanalyze:
                # Re-analyze all tasks
                case_status = await self._case_aggregation.get_case_analysis_status(case_id)
                all_task_ids = [t["task_id"] for t in case_status["tasks"]]
                plan["analyze_tasks"] = all_task_ids
                plan["skip_tasks"] = []

            if not plan["analyze_tasks"]:
                result["steps"]["analysis"] = {
                    "skipped": True,
                    "reason": "All tasks already analyzed",
                    "reuse_descriptions": plan["reuse_descriptions"],
                }
                return result

        except Exception as e:
            logger.error(f"[INCREMENTAL] Failed to plan analysis: {e}", exc_info=True)
            result["steps"]["plan"] = {"error": str(e)}
            return result

        # Step 2: Execute analysis on pending tasks
        if progress_callback:
            await progress_callback("analyzing", f"正在分析 {len(plan['analyze_tasks'])} 个任务...")

        try:
            # Define analysis function for each task
            async def analyze_single_task(task_id: str, case_id: str, progress_cb):
                """Analyze a single task using the full analysis pipeline"""
                # Get task info from C++ backend
                task_info = await self._cpp_backend.get_task(task_id)
                files_db = task_info.get("output_files_db", "")
                events_db = task_info.get("output_events_db", "")

                if not files_db:
                    raise RuntimeError(f"Task {task_id} has no files_db")

                # Run full analysis (filtering will be skipped if already done)
                return await self.run_full_analysis(
                    task_id=task_id,
                    files_db_path=files_db,
                    case_description=task_info.get("case_description", ""),
                    max_filter_files=200,
                    run_filtering=True,  # Will auto-skip if filtered files exist
                    progress_callback=progress_cb,
                )

            # Execute incremental analysis
            execution_result = await self._case_aggregation.execute_incremental_analysis(
                case_id=case_id,
                plan=plan,
                analyze_func=analyze_single_task,
                progress_callback=progress_callback,
            )
            result["steps"]["execution"] = execution_result

        except Exception as e:
            logger.error(f"[INCREMENTAL] Failed to execute analysis: {e}", exc_info=True)
            result["steps"]["execution"] = {"error": str(e)}
            return result

        # Step 3: Incremental knowledge graph update
        if self._graphiti_service:
            if progress_callback:
                await progress_callback("graph_ingestion", "正在更新知识图谱...")

            try:
                # Get all task IDs in case
                case_status = await self._case_aggregation.get_case_analysis_status(case_id)
                all_task_ids = [t["task_id"] for t in case_status["tasks"]]

                # Get database paths for all tasks
                files_db_paths = []
                events_db_paths = []

                for task_id in all_task_ids:
                    try:
                        task_info = await self._cpp_backend.get_task(task_id)
                        files_db = task_info.get("output_files_db", "")
                        events_db = task_info.get("output_events_db", "")
                        if files_db:
                            files_db_paths.append(files_db)
                        if events_db:
                            events_db_paths.append(events_db)
                    except Exception:
                        pass

                # Ingest only new/updated tasks' data
                kg_result = await self._graphiti_service.ingest_case_data(
                    case_id=case_id,
                    task_ids=all_task_ids,
                    files_db_paths=files_db_paths,
                    events_db_paths=events_db_paths,
                    progress_callback=progress_callback,
                )
                result["steps"]["knowledge_graph"] = {"ingested": kg_result}

            except Exception as e:
                logger.error(f"[INCREMENTAL] Graph ingestion failed: {e}", exc_info=True)
                result["steps"]["knowledge_graph"] = {"error": str(e)}

        # Step 4: Generate updated case report
        if progress_callback:
            await progress_callback("reporting", "正在生成案件报告...")

        try:
            # Aggregate all descriptions from all tasks
            all_descriptions = []
            case_status = await self._case_aggregation.get_case_analysis_status(case_id)

            for task_status in case_status["tasks"]:
                task_id = task_status["task_id"]
                try:
                    task_info = await self._cpp_backend.get_task(task_id)
                    files_db = task_info.get("output_files_db", "")
                    if files_db:
                        stats = get_file_description_stats(files_db)
                        if stats["analyzed_files"] > 0:
                            # Load descriptions from database
                            all_descriptions.extend(
                                [{"task_id": task_id, "has_analysis": True}] * stats["analyzed_files"]
                            )
                except Exception:
                    pass

            # Generate report
            report = await self.generate_case_report(
                case_description="",  # Will load from case
                file_descriptions=all_descriptions,
                task_id=case_id,
                is_cross_image_report=True,
            )
            result["steps"]["report"] = report

        except Exception as e:
            logger.error(f"[INCREMENTAL] Report generation failed: {e}", exc_info=True)
            result["steps"]["report"] = {"error": str(e)}

        logger.info(f"[INCREMENTAL] Case {case_id}: Complete - "
                    f"{len(execution_result.get('analyzed_tasks', []))} analyzed, "
                    f"{len(execution_result.get('skipped_tasks', []))} skipped")

        return result

