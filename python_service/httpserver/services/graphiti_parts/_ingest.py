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


class GraphitiIngestMixin:
    """Auto-extracted method group; see module docstring."""

    async def ingest_case_data(
        self,
        case_id: str,
        task_ids: List[str],
        files_db_paths: List[str],
        events_db_paths: Optional[List[str]] = None,
        progress_callback=None,
    ) -> bool:
        """
        Ingest data from multiple tasks into a case-level knowledge graph.

        This method aggregates file descriptions and event clusters from all images
        in a case and ingests them into a unified case-level graph for cross-image analysis.

        Args:
            case_id: Case identifier (used as group_id for case-level graph)
            task_ids: List of task IDs for the images in this case
            files_db_paths: List of _files.db paths
            events_db_paths: Optional list of _events.db paths
            progress_callback: Optional progress callback

        Returns:
            True if ingestion succeeded, False otherwise
        """
        if not self._initialized:
            await self.initialize()

        if not events_db_paths:
            events_db_paths = []

        try:
            from graphiti_integration.toon_transformer import EpisodeData
            from datetime import datetime
            import sqlite3
            import json

            # Get or create case-level graph
            graph_entry = await self._get_case_graph(case_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                logger.error(f"Could not get case graph for {case_id}")
                return False

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                logger.error(f"No ingestor available for case {case_id}")
                return False

            episodes = []
            total_files = 0
            total_clusters = 0

            # Aggregate file descriptions from all images
            for idx, (task_id, files_db) in enumerate(zip(task_ids, files_db_paths)):
                try:
                    if not Path(files_db).exists():
                        logger.warning(f"[{case_id}] Files database {idx+1} not found: {files_db}")
                        continue

                    with sqlite3.connect(files_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get file descriptions
                        from ..case_analysis.db_utils import ensure_file_descriptions_schema
                        ensure_file_descriptions_schema(conn)

                        cur = conn.execute(
                            "SELECT file_path, description FROM file_descriptions WHERE is_relevant = 1 AND description IS NOT NULL"
                        )
                        rows = cur.fetchall()

                        for row in rows:
                            file_path = row["file_path"]
                            description = row["description"]

                            # Tag with source image
                            tagged_path = f"[IMG{idx+1}] {file_path}"

                            # Chunk long descriptions
                            chunks = self._chunk_text_for_graph(description, max_chars=3000)
                            for j, chunk in enumerate(chunks):
                                ep_name = f"文件分析: {tagged_path}"
                                if len(chunks) > 1:
                                    ep_name += f" (第{j+1}部分)"

                                episodes.append(EpisodeData(
                                    name=ep_name,
                                    episode_body=json.dumps({
                                        "file_path": file_path,
                                        "source_image": f"IMG{idx+1}",
                                        "task_id": task_id,
                                        "analysis": chunk
                                    }, ensure_ascii=False),
                                    source_description=f"LLM分析结果 - 镜像{idx+1} - {file_path}",
                                    reference_time=datetime.now(),
                                    file_path=file_path,
                                    file_id=0,
                                    category="file_description"
                                ))
                                total_files += 1

                    if progress_callback:
                        await progress_callback("aggregating_files", f"已聚合镜像{idx+1}的文件分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate files from image {idx+1}: {e}")

            # Aggregate event clusters from all images
            for idx, (task_id, events_db) in enumerate(zip(task_ids, events_db_paths)):
                try:
                    if not events_db or not Path(events_db).exists():
                        continue

                    with sqlite3.connect(events_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get event clusters with LLM analysis
                        cur = conn.execute("""
                            SELECT DISTINCT event_type, llm_description, llm_summary,
                                   (timestamp / 60) as time_window
                            FROM events
                            WHERE llm_description IS NOT NULL
                            GROUP BY event_type, time_window
                        """)
                        rows = cur.fetchall()

                        for row in rows:
                            description = row["llm_description"] or row["llm_summary"] or ""
                            event_type = row["event_type"]
                            time_window = row["time_window"]

                            if description:
                                # Chunk long descriptions
                                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                                for j, chunk in enumerate(chunks):
                                    ep_name = f"事件簇分析: 镜像{idx+1} - {event_type} @ {time_window}"
                                    if len(chunks) > 1:
                                        ep_name += f" (第{j+1}部分)"

                                    episodes.append(EpisodeData(
                                        name=ep_name,
                                        episode_body=json.dumps({
                                            "event_type": event_type,
                                            "time_window": time_window,
                                            "source_image": f"IMG{idx+1}",
                                            "task_id": task_id,
                                            "analysis": chunk
                                        }, ensure_ascii=False),
                                        source_description=f"事件簇LLM分析 - 镜像{idx+1} - {event_type}",
                                        reference_time=datetime.now(),
                                        file_path="",
                                        file_id=0,
                                        category="event_cluster_description"
                                    ))
                                    total_clusters += 1

                    if progress_callback:
                        await progress_callback("aggregating_clusters", f"已聚合镜像{idx+1}的事件簇分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate clusters from image {idx+1}: {e}")

            if not episodes:
                logger.info(f"[{case_id}] No episodes to ingest into case graph")
                return True

            # Batch ingest all episodes
            logger.info(f"[{case_id}] Ingesting {len(episodes)} episodes ({total_files} files + {total_clusters} clusters) into case-level graph")
            if progress_callback:
                await progress_callback("ingesting", f"正在摄入 {len(episodes)} 个分析结果到知识图谱...")

            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=case_id,
            )

            success_count = getattr(result, 'successful', 0)
            total_count = getattr(result, 'total_episodes', len(episodes))

            logger.info(f"[{case_id}] Case-level graph ingestion complete: {success_count}/{total_count} successful")

            if progress_callback:
                await progress_callback("completed", f"知识图谱摄入完成：{success_count}/{total_count} 成功")

            return success_count > 0

        except Exception as e:
            logger.error(f"[{case_id}] Case-level graph ingestion failed: {e}", exc_info=True)
            return False

    async def ingest_task_episodes(
        self,
        task_id: str,
        file_descriptions: List[Dict[str, Any]],
        cluster_descriptions: Optional[List[Dict[str, Any]]] = None,
        case_description: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Unified path-A ingestion: build one Episode per analysis result and let
        Graphiti's LLM extract entities/relationships (``add_episode``).

        This is the entry point the analysis pipeline and the manual "ingest"
        button should both funnel through, so every code path produces the same
        Episodic → Entity → RELATES_TO graph the frontend visualises.

        Unlike the older boolean-returning helpers, this returns a dict with
        per-episode error details so LLM extraction failures are no longer
        silently swallowed (the most common reason a graph ends up nearly empty).

        Args:
            task_id: Used as the graph group_id.
            file_descriptions: Per-file (or per-artifact) dicts with at least
                ``file_path``/``description``/``success``. Extra keys are passed
                through into the episode body for richer extraction.
            cluster_descriptions: Optional event-cluster dicts.
            case_description: Optional case-level context text.
            progress_callback: Optional async callback(stage, message).

        Returns:
            Dict: success (bool), successful, total, failed, errors (list),
            episodes_built (int).
        """
        if not self._initialized:
            await self.initialize()

        try:
            from graphiti_integration.toon_transformer import EpisodeData
            from datetime import datetime
            import json

            graph_entry = await self._get_task_graph(task_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                return {"success": False, "error": f"Could not get task graph for {task_id}"}

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                return {"success": False, "error": "No ingestor in task graph entry"}

            episodes: List[Any] = []

            # 1. Case context (chunked) — gives the extractor shared background
            if case_description:
                case_chunks = self._chunk_text_for_graph(case_description, max_chars=3000)
                for i, chunk in enumerate(case_chunks):
                    ep_name = f"案情描述 (第{i+1}部分)" if len(case_chunks) > 1 else "案情描述"
                    episodes.append(EpisodeData(
                        name=ep_name,
                        episode_body=json.dumps({"text": chunk}, ensure_ascii=False),
                        source_description=f"用户提供的案情描述 - 第{i+1}部分",
                        reference_time=datetime.now(),
                        file_path="",
                        file_id=0,
                        category="case_description",
                    ))

            # 2. One episode per analyzed file/artifact
            successful_files = [f for f in (file_descriptions or []) if f.get("success") and f.get("description")]
            for desc in successful_files:
                file_path = desc.get("file_path", "") or desc.get("id", "")
                description = desc.get("description", "")
                if not description:
                    continue
                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                for j, chunk in enumerate(chunks):
                    ep_name = f"文件分析: {file_path}"
                    if len(chunks) > 1:
                        ep_name += f" (第{j+1}部分)"
                    # Build a rich episode body. The renderer in GraphitiIngestor
                    # turns each dict key into a "Field: value" line, so every
                    # key here becomes visible to the entity extractor. Including
                    # summary/keywords/category/md5/name means the LLM can extract
                    # hash identifiers, file-type entities, and category-derived
                    # relationships it would otherwise discard as "generic values".
                    body = {
                        "file_path": file_path,
                        "analysis": chunk,
                    }
                    if desc.get("summary"):
                        body["summary"] = desc["summary"]
                    if desc.get("keywords"):
                        body["keywords"] = desc["keywords"]
                    if desc.get("category"):
                        body["category"] = desc["category"]
                    if desc.get("md5"):
                        body["md5"] = desc["md5"]
                    if desc.get("name"):
                        body["filename"] = desc["name"]
                    if desc.get("file_type"):
                        body["file_type"] = desc["file_type"]
                    if desc.get("is_relevant") is not None:
                        body["is_relevant"] = bool(desc["is_relevant"])
                    episodes.append(EpisodeData(
                        name=ep_name,
                        episode_body=json.dumps(body, ensure_ascii=False),
                        source_description=f"LLM分析结果 - {file_path}",
                        reference_time=datetime.now(),
                        file_path=file_path,
                        file_id=0,
                        category=desc.get("category", "file_description"),
                    ))

            # 3. One episode per event cluster
            for cluster in (cluster_descriptions or []):
                analysis = cluster.get("analysis", {}) if isinstance(cluster.get("analysis"), dict) else {}
                description = analysis.get("description") or cluster.get("description") or ""
                if not description:
                    continue
                event_type = cluster.get("event_type", "UNKNOWN")
                time_window = cluster.get("time_window", 0)
                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                for j, chunk in enumerate(chunks):
                    ep_name = f"事件簇分析: {event_type} @ {time_window}"
                    if len(chunks) > 1:
                        ep_name += f" (第{j+1}部分)"
                    episodes.append(EpisodeData(
                        name=ep_name,
                        episode_body=json.dumps({
                            "event_type": event_type, "time_window": time_window, "analysis": chunk,
                        }, ensure_ascii=False),
                        source_description=f"事件簇LLM分析 - {event_type} @ time_window={time_window}",
                        reference_time=datetime.now(),
                        file_path="",
                        file_id=0,
                        category="event_cluster_description",
                    ))

            if not episodes:
                logger.info(f"[{task_id}] No episodes to ingest")
                return {"success": True, "successful": 0, "total": 0, "failed": 0, "errors": [], "episodes_built": 0}

            if progress_callback:
                await progress_callback("ingesting", f"正在摄入 {len(episodes)} 个分析结果到知识图谱...")

            logger.info(f"[{task_id}] Ingesting {len(episodes)} episodes via add_episode")
            result = await ingestor.batch_ingest(episodes=episodes, group_id=task_id)

            successful = getattr(result, 'successful', 0)
            total = getattr(result, 'total_episodes', len(episodes))
            failed = getattr(result, 'failed', 0)
            errors = getattr(result, 'errors', []) or []
            logger.info(f"[{task_id}] Episode ingestion: {successful}/{total} successful, {failed} failed")
            if failed:
                # Surface up to 5 failure samples so users can see why the graph is sparse
                for err in errors[:5]:
                    logger.warning(f"[{task_id}] Episode ingestion failure: {err}")

            if progress_callback:
                await progress_callback("completed", f"知识图谱摄入完成：{successful}/{total} 成功")

            return {
                "success": successful > 0,
                "successful": successful,
                "total": total,
                "failed": failed,
                "errors": errors,
                "episodes_built": len(episodes),
            }

        except Exception as e:
            logger.error(f"[{task_id}] Episode ingestion failed: {e}", exc_info=True)
            return {"success": False, "error": "episode ingestion failed", "episodes_built": 0}

    @staticmethod
    def _chunk_text_for_graph(text: str, max_chars: int = 3000) -> List[str]:
        """Split text into chunks for graph ingestion."""
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

    async def ingest_case_data_incremental(
        self,
        case_id: str,
        new_task_ids: List[str],
        existing_task_ids: List[str],
        files_db_paths: List[str],
        events_db_paths: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        增量摄入案件数据到知识图谱

        Unlike ingest_case_data which processes ALL tasks, this method
        only ingests data from new tasks while establishing relationships
        with existing tasks' data in the graph.

        Args:
            case_id: Case identifier (used as group_id)
            new_task_ids: List of new task IDs to ingest
            existing_task_ids: List of existing task IDs (for relationship linking)
            files_db_paths: List of _files.db paths (for all tasks)
            events_db_paths: Optional list of _events.db paths
            progress_callback: Optional progress callback (stage, message)

        Returns:
            Dict with ingestion statistics
        """
        if not self._initialized:
            await self.initialize()

        if events_db_paths is None:
            events_db_paths = []

        episodes = []
        total_files = 0
        total_clusters = 0

        logger.info(f"[{case_id}] Starting incremental graph ingestion: "
                    f"{len(new_task_ids)} new tasks, {len(existing_task_ids)} existing tasks")

        try:
            from graphiti_integration.toon_transformer import EpisodeData
            from datetime import datetime
            import sqlite3
            import json

            # Get or create case-level graph (reuses the same path as the
            # non-incremental ingest_case_data so group_id/isolation is consistent).
            # NOTE: previously this called GraphitiIngestor(neo4j_uri=...) directly,
            # but __init__ takes a GraphitiConfig — that call always raised.
            graph_entry = await self._get_case_graph(case_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                logger.error(f"[{case_id}] Could not get case graph for incremental ingestion")
                return {"success": False, "error": "Could not get case graph"}

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                logger.error(f"[{case_id}] No ingestor available for incremental ingestion")
                return {"success": False, "error": "No ingestor available"}

            # Only process NEW tasks (not existing ones)
            for idx, task_id in enumerate(new_task_ids):
                if idx >= len(files_db_paths):
                    break

                files_db = files_db_paths[idx]

                # Aggregate file descriptions from new tasks only
                try:
                    if not files_db or not Path(files_db).exists():
                        continue

                    with sqlite3.connect(files_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get analyzed files from this task
                        cur = conn.execute("""
                            SELECT DISTINCT file_path, description, summary
                            FROM file_descriptions
                            WHERE description IS NOT NULL AND description != ''
                            LIMIT 500
                        """)
                        rows = cur.fetchall()

                        for row in rows:
                            file_path = row["file_path"]
                            description = row["description"] or row["summary"] or ""

                            if description:
                                # Chunk long descriptions
                                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                                for j, chunk in enumerate(chunks):
                                    ep_name = f"文件分析: {Path(file_path).name}"
                                    if len(chunks) > 1:
                                        ep_name += f" (第{j+1}部分)"

                                    episodes.append(EpisodeData(
                                        name=ep_name,
                                        episode_body=json.dumps({
                                            "file_path": file_path,
                                            "task_id": task_id,
                                            "source_image": f"NEW",
                                            "related_tasks": existing_task_ids,  # Link to existing
                                            "analysis": chunk
                                        }, ensure_ascii=False),
                                        source_description=f"LLM分析结果 - 新任务 {task_id[:8]} - {file_path}",
                                        reference_time=datetime.now(),
                                        file_path=file_path,
                                        file_id=0,
                                        category="file_description"
                                    ))
                                    total_files += 1

                        if progress_callback:
                            await progress_callback("aggregating_new", f"已聚合新任务{idx+1}的文件分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate files from new task {task_id[:8]}: {e}")

            # Aggregate event clusters from new tasks only
            for idx, task_id in enumerate(new_task_ids):
                if idx >= len(events_db_paths):
                    break

                events_db = events_db_paths[idx]

                try:
                    if not events_db or not Path(events_db).exists():
                        continue

                    with sqlite3.connect(events_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get event clusters with LLM analysis
                        cur = conn.execute("""
                            SELECT DISTINCT event_type, llm_description, llm_summary,
                                   (timestamp / 60) as time_window
                            FROM events
                            WHERE llm_description IS NOT NULL
                            GROUP BY event_type, time_window
                        """)
                        rows = cur.fetchall()

                        for row in rows:
                            description = row["llm_description"] or row["llm_summary"] or ""
                            event_type = row["event_type"]
                            time_window = row["time_window"]

                            if description:
                                # Chunk long descriptions
                                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                                for j, chunk in enumerate(chunks):
                                    ep_name = f"事件簇分析: 新任务 {task_id[:8]} - {event_type} @ {time_window}"
                                    if len(chunks) > 1:
                                        ep_name += f" (第{j+1}部分)"

                                    episodes.append(EpisodeData(
                                        name=ep_name,
                                        episode_body=json.dumps({
                                            "event_type": event_type,
                                            "time_window": time_window,
                                            "task_id": task_id,
                                            "source_image": "NEW",
                                            "related_tasks": existing_task_ids,
                                            "analysis": chunk
                                        }, ensure_ascii=False),
                                        source_description=f"事件簇LLM分析 - 新任务 {task_id[:8]} - {event_type}",
                                        reference_time=datetime.now(),
                                        file_path="",
                                        file_id=0,
                                        category="event_cluster_description"
                                    ))
                                    total_clusters += 1

                    if progress_callback:
                        await progress_callback("aggregating_clusters_new", f"已聚合新任务{idx+1}的事件簇分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate clusters from new task {task_id[:8]}: {e}")

            if not episodes:
                logger.info(f"[{case_id}] No new episodes to ingest into case graph")
                return {
                    "success": True,
                    "episodes_ingested": 0,
                    "files": 0,
                    "clusters": 0,
                }

            # Batch ingest all new episodes
            logger.info(f"[{case_id}] Incrementally ingesting {len(episodes)} new episodes "
                        f"({total_files} files + {total_clusters} clusters) into case-level graph")
            if progress_callback:
                await progress_callback("ingesting", f"正在摄入 {len(episodes)} 个新分析结果到知识图谱...")

            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=case_id,
            )

            success_count = getattr(result, 'successful', 0)
            total_count = getattr(result, 'total_episodes', len(episodes))

            logger.info(f"[{case_id}] Incremental case-level graph ingestion complete: "
                        f"{success_count}/{total_count} successful")

            if progress_callback:
                await progress_callback("completed", f"增量知识图谱摄入完成：{success_count}/{total_count} 成功")

            return {
                "success": success_count > 0,
                "episodes_ingested": success_count,
                "total_episodes": total_count,
                "files": total_files,
                "clusters": total_clusters,
            }

        except Exception as e:
            logger.error(f"[{case_id}] Incremental case-level graph ingestion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": "graph ingestion failed",
            }

