"""Part of GraphitiService (split for maintainability).

This mixin contributes a group of methods to the GraphitiService class. It is
mixed into GraphitiService in services/graphiti_service.py and relies on the
instance attributes defined there (self.settings, self._initialized,
self._task_graphs, self._jobs, ...).
"""

import asyncio
import logging
import uuid
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GraphitiJobsMixin:
    """Auto-extracted method group; see module docstring."""

    async def start_ingestion(
        self,
        task_id: str,
        include_llm_descriptions: bool = True,
        batch_size: int = 50,
        max_episodes: int = 100,
    ) -> str:
        """
        Start background ingestion of forensic data for a specific task.
        Uses task_id as the graph namespace.
        """
        job_id = str(uuid.uuid4())
        
        self._jobs[job_id] = {
            "status": "running",
            "task_id": task_id,
            "progress": 0.0,
            "entities_created": 0,
            "relationships_created": 0,
            "errors": [],
        }
        
        asyncio.create_task(self._run_ingestion(
            job_id, task_id, include_llm_descriptions, batch_size, max_episodes
        ))
        
        return job_id

    async def _run_ingestion(
        self,
        job_id: str,
        task_id: str,
        include_llm_descriptions: bool,
        batch_size: int,
        max_episodes: int,
    ):
        """Run the actual ingestion using MultiSourcePipeline."""
        try:
            # Get task info from C++ backend to find database paths
            from ..services import get_service_manager
            service_manager = get_service_manager()

            # Try to get database info for this task
            task_data = None
            try:
                task_data = await service_manager.cpp_backend.get_task(task_id)
            except Exception as e:
                logger.warning(f"Could not fetch task data from C++ backend: {e}")

            # Build config for multi-source pipeline
            from graphiti_integration.pipeline import MultiSourcePipeline

            config = self._build_graphiti_config(group_id=task_id)
            # Apply run-specific overrides
            config.batch_size = batch_size
            config.max_episodes = max_episodes
            config.filter_analyzed_only = not include_llm_descriptions

            # Determine the output_dir and base_name from task data
            # New structure: build/data/tasks/<uuid>/files.db
            output_dir = self.settings.db_output_dir
            base_name = "forensics"
            any_db_path = None

            if task_data:
                # 1. Use the explicit files.db path if available
                any_db_path = task_data.get("output_files_db")
                
                # 2. Extract base_name from image path for potential other databases
                img_path = task_data.get("image_path", "")
                if img_path:
                    base_name = os.path.basename(img_path).split('.')[0]
                
                # 3. If any_db_path is set, ensure output_dir is its parent
                if any_db_path:
                    output_dir = os.path.dirname(any_db_path)
                else:
                    # Fallback to task-specific directory
                    t_out_dir = task_data.get("db_output_dir")
                    if t_out_dir:
                        output_dir = t_out_dir

            # Safe globbing: only use relative patterns
            try:
                # We only need to check if directory exists, MultiSourcePipeline will handle the rest
                if not any_db_path and output_dir and os.path.exists(output_dir):
                    # Only glob if we don't have a direct path, and ensure pattern is simple
                    safe_pattern = f"*{base_name}*.db"
                    logger.info(f"Searching for databases in {output_dir} with pattern {safe_pattern}")
            except Exception as e:
                logger.warning(f"Database discovery warning: {e}")

            pipeline = MultiSourcePipeline(config)

            def progress_cb(source, phase, current, total):
                self._update_job_progress(job_id, current / total if total > 0 else 0)

            result = await pipeline.run(
                base_name=base_name,
                output_dir=output_dir,
                any_db_path=any_db_path,
                group_id=task_id,
                dry_run=False,
                progress_callback=progress_cb,
            )

            self._jobs[job_id].update({
                "status": "completed",
                "progress": 1.0,
                "entities_created": result.total_ingested,
                "relationships_created": 0,
                "sources_processed": result.sources_processed,
                "summary": result.summary(),
            })

        except Exception as e:
            import traceback
            logger.error(f"Ingestion job {job_id} failed: {e}")
            logger.error(traceback.format_exc())
            self._jobs[job_id].update({
                "status": "failed",
                "message": str(e),
            })

    def _update_job_progress(self, job_id: str, progress: float):
        """Update job progress."""
        if job_id in self._jobs:
            self._jobs[job_id]["progress"] = progress

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of an ingestion job."""
        return self._jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running ingestion job.

        Note: This marks the job as cancelled but doesn't actually stop
        the background task. The task will check the job status on completion.
        """
        if job_id in self._jobs:
            job = self._jobs[job_id]
            if job.get("status") == "running":
                job["status"] = "cancelled"
                job["message"] = "Job cancelled by user"
                logger.info(f"Ingestion job {job_id} marked as cancelled")
                return True
        return False

