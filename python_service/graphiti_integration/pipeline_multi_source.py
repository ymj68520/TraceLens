"""Multi-source pipeline for Database-Graphiti integration.

Extracted from pipeline.py for maintainability. Provides MultiSourcePipeline
and run_multi_source_pipeline for ingesting multiple data sources into Graphiti.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import GraphitiConfig
from .database_reader import ForensicsDatabase
from .exceptions import (
    DatabaseError,
    GraphitiIntegrationError,
    IngestionError,
    TransformationError,
)
from .graphiti_ingestor import GraphitiIngestor, IngestionResult
from .toon_transformer import TOONTransformer
from .pipeline import PipelineResult

logger = logging.getLogger(__name__)


# =============================================================================
# Multi-Source Pipeline (processes all per-image databases)
# =============================================================================

@dataclass
class MultiSourceResult:
    """Result of a multi-source pipeline run."""

    # Per-source results
    source_results: dict = field(default_factory=dict)  # {source_type: PipelineResult}

    # Aggregated counts
    total_episodes: int = 0
    total_ingested: int = 0
    total_failed: int = 0

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    @property
    def sources_processed(self) -> int:
        return len(self.source_results)

    def summary(self) -> str:
        lines = [
            f"Multi-Source Pipeline Result:",
            f"  Sources processed: {self.sources_processed}",
            f"  Total episodes: {self.total_episodes}",
            f"  Total ingested: {self.total_ingested}",
            f"  Total failed:   {self.total_failed}",
            f"  Duration: {self.duration_seconds:.2f}s",
        ]
        for source, result in self.source_results.items():
            lines.append(f"  [{source}] ingested={result.ingested}, failed={result.failed}")
        return "\n".join(lines)


class MultiSourcePipeline:
    """
    Orchestrates knowledge graph construction from all per-image databases.

    Flow:
      1. Auto-discover databases for a given image base name / output dir
      2. For each discovered database (files, events, windows, linux, android):
         a. Read records in batches
         b. Transform to Graphiti episodes
         c. Ingest into Neo4j with group_id = task_id
      3. Report aggregated results
    """

    def __init__(self, config: GraphitiConfig):
        self.config = config
        self.ingestor: Optional[GraphitiIngestor] = None

    async def run(
        self,
        base_name: Optional[str] = None,
        output_dir: Optional[str] = None,
        any_db_path: Optional[str] = None,
        group_id: Optional[str] = None,
        dry_run: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> MultiSourceResult:
        """
        Run the multi-source pipeline.

        Args:
            base_name: Image base name (e.g. "Server").
            output_dir: Directory with database files.
            any_db_path: Path to any one DB; base name is inferred.
            group_id: Graphiti group_id for per-image isolation.
            dry_run: If True, transform but don't ingest.
            progress_callback: Optional callback(source, phase, current, total).

        Returns:
            MultiSourceResult with per-source and aggregated statistics.
        """
        from .database_reader import (
            ForensicsDatabaseFactory,
            EventsDatabase,
            WindowsDatabase,
            LinuxDatabase,
            AndroidDatabase,
        )
        from .toon_transformer import ForensicEpisodeTransformer

        result = MultiSourceResult(started_at=datetime.now())
        group_id = group_id or self.config.group_id

        # Discover databases
        discovered = ForensicsDatabaseFactory.discover(
            base_name=base_name,
            output_dir=output_dir,
            any_db_path=any_db_path,
        )
        logger.info(discovered.summary())

        if not discovered.available_types:
            logger.warning("No databases discovered")
            result.completed_at = datetime.now()
            return result

        # Initialize ingestor if not dry run
        if not dry_run:
            self.ingestor = GraphitiIngestor(self.config)
            await self.ingestor.initialize()

        readers = ForensicsDatabaseFactory.create_readers(discovered)
        file_transformer = TOONTransformer(
            include_full_description=self.config.include_full_description
        )
        forensic_transformer = ForensicEpisodeTransformer()

        try:
            # --- Process files database ---
            if "files" in readers:
                logger.info("Processing files database...")
                file_result = await self._process_files(
                    readers["files"], file_transformer, group_id, dry_run, progress_callback
                )
                result.source_results["files"] = file_result
                result.total_episodes += file_result.transformed
                result.total_ingested += file_result.ingested
                result.total_failed += file_result.failed

            # --- Process events database ---
            if "events" in readers:
                logger.info("Processing events database...")
                events_result = await self._process_events(
                    readers["events"], forensic_transformer, group_id, dry_run, progress_callback
                )
                result.source_results["events"] = events_result
                result.total_episodes += events_result.transformed
                result.total_ingested += events_result.ingested
                result.total_failed += events_result.failed

            # --- Process platform-specific databases ---
            for platform in ["windows", "linux", "android"]:
                if platform in readers:
                    logger.info(f"Processing {platform} database...")
                    plat_result = await self._process_platform(
                        platform, readers[platform], forensic_transformer,
                        group_id, dry_run, progress_callback,
                    )
                    result.source_results[platform] = plat_result
                    result.total_episodes += plat_result.transformed
                    result.total_ingested += plat_result.ingested
                    result.total_failed += plat_result.failed

        finally:
            if self.ingestor:
                await self.ingestor.close()

        result.completed_at = datetime.now()
        logger.info(result.summary())
        return result

    async def _process_files(
        self, reader, transformer, group_id, dry_run, progress_callback
    ) -> PipelineResult:
        """Process files database using existing TOONTransformer."""
        res = PipelineResult(started_at=datetime.now())
        res.total_files = reader.count_files()
        max_eps = self.config.max_episodes

        logger.info(f"Starting files processing: {res.total_files} files (max_episodes={max_eps or 'unlimited'})")

        processed_count = 0
        for batch in reader.iter_files_batched(
            batch_size=self.config.batch_size,
            analyzed_only=self.config.filter_analyzed_only,
        ):
            # Check max_episodes limit
            if max_eps > 0 and processed_count >= max_eps:
                logger.info(f"Reached max_episodes limit ({max_eps}), stopping files processing")
                break

            episodes, errors = transformer.transform_batch(batch)
            res.transformed += len(episodes)
            res.failed += len(errors)
            for record, error in errors:
                res.transformation_errors.append({"file_path": record.path, "error": str(error)})

            if not dry_run and episodes and self.ingestor:
                logger.info(f"Ingesting batch of {len(episodes)} episodes (total processed: {processed_count + len(episodes)})")
                ingestion_result = await self.ingestor.batch_ingest(episodes, group_id=group_id)
                res.ingested += ingestion_result.successful
                res.failed += ingestion_result.failed
                processed_count += len(episodes)
            elif dry_run:
                res.ingested += len(episodes)
                processed_count += len(episodes)

        logger.info(f"Files processing complete: {res.ingested} ingested, {res.failed} failed")
        res.completed_at = datetime.now()
        return res

    async def _process_events(
        self, reader, transformer, group_id, dry_run, progress_callback
    ) -> PipelineResult:
        """Process events database, including event clusters with AI analysis."""
        res = PipelineResult(started_at=datetime.now())
        max_eps = self.config.max_episodes

        # Process regular events
        logger.info("Processing regular events...")
        event_count = reader.count_events()
        res.total_files += event_count

        processed_count = 0
        for batch in reader.iter_events_batched(batch_size=self.config.batch_size):
            # Check max_episodes limit
            if max_eps > 0 and processed_count >= max_eps:
                logger.info(f"Reached max_episodes limit ({max_eps}), stopping events processing")
                break

            episodes, errors = transformer.transform_events_batch(batch)
            res.transformed += len(episodes)
            res.failed += len(errors)

            if not dry_run and episodes and self.ingestor:
                logger.info(f"Ingesting event batch of {len(episodes)} episodes")
                ingestion_result = await self.ingestor.batch_ingest(episodes, group_id=group_id)
                res.ingested += ingestion_result.successful
                res.failed += ingestion_result.failed
                processed_count += len(episodes)
            elif dry_run:
                res.ingested += len(episodes)
                processed_count += len(episodes)

        # Process event clusters with AI analysis
        logger.info("Processing event clusters with AI analysis...")
        cluster_stats = reader.get_event_cluster_stats()
        cluster_count = cluster_stats.get("analyzed_clusters", 0)
        res.total_files += cluster_count

        if cluster_count > 0:
            for batch in reader.iter_event_clusters_batched(
                batch_size=self.config.batch_size,
                analyzed_only=True
            ):
                # Check max_episodes limit for clusters too
                if max_eps > 0 and processed_count >= max_eps:
                    logger.info(f"Reached max_episodes limit ({max_eps}), stopping cluster processing")
                    break

                episodes, errors = transformer.transform_event_clusters_batch(batch)
                res.transformed += len(episodes)
                res.failed += len(errors)

                if not dry_run and episodes and self.ingestor:
                    logger.info(f"Ingesting cluster batch of {len(episodes)} episodes")
                    ingestion_result = await self.ingestor.batch_ingest(episodes, group_id=group_id)
                    res.ingested += ingestion_result.successful
                    res.failed += ingestion_result.failed
                    processed_count += len(episodes)
                elif dry_run:
                    res.ingested += len(episodes)
                    processed_count += len(episodes)

        logger.info(f"Events processing complete: {res.ingested} ingested, {res.failed} failed")
        res.completed_at = datetime.now()
        return res

    async def _process_platform(
        self, platform, reader, transformer, group_id, dry_run, progress_callback
    ) -> PipelineResult:
        """Process platform-specific database (Windows/Linux/Android)."""
        res = PipelineResult(started_at=datetime.now())

        transform_method = {
            "windows": transformer.transform_windows_batch,
            "linux": transformer.transform_linux_batch,
            "android": transformer.transform_android_batch,
        }[platform]

        for artifact_type, batch in reader.get_all_artifacts_batched(
            batch_size=self.config.batch_size
        ):
            episodes, errors = transform_method(artifact_type, batch)
            res.total_files += len(batch)
            res.transformed += len(episodes)
            res.failed += len(errors)

            if not dry_run and episodes and self.ingestor:
                ingestion_result = await self.ingestor.batch_ingest(episodes, group_id=group_id)
                res.ingested += ingestion_result.successful
                res.failed += ingestion_result.failed
            elif dry_run:
                res.ingested += len(episodes)

        res.completed_at = datetime.now()
        return res


async def run_multi_source_pipeline(
    base_name: Optional[str] = None,
    output_dir: Optional[str] = None,
    any_db_path: Optional[str] = None,
    group_id: Optional[str] = None,
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    batch_size: Optional[int] = None,
    dry_run: bool = False,
) -> MultiSourceResult:
    """
    Convenience function to run the multi-source pipeline.

    Args:
        base_name: Image base name (e.g., "Server").
        output_dir: Output directory containing databases.
        any_db_path: Path to any one database file.
        group_id: Graphiti group_id for per-image isolation.
        neo4j_uri: Neo4j connection URI.
        neo4j_user: Neo4j username.
        neo4j_password: Neo4j password.
        batch_size: Records per batch.
        dry_run: Transform without ingesting.

    Returns:
        MultiSourceResult with per-source and aggregated statistics.
    """
    config = GraphitiConfig.from_env()
    
    if neo4j_uri is not None:
        config.neo4j_uri = neo4j_uri
    if neo4j_user is not None:
        config.neo4j_user = neo4j_user
    if neo4j_password is not None and neo4j_password != "":
        config.neo4j_password = neo4j_password
        
    if batch_size is not None:
        config.batch_size = batch_size
    if group_id is not None:
        config.group_id = group_id

    pipeline = MultiSourcePipeline(config)
    return await pipeline.run(
        base_name=base_name,
        output_dir=output_dir,
        any_db_path=any_db_path,
        group_id=config.group_id,
        dry_run=dry_run,
    )

