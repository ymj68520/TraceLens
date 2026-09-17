"""Part of IngestionJobManager (split for maintainability).

This mixin contributes a group of methods to the IngestionJobManager class
declared in services/ingestion_job_manager.py. The dataclasses/enums
(IngestionMode, JobStatus, IngestionJob, JobSummary) remain in the main module.
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from ...config import Settings
from ..ingestion_job_models import (
    IngestionMode, JobStatus, IngestionJob, JobSummary,
)

logger = logging.getLogger(__name__)


class IngestionJobManagerMixin:
    """Auto-extracted method group; see module docstring."""

    def __init__(self, settings: Settings):
        """
        Initialize the Ingestion Job Manager.

        Args:
            settings: Application settings.
        """
        self.settings = settings

        # In-memory job storage (fallback when Redis unavailable)
        self._jobs: dict[str, IngestionJob] = {}

        # Redis client (optional)
        self._redis = None
        self._use_redis = False

        # Component services (initialized later)
        self._file_ingestor = None
        self._entity_builder = None

        # Type holders for graphiti integration components
        self._EventRecord = None
        self._FileIngestionResult = None
        self._RelationBuildResult = None

        # Background worker task
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

        # Live asyncio handles for kg_sync jobs (self-run coroutines). Needed
        # so cancel_job can actually interrupt a RUNNING kg_sync ingestion
        # instead of only flipping the recorded status.
        self._kg_sync_tasks: dict[str, asyncio.Task] = {}

        # llm-throughput-hardening SPEC A: this process's boot epoch, stamped
        # on every job it moves to RUNNING so the next startup can identify
        # jobs orphaned by a restart mid-run (stale sweep).
        self._runner_epoch: str = uuid.uuid4().hex

        # Database readers (imported later to avoid module-level import issues)
        self._ForensicsDatabase = None
        self._EventsDatabase = None

    async def initialize(self):
        """Initialize the job manager and background worker."""
        if self._running:
            return

        # Try to initialize Redis for persistent storage
        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                # Bounded connect/read timeouts so a stuck server fails fast
                # instead of hanging the job manager. socket_timeout is kept
                # large enough that any single command (incl. short blocking
                # pops) completes well within it.
                socket_connect_timeout=5,
                socket_timeout=30,
                # periodic keep-alive so dead connections are reaped
                health_check_interval=30,
            )
            # Test connection
            await self._redis.ping()
            self._use_redis = True
            logger.info(f"IngestionJobManager using Redis at {self.settings.redis_url}")
        except Exception as e:
            logger.warning(f"Redis not available, using in-memory storage: {e}")
            self._use_redis = False

        # Try to initialize Neo4j-dependent component services
        try:
            # Locate the python_service/ dir (sibling of httpserver/) that
            # contains graphiti_integration/, and make it importable.
            # NOTE: this file lives at python_service/httpserver/services/
            #       ingestion_job_parts/_manager.py, so python_service/ is
            #       FOUR parents up — not three. Using parents[3] previously
            #       resolved to httpserver/ and the import silently failed
            #       ("No module named 'graphiti_integration'") whenever the
            #       launcher forgot to pre-set PYTHONPATH (e.g. when the
            #       service was started via start_python_service.sh instead
            #       of start_all_services.sh).
            import sys
            from pathlib import Path
            python_service_path = str(Path(__file__).resolve().parents[3])
            if python_service_path not in sys.path:
                sys.path.insert(0, python_service_path)

            # Import graphiti integration components
            from graphiti_integration.file_entity_ingestor import FileEntityIngestor, EventRecord, FileIngestionResult
            from graphiti_integration.entity_relation_builder import EntityRelationBuilder, RelationBuildResult
            from graphiti_integration.database_reader.raw_reader import ForensicsDatabase
            from graphiti_integration.database_reader.events_reader import EventsDatabase

            # Store type references
            self._EventRecord = EventRecord
            self._FileIngestionResult = FileIngestionResult
            self._RelationBuildResult = RelationBuildResult

            # Initialize component services
            self._file_ingestor = FileEntityIngestor(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
                neo4j_connect_timeout=getattr(self.settings, "neo4j_connect_timeout", 5.0),
                neo4j_query_timeout=getattr(self.settings, "neo4j_query_timeout", 5.0),
            )
            await self._file_ingestor.initialize()

            self._entity_builder = EntityRelationBuilder(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
                neo4j_connect_timeout=getattr(self.settings, "neo4j_connect_timeout", 5.0),
                neo4j_query_timeout=getattr(self.settings, "neo4j_query_timeout", 5.0),
            )
            await self._entity_builder.initialize()

            # Store database reader classes
            self._ForensicsDatabase = ForensicsDatabase
            self._EventsDatabase = EventsDatabase

            logger.info("IngestionJobManager: Neo4j components initialized")
        except ImportError as e:
            logger.warning(f"Graphiti integration not available: {e}")
            logger.warning("IngestionJobManager will run in degraded mode without Neo4j")
        except Exception as e:
            logger.warning(f"Neo4j components initialization failed: {e}")
            logger.warning("IngestionJobManager will run in degraded mode without Neo4j")

        # Start background worker (even if Neo4j is unavailable)
        self._running = True
        await self._sweep_stale_jobs()
        self._worker_task = asyncio.create_task(self._background_worker())

        logger.info("IngestionJobManager initialized")

    async def _sweep_stale_jobs(self) -> int:
        """Mark RUNNING jobs from a previous process as stale (SPEC A5).

        A service restart orphans any RUNNING job: nothing will ever update
        it again, so it would sit as a zombie forever (2026-09-16 live state:
        4 jobs from August + 4 from the same day stuck in "running"). Runs
        before the worker starts, so every RUNNING job found belongs to a
        dead process by construction.
        """
        try:
            entries = await self.list_jobs(status=JobStatus.RUNNING.value, limit=1000)
        except Exception as e:
            logger.warning(f"Stale sweep: could not list RUNNING jobs: {e}")
            return 0

        swept = 0
        for entry in entries:
            job_id = str(entry.get("job_id", ""))
            if not job_id:
                continue
            job = await self._load_job(job_id)
            if job is None or job.status != JobStatus.RUNNING:
                continue
            if job.runner_epoch == self._runner_epoch:
                continue  # defensive: never sweep our own jobs
            job.status = JobStatus.FAILED
            job.current_phase = "stale"
            job.error = "stale: service restarted mid-run"
            job.completed_at = datetime.utcnow().isoformat()
            await self._save_job(job)
            swept += 1
        if swept:
            logger.warning(f"Stale sweep: marked {swept} orphaned RUNNING job(s) as stale")
        return swept

    async def shutdown(self):
        """Shutdown the job manager and cleanup resources."""
        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        if self._file_ingestor:
            await self._file_ingestor.close()

        if self._entity_builder:
            await self._entity_builder.close()

        if self._redis:
            await self._redis.close()

        logger.info("IngestionJobManager shutdown")

    async def redis_health_check(self) -> dict:
        """Check Redis connectivity.

        Redis is optional: when unavailable the manager falls back to in-memory
        storage, so this never raises. ``in_use`` reflects whether Redis was
        configured/connected at initialization time, while ``connected`` reports
        live reachability at the moment of the check.
        """
        # Never initialized with Redis — running purely in-memory.
        if not self._use_redis or self._redis is None:
            return {
                "connected": False,
                "in_use": False,
                "status": "disconnected",
            }
        try:
            await self._redis.ping()
            return {
                "connected": True,
                "in_use": True,
                "status": "connected",
            }
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            return {
                "connected": False,
                "in_use": True,
                "status": "error",
                "error": str(e),
            }

    async def _save_job(self, job: IngestionJob):
        """Save job state to storage."""
        # SPEC A5: stamp the current boot epoch whenever this process moves a
        # job to RUNNING — the next startup's stale sweep uses it to tell
        # "running here" from "orphaned by a restart".
        if job.status == JobStatus.RUNNING:
            job.runner_epoch = self._runner_epoch

        job_dict = {
            "job_id": job.job_id,
            "task_id": job.task_id,
            "mode": job.mode.value,
            "status": job.status.value,
            "progress": job.progress,
            "current_phase": job.current_phase,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "error": job.error,
            "result": job.result,
            "file_id": job.file_id,
            "events_count": job.events_count,
            "runner_epoch": job.runner_epoch,
            "force": int(job.force),
        }

        # Redis HSET mapping does not accept None values — strip them
        job_dict = {k: v for k, v in job_dict.items() if v is not None}

        # Redis can only store scalar types (str, bytes, int, float).
        # Convert dicts/lists to JSON strings so nested values serialize cleanly.
        import json
        _serializable = {}
        for k, v in job_dict.items():
            if isinstance(v, (dict, list)):
                _serializable[k] = json.dumps(v, ensure_ascii=False, default=str)
            else:
                _serializable[k] = v

        if self._use_redis:
            await self._redis.hset(
                f"job:{job.job_id}",
                mapping=_serializable
            )
        else:
            self._jobs[job.job_id] = job

    async def _load_job(self, job_id: str) -> Optional[IngestionJob]:
        """Load job state from storage."""
        if self._use_redis:
            data = await self._redis.hgetall(f"job:{job_id}")
            if not data:
                return None
            # Redis returns all values as strings — convert enum fields back
            if "mode" in data and isinstance(data["mode"], str):
                data["mode"] = IngestionMode(data["mode"])
            if "status" in data and isinstance(data["status"], str):
                data["status"] = JobStatus(data["status"])
            # result was serialized to a JSON string by _save_job — restore to dict
            if "result" in data and isinstance(data["result"], str):
                import json
                try:
                    data["result"] = json.loads(data["result"])
                except (json.JSONDecodeError, TypeError):
                    data["result"] = None
            # Redis stores bools as "0"/"1" strings; a bare "0" is truthy in
            # Python, so coerce explicitly.
            if "force" in data:
                data["force"] = str(data["force"]) in ("1", "true", "True")
            return IngestionJob(**data)
        else:
            return self._jobs.get(job_id)

    async def _update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        current_phase: str = None,
        progress: int = None,
        error: str = None,
        result: dict = None,
    ):
        """Update job status in storage."""
        job = await self._load_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for status update")
            return

        job.status = status
        if current_phase:
            job.current_phase = current_phase
        if progress is not None:
            job.progress = progress
        if error:
            job.error = error
        if result:
            job.result = result

        if status == JobStatus.RUNNING and not job.started_at:
            job.started_at = datetime.utcnow().isoformat()
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            job.completed_at = datetime.utcnow().isoformat()

        await self._save_job(job)

    def _generate_job_id(self) -> str:
        """Generate a unique job ID."""
        return f"job_{uuid.uuid4().hex[:16]}"

    async def queue_ingestion(
        self,
        task_id: str,
        mode: IngestionMode = IngestionMode.FULL,
        force: bool = False,
    ) -> str:
        """
        Queue a background ingestion job for a task.

        Args:
            task_id: Task ID to ingest.
            mode: Ingestion mode.
            force: Bypass the foreground gate (SPEC A3 escape hatch).

        Returns:
            Job ID for tracking.
        """
        job_id = self._generate_job_id()

        job = IngestionJob(
            job_id=job_id,
            task_id=task_id,
            mode=mode,
            force=force,
        )

        await self._save_job(job)

        # Signal worker by adding to queue
        if self._use_redis:
            await self._redis.lpush("ingestion_queue", json.dumps({
                "job_id": job_id,
                "task_id": task_id,
                "mode": mode.value,
                "force": bool(force),
            }))

        logger.info(f"Queued ingestion job {job_id} for task {task_id} (mode: {mode.value})")
        return job_id

    async def queue_file_update(
        self,
        file_id: int,
        task_id: str,
    ) -> str:
        """
        Queue a single file update job.

        Args:
            file_id: Database ID of the file.
            task_id: Task ID.

        Returns:
            Job ID for tracking.
        """
        job_id = self._generate_job_id()

        job = IngestionJob(
            job_id=job_id,
            task_id=task_id,
            mode=IngestionMode.SINGLE_FILE,
            file_id=file_id,
        )

        await self._save_job(job)

        if self._use_redis:
            await self._redis.lpush("ingestion_queue", json.dumps({
                "job_id": job_id,
                "task_id": task_id,
                "mode": IngestionMode.SINGLE_FILE.value,
                "file_id": file_id,
            }))

        logger.info(f"Queued file update job {job_id} for file {file_id}")
        return job_id

    async def queue_event_sync(
        self,
        task_id: str,
        events: list[dict],
    ) -> str:
        """
        Queue an event synchronization job.

        Args:
            task_id: Task ID.
            events: List of event dictionaries.

        Returns:
            Job ID for tracking.
        """
        job_id = self._generate_job_id()

        job = IngestionJob(
            job_id=job_id,
            task_id=task_id,
            mode=IngestionMode.EVENTS_ONLY,
            events_count=len(events),
        )

        await self._save_job(job)

        # Store events temporarily
        events_key = f"job_events:{job_id}"
        events_json = json.dumps(events)
        if self._use_redis:
            await self._redis.set(events_key, events_json, ex=3600)  # 1 hour TTL
        else:
            self._jobs[job_id]._events = events

        if self._use_redis:
            await self._redis.lpush("ingestion_queue", json.dumps({
                "job_id": job_id,
                "task_id": task_id,
                "mode": IngestionMode.EVENTS_ONLY.value,
                "events_count": len(events),
            }))

        logger.info(f"Queued event sync job {job_id} for {len(events)} events")
        return job_id

    async def queue_kg_sync_job(
        self,
        task_id: str,
        runner,
    ) -> str:
        """
        Queue a KG-sync job that runs its own coroutine (SPEC §B2).

        Unlike the queue-fed modes, ``runner`` (an async callable receiving a
        ``progress(stage, message)`` callback) is started here as its own
        task and the job transitions straight to RUNNING: the in-memory
        worker loop scans PENDING jobs and would fail on this mode, and the
        runner closes over fresh analysis results that must not be re-read
        from databases.

        Args:
            task_id: Task ID the ingestion belongs to.
            runner: async callable(progress) -> dict-like result.

        Returns:
            Job ID for tracking via GET /api/graphiti/jobs/{id}.
        """
        job_id = self._generate_job_id()

        job = IngestionJob(
            job_id=job_id,
            task_id=task_id,
            mode=IngestionMode.KG_SYNC,
        )
        job.status = JobStatus.RUNNING
        job.current_phase = "queued"
        job.started_at = datetime.utcnow().isoformat()
        await self._save_job(job)

        task = asyncio.create_task(self._run_kg_sync_job(job_id, runner, task_id))
        self._kg_sync_tasks[job_id] = task

        logger.info(f"Queued kg_sync job {job_id} for task {task_id}")
        return job_id

    async def _run_kg_sync_job(self, job_id: str, runner, task_id: str = ""):
        """Drive a kg_sync job through RUNNING -> COMPLETED/FAILED/CANCELLED."""
        async def progress(stage: str, message: str):
            await self._update_job_status(job_id, JobStatus.RUNNING, stage)

        # SPEC A: kg_sync ingestion goes through the same episode gate — the
        # timeout applies; the gate pause applies (no force flag on this path).
        from ..ingestion_gate import gate_context, make_job_context

        async def _set_gate_phase(phase: Optional[str]):
            target = phase or "ingesting_episodes"
            await self._update_job_status(job_id, JobStatus.RUNNING, target)

        job_ctx = make_job_context(
            self.settings,
            job_id=job_id,
            label=task_id or job_id,
            force=False,
            set_phase=_set_gate_phase,
        )
        gate_token = gate_context.set(job_ctx)

        try:
            result = await runner(progress)
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, "completed", progress=100,
                result=result if isinstance(result, dict) else None,
            )
            logger.info(f"kg_sync job {job_id} completed")
        except asyncio.CancelledError:
            await self._update_job_status(job_id, JobStatus.CANCELLED, "cancelled")
            raise
        except Exception as e:
            # Includes GateAborted on timeout — the job ends FAILED with the
            # gate's timeout message.
            logger.error(f"kg_sync job {job_id} failed: {e}", exc_info=True)
            await self._update_job_status(
                job_id, JobStatus.FAILED, "failed", error=str(e)
            )
        finally:
            gate_context.reset(gate_token)
            self._kg_sync_tasks.pop(job_id, None)

    async def get_job_status(self, job_id: str) -> Optional[dict]:
        """
        Get the status of an ingestion job.

        Args:
            job_id: Job ID.

        Returns:
            Job status dictionary or None.
        """
        job = await self._load_job(job_id)
        if not job:
            return None

        return {
            "job_id": job.job_id,
            "task_id": job.task_id,
            "mode": job.mode.value,
            "status": job.status.value,
            "progress": job.progress,
            "current_phase": job.current_phase,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "error": job.error,
            "result": job.result,
        }

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending or running job.

        Args:
            job_id: Job ID.

        Returns:
            True if cancelled, False if job cannot be cancelled.
        """
        job = await self._load_job(job_id)
        if not job:
            return False

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        # A RUNNING kg_sync job owns its own asyncio task — cancelling the
        # status alone would leave the ingestion writing to Neo4j long after
        # the caller (e.g. task/graph deletion) considered it gone.
        pending_task = self._kg_sync_tasks.get(job_id)
        await self._update_job_status(job_id, JobStatus.CANCELLED)
        if pending_task is not None:
            pending_task.cancel()
        logger.info(f"Cancelled job {job_id}")
        return True

    async def cancel_jobs_for_task(self, task_id: str) -> int:
        """
        Cancel every pending/running ingestion job of one task.

        Used by graph deletion so a still-running ingestion cannot resurrect
        the graph right after it was purged.

        Args:
            task_id: Task (or case) ID whose jobs should be cancelled.

        Returns:
            Number of jobs transitioned to CANCELLED.
        """
        try:
            jobs = await self.list_jobs(task_id=task_id, limit=100)
        except Exception as e:
            logger.warning(f"cancel_jobs_for_task({task_id}): list_jobs failed: {e}")
            return 0

        cancelled = 0
        for entry in jobs:
            if entry.get("status") not in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
                continue
            try:
                if await self.cancel_job(entry.get("job_id", "")):
                    cancelled += 1
            except Exception as e:
                logger.warning(f"cancel_jobs_for_task({task_id}): cancel failed for "
                               f"{entry.get('job_id')}: {e}")
        return cancelled

    async def list_jobs(
        self,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        List ingestion jobs with optional filtering.

        Args:
            task_id: Filter by task ID.
            status: Filter by status.
            limit: Maximum number of jobs to return.

        Returns:
            List of job status dictionaries.
        """
        if self._use_redis:
            # Scan for job keys
            jobs = []
            async for key in self._redis.scan_iter(match="job:*"):
                job_data = await self._redis.hgetall(key)
                if job_data:
                    # Apply filters
                    if task_id and job_data.get("task_id") != task_id:
                        continue
                    if status and job_data.get("status") != status:
                        continue
                    jobs.append(job_data)
                    if len(jobs) >= limit:
                        break
            return jobs
        else:
            jobs = list(self._jobs.values())
            if task_id:
                jobs = [j for j in jobs if j.task_id == task_id]
            if status:
                jobs = [j for j in jobs if j.status.value == status]
            return [
                {
                    "job_id": j.job_id,
                    "task_id": j.task_id,
                    "mode": j.mode.value,
                    "status": j.status.value,
                    "progress": j.progress,
                    "current_phase": j.current_phase,
                    "created_at": j.created_at,
                }
                for j in jobs[:limit]
            ]

