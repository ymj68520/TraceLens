"""
LLM Service - Main service orchestration.

This module provides the main LLMService class that orchestrates:
- Service initialization and lifecycle
- Model client management
- File analysis operations (via FileAnalyzer)
- Model status monitoring (via ModelManager)
- Event cluster analysis (via EventAnalyzer)
- Database persistence for analysis results
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ...config import Settings
from .file_analyzer import FileAnalyzer
from .model_manager import ModelManager
from .event_analyzer import EventAnalyzer

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for LLM-based analysis operations.

    Supports:
    - Text analysis via text models
    - Image analysis via vision models
    - Batch processing with background jobs
    - Event cluster analysis
    - Database persistence
    """

    def __init__(self, settings: Settings):
        """
        Initialize the LLM service.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self._text_client: Optional[httpx.AsyncClient] = None
        self._vision_client: Optional[httpx.AsyncClient] = None
        self._initialized = False

        # Initialize sub-modules
        self.file_analyzer = FileAnalyzer(settings)
        self.model_manager = ModelManager(settings)
        self.event_analyzer = EventAnalyzer(settings)

    async def initialize(self):
        """Initialize HTTP clients for LLM APIs."""
        if self._initialized:
            return

        # Text model client
        self._text_client = httpx.AsyncClient(
            base_url=self.settings.llm_text_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )

        # Vision model client
        self._vision_client = httpx.AsyncClient(
            base_url=self.settings.llm_vision_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )

        self._initialized = True
        logger.info("LLM service initialized")

    async def shutdown(self):
        """Close HTTP clients."""
        if self._text_client:
            await self._text_client.aclose()
            self._text_client = None

        if self._vision_client:
            await self._vision_client.aclose()
            self._vision_client = None

        self._initialized = False

    # ============================================================================
    # Database Persistence Methods
    # ============================================================================

    def _ensure_file_descriptions_schema(self, conn: sqlite3.Connection):
        """Ensure file_descriptions table and its columns exist."""
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS file_descriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                description TEXT,
                summary TEXT,
                keywords TEXT,
                model_used TEXT,
                is_relevant INTEGER DEFAULT 1,
                created_at INTEGER
            )
        """)

        # Check for is_relevant column
        cur.execute("PRAGMA table_info(file_descriptions)")
        columns = [col[1] for col in cur.fetchall()]
        if "is_relevant" not in columns:
            logger.info("Migrating table: adding is_relevant column")
            cur.execute("ALTER TABLE file_descriptions ADD COLUMN is_relevant INTEGER DEFAULT 1")

    def persist_to_files_db(
        self,
        db_path: str,
        file_path: str,
        description: str,
        summary: str,
        keywords: str,
        model_used: str = "",
    ) -> bool:
        """
        Persist LLM analysis result to C++ _files.db SQLite database.

        Args:
            db_path: Absolute path to the _files.db SQLite file.
            file_path: Path of the analyzed file.
            description: Full LLM description text.
            summary: Short summary.
            keywords: Comma-separated keyword string.
            model_used: Model identifier.

        Returns:
            True if a row was updated, False otherwise.
        """
        if not db_path or not Path(db_path).exists():
            test_db = "/home/ymj68520/projects/Forensics/ForensicsProject/build/test_image_files.db"
            if Path(test_db).exists():
                logger.debug(f"persist_to_files_db: db not found at {db_path!r}, falling back to {test_db!r}")
                db_path = test_db
            else:
                logger.debug(f"persist_to_files_db: db not found at {db_path!r}, skipping")
                return False

        sql = """
            UPDATE files SET
                llm_summary = ?,
                llm_description = ?,
                llm_keywords = ?,
                llm_analyzed_at = ?,
                llm_model_used = ?
            WHERE path = ? OR path LIKE ? OR instr(path, ?) > 0
        """
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                self._ensure_file_descriptions_schema(conn)

                cur = conn.cursor()

                # Insert into file_descriptions table
                cur.execute("""
                    INSERT INTO file_descriptions
                        (file_path, description, summary, keywords, model_used, is_relevant, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        description = excluded.description,
                        summary = excluded.summary,
                        keywords = excluded.keywords,
                        model_used = excluded.model_used,
                        created_at = excluded.created_at
                """, (
                    file_path,
                    description,
                    summary or description[:200],
                    keywords,
                    model_used,
                    int(time.time())
                ))

                # Update main files table with path variants
                path_variants = [
                    file_path,
                    f"%{Path(file_path).name}",
                    Path(file_path).name
                ]

                cur.execute(sql, (
                    summary or description[:200],
                    description,
                    keywords,
                    int(time.time()),
                    model_used,
                    path_variants[0],
                    path_variants[1],
                    path_variants[2]
                ))
                conn.commit()

                if cur.rowcount > 0 or conn.total_changes > 0:
                    logger.info(f"Successfully persisted LLM result for {file_path!r}")
                    return True

                logger.warning(f"Path match failed for {file_path!r} in {db_path!r}")
                return False
        except Exception as e:
            logger.error(f"persist_to_files_db failed for {file_path!r}: {e}", exc_info=True)
            return False

    def _ensure_events_schema(self, conn: sqlite3.Connection):
        """Ensure the events table has AI-related columns."""
        cols = ["llm_summary", "llm_description", "llm_keywords", "llm_analyzed_at", "llm_model_used", "llm_is_relevant"]
        cur = conn.cursor()
        for col in cols:
            try:
                col_type = "INTEGER" if "at" in col or "relevant" in col else "TEXT"
                cur.execute(f"ALTER TABLE events ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def persist_to_events_db(
        self,
        db_path: str,
        event_id: int,
        description: str,
        summary: str,
        keywords: str,
        model_used: str = "",
        is_relevant: bool = True,
    ) -> bool:
        """
        Persist LLM analysis result to C++ _events.db SQLite database for event clusters.
        """
        if not db_path or not Path(db_path).exists():
            logger.debug(f"persist_to_events_db: db not found at {db_path!r}, skipping")
            return False

        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                self._ensure_events_schema(conn)

                cur = conn.cursor()
                sql = """
                    UPDATE events SET
                        llm_summary = ?,
                        llm_description = ?,
                        llm_keywords = ?,
                        llm_analyzed_at = ?,
                        llm_model_used = ?,
                        llm_is_relevant = ?
                    WHERE id = ?
                """
                cur.execute(sql, (
                    summary or description[:200],
                    description,
                    keywords,
                    int(time.time()),
                    model_used,
                    1 if is_relevant else 0,
                    event_id,
                ))
                conn.commit()

                if cur.rowcount > 0:
                    logger.info(f"Persisted LLM result for event cluster {event_id} → {db_path!r}")
                    return True

                logger.warning(f"persist_to_events_db: no row matched event_id={event_id} in {db_path!r}")
                return False
        except Exception as e:
            logger.error(f"persist_to_events_db failed for event_id={event_id}: {e}", exc_info=True)
            return False

    def set_file_relevance(self, db_path: str, file_path: str, is_relevant: bool) -> bool:
        """
        Mark a file as relevant or irrelevant for the case report.
        """
        if not db_path or not Path(db_path).exists():
            logger.warning(f"set_file_relevance: DB not found at {db_path}")
            return False

        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                self._ensure_file_descriptions_schema(conn)

                cur = conn.cursor()
                cur.execute(
                    "UPDATE file_descriptions SET is_relevant = ? WHERE file_path = ?",
                    (1 if is_relevant else 0, file_path)
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to set file relevance for {file_path}: {e}")
            return False

    # ============================================================================
    # File Analysis Methods (delegated to FileAnalyzer)
    # ============================================================================

    async def read_file_content(self, file_path: str) -> str:
        """Read content from a file."""
        return await self.file_analyzer.read_file_content(file_path)

    async def analyze(
        self,
        content: str,
        model_type: str = "text",
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze content using LLM.

        Args:
            content: Content to analyze.
            model_type: 'text' or 'vision'.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).

        Returns:
            Analysis result dict.
        """
        if not self._initialized:
            logger.info("LLM service not initialized, initializing now...")
            await self.initialize()

        return await self.file_analyzer.analyze_file(
            content, self._text_client, self._vision_client,
            model_type, prompt, max_tokens, temperature
        )

    async def analyze_image(
        self,
        image_data: bytes,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an image using vision model.

        Args:
            image_data: Image binary data.
            prompt: Custom prompt (optional).

        Returns:
            Analysis result dict.
        """
        if not self._vision_client:
            await self.initialize()

        return await self.file_analyzer.analyze_image(image_data, self._vision_client, prompt)

    async def start_batch_analysis(
        self,
        files: list,
        model_type: str = "text",
        files_db_path: Optional[str] = None,
        extraction_dir: Optional[str] = None,
    ) -> str:
        """
        Start batch analysis of files.

        Args:
            files: List of file info dicts with 'path' key.
            model_type: 'text' or 'vision'.
            files_db_path: Optional path to _files.db for persisting results.
            extraction_dir: Optional file extraction directory.

        Returns:
            Job ID for tracking progress.
        """
        if not self._initialized:
            await self.initialize()

        return await self.file_analyzer.start_batch_analysis(
            files, self._text_client, self._vision_client,
            model_type, files_db_path, extraction_dir,
            persist_callback=self.persist_to_files_db
        )

    async def get_batch_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a batch analysis job."""
        return await self.file_analyzer.get_batch_status(job_id)

    # ============================================================================
    # Model Status Methods (delegated to ModelManager)
    # ============================================================================

    async def health_check(self) -> bool:
        """Check if LLM service is healthy."""
        return await self.model_manager.health_check(self._text_client, self._vision_client)

    async def check_model_status(self, model_type: str) -> bool:
        """Check if a specific model is available."""
        return await self.model_manager.check_model_status(model_type, self._text_client, self._vision_client)

    async def get_status(self) -> Dict[str, Any]:
        """Get the status of LLM services."""
        return await self.model_manager.get_status(self._text_client, self._vision_client)

    async def list_models(self, model_type: str) -> Dict[str, Any]:
        """List available models for a specific type."""
        return await self.model_manager.list_models(model_type, self._text_client, self._vision_client)

    # ============================================================================
    # Event Cluster Analysis Methods (delegated to EventAnalyzer)
    # ============================================================================

    async def analyze_event_cluster(
        self,
        event_data: Dict[str, Any],
        model_type: str = "text",
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an event cluster using LLM.

        Args:
            event_data: Event cluster data with event_type, file_path, description, etc.
            model_type: 'text' or 'vision'.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).

        Returns:
            Analysis result dict.
        """
        if not self._initialized:
            logger.info("LLM service not initialized, initializing now...")
            await self.initialize()

        return await self.event_analyzer.analyze_event_cluster(
            event_data, self._text_client, prompt, max_tokens, temperature
        )
