"""
Main pipeline orchestration for Database-Graphiti integration.

This module provides the main entry point for running the complete
data pipeline: read from database -> transform -> ingest to Graphiti.
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

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

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a complete pipeline run."""
    
    # Counts
    total_files: int = 0
    transformed: int = 0
    ingested: int = 0
    failed: int = 0
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Errors
    transformation_errors: list = field(default_factory=list)
    ingestion_errors: list = field(default_factory=list)
    
    @property
    def duration_seconds(self) -> float:
        """Calculate pipeline duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate overall success rate."""
        if self.total_files == 0:
            return 0.0
        return (self.ingested / self.total_files) * 100
    
    def summary(self) -> str:
        """Generate a human-readable summary."""
        return (
            f"Pipeline Result:\n"
            f"  Total files: {self.total_files}\n"
            f"  Transformed: {self.transformed}\n"
            f"  Ingested: {self.ingested}\n"
            f"  Failed: {self.failed}\n"
            f"  Success rate: {self.success_rate:.1f}%\n"
            f"  Duration: {self.duration_seconds:.2f}s"
        )


class GraphitiPipeline:
    """
    Main pipeline for Database-Graphiti integration.
    
    Orchestrates the complete flow:
    1. Read file records from SQLite database
    2. Transform records to Graphiti episodes
    3. Batch ingest episodes into the knowledge graph
    """
    
    def __init__(self, config: GraphitiConfig):
        """
        Initialize pipeline.

        Args:
            config: Pipeline configuration.
        """
        self.config = config
        self.transformer = TOONTransformer(
            include_full_description=config.include_full_description
        )
        self.ingestor: Optional[GraphitiIngestor] = None
    
    async def run(
        self,
        db_path: Optional[str] = None,
        dry_run: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> PipelineResult:
        """
        Run the complete pipeline.
        
        Args:
            db_path: Path to SQLite database (overrides config).
            dry_run: If True, transform but don't ingest.
            progress_callback: Optional callback(phase, current, total) for progress.
        
        Returns:
            PipelineResult with statistics and errors.
        """
        result = PipelineResult(started_at=datetime.now())
        
        # Use provided db_path or config
        db_path = db_path or self.config.db_path
        if not db_path:
            raise GraphitiIntegrationError("Database path is required")
        
        try:
            # Phase 1: Read from database
            logger.info(f"Reading files from database: {db_path}")
            database = ForensicsDatabase(db_path)
            
            # Get stats first
            stats = database.get_analysis_stats()
            result.total_files = stats["analyzed_files"] if self.config.filter_analyzed_only else stats["total_files"]
            logger.info(f"Found {result.total_files} files to process")
            
            if result.total_files == 0:
                logger.warning("No files to process")
                result.completed_at = datetime.now()
                return result
            
            # Initialize ingestor if not dry run
            if not dry_run:
                self.ingestor = GraphitiIngestor(self.config)
                await self.ingestor.initialize()
            
            # Phase 2 & 3: Transform and ingest in batches
            batch_num = 0
            total_batches = (result.total_files + self.config.batch_size - 1) // self.config.batch_size
            
            for batch in database.iter_files_batched(
                batch_size=self.config.batch_size,
                analyzed_only=self.config.filter_analyzed_only,
                categories=self.config.filter_categories if self.config.filter_categories else None,
            ):
                batch_num += 1
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} files)")
                
                # Transform batch
                episodes, transform_errors = self.transformer.transform_batch(batch)
                result.transformed += len(episodes)
                
                for record, error in transform_errors:
                    result.transformation_errors.append({
                        "file_path": record.path,
                        "error": str(error),
                    })
                    result.failed += 1
                
                if transform_errors:
                    logger.warning(f"Batch {batch_num}: {len(transform_errors)} transformation errors")
                
                # Ingest batch (unless dry run)
                if not dry_run and episodes:
                    ingestion_result = await self.ingestor.batch_ingest(
                        episodes,
                        group_id=self.config.group_id,
                    )
                    result.ingested += ingestion_result.successful
                    result.failed += ingestion_result.failed
                    result.ingestion_errors.extend(ingestion_result.errors)
                elif dry_run:
                    # In dry run, count transformed as "ingested" for success rate
                    result.ingested += len(episodes)
                    logger.info(f"[DRY RUN] Would ingest {len(episodes)} episodes")
                
                # Progress callback
                if progress_callback:
                    processed = batch_num * self.config.batch_size
                    progress_callback("processing", min(processed, result.total_files), result.total_files)
            
            result.completed_at = datetime.now()
            logger.info(result.summary())
            return result
        
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            result.failed = result.total_files
            result.completed_at = datetime.now()
            raise
        
        finally:
            # Cleanup
            if self.ingestor:
                await self.ingestor.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.ingestor:
            await self.ingestor.close()


async def run_pipeline(
    db_path: str,
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    batch_size: Optional[int] = None,
    dry_run: bool = False,
    group_id: Optional[str] = None,
    filter_analyzed_only: bool = False,
) -> PipelineResult:
    """
    Convenience function to run the pipeline with minimal configuration.
    
    Args:
        db_path: Path to SQLite database.
        neo4j_uri: Neo4j connection URI.
        neo4j_user: Neo4j username.
        neo4j_password: Neo4j password.
        batch_size: Number of records per batch.
        dry_run: If True, transform but don't ingest.
        group_id: Graphiti group ID for organizing data.
        filter_analyzed_only: If True, only process files with LLM analysis.
    
    Returns:
        PipelineResult with statistics.
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
    config.filter_analyzed_only = filter_analyzed_only
    
    pipeline = GraphitiPipeline(config)
    return await pipeline.run(db_path=db_path, dry_run=dry_run)


def main():
    """CLI entry point for the pipeline."""
    parser = argparse.ArgumentParser(
        description="Database-Graphiti Integration Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to verify transformation
  python -m graphiti_integration.pipeline --db-path ./data.db --dry-run
  
  # Full ingestion
  python -m graphiti_integration.pipeline --db-path ./data.db --neo4j-uri neo4j://localhost:7687
        """,
    )
    
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to SQLite database with file records",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="neo4j://127.0.0.1:7687",
        help="Neo4j connection URI (default: neo4j://127.0.0.1:7687)",
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username (default: neo4j)",
    )
    parser.add_argument(
        "--neo4j-password",
        default="",
        help="Neo4j password",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Records per batch (default: 50)",
    )
    parser.add_argument(
        "--group-id",
        default="forensics_files",
        help="Graphiti group ID (default: forensics_files)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Transform without ingesting",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--analyzed-only",
        action="store_true",
        help="Only process files that have LLM analysis (default: process all files)",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Run pipeline
    try:
        result = asyncio.run(run_pipeline(
            db_path=args.db_path,
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            group_id=args.group_id,
            filter_analyzed_only=args.analyzed_only,
        ))
        
        print("\n" + result.summary())
        
        if result.failed > 0:
            print(f"\nErrors encountered: {result.failed}")
            sys.exit(1)
        
        sys.exit(0)
    
    except GraphitiIntegrationError as e:
        logger.error(f"Pipeline error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()


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

