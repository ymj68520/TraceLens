"""
Windows Artifacts Service — Main service class for Windows artifact analysis.

This is the main entry point that coordinates Windows artifact filtering,
analysis, and report generation.
"""

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings

from .windows_filter import WindowsArtifactFilter
from .windows_analyzer import WindowsArtifactAnalyzer

logger = logging.getLogger(__name__)


class WindowsArtifactsService:
    """Service for end-to-end Windows artifact analysis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm_service = None
        self._graphiti_service = None
        self._cpp_backend = None

        # Sub-modules (initialized after dependency injection)
        self._filter = None
        self._analyzer = None

    def set_llm_service(self, llm_service):
        """Inject the LLM service dependency."""
        self._llm_service = llm_service
        self._initialize_modules()

    def set_graphiti_service(self, graphiti_service):
        """Inject the Graphiti knowledge graph service (optional)."""
        self._graphiti_service = graphiti_service
        self._initialize_modules()

    def set_cpp_backend(self, cpp_backend):
        """Inject the C++ backend service dependency."""
        self._cpp_backend = cpp_backend
        self._initialize_modules()

    def _initialize_modules(self):
        """Initialize sub-modules after all dependencies are injected."""
        if self._llm_service:
            self._filter = WindowsArtifactFilter(self.settings, self._llm_service)
            self._analyzer = WindowsArtifactAnalyzer(
                self.settings,
                self._llm_service,
                self._graphiti_service
            )
            logger.info("Windows artifacts sub-modules initialized")
            if self._graphiti_service:
                logger.info("Graphiti service is available for Windows artifacts")
            else:
                logger.info("Graphiti service not available - knowledge graph features disabled")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_full_analysis(
        self,
        task_id: str,
        windows_db_path: str,
        case_description: str,
        max_artifacts: int = 200,
        artifact_types: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run the full Windows artifacts analysis pipeline.

        Args:
            task_id: Task identifier
            windows_db_path: Path to _windows.db
            case_description: Case description for filtering/analysis
            max_artifacts: Maximum artifacts to analyze per type
            artifact_types: Artifact types to process (None = all)
            progress_callback: Optional progress callback

        Returns:
            Analysis results with statistics
        """
        if not self._filter or not self._analyzer:
            raise RuntimeError("Windows artifacts modules not initialized")

        start_time = time.time()

        # Step 1: Filter artifacts by case
        if progress_callback:
            await progress_callback("filtering", "正在筛选Windows痕迹...")

        filter_result = await self._filter.filter_artifacts_by_case(
            windows_db_path=windows_db_path,
            case_description=case_description,
            max_artifacts=max_artifacts,
            artifact_types=artifact_types,
            progress_callback=progress_callback,
        )

        selected_by_type = filter_result["selected_by_type"]
        total_selected = filter_result["total_selected"]

        if total_selected == 0:
            logger.warning(f"No Windows artifacts selected for task {task_id}")
            return {
                "success": True,
                "task_id": task_id,
                "filter": {"selected_count": 0, "by_type": {}},
                "analysis": {"analyzed_count": 0, "results": []},
                "total_time": time.time() - start_time,
            }

        # Step 2: Analyze selected artifacts
        if progress_callback:
            await progress_callback("analyzing", "正在分析Windows痕迹...")

        analysis_results = await self._analyzer.analyze_selected_artifacts(
            windows_db_path=windows_db_path,
            selected_by_type=selected_by_type,
            case_description=case_description,
            progress_callback=progress_callback,
        )

        # Step 3: Persist results
        if progress_callback:
            await progress_callback("persisting", "正在保存分析结果...")

        persisted = self._persist_analysis_results(
            windows_db_path=windows_db_path,
            results=analysis_results,
            task_id=task_id
        )

        # Step 4: Ingest to knowledge graph (if available)
        if self._graphiti_service:
            if progress_callback:
                await progress_callback("graphiti", "正在导入知识图谱...")

            try:
                await self._ingest_to_graphiti(
                    task_id=task_id,
                    case_description=case_description,
                    artifact_descriptions=analysis_results,
                )
            except Exception as e:
                logger.warning(f"Graphiti ingestion failed: {e}")

        total_time = time.time() - start_time

        return {
            "success": True,
            "task_id": task_id,
            "filter": {
                "selected_count": total_selected,
                "by_type": {k: len(v) for k, v in selected_by_type.items()},
            },
            "analysis": {
                "analyzed_count": len(analysis_results),
                "results": analysis_results[:10],  # Return first 10 as sample
            },
            "persisted": persisted,
            "total_time": total_time,
        }

    def get_artifact_report(
        self,
        windows_db_path: str,
        task_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve the persisted Windows artifact analysis report.

        Args:
            windows_db_path: Path to _windows.db
            task_id: Task identifier

        Returns:
            Report data or None if not found
        """
        try:
            with sqlite3.connect(windows_db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute("""
                    SELECT artifact_type, COUNT(*) as count
                    FROM windows_artifact_descriptions
                    GROUP BY artifact_type
                """)
                by_type = {row["artifact_type"]: row["count"] for row in cur.fetchall()}

                cur = conn.execute("SELECT COUNT(*) as total FROM windows_artifact_descriptions")
                total = cur.fetchone()["total"]

                cur = conn.execute("""
                    SELECT artifact_type, artifact_id, summary, description, severity
                    FROM windows_artifact_descriptions
                    WHERE severity IN ('high', 'critical')
                    ORDER BY severity DESC, relevance DESC
                    LIMIT 50
                """)
                high_priority = [dict(row) for row in cur.fetchall()]

                return {
                    "task_id": task_id,
                    "total_analyzed": total,
                    "by_type": by_type,
                    "high_priority_artifacts": high_priority,
                    "has_analysis": total > 0,
                }
        except Exception as e:
            logger.error(f"Error retrieving Windows artifact report: {e}", exc_info=True)
            return None

    async def reanalyze_artifacts(
        self,
        task_id: str,
        artifact_ids: List[tuple],  # List of (artifact_type, artifact_id)
        user_hint: str,
        windows_db_path: str,
        case_description: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Re-analyze specific artifacts with additional user context.

        Args:
            task_id: Task identifier
            artifact_ids: List of (artifact_type, artifact_id) tuples
            user_hint: Additional user context
            windows_db_path: Path to _windows.db
            case_description: Original case description

        Returns:
            Analysis results for re-analyzed artifacts
        """
        if not self._analyzer:
            raise RuntimeError("Windows artifacts analyzer not initialized")

        from graphiti_integration.database_reader import WindowsDatabase

        windows_db = WindowsDatabase(windows_db_path)
        results = []

        for artifact_type, artifact_id in artifact_ids:
            try:
                # Get artifact from database
                artifacts = await self._analyzer._get_artifacts_by_type(windows_db, artifact_type)
                artifact = next((a for a in artifacts if str(a.get("id")) == str(artifact_id)), None)

                if not artifact:
                    logger.warning(f"Artifact {artifact_type}:{artifact_id} not found")
                    continue

                # Analyze with user hint
                result = await self._analyzer._analyze_single_artifact(
                    artifact=artifact,
                    artifact_type=artifact_type,
                    case_description=case_description,
                    user_hint=user_hint
                )

                results.append(result)

                # Persist updated result
                self._persist_single_result(windows_db_path, result)

            except Exception as e:
                logger.error(f"Error re-analyzing {artifact_type}:{artifact_id}: {e}")
                results.append({"success": False, "error": "artifact analysis failed"})

        return results

    def get_filtered_artifacts(
        self,
        windows_db_path: str,
        artifact_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get filtered artifact descriptions from database."""
        try:
            with sqlite3.connect(windows_db_path) as conn:
                conn.row_factory = sqlite3.Row

                query = "SELECT * FROM windows_artifact_descriptions WHERE 1=1"
                params = []

                if artifact_type:
                    query += " AND artifact_type = ?"
                    params.append(artifact_type)

                if severity:
                    query += " AND severity = ?"
                    params.append(severity)

                query += " ORDER BY relevance DESC LIMIT ?"
                params.append(limit)

                cur = conn.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting filtered artifacts: {e}")
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist_analysis_results(
        self,
        windows_db_path: str,
        results: List[Dict[str, Any]],
        task_id: str,
    ) -> int:
        """Persist analysis results to database."""
        try:
            with sqlite3.connect(windows_db_path) as conn:
                # Ensure table exists
                self._ensure_artifact_descriptions_table(conn)

                persisted = 0
                for result in results:
                    if result.get("success"):
                        try:
                            conn.execute("""
                                INSERT OR REPLACE INTO windows_artifact_descriptions
                                (artifact_type, artifact_id, summary, description, keywords,
                                 severity, relevance, model_used, analyzed_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                result["type"],
                                result["id"],
                                result.get("summary", ""),
                                result.get("description", ""),
                                result.get("keywords", ""),
                                result.get("severity", "low"),
                                result.get("relevance", 0.0),
                                result.get("model_used", ""),
                                result.get("analyzed_at", int(time.time()))
                            ))
                            persisted += 1
                        except Exception as e:
                            logger.error(f"Error persisting artifact: {e}")

                conn.commit()
                logger.info(f"Persisted {persisted} Windows artifact descriptions")
                return persisted
        except Exception as e:
            logger.error(f"Error persisting results: {e}", exc_info=True)
            return 0

    def _persist_single_result(self, windows_db_path: str, result: Dict[str, Any]):
        """Persist a single analysis result."""
        try:
            with sqlite3.connect(windows_db_path) as conn:
                self._ensure_artifact_descriptions_table(conn)

                if result.get("success"):
                    conn.execute("""
                        INSERT OR REPLACE INTO windows_artifact_descriptions
                        (artifact_type, artifact_id, summary, description, keywords,
                         severity, relevance, model_used, analyzed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        result["type"],
                        result["id"],
                        result.get("summary", ""),
                        result.get("description", ""),
                        result.get("keywords", ""),
                        result.get("severity", "low"),
                        result.get("relevance", 0.0),
                        result.get("model_used", ""),
                        result.get("analyzed_at", int(time.time()))
                    ))
                    conn.commit()
        except Exception as e:
            logger.error(f"Error persisting single result: {e}")

    def _ensure_artifact_descriptions_table(self, conn: sqlite3.Connection):
        """Ensure the artifact descriptions table exists."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS windows_artifact_descriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_type TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                summary TEXT,
                description TEXT,
                keywords TEXT,
                severity TEXT DEFAULT 'low',
                relevance REAL DEFAULT 0.0,
                model_used TEXT,
                analyzed_at INTEGER,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                UNIQUE(artifact_type, artifact_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_windows_desc_type
            ON windows_artifact_descriptions(artifact_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_windows_desc_relevance
            ON windows_artifact_descriptions(relevance DESC)
        """)

    async def _ingest_to_graphiti(
        self,
        task_id: str,
        case_description: str,
        artifact_descriptions: List[Dict[str, Any]],
    ):
        """Ingest Windows artifact descriptions into Graphiti knowledge graph.

        Routes through GraphitiService.ingest_task_episodes so each artifact
        becomes a real episode (add_episode) and the LLM can extract entities/
        relationships — the previous code called a non-existent ``.ingest()``
        method and never ran.
        """
        if not self._graphiti_service:
            return

        # Normalize artifact descriptions into the file_description-like shape
        # expected by ingest_task_episodes (file_path/id + description + success).
        normalized = []
        for desc in artifact_descriptions:
            if not desc.get("success"):
                continue
            body = (desc.get("description", "") or "") + "\n\n" + (desc.get("summary", "") or "")
            normalized.append({
                "file_path": f"{desc.get('type', 'windows_artifact')}:{desc.get('id', '')}",
                "description": body,
                "category": f"windows_{desc.get('type', 'artifact')}",
                "success": True,
            })

        if not normalized:
            return

        result = await self._graphiti_service.ingest_task_episodes(
            task_id=task_id,
            file_descriptions=normalized,
            case_description=case_description,
        )
        logger.info(
            f"Ingested Windows artifacts to Graphiti: "
            f"{result.get('successful', 0)}/{result.get('total', 0)} successful"
        )
