"""
Ingestion Job Manager - Background job queue for Graphiti ingestion operations.

This service manages asynchronous ingestion jobs with persistent state tracking,
supporting different ingestion modes and providing status polling capabilities.
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import Settings

logger = logging.getLogger(__name__)


class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"  # Only AI-analyzed files


class JobStatus(str, Enum):
    """Job status states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IngestionJob:
    """Represents an ingestion job."""
    job_id: str
    task_id: str
    mode: IngestionMode
    status: JobStatus = JobStatus.PENDING
    progress: int = 0  # 0-100
    current_phase: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None

    # Additional metadata
    file_id: Optional[int] = None  # For SINGLE_FILE mode
    events_count: int = 0  # For EVENTS_ONLY mode


@dataclass
class JobSummary:
    """Summary of job results."""
    job_id: str
    status: JobStatus
    progress: int
    current_phase: str
    files_created: int = 0
    files_updated: int = 0
    events_attached: int = 0
    entities_linked: int = 0
    duplicates_merged: int = 0
    error: Optional[str] = None


class IngestionJobManager:
    """
    Manages background ingestion jobs with persistent state.

    Provides job queue management, status tracking, and coordinates
    between FileEntityIngestor and EntityRelationBuilder.
    """

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
                decode_responses=True
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
            # Fix import path for graphiti_integration
            import sys
            from pathlib import Path
            # Add python_service to path if not already there
            python_service_path = str(Path(__file__).parent.parent.parent)
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
                neo4j_password=self.settings.neo4j_password
            )
            await self._file_ingestor.initialize()

            self._entity_builder = EntityRelationBuilder(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password
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
        self._worker_task = asyncio.create_task(self._background_worker())

        logger.info("IngestionJobManager initialized")

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

    async def _save_job(self, job: IngestionJob):
        """Save job state to storage."""
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
        }

        if self._use_redis:
            await self._redis.hset(
                f"job:{job.job_id}",
                mapping=job_dict
            )
        else:
            self._jobs[job.job_id] = job

    async def _load_job(self, job_id: str) -> Optional[IngestionJob]:
        """Load job state from storage."""
        if self._use_redis:
            data = await self._redis.hgetall(f"job:{job_id}")
            if not data:
                return None
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
    ) -> str:
        """
        Queue a background ingestion job for a task.

        Args:
            task_id: Task ID to ingest.
            mode: Ingestion mode.

        Returns:
            Job ID for tracking.
        """
        job_id = self._generate_job_id()

        job = IngestionJob(
            job_id=job_id,
            task_id=task_id,
            mode=mode,
        )

        await self._save_job(job)

        # Signal worker by adding to queue
        if self._use_redis:
            await self._redis.lpush("ingestion_queue", json.dumps({
                "job_id": job_id,
                "task_id": task_id,
                "mode": mode.value,
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

        await self._update_job_status(job_id, JobStatus.CANCELLED)
        logger.info(f"Cancelled job {job_id}")
        return True

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

    async def _background_worker(self):
        """Background worker that processes the ingestion queue."""
        logger.info("Background worker started")

        while self._running:
            try:
                if self._use_redis:
                    # Pop from queue with timeout
                    item = await self._redis.brpop("ingestion_queue", timeout=5)
                    if item:
                        queue_data_raw = item[1]
                        queue_data = json.loads(queue_data_raw)
                        await self._process_job(queue_data)
                else:
                    # In-memory mode: check for pending jobs periodically
                    await asyncio.sleep(1)
                    jobs = list(self._jobs.values())
                    for job in jobs:
                        if job.status == JobStatus.PENDING:
                            await self._process_job({
                                "job_id": job.job_id,
                                "task_id": job.task_id,
                                "mode": job.mode.value,
                                "file_id": job.file_id,
                            })
                            break  # Process one at a time in-memory mode

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background worker: {e}")
                await asyncio.sleep(5)

        logger.info("Background worker stopped")

    async def _process_job(self, queue_data: dict):
        """Process a single ingestion job."""
        job_id = queue_data["job_id"]
        task_id = queue_data["task_id"]
        mode = IngestionMode(queue_data["mode"])

        try:
            await self._update_job_status(job_id, JobStatus.RUNNING, "starting")

            if mode == IngestionMode.FULL:
                await self._process_full_ingestion(job_id, task_id)
            elif mode == IngestionMode.FILES_ONLY:
                await self._process_files_only(job_id, task_id)
            elif mode == IngestionMode.EVENTS_ONLY:
                await self._process_events_only(job_id, task_id)
            elif mode == IngestionMode.SINGLE_FILE:
                file_id = queue_data.get("file_id")
                await self._process_single_file(job_id, task_id, file_id)
            elif mode == IngestionMode.ANALYZED_ONLY:
                await self._process_analyzed_only(job_id, task_id)

            await self._update_job_status(job_id, JobStatus.COMPLETED, progress=100)

        except Exception as e:
            import traceback
            logger.error(f"Job {job_id} failed: {e}")
            logger.error(traceback.format_exc())
            await self._update_job_status(
                job_id,
                JobStatus.FAILED,
                error=str(e)
            )

    async def _process_full_ingestion(self, job_id: str, task_id: str):
        """Process full ingestion: files, events, entities."""
        # Check if Neo4j components are available
        if self._file_ingestor is None or self._ForensicsDatabase is None:
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, progress=100,
                result={"message": "Full ingestion skipped - Neo4j not available"}
            )
            return

        await self._update_job_status(job_id, JobStatus.RUNNING, "reading_databases")

        # Get database paths
        output_dir = self.settings.db_output_dir
        # Try to find database files
        files_db = self._find_database(task_id, "files")
        events_db = self._find_database(task_id, "events")

        if not files_db:
            raise FileNotFoundError(f"Files database not found for task {task_id}")

        # Step 1: Create/update File entities
        await self._update_job_status(job_id, JobStatus.RUNNING, "creating_file_entities", progress=10)

        db = self._ForensicsDatabase(files_db)
        files = db.get_files()

        file_result = await self._file_ingestor.batch_ensure_files(
            files,
            task_id,
            progress_callback=lambda cur, total: asyncio.create_task(
                self._update_job_status(
                    job_id, JobStatus.RUNNING, "creating_file_entities",
                    progress=10 + int(70 * cur / total)
                )
            )
        )

        # Step 2: Attach events to files
        if events_db:
            await self._update_job_status(job_id, JobStatus.RUNNING, "attaching_events", progress=80)

            events_db_reader = self._EventsDatabase(events_db)
            events = events_db_reader.get_events()

            event_list = []
            for e in events:
                if self._EventRecord is None:
                    # Neo4j not available, skip event attachment
                    continue
                event_list.append((
                    e.file_path,
                    self._EventRecord(
                        file_inode=e.inode,
                        file_path=e.file_path,
                        event_type=e.event_type,
                        timestamp=e.timestamp,
                        task_id=task_id
                    )
                ))

            if self._file_ingestor:
                events_attached = await self._file_ingestor.attach_events_batch(event_list)
                file_result.events_attached = events_attached
            else:
                logger.warning("File ingestor not available, skipping event attachment")

        # Step 3: Create MENTIONED_IN edges
        await self._update_job_status(job_id, JobStatus.RUNNING, "linking_entities", progress=85)

        # Get existing episodes and link them to files
        relation_result = await self._create_mentioned_in_edges(task_id, files)

        # Step 4: Merge duplicate files
        await self._update_job_status(job_id, JobStatus.RUNNING, "deduplicating_files", progress=90)

        duplicates = await self._file_ingestor.merge_duplicate_files(task_id)
        file_result.duplicates_merged = duplicates

        # Store result
        await self._update_job_status(
            job_id,
            JobStatus.RUNNING,
            "finalizing",
            progress=95,
            result={
                "files_created": file_result.files_created,
                "files_updated": file_result.files_updated,
                "events_attached": file_result.events_attached,
                "entities_linked": relation_result.mentioned_in_edges_created,
                "duplicates_merged": duplicates,
            }
        )

    async def _process_files_only(self, job_id: str, task_id: str):
        """Process files-only ingestion (no events)."""
        # Check if Neo4j components are available
        if self._file_ingestor is None or self._ForensicsDatabase is None:
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, progress=100,
                result={"message": "Files ingestion skipped - Neo4j not available"}
            )
            return

        await self._update_job_status(job_id, JobStatus.RUNNING, "reading_files", progress=10)

        files_db = self._find_database(task_id, "files")
        if not files_db:
            raise FileNotFoundError(f"Files database not found for task {task_id}")

        db = self._ForensicsDatabase(files_db)
        files = db.get_files()

        file_result = await self._file_ingestor.batch_ensure_files(
            files,
            task_id,
            progress_callback=lambda cur, total: asyncio.create_task(
                self._update_job_status(
                    job_id, JobStatus.RUNNING, "processing_files",
                    progress=10 + int(80 * cur / total)
                )
            )
        )

        await self._update_job_status(
            job_id,
            JobStatus.RUNNING,
            "completed",
            progress=95,
            result={
                "files_created": file_result.files_created,
                "files_updated": file_result.files_updated,
            }
        )

    async def _process_events_only(self, job_id: str, task_id: str):
        """Process events-only ingestion."""
        await self._update_job_status(job_id, JobStatus.RUNNING, "reading_events", progress=10)

        # Check if Neo4j components are available
        if self._file_ingestor is None or self._EventRecord is None:
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, progress=100,
                result={"message": "Events processing skipped - Neo4j not available"}
            )
            return

        # Load events from storage
        events_key = f"job_events:{job_id}"
        if self._use_redis:
            events_json = await self._redis.get(events_key)
            events = json.loads(events_json) if events_json else []
        else:
            events = getattr(self._jobs.get(job_id), '_events', [])

        # Convert to EventRecord and attach
        event_list = []
        for e in events:
            event_list.append((
                e.get("file_path", ""),
                self._EventRecord(
                    file_inode=e.get("inode", 0),
                    file_path=e.get("file_path", ""),
                    event_type=e.get("event_type", "UNKNOWN"),
                    timestamp=e.get("timestamp", 0),
                    task_id=task_id
                )
            ))

        attached = await self._file_ingestor.attach_events_batch(event_list)

        await self._update_job_status(
            job_id,
            JobStatus.RUNNING,
            "completed",
            progress=100,
            result={"events_attached": attached}
        )

    async def _process_analyzed_only(self, job_id: str, task_id: str):
        """Process only AI-analyzed files and event clusters."""
        # Check if Neo4j components are available
        if self._file_ingestor is None or self._ForensicsDatabase is None:
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, progress=100,
                result={"message": "Analyzed files ingestion skipped - Neo4j not available"}
            )
            return

        await self._update_job_status(job_id, JobStatus.RUNNING, "reading_databases", progress=5)

        # 1. Get database paths
        files_db = self._find_database(task_id, "files")
        events_db = self._find_database(task_id, "events")

        if not files_db:
            raise FileNotFoundError(f"Files database not found for task {task_id}")

        # 2. Check for AI-analyzed files
        db = self._ForensicsDatabase(files_db)
        stats = db.get_analysis_stats()
        analyzed_count = stats.get("analyzed_files", 0)
        total_files = stats.get("total_files", 0)

        await self._update_job_status(
            job_id, JobStatus.RUNNING, "checking_analyzed_files",
            progress=10, result={"analyzed_files": analyzed_count, "total_files": total_files}
        )

        if analyzed_count == 0:
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, "completed", progress=100,
                result={"message": "No AI-analyzed files found", "files_processed": 0}
            )
            return

        # 3. Process only files with existing LLM analysis
        await self._update_job_status(job_id, JobStatus.RUNNING, "processing_files", progress=15)

        # Use iter_files_batched with analyzed_only=True
        all_files = []
        for batch in db.iter_files_batched(batch_size=100, analyzed_only=True):
            all_files.extend(batch)

        file_result = await self._file_ingestor.batch_ensure_files(
            all_files,
            task_id,
            progress_callback=lambda cur, total: asyncio.create_task(
                self._update_job_status(
                    job_id, JobStatus.RUNNING, "processing_files",
                    progress=15 + int(55 * cur / total)
                )
            )
        )

        # 4. Process events for analyzed files
        events_attached = 0
        if events_db:
            await self._update_job_status(job_id, JobStatus.RUNNING, "attaching_events", progress=70)

            events_db_reader = self._EventsDatabase(events_db)
            # Get events for analyzed files only
            analyzed_paths = {f.path for f in all_files}
            all_events = events_db_reader.get_events()
            events = [e for e in all_events if e.file_path in analyzed_paths]

            event_list = []
            for e in events:
                if self._EventRecord is None:
                    continue
                event_list.append((
                    e.file_path,
                    self._EventRecord(
                        file_inode=e.inode,
                        file_path=e.file_path,
                        event_type=e.event_type,
                        timestamp=e.timestamp,
                        task_id=task_id
                    )
                ))

            if self._file_ingestor and event_list:
                events_attached = await self._file_ingestor.attach_events_batch(event_list)
                file_result.events_attached = events_attached

        # 5. Create MENTIONED_IN edges from existing episodes
        await self._update_job_status(job_id, JobStatus.RUNNING, "linking_entities", progress=85)

        if self._entity_builder:
            relation_result = await self._create_mentioned_in_edges(task_id, all_files)
        else:
            logger.warning("Entity builder not available, skipping relationship creation")

        # 6. Merge duplicate files
        await self._update_job_status(job_id, JobStatus.RUNNING, "deduplicating_files", progress=90)

        if self._file_ingestor:
            duplicates = await self._file_ingestor.merge_duplicate_files(task_id)
            file_result.duplicates_merged = duplicates

        # 7. Store final result
        await self._update_job_status(
            job_id,
            JobStatus.RUNNING,
            "finalizing",
            progress=95,
            result={
                "files_created": file_result.files_created,
                "files_updated": file_result.files_updated,
                "events_attached": events_attached,
                "entities_linked": relation_result.mentioned_in_edges_created,
                "duplicates_merged": duplicates,
                "analyzed_files_processed": len(all_files),
            }
        )

    async def _process_single_file(self, job_id: str, task_id: str, file_id: int):
        """Process single file update."""
        # Check if Neo4j components are available
        if self._file_ingestor is None or self._ForensicsDatabase is None:
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, progress=100,
                result={"message": "Single file ingestion skipped - Neo4j not available"}
            )
            return

        await self._update_job_status(job_id, JobStatus.RUNNING, "reading_file", progress=10)

        files_db = self._find_database(task_id, "files")
        if not files_db:
            raise FileNotFoundError(f"Files database not found for task {task_id}")

        db = self._ForensicsDatabase(files_db)
        file = db.get_files(limit=1, offset=file_id - 1)
        if not file:
            raise FileNotFoundError(f"File {file_id} not found")
        file = file[0]

        file_id_hash = await self._file_ingestor.ensure_file_entity(file, task_id)

        await self._update_job_status(
            job_id,
            JobStatus.RUNNING,
            "completed",
            progress=100,
            result={"file_id": file_id_hash, "path": file.path}
        )

    async def _create_mentioned_in_edges(
        self,
        task_id: str,
        files: list,
    ):
        """Create MENTIONED_IN edges from episodes to files."""
        # Build episode -> file mapping
        episode_file_map = {}

        # Get episodes for this task
        query = """
            MATCH (e:Episodic {group_id: $task_id})
            RETURN e.uuid AS uuid, e.name AS name
        """

        episodes = await self._file_ingestor._run_query(query, {"task_id": task_id})

        for ep in episodes:
            ep_name = ep["name"]
            # Extract file path from episode name
            # Format: category:filename or event_type:file_path
            if ":" in ep_name:
                _, path_part = ep_name.split(":", 1)
                # Generate file ID hash
                file_id = hashlib.sha256(path_part.encode()).hexdigest()
                episode_file_map[ep["uuid"]] = file_id

        # Create edges
        return await self._entity_builder.batch_create_mentioned_in_edges({}, episode_file_map)

    def _find_database(self, task_id: str, db_type: str) -> Optional[str]:
        """Find database file for a task."""
        output_dir = self.settings.db_output_dir

        # Try task-specific directory first
        task_dir = Path(output_dir) / "tasks" / task_id
        if task_dir.exists():
            for db_file in task_dir.glob(f"*{db_type}.db"):
                return str(db_file)

        # Try output dir directly
        for db_file in Path(output_dir).glob(f"*{db_type}.db"):
            return str(db_file)

        return None
