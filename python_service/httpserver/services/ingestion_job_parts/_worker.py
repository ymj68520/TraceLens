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


class IngestionJobWorkerMixin:
    """Auto-extracted method group; see module docstring."""

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

        # Step 5: Path-A episode ingestion (add_episode) so the LLM builds the
        # Entity/RELATES_TO graph the frontend visualises. Without this the
        # manual "Ingest" button only writes :File nodes (invisible to viz).
        ep_stats = await self._ingest_episodes_path_a(
            job_id, task_id, files_db, events_db, analyzed_only=False
        )

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
                **ep_stats,
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
            logger.warning(f"[ANALYZED_ONLY] Files database not found for task {task_id}, skipping ingestion")
            await self._update_job_status(
                job_id, JobStatus.COMPLETED, "completed", progress=100,
                result={"message": f"Files database not found for task {task_id}, skipping analyzed files ingestion"}
            )
            return

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

        duplicates = 0
        if self._file_ingestor:
            duplicates = await self._file_ingestor.merge_duplicate_files(task_id)
            file_result.duplicates_merged = duplicates

        # 7. Path-A episode ingestion (add_episode) for the analyzed files so
        # the frontend visualisation actually shows entities/relationships.
        ep_stats = await self._ingest_episodes_path_a(
            job_id, task_id, files_db, events_db, analyzed_only=True
        )

        # 8. Store final result
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
                **ep_stats,
            }
        )

    async def _ingest_episodes_path_a(
        self,
        job_id: str,
        task_id: str,
        files_db: Optional[str],
        events_db: Optional[str],
        analyzed_only: bool,
    ) -> dict:
        """
        Run path-A (add_episode) ingestion via GraphitiService.

        The manual "Ingest" button must ALSO produce the Episodic → Entity →
        RELATES_TO graph the frontend visualises, otherwise users see an empty
        graph after ingesting. This reads the LLM-analyzed file_descriptions
        (and event cluster analyses) from SQLite and feeds them to
        ``GraphitiService.ingest_task_episodes`` so the extractor can build
        entities/relationships.

        Failures here are non-fatal: the path-B :File entities are still valid.
        Returns a stats dict.
        """
        stats = {"episodes_successful": 0, "episodes_total": 0, "episodes_failed": 0, "error": None}
        try:
            from ..dependencies import get_service_manager
            service_manager = get_service_manager()
            graphiti_service = getattr(service_manager, "graphiti_service", None)
            if graphiti_service is None:
                stats["error"] = "graphiti_service unavailable"
                return stats

            if not files_db or not Path(files_db).exists():
                stats["error"] = f"files_db not found: {files_db}"
                return stats

            import sqlite3
            file_descs: list = []
            with sqlite3.connect(files_db, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                # Ensure schema has the description columns (added lazily by analysis pipeline)
                where = "WHERE description IS NOT NULL AND description != ''" if analyzed_only else ""
                try:
                    cur = conn.execute(
                        f"SELECT DISTINCT file_path, description, summary FROM file_descriptions {where}"
                    )
                    for row in cur.fetchall():
                        desc = row["description"] or row["summary"] or ""
                        if desc:
                            file_descs.append({"file_path": row["file_path"], "description": desc, "success": True})
                except sqlite3.OperationalError:
                    # file_descriptions table may not exist yet for this task
                    stats["error"] = "file_descriptions table missing"

            # Event cluster analyses (optional)
            cluster_descs: list = []
            if events_db and Path(events_db).exists():
                import sqlite3
                with sqlite3.connect(events_db, timeout=10) as conn:
                    conn.row_factory = sqlite3.Row
                    try:
                        cur = conn.execute(
                            "SELECT DISTINCT event_type, llm_description, llm_summary, "
                            "(timestamp / 60) as time_window FROM events "
                            "WHERE llm_description IS NOT NULL GROUP BY event_type, time_window"
                        )
                        for row in cur.fetchall():
                            desc = row["llm_description"] or row["llm_summary"] or ""
                            if desc:
                                cluster_descs.append({
                                    "event_type": row["event_type"],
                                    "time_window": row["time_window"],
                                    "analysis": {"description": desc},
                                })
                    except sqlite3.OperationalError:
                        pass  # events table may be absent

            if not file_descs and not cluster_descs:
                stats["error"] = stats.get("error") or "no analyzed descriptions to ingest"
                return stats

            await self._update_job_status(
                job_id, JobStatus.RUNNING, "ingesting_episodes",
                progress=92,
            )
            result = await graphiti_service.ingest_task_episodes(
                task_id=task_id,
                file_descriptions=file_descs,
                cluster_descriptions=cluster_descs,
            )
            stats["episodes_successful"] = result.get("successful", 0)
            stats["episodes_total"] = result.get("total", 0)
            stats["episodes_failed"] = result.get("failed", 0)
            if result.get("error"):
                stats["error"] = result["error"]
            logger.info(
                f"[{task_id}] Path-A episode ingestion: "
                f"{stats['episodes_successful']}/{stats['episodes_total']} successful"
            )
        except Exception as e:
            logger.warning(f"[{task_id}] Path-A episode ingestion failed (non-fatal): {e}")
            stats["error"] = str(e)
        return stats

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
        task_ids = [task_id]
        compact_task_id = task_id.replace("-", "")

        # Support both hyphenated and compact UUID formats.
        if compact_task_id != task_id:
            task_ids.append(compact_task_id)
        if len(compact_task_id) == 32:
            try:
                hyphenated_task_id = str(uuid.UUID(compact_task_id))
                if hyphenated_task_id not in task_ids:
                    task_ids.append(hyphenated_task_id)
            except ValueError:
                pass

        current_root = Path.cwd()
        project_root = Path(__file__).resolve().parents[3]
        configured_output = Path(self.settings.db_output_dir).expanduser()

        candidate_roots: list[Path] = []

        def add_root(path: Path):
            if path not in candidate_roots:
                candidate_roots.append(path)

        # Resolve configured output dir relative to both process CWD and project root.
        if configured_output.is_absolute():
            add_root(configured_output)
        else:
            add_root(current_root / configured_output)
            add_root(project_root / configured_output)

        # Common locations used by C++ PathManager and local dev runs.
        add_root(current_root / "build" / "data")
        add_root(project_root / "build" / "data")
        add_root(current_root / "data")
        add_root(project_root / "data")

        for root in candidate_roots:
            for tid in task_ids:
                for task_dir in (root / "tasks" / tid, root / tid):
                    if not task_dir.exists():
                        continue

                    exact = task_dir / f"{db_type}.db"
                    if exact.exists():
                        return str(exact)

                    matches = sorted(task_dir.glob(f"*{db_type}.db"))
                    if matches:
                        return str(matches[0])

        # Legacy fallback: search directly in root dirs.
        for root in candidate_roots:
            matches = sorted(root.glob(f"*{db_type}.db"))
            if matches:
                return str(matches[0])

        return None

