"""
Cluster Analyzer Module — Event cluster analysis and Graphiti integration.

This module handles the complete event cluster data flow:
1. Fetch event clusters from database
2. LLM analysis for each cluster
3. Persist to database
4. Ingest to Graphiti knowledge graph
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings

logger = logging.getLogger(__name__)


class ClusterAnalyzer:
    """
    Handles event cluster analysis operations with Graphiti integration.

    Data Flow:
    - fetch_event_clusters() → Get clusters from _events.db
    - analyze_cluster() → LLM analysis
    - persist_cluster() → Save to _events.db
    - ingest_clusters_to_graphiti() → Send to Graphiti
    """

    def __init__(self, settings: Settings, llm_service, graphiti_service):
        """
        Initialize ClusterAnalyzer.

        Args:
            settings: Application settings
            llm_service: LLM service for analysis
            graphiti_service: Knowledge graph service (optional)
        """
        self.settings = settings
        self._llm_service = llm_service
        self._graphiti_service = graphiti_service

    async def analyze_and_ingest_clusters(
        self,
        events_db: str,
        case_description: str,
        task_id: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Complete pipeline: fetch, analyze, persist, and ingest event clusters.

        Args:
            events_db: Path to _events.db database
            case_description: Case description for LLM context
            task_id: Task identifier
            progress_callback: Optional progress callback

        Returns:
            List of cluster analysis results.
        """
        if not Path(events_db).exists():
            logger.warning(f"Events database not found: {events_db}")
            return []

        # Step 1: Fetch event clusters
        clusters = await self.fetch_event_clusters(events_db)
        if not clusters:
            logger.info(f"Task {task_id}: No event clusters to analyze")
            return []

        if progress_callback:
            await progress_callback("fetching_clusters", f"获取到 {len(clusters)} 个事件簇")

        # Step 2: Analyze each cluster (with concurrency control)
        results = await self._analyze_clusters_concurrent(
            clusters, case_description, events_db, progress_callback
        )

        # Step 3: Ingest to Graphiti
        if self._graphiti_service and results:
            if progress_callback:
                await progress_callback("ingesting_clusters", "正在将事件簇摄入知识图谱...")
            await self.ingest_clusters_to_graphiti(
                task_id, case_description, results
            )

        return results

    async def fetch_event_clusters(
        self,
        events_db: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch event clusters from the events database.

        Clusters are grouped by (time_window, event_type, parent_directory).
        Only fetches clusters that haven't been analyzed yet (llm_analyzed_at IS NULL).

        Args:
            events_db: Path to _events.db database
            limit: Maximum number of clusters to fetch (None = no limit)

        Returns:
            List of cluster dictionaries.
        """
        try:
            with sqlite3.connect(events_db, timeout=10) as conn:
                conn.row_factory = sqlite3.Row

                # Build SQL query
                limit_clause = f"LIMIT {limit}" if limit else ""
                sql = f"""
                    SELECT
                        (timestamp / 60) as time_window,
                        event_type,
                        COUNT(*) as cluster_count,
                        MIN(timestamp) as cluster_start,
                        MAX(timestamp) as cluster_end,
                        CASE
                            WHEN file_path LIKE '%/%' THEN RTRIM(file_path, REPLACE(file_path, '/', ''))
                            ELSE ''
                        END as parent_directory,
                        GROUP_CONCAT(COALESCE(description, ''), '\n') as group_desc,
                        GROUP_CONCAT(COALESCE(file_path, ''), '\n') as group_paths,
                        GROUP_CONCAT(id) as member_ids,
                        MIN(id) as first_event_id
                    FROM events
                    WHERE llm_analyzed_at IS NULL
                    GROUP BY time_window, event_type, parent_directory
                    ORDER BY cluster_count DESC
                    {limit_clause}
                """

                cur = conn.execute(sql)
                rows = cur.fetchall()
                clusters = [dict(row) for row in rows]

                logger.info(f"Fetched {len(clusters)} event clusters from {events_db}")
                return clusters

        except sqlite3.Error as e:
            logger.error(f"Failed to fetch event clusters: {e}")
            return []

    async def _analyze_clusters_concurrent(
        self,
        clusters: List[Dict[str, Any]],
        case_description: str,
        events_db: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Analyze clusters concurrently with semaphore control.

        Args:
            clusters: List of cluster dictionaries
            case_description: Case description for LLM context
            events_db: Path to _events.db for persistence
            progress_callback: Optional progress callback

        Returns:
            List of analysis results.
        """
        total = len(clusters)
        processed = 0

        # Concurrency control
        sem = asyncio.Semaphore(
            self.settings.llm_max_concurrency if hasattr(self.settings, "llm_max_concurrency") else 3
        )

        async def analyze_one(cluster: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal processed
            async with sem:
                try:
                    result = await self.analyze_cluster(cluster, case_description)
                    # Persist result
                    self.persist_cluster_analysis(events_db, cluster, result)

                    processed += 1
                    if progress_callback:
                        await progress_callback(
                            processed, total,
                            f"分析事件簇: {cluster['event_type']} @ {cluster['time_window']}"
                        )

                    return result
                except Exception as e:
                    logger.warning(f"Failed to analyze cluster {cluster['time_window']}: {e}")
                    processed += 1
                    return {
                        "event_type": cluster.get("event_type", "UNKNOWN"),
                        "time_window": cluster.get("time_window", 0),
                        "success": False,
                        "error": str(e),
                    }

        tasks = [analyze_one(c) for c in clusters]
        return await asyncio.gather(*tasks)

    async def analyze_cluster(
        self,
        cluster: Dict[str, Any],
        case_description: str,
    ) -> Dict[str, Any]:
        """
        Analyze a single event cluster using LLM.

        Args:
            cluster: Cluster dictionary with event_type, time_window, etc.
            case_description: Case description for context

        Returns:
            Analysis result dictionary.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Prepare cluster context for LLM
        content = f"### 事件簇信息\n"
        content += f"- 类型: {cluster['event_type']}\n"
        content += f"- 时间窗口: {cluster['time_window']} (timestamp / 60)\n"
        content += f"- 事件数量: {cluster['cluster_count']}\n"
        content += f"- 目录: {cluster['parent_directory'] or '/'}\n"
        content += f"- 时间范围: {cluster['cluster_start']} ~ {cluster['cluster_end']}\n"
        content += f"\n### 事件详情 (样本)\n"

        paths = cluster['group_paths'].split('\n')[:10]
        descs = cluster['group_desc'].split('\n')[:10]
        for p, d in zip(paths, descs):
            content += f"- {p}: {d}\n"

        # Build LLM prompt
        prompt = f"""案情背景：{case_description}

请针对以上案情背景，分析这个事件簇在取证上的意义，并给出研判结论。

{content}

请提供：
1. 简要总结（1-2句话概括事件簇的核心特征）
2. 详细分析（包括行为模式、时间特征、文件路径特征、行为意图研判）
3. 关键词（3-5个，用逗号分隔）
4. 取证价值评估（高/中/低，并说明理由）"""

        # Call LLM
        try:
            result = await self._llm_service.analyze_event_cluster(
                event_data={
                    "event_type": cluster['event_type'],
                    "description": content,
                    "time_window": cluster['time_window']
                },
                prompt=prompt
            )

            # Enhance result with cluster metadata
            result["event_type"] = cluster['event_type']
            result["time_window"] = cluster['time_window']
            result["cluster_count"] = cluster['cluster_count']
            result["parent_directory"] = cluster['parent_directory']
            result["success"] = True

            return result

        except Exception as e:
            logger.error(f"LLM analysis failed for cluster {cluster['time_window']}: {e}")
            return {
                "event_type": cluster['event_type'],
                "time_window": cluster['time_window'],
                "success": False,
                "error": str(e),
            }

    def persist_cluster_analysis(
        self,
        events_db: str,
        cluster: Dict[str, Any],
        analysis_result: Dict[str, Any],
    ):
        """
        Persist cluster analysis to the events database.

        Updates all events in the cluster with LLM analysis results.

        Args:
            events_db: Path to _events.db
            cluster: Original cluster data
            analysis_result: LLM analysis result
        """
        try:
            analysis = analysis_result.get("analysis", {})
            description = analysis.get("description", "")
            summary = analysis.get("summary", "") or description[:200]
            keywords = analysis.get("keywords", [])
            keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
            model_used = analysis_result.get("model", "unknown")
            member_ids = [int(value) for value in str(cluster.get("member_ids") or "").split(",") if value]
            if not member_ids:
                raise sqlite3.DatabaseError("cluster has no trusted member IDs")

            with sqlite3.connect(events_db, timeout=10) as conn:
                placeholders = ", ".join("?" for _ in member_ids)
                sql = f"""
                    UPDATE events
                    SET llm_summary = ?,
                        llm_description = ?,
                        llm_keywords = ?,
                        llm_is_relevant = 1,
                        llm_analyzed_at = ?,
                        llm_model_used = ?
                    WHERE id IN ({placeholders})
                """
                import time
                now = int(time.time())
                cur = conn.execute(sql, (
                    summary, description, keywords_str, now, model_used, *member_ids
                ))
                if cur.rowcount != len(member_ids):
                    raise sqlite3.DatabaseError(
                        f"cluster member update incomplete: expected {len(member_ids)}, got {cur.rowcount}"
                    )
                conn.commit()

            logger.debug(f"Persisted cluster analysis: {cluster['event_type']} @ {cluster['time_window']}")

        except sqlite3.Error as e:
            logger.error(f"Failed to persist cluster analysis: {e}")
            raise

    async def ingest_clusters_to_graphiti(
        self,
        task_id: str,
        case_description: str,
        cluster_results: List[Dict[str, Any]],
    ) -> bool:
        """
        Ingest cluster analysis results into Graphiti knowledge graph.

        Args:
            task_id: Task identifier (used as group_id)
            case_description: Case description
            cluster_results: List of cluster analysis results

        Returns:
            True if ingestion succeeded, False otherwise.
        """
        if not self._graphiti_service:
            logger.info("Graphiti service not available, skipping cluster ingestion")
            return False

        try:
            from graphiti_integration.toon_transformer import EpisodeData

            # Ensure graphiti is initialized
            await self._graphiti_service.initialize()

            # Get or create task graph
            graph_entry = await self._graphiti_service._get_task_graph(task_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                logger.warning(f"Could not get task graph for {task_id}")
                return False

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                logger.warning(f"No ingestor available for task {task_id}")
                return False

            episodes = []

            # Only ingest successful analyses
            successful = [c for c in cluster_results if c.get("success")]
            for cluster in successful:
                analysis = cluster.get("analysis", {})
                description = analysis.get("description", "")
                event_type = cluster.get("event_type", "UNKNOWN")
                time_window = cluster.get("time_window", 0)
                cluster_count = cluster.get("cluster_count", 0)

                if description:
                    # Chunk long descriptions
                    chunks = self._chunk_text(description, max_chars=3000)
                    for j, chunk in enumerate(chunks):
                        ep_name = f"事件簇分析: {event_type} @ {time_window}"
                        if len(chunks) > 1:
                            ep_name += f" (第{j+1}部分)"

                        episodes.append(EpisodeData(
                            name=ep_name,
                            episode_body=json.dumps({
                                "event_type": event_type,
                                "time_window": time_window,
                                "cluster_count": cluster_count,
                                "analysis": chunk
                            }, ensure_ascii=False),
                            source_description=f"事件簇LLM分析 - {event_type} (count={cluster_count})",
                            reference_time=datetime.now(),
                            file_path="",
                            file_id=0,
                            category="event_cluster_description"
                        ))

            if not episodes:
                logger.info("No cluster episodes to ingest")
                return True

            # Batch ingest
            logger.info(f"Ingesting {len(episodes)} cluster episodes into Graphiti for task {task_id}")
            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=task_id,
            )
            logger.info(
                f"Cluster Graphiti ingestion complete: {getattr(result, 'successful', 0)}/{getattr(result, 'total_episodes', len(episodes))} successful"
            )
            return getattr(result, 'successful', 0) > 0

        except ImportError:
            logger.warning("graphiti_integration not available, skipping cluster ingestion")
            return False
        except Exception as e:
            logger.error(f"Cluster Graphiti ingestion failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 3000) -> List[str]:
        """Split text into chunks, breaking at paragraph boundaries."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > max_chars and current:
                chunks.append(current.strip())
                current = para
            else:
                current = current + "\n\n" + para if current else para
        if current.strip():
            chunks.append(current.strip())
        return chunks if chunks else [text]
