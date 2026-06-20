"""
Case Aggregation Manager — Coordinates incremental cross-image analysis.

This manager handles:
- Scanning and associating completed tasks to cases
- Checking task analysis status
- Planning incremental analysis (which tasks need analysis)
- Coordinating the execution of incremental analysis workflows
"""

import asyncio
import httpx
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

from ...config import Settings
from .db_utils import (
    TaskAnalysisState,
    get_case_db_path,
    ensure_case_task_status_table,
    update_task_analysis_status,
    get_task_analysis_status,
    get_case_all_task_status,
    get_file_description_stats,
)

logger = logging.getLogger(__name__)


class CaseAggregationManager:
    """
    案件聚合管理器 - 协调增量跨镜像分析

    Core responsibilities:
    1. Discover and auto-associate completed tasks to cases
    2. Track analysis state of each task within a case
    3. Plan incremental analysis (skip already-analyzed tasks)
    4. Coordinate execution of incremental analysis
    """

    def __init__(self, settings: Settings, cpp_backend, graphiti_service=None):
        """
        Initialize the Case Aggregation Manager.

        Args:
            settings: Server configuration settings
            cpp_backend: C++ backend service client
            graphiti_service: Optional Graphiti knowledge graph service
        """
        self.settings = settings
        self._cpp_backend = cpp_backend
        self._graphiti = graphiti_service

    # ─────────────────────────────────────────────────────────────────────────────
    # Public API: Task Discovery and Association
    # ─────────────────────────────────────────────────────────────────────────────

    async def scan_and_associate_completed_tasks(
        self,
        case_id: str,
        auto_associate: bool = True,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        扫描所有已完成的任务，自动关联到案件

        This method discovers all completed tasks from the C++ backend,
        checks their analysis status, and optionally associates them
        with the case.

        Args:
            case_id: Case identifier
            auto_associate: If True, automatically add tasks to the case
            progress_callback: Optional progress callback (stage, message)

        Returns:
            Dict with keys:
                - associated: List of newly associated task IDs
                - already_analyzed: List of already associated and analyzed task IDs
                - pending_analysis: List of associated but not yet analyzed task IDs
                - total_files: Total files across all tasks
                - analyzed_files: Total analyzed files across all tasks
        """
        if progress_callback:
            await progress_callback("scanning", "正在扫描已完成的任务...")

        logger.info(f"[CASE_AGGREG] Case {case_id}: Scanning for completed tasks")

        # Get all tasks from C++ backend
        try:
            all_tasks = await self._cpp_backend.list_tasks()
        except Exception as e:
            logger.error(f"[CASE_AGGREG] Failed to list tasks: {e}")
            return {
                "associated": [],
                "already_analyzed": [],
                "pending_analysis": [],
                "total_files": 0,
                "analyzed_files": 0,
                "error": str(e),
            }

        # Filter completed tasks
        completed_tasks = [
            t for t in all_tasks
            if t.get("status") == "completed"
        ]

        logger.info(f"[CASE_AGGREG] Found {len(completed_tasks)} completed tasks")

        # Initialize case database
        case_db_path = get_case_db_path(case_id)
        ensure_case_task_status_table(case_db_path)

        associated = []
        already_analyzed = []
        pending_analysis = []
        total_files = 0
        analyzed_files = 0

        for task in completed_tasks:
            task_id = task.get("id")
            if not task_id:
                continue

            # Get task database paths
            files_db = task.get("output_files_db", "")
            if not files_db or not Path(files_db).exists():
                continue

            # Check analysis status
            stats = get_file_description_stats(files_db)
            task_has_descriptions = stats["analyzed_files"] > 0

            # Determine status
            if task_has_descriptions:
                status = TaskAnalysisState.ANALYZED.value
                already_analyzed.append(task_id)
                analyzed_files += stats["analyzed_files"]
            else:
                status = TaskAnalysisState.PENDING.value
                pending_analysis.append(task_id)

            total_files += stats["total_files"]

            # Update status in case database
            update_task_analysis_status(
                db_path=case_db_path,
                case_id=case_id,
                task_id=task_id,
                status=status,
                files_count=stats["total_files"],
                analyzed_files_count=stats["analyzed_files"],
            )

            # Auto-associate to case
            if auto_associate:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        response = await client.put(
                            f"{self.settings.cpp_backend_url}/api/cases/{case_id}/tasks",
                            json={"task_ids": [task_id]},
                        )
                        if response.status_code == 200:
                            associated.append(task_id)
                        else:
                            logger.warning(f"[CASE_AGGREG] Failed to associate task {task_id}: {response.status_code}")
                except Exception as e:
                    logger.warning(f"[CASE_AGGREG] Failed to associate task {task_id}: {e}")

        logger.info(f"[CASE_AGGREG] Case {case_id}: "
                    f"Associated {len(associated)} tasks, "
                    f"{len(already_analyzed)} already analyzed, "
                    f"{len(pending_analysis)} pending analysis")

        return {
            "associated": associated,
            "already_analyzed": already_analyzed,
            "pending_analysis": pending_analysis,
            "total_files": total_files,
            "analyzed_files": analyzed_files,
        }

    async def associate_tasks(
        self,
        case_id: str,
        task_ids: List[str],
    ) -> Dict[str, Any]:
        """
        Associate a specific set of (typically already-completed) tasks to a case.

        Unlike scan_and_associate_completed_tasks (which pulls in ALL completed
        tasks system-wide), this only touches the explicitly requested tasks.
        For each task it inspects the real _files.db and pre-populates the
        case-level analysis-state row so that a subsequent cross-image /
        incremental run correctly REUSES already-analyzed tasks instead of
        re-analyzing them.

        Tasks already present in the case are skipped (idempotent). Tasks whose
        case-level state row already exists are not overwritten.

        Args:
            case_id: Case identifier
            task_ids: Task IDs to associate

        Returns:
            Dict with per-task results:
                - associated:        task IDs newly added to the case
                - reused:            task IDs added that already have descriptions
                                     (will be reused as-is by cross-image analysis)
                - pending_analysis:  task IDs added without descriptions yet
                - skipped:           task IDs already in the case
                - not_found:         task IDs that could not be resolved
                - not_completed:     task IDs not yet finished analyzing
        """
        # Ensure the case DB + status table exist
        case_db_path = get_case_db_path(case_id)
        ensure_case_task_status_table(case_db_path)

        # Current task_ids in the case (to skip duplicates)
        existing_task_ids: set = set()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.settings.cpp_backend_url}/api/cases/{case_id}"
                )
                if resp.status_code == 200:
                    existing_task_ids = set(resp.json().get("task_ids", []) or [])
        except Exception as e:
            logger.warning(f"[CASE_AGGREG] Could not read case {case_id}: {e}")

        associated: List[str] = []
        reused: List[str] = []
        pending_analysis: List[str] = []
        skipped: List[str] = []
        not_found: List[str] = []
        not_completed: List[str] = []

        for task_id in task_ids:
            # Idempotent: skip tasks already in this case
            if task_id in existing_task_ids:
                skipped.append(task_id)
                continue

            # Resolve the task record + its _files.db
            try:
                task_info = await self._cpp_backend.get_task(task_id)
            except Exception as e:
                logger.warning(f"[CASE_AGGREG] associate: get_task({task_id}) failed: {e}")
                not_found.append(task_id)
                continue

            if not task_info:
                not_found.append(task_id)
                continue

            if task_info.get("status") != "completed":
                not_completed.append(task_id)
                continue

            files_db = task_info.get("output_files_db", "")
            if not files_db or not Path(files_db).exists():
                not_completed.append(task_id)
                continue

            # Inspect real analysis state from the task's own _files.db
            stats = get_file_description_stats(files_db)
            has_descriptions = stats["analyzed_files"] > 0
            status = TaskAnalysisState.ANALYZED.value if has_descriptions else TaskAnalysisState.PENDING.value

            # Pre-populate the case-level state row so the next cross-image run
            # knows whether to reuse or analyze this task.
            update_task_analysis_status(
                db_path=case_db_path,
                case_id=case_id,
                task_id=task_id,
                status=status,
                files_count=stats["total_files"],
                analyzed_files_count=stats["analyzed_files"],
            )

            # Add the task to the case record in the C++ backend
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.put(
                        f"{self.settings.cpp_backend_url}/api/cases/{case_id}/tasks",
                        json={"task_ids": [task_id]},
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            f"[CASE_AGGREG] associate: add task {task_id} to case "
                            f"{case_id} failed: {resp.status_code}"
                        )
                        continue
            except Exception as e:
                logger.warning(f"[CASE_AGGREG] associate: add task {task_id} failed: {e}")
                continue

            associated.append(task_id)
            if has_descriptions:
                reused.append(task_id)
            else:
                pending_analysis.append(task_id)

        logger.info(
            f"[CASE_AGGREG] Case {case_id}: associated {len(associated)} tasks "
            f"({len(reused)} reused, {len(pending_analysis)} pending), "
            f"{len(skipped)} already present"
        )

        return {
            "associated": associated,
            "reused": reused,
            "pending_analysis": pending_analysis,
            "skipped": skipped,
            "not_found": not_found,
            "not_completed": not_completed,
        }

    # ─────────────────────────────────────────────────────────────────────────────
    # Public API: Status Queries
    # ─────────────────────────────────────────────────────────────────────────────

    async def get_case_analysis_status(
        self, case_id: str
    ) -> Dict[str, Any]:
        """
        获取案件完整分析状态

        Returns comprehensive status of all tasks within a case,
        including their analysis states and file statistics.

        Args:
            case_id: Case identifier

        Returns:
            Dict with keys:
                - case_id: Case identifier
                - total_tasks: Total number of tasks
                - analyzed_tasks: Number of analyzed tasks
                - pending_tasks: Number of pending tasks
                - failed_tasks: Number of failed tasks
                - total_files: Total files across all tasks
                - analyzed_files: Total analyzed files
                - tasks: List of task status dicts
        """
        case_db_path = get_case_db_path(case_id)

        if not Path(case_db_path).exists():
            return {
                "case_id": case_id,
                "total_tasks": 0,
                "analyzed_tasks": 0,
                "pending_tasks": 0,
                "failed_tasks": 0,
                "total_files": 0,
                "analyzed_files": 0,
                "tasks": [],
            }

        task_statuses = get_case_all_task_status(case_db_path, case_id)

        total_tasks = len(task_statuses)
        analyzed_tasks = sum(1 for t in task_statuses if t["analysis_status"] == "analyzed")
        pending_tasks = sum(1 for t in task_statuses if t["analysis_status"] == "pending")
        failed_tasks = sum(1 for t in task_statuses if t["analysis_status"] == "failed")

        total_files = sum(t.get("files_count", 0) for t in task_statuses)
        analyzed_files = sum(t.get("analyzed_files_count", 0) for t in task_statuses)

        return {
            "case_id": case_id,
            "total_tasks": total_tasks,
            "analyzed_tasks": analyzed_tasks,
            "pending_tasks": pending_tasks,
            "failed_tasks": failed_tasks,
            "total_files": total_files,
            "analyzed_files": analyzed_files,
            "tasks": task_statuses,
        }

    async def check_task_analysis_status(
        self, task_id: str, files_db_path: str
    ) -> str:
        """
        检查任务分析状态

        Determines whether a task has been analyzed by checking
        if file_descriptions exist in its database.

        Args:
            task_id: Task identifier
            files_db_path: Path to the task's _files.db

        Returns:
            Status string: "analyzed", "pending", "needs_update", or "failed"
        """
        if not files_db_path or not Path(files_db_path).exists():
            return TaskAnalysisState.FAILED.value

        stats = get_file_description_stats(files_db_path)

        if stats["analyzed_files"] > 0:
            return TaskAnalysisState.ANALYZED.value

        # Check task status from C++ backend
        try:
            task = await self._cpp_backend.get_task(task_id)
            if task.get("status") != "completed":
                return TaskAnalysisState.PENDING.value
        except Exception:
            pass

        return TaskAnalysisState.NEEDS_UPDATE.value

    # ─────────────────────────────────────────────────────────────────────────────
    # Public API: Incremental Analysis Planning
    # ─────────────────────────────────────────────────────────────────────────────

    async def plan_incremental_analysis(
        self,
        case_id: str,
        new_task_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """
        规划增量分析 - 确定哪些任务需要分析

        Analyzes the current state of a case and determines which
        tasks need to be analyzed, which can be skipped, and estimates
        the time required.

        Args:
            case_id: Case identifier
            new_task_ids: Optional list of new task IDs to add

        Returns:
            Dict with keys:
                - skip_tasks: List of task IDs to skip (already analyzed)
                - analyze_tasks: List of task IDs to analyze
                - reuse_descriptions: Number of descriptions to reuse
                - estimated_time_minutes: Estimated analysis time
        """
        if progress_callback:
            await progress_callback("planning", "正在规划增量分析...")

        # Get current case status
        case_status = await self.get_case_analysis_status(case_id)

        skip_tasks = []
        analyze_tasks = []
        reuse_descriptions = case_status["analyzed_files"]

        # Process existing tasks
        for task_status in case_status["tasks"]:
            task_id = task_status["task_id"]
            status = task_status["analysis_status"]

            if status == "analyzed":
                skip_tasks.append(task_id)
            elif status in ("pending", "needs_update", "failed"):
                analyze_tasks.append(task_id)

        # Add new tasks
        if new_task_ids:
            for task_id in new_task_ids:
                if task_id not in skip_tasks and task_id not in analyze_tasks:
                    analyze_tasks.append(task_id)

        # Estimate time (5 minutes per task to analyze)
        estimated_time = len(analyze_tasks) * 5

        logger.info(f"[CASE_AGGREG] Case {case_id}: Incremental plan - "
                    f"Skip {len(skip_tasks)}, Analyze {len(analyze_tasks)}, "
                    f"Reuse {reuse_descriptions} descriptions, "
                    f"Est. {estimated_time} minutes")

        return {
            "skip_tasks": skip_tasks,
            "analyze_tasks": analyze_tasks,
            "reuse_descriptions": reuse_descriptions,
            "estimated_time_minutes": estimated_time,
        }

    # ─────────────────────────────────────────────────────────────────────────────
    # Public API: Incremental Analysis Execution
    # ─────────────────────────────────────────────────────────────────────────────

    async def execute_incremental_analysis(
        self,
        case_id: str,
        plan: Dict[str, Any],
        analyze_func,  # Callback function to analyze a task
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        执行增量分析计划

        Executes the incremental analysis by calling the provided
        analyze_func for each task that needs analysis.

        Args:
            case_id: Case identifier
            plan: Analysis plan from plan_incremental_analysis()
            analyze_func: Async function to analyze a task
                         Signature: async def analyze_func(task_id, case_id, progress_cb)
            progress_callback: Optional progress callback

        Returns:
            Dict with keys:
                - analyzed_tasks: List of successfully analyzed task IDs
                - skipped_tasks: List of skipped task IDs
                - failed_tasks: List of failed task IDs
                - total_time_seconds: Total execution time
        """
        import time
        start_time = time.time()

        analyzed_tasks = []
        skipped_tasks = plan.get("skip_tasks", [])
        failed_tasks = []

        analyze_task_ids = plan.get("analyze_tasks", [])

        logger.info(f"[CASE_AGGREG] Case {case_id}: Executing incremental analysis - "
                    f"{len(analyze_task_ids)} tasks to analyze")

        for idx, task_id in enumerate(analyze_task_ids):
            if progress_callback:
                await progress_callback(
                    "analyzing",
                    f"正在分析任务 {idx+1}/{len(analyze_task_ids)} ({task_id[:8]}...)"
                )

            try:
                # Update status to analyzing
                case_db_path = get_case_db_path(case_id)
                update_task_analysis_status(
                    db_path=case_db_path,
                    case_id=case_id,
                    task_id=task_id,
                    status="analyzing",  # Temporary status
                )

                # Call the analysis function
                await analyze_func(task_id, case_id, progress_callback)

                analyzed_tasks.append(task_id)

                # Update status to analyzed
                update_task_analysis_status(
                    db_path=case_db_path,
                    case_id=case_id,
                    task_id=task_id,
                    status="analyzed",
                )

            except Exception as e:
                logger.error(f"[CASE_AGGREG] Failed to analyze task {task_id}: {e}", exc_info=True)
                failed_tasks.append(task_id)

                # Update status to failed
                update_task_analysis_status(
                    db_path=case_db_path,
                    case_id=case_id,
                    task_id=task_id,
                    status="failed",
                    error_message=str(e),
                )

        total_time = time.time() - start_time

        logger.info(f"[CASE_AGGREG] Case {case_id}: Incremental analysis completed - "
                    f"{len(analyzed_tasks)} analyzed, {len(skipped_tasks)} skipped, "
                    f"{len(failed_tasks)} failed, {total_time:.1f}s")

        return {
            "analyzed_tasks": analyzed_tasks,
            "skipped_tasks": skipped_tasks,
            "failed_tasks": failed_tasks,
            "total_time_seconds": total_time,
        }
