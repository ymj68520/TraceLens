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
        self.transformer = TOONTransformer()
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
    neo4j_uri: str = "neo4j://127.0.0.1:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "password",
    batch_size: int = 50,
    dry_run: bool = False,
    group_id: str = "forensics_files",
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
    config = GraphitiConfig(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        batch_size=batch_size,
        group_id=group_id,
        filter_analyzed_only=filter_analyzed_only,
    )
    
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
        default="password",
        help="Neo4j password (default: password)",
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
