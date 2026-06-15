"""
File Analyzer Module — LLM-driven file description generation.

This module handles file analysis logic, including text and vision analysis.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings

logger = logging.getLogger(__name__)


class FileAnalyzer:
    """Handles file analysis operations."""

    def __init__(self, settings: Settings, llm_service, graphiti_service):
        """
        Initialize FileAnalyzer.

        Args:
            settings: Application settings
            llm_service: LLM service for analysis
            graphiti_service: Knowledge graph service (optional)
        """
        self.settings = settings
        self._llm_service = llm_service
        self._graphiti_service = graphiti_service

    async def analyze_files(
        self,
        files_db_path: str,
        file_paths: List[str],
        case_description: str,
        extraction_dir: Optional[str] = None,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Generate LLM description for each file in the list using concurrency.
        Skips files that already have descriptions in the database.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Pre-check: find files that already have descriptions
        already_described = set()
        existing_descriptions = {}
        if files_db_path:
            try:
                import sqlite3
                with sqlite3.connect(files_db_path, timeout=10) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute(
                        "SELECT file_path, description, summary, keywords, model_used FROM file_descriptions WHERE description IS NOT NULL AND description != ''"
                    )
                    for row in cur.fetchall():
                        already_described.add(row["file_path"])
                        existing_descriptions[row["file_path"]] = {
                            "file_path": row["file_path"],
                            "description": row["description"],
                            "model_used": row["model_used"] or "",
                            "success": True,
                        }
            except Exception as e:
                logger.warning(f"Failed to check existing descriptions: {e}")

        files_to_analyze = [fp for fp in file_paths if fp not in already_described]
        skipped_count = len(file_paths) - len(files_to_analyze)

        if skipped_count > 0:
            logger.info(f"[FILE_ANALYZER] Skipping {skipped_count} files with existing descriptions, analyzing {len(files_to_analyze)}")

        if not files_to_analyze:
            logger.info(f"[FILE_ANALYZER] All {len(file_paths)} files already have descriptions, returning existing results")
            return [existing_descriptions.get(fp, {"file_path": fp, "description": "", "success": False}) for fp in file_paths]

        total = len(files_to_analyze)
        IMAGE_EXTENSIONS = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
            '.svg', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw'
        }

        # Concurrency control (semaphore)
        sem = asyncio.Semaphore(self.settings.llm_max_concurrency if hasattr(self.settings, "llm_max_concurrency") else 5)

        # Track progress
        processed_count = 0

        async def analyze_file(file_path: str) -> Dict[str, Any]:
            nonlocal processed_count
            async with sem:
                try:
                    file_ext = Path(file_path).suffix.lower()
                    is_image = file_ext in IMAGE_EXTENSIONS

                    # Resolve full file path
                    full_path = file_path
                    if not Path(file_path).is_absolute() and extraction_dir:
                        full_path = str(Path(extraction_dir) / file_path)

                    # Check if file exists
                    if not Path(full_path).exists():
                        return {"file_path": file_path, "description": "", "error": f"File not found: {full_path}", "success": False}

                    result = None

                    # Try document extractor first (markitdown handles images, docs, etc.)
                    from ..document_extractor import get_document_extractor_locator
                    from ...prompts import CASE_FILE_ANALYSIS_TEMPLATE, CASE_VISION_ANALYSIS_TEMPLATE
                    doc_locator = get_document_extractor_locator()
                    extractor = doc_locator.get_extractor(full_path)

                    if extractor:
                        try:
                            content = await extractor.extract_to_markdown(full_path)
                            custom_prompt = CASE_FILE_ANALYSIS_TEMPLATE.format(
                                case_description=case_description,
                                file_path=file_path,
                                content=content,
                            )

                            result = await self._llm_service.analyze(
                                content=content,
                                model_type="text",
                                prompt=custom_prompt
                            )
                        except Exception as e:
                            logger.warning(f"Extractor failed for {full_path}: {e}, falling back to vision/raw")

                    if not result and is_image:
                        with open(full_path, 'rb') as f:
                            image_data = f.read()

                        vision_prompt = CASE_VISION_ANALYSIS_TEMPLATE.format(
                            case_description=case_description,
                        )

                        try:
                            result = await self._llm_service.analyze_image(
                                image_data=image_data,
                                prompt=vision_prompt,
                            )
                            # Check for the special error return from enhanced analyze_image
                            if result.get("error_type") == "image_decode_failed":
                                logger.info(f"Image decode failed for {file_path}, falling back to text analysis")
                                result = None # Trigger fallback below
                        except Exception as e:
                            logger.warning(f"Vision model failed for {file_path}, attempting text fallback: {e}")
                            result = None

                    if not result:
                        # Fallback or normal text analysis
                        content = await self._llm_service.read_file_content(full_path)

                        from ...prompts import CASE_FILE_ANALYSIS_TEMPLATE
                        custom_prompt = CASE_FILE_ANALYSIS_TEMPLATE.format(
                            case_description=case_description,
                            file_path=file_path,
                            content=content,
                        )

                        result = await self._llm_service.analyze(
                            content=content,
                            model_type="text",
                            prompt=custom_prompt
                        )

                    analysis = result.get("analysis", {})
                    description = analysis.get("description", "")

                    # Extract metadata for better persistence
                    summary = description[:200].split('\n')[0]

                    keywords = ""
                    # re is now global
                    found_entities = re.findall(r'[\u4e00-\u9fa5]{2,6}', description[:500])
                    if found_entities:
                        keywords = ", ".join(list(set(found_entities))[:5])

                    # Persist to _files.db (this will update both 'files' and 'file_descriptions' tables)
                    if files_db_path and description:
                        try:
                            self._llm_service.persist_to_files_db(
                                db_path=files_db_path,
                                file_path=file_path,
                                description=description,
                                summary=summary,
                                keywords=keywords,
                                model_used=result.get("model", ""),
                            )
                        except Exception as e:
                            logger.warning(f"Failed to persist {file_path} analysis: {e}")

                    processed_count += 1
                    if progress_callback:
                        await progress_callback(processed_count, total, file_path)

                    return {"file_path": file_path, "description": description, "model_used": result.get("model", ""), "success": True}

                except Exception as e:
                    logger.warning(f"Failed to analyze file {file_path}: {e}")
                    processed_count += 1
                    if progress_callback:
                        await progress_callback(processed_count, total, file_path)
                    return {"file_path": file_path, "description": "", "error": str(e), "success": False}

        # Run analysis tasks concurrently (only for files without existing descriptions)
        tasks = [analyze_file(fp) for fp in files_to_analyze]
        new_results = await asyncio.gather(*tasks)

        # Build result map from new analysis
        result_map = {r["file_path"]: r for r in new_results}

        # Merge: return results in original order, using existing descriptions for skipped files
        final_results = []
        for fp in file_paths:
            if fp in result_map:
                final_results.append(result_map[fp])
            elif fp in existing_descriptions:
                final_results.append(existing_descriptions[fp])
            else:
                final_results.append({"file_path": fp, "description": "", "success": False})
        return final_results

    async def reanalyze_files(
        self,
        task_id: str,
        file_paths: List[str],
        user_hint: str,
        files_db_path: str,
        case_description: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Re-analyze files with additional user context.

        Combines: case description + knowledge graph context + user hint
        to generate an improved description.

        Args:
            task_id: Task identifier.
            file_paths: List of file paths to re-analyze.
            user_hint: User-provided additional description/hint.
            files_db_path: Path to _files.db for persisting results.
            case_description: Case description text.

        Returns:
            List of re-analysis results.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        logger.info(f"Starting reanalyze_files - task_id: {task_id}, "
                   f"files_count: {len(file_paths)}, "
                   f"files_db_path: {files_db_path!r}, "
                   f"case_description: {len(case_description) if case_description else 0} chars")

        # Retrieve knowledge graph context if available
        kg_context = ""
        if self._graphiti_service and task_id:
            try:
                search_results = await self._graphiti_service.search(
                    query=user_hint,
                    task_id=task_id,
                    limit=10,
                    include_relationships=True,
                )
                context_lines = []
                for r in search_results:
                    name = r.get("name", "")
                    props = r.get("properties", {})
                    body = props.get("body", "") or props.get("summary", "") or name
                    if body:
                        context_lines.append(f"- {body[:300]}")
                if context_lines:
                    kg_context = "\n".join(context_lines)
            except Exception as e:
                logger.warning(f"KG search for re-analysis failed: {e}")

        results = []
        total = len(file_paths)

        # Image file extensions for auto-detection
        IMAGE_EXTENSIONS = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
            '.svg', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw'
        }

        for i, file_path in enumerate(file_paths):
            try:
                logger.info(f"Starting re-analysis for file {i+1}/{total}: {file_path}")

                # Check if file exists
                if not Path(file_path).exists():
                    logger.error(f"File not found: {file_path}")
                    results.append({
                        "file_path": file_path,
                        "description": "",
                        "error": f"File not found: {file_path}",
                        "success": False,
                        "reanalysis": True,
                    })
                    continue

                file_ext = Path(file_path).suffix.lower()
                is_image = file_ext in IMAGE_EXTENSIONS

                # Try document extractor first (markitdown handles images, docs, etc.)
                from ..document_extractor import get_document_extractor_locator
                doc_locator = get_document_extractor_locator()
                extractor = doc_locator.get_extractor(file_path)

                if extractor:
                    try:
                        content = await extractor.extract_to_markdown(file_path)
                        logger.info(f"Extractor converted {file_path}: {len(content)} chars")
                    except Exception as e:
                        logger.warning(f"Extractor failed for {file_path}: {e}, falling back")
                        extractor = None  # Trigger fallback below

                if not extractor:
                    if is_image:
                        # Use vision model for images with custom prompt
                        logger.info(f"Using vision model for image re-analysis: {file_path}")

                        # Build vision prompt with case context
                        from ...prompts import CASE_VISION_REANALYSIS_TEMPLATE
                        vision_prompt_parts = []
                        if case_description:
                            vision_prompt_parts.append(f"案情背景：{case_description}")
                        if user_hint:
                            vision_prompt_parts.append(f"调查人员补充说明：{user_hint}")
                        if kg_context:
                            vision_prompt_parts.append(f"相关上下文：{kg_context}")

                        vision_prompt = CASE_VISION_REANALYSIS_TEMPLATE.format(
                            context_parts="\n".join(vision_prompt_parts)
                        )

                        try:
                            with open(file_path, 'rb') as f:
                                image_data = f.read()

                            logger.info(f"Read {len(image_data)} bytes from {file_path}, sending to vision model")
                            result = await self._llm_service.analyze_image(
                                image_data=image_data,
                                prompt=vision_prompt,
                            )
                        except Exception as e:
                            logger.error(f"Failed to analyze {file_path} as image: {e}", exc_info=True)
                            results.append({
                                "file_path": file_path,
                                "description": "",
                                "error": f"Vision analysis failed: {str(e)}",
                                "success": False,
                                "reanalysis": True,
                            })
                            continue
                    else:
                        # Use text model for text files
                        content = await self._llm_service.read_file_content(file_path)
                        logger.info(f"Read {len(content)} characters from {file_path}")

                if extractor or not is_image:
                    # Text analysis path (extractor content or raw text)
                    from ..prompts import (
                        FILE_REANALYSIS_HEADER,
                        FILE_REANALYSIS_CONTEXT_CASE,
                        FILE_REANALYSIS_CONTEXT_KG,
                        FILE_REANALYSIS_CONTEXT_HINT,
                        FILE_REANALYSIS_CONTEXT_FILE,
                        FILE_REANALYSIS_INSTRUCTION,
                    )

                    prompt_parts = [FILE_REANALYSIS_HEADER]

                    if case_description:
                        prompt_parts.append(FILE_REANALYSIS_CONTEXT_CASE.format(
                            case_description=case_description
                        ))

                    if kg_context:
                        prompt_parts.append(FILE_REANALYSIS_CONTEXT_KG.format(
                            kg_context=kg_context
                        ))

                    prompt_parts.append(FILE_REANALYSIS_CONTEXT_HINT.format(
                        user_hint=user_hint
                    ))
                    prompt_parts.append(FILE_REANALYSIS_CONTEXT_FILE.format(
                        file_path=file_path,
                        content=content,
                    ))
                    prompt_parts.append(FILE_REANALYSIS_INSTRUCTION)

                    custom_prompt = "\n".join(prompt_parts)
                    logger.info(f"Sending re-analysis request to LLM for {file_path}")

                    result = await self._llm_service.analyze(
                        content=content,
                        model_type="text",
                        prompt=custom_prompt,
                    )

                analysis = result.get("analysis", {})
                description = analysis.get("description", "")

                logger.info(f"Received LLM response for {file_path}: {len(description)} characters")

                # Persist updated description to _files.db
                if files_db_path and description:
                    persisted = self._llm_service.persist_to_files_db(
                        db_path=files_db_path,
                        file_path=file_path,
                        description=description,
                        summary=description[:200],
                        keywords="",
                        model_used=result.get("model", ""),
                    )
                    if persisted:
                        logger.info(f"Successfully persisted re-analysis for {file_path}")
                    else:
                        logger.warning(f"Failed to persist re-analysis for {file_path} (no matching row)")
                elif not files_db_path:
                    logger.warning(f"No files_db_path provided - re-analysis result for {file_path} will NOT be saved to database")

                results.append({
                    "file_path": file_path,
                    "description": description,
                    "model_used": result.get("model", ""),
                    "success": True,
                    "reanalysis": True,
                })

            except Exception as e:
                logger.error(f"Re-analysis failed for {file_path}: {e}", exc_info=True)
                results.append({
                    "file_path": file_path,
                    "description": "",
                    "error": str(e),
                    "success": False,
                    "reanalysis": True,
                })

        # KG INCREMENTAL SYNC: Trigger ingestion for newly analyzed files
        if self._graphiti_service and any(r.get("success") for r in results):
            logger.info(f"Task {task_id}: Triggering incremental Graphiti sync for re-analyzed files...")
            asyncio.create_task(self.ingest_to_knowledge_graph(
                task_id, case_description, results
            ))

        logger.info(f"Re-analysis completed: {sum(1 for r in results if r.get('success'))}/{len(results)} files successful")
        return results

    async def ingest_to_knowledge_graph(
        self,
        task_id: str,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        cluster_descriptions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Ingest case description, file descriptions, and event clusters into Graphiti.

        This enables semantic retrieval during report generation,
        overcoming LLM context length limitations.

        Args:
            task_id: Task identifier (used as graph group_id).
            case_description: Full case description text.
            file_descriptions: List of per-file analysis results.
            cluster_descriptions: Optional list of event cluster analysis results.

        Returns:
            True if ingestion succeeded, False otherwise.
        """
        logger.info(f"[KG_INGEST] Task {task_id}: Starting knowledge graph ingestion")
        logger.info(f"[KG_INGEST] Task {task_id}: graphiti_service available: {self._graphiti_service is not None}")

        if not self._graphiti_service:
            logger.warning("[KG_INGEST] Graphiti service not available, skipping KG ingestion")
            return False

        try:
            from graphiti_integration.toon_transformer import EpisodeData
            from datetime import datetime

            # Ensure graphiti is initialized
            logger.info(f"[KG_INGEST] Task {task_id}: Initializing graphiti service...")
            await self._graphiti_service.initialize()
            logger.info(f"[KG_INGEST] Task {task_id}: Graphiti service initialized successfully")

            # Get or create task graph
            logger.info(f"[KG_INGEST] Task {task_id}: Getting task graph...")
            graph_entry = await self._graphiti_service._get_task_graph(task_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                logger.error(f"[KG_INGEST] Task {task_id}: Could not get task graph - graph_entry type: {type(graph_entry)}")
                return False

            logger.info(f"[KG_INGEST] Task {task_id}: Task graph obtained successfully")

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                logger.error(f"[KG_INGEST] Task {task_id}: No ingestor in graph_entry - keys: {list(graph_entry.keys()) if isinstance(graph_entry, dict) else 'N/A'}")
                return False

            logger.info(f"[KG_INGEST] Task {task_id}: Ingestor obtained successfully")

            episodes = []

            # 1. Ingest case description (chunk long descriptions)
            desc_chunks = self._chunk_text(case_description, max_chars=3000)
            for i, chunk in enumerate(desc_chunks):
                episodes.append(EpisodeData(
                    name=f"案情描述 (第{i+1}部分)" if len(desc_chunks) > 1 else "案情描述",
                    episode_body=json.dumps({"text": chunk}, ensure_ascii=False),
                    source_description=f"用户提供的案情描述 - 第{i+1}/{len(desc_chunks)}部分",
                    reference_time=datetime.now(),
                    file_path="",
                    file_id=0,
                    category="case_description"
                ))

            # 2. Ingest each file description
            successful = [f for f in file_descriptions if f.get("success") and f.get("description")]
            for desc in successful:
                file_path = desc.get("file_path", "")
                description = desc.get("description", "")
                if description:
                    # Chunk long descriptions
                    chunks = self._chunk_text(description, max_chars=3000)
                    for j, chunk in enumerate(chunks):
                        ep_name = f"文件分析: {file_path}"
                        if len(chunks) > 1:
                            ep_name += f" (第{j+1}部分)"
                        episodes.append(EpisodeData(
                            name=ep_name,
                            episode_body=json.dumps({"file_path": file_path, "analysis": chunk}, ensure_ascii=False),
                            source_description=f"LLM分析结果 - {file_path}",
                            reference_time=datetime.now(),
                            file_path=file_path,
                            file_id=0,
                            category="file_description"
                        ))

            # 3. Ingest event cluster descriptions (if provided)
            if cluster_descriptions:
                successful_clusters = [c for c in cluster_descriptions if c.get("success") or c.get("analysis")]
                for cluster in successful_clusters:
                    analysis = cluster.get("analysis", {})
                    description = analysis.get("description", "")
                    event_type = cluster.get("event_type", "UNKNOWN")
                    time_window = cluster.get("time_window", 0)

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
                                    "analysis": chunk
                                }, ensure_ascii=False),
                                source_description=f"事件簇LLM分析 - {event_type} @ time_window={time_window}",
                                reference_time=datetime.now(),
                                file_path="",
                                file_id=0,
                                category="event_cluster_description"
                            ))

            if not episodes:
                logger.info("No episodes to ingest")
                return True

            # Batch ingest
            logger.info(f"Ingesting {len(episodes)} episodes into Graphiti for task {task_id}")
            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=task_id,
            )
            successful = getattr(result, 'successful', 0)
            total = getattr(result, 'total_episodes', len(episodes))
            failed = getattr(result, 'failed', 0)
            errors = getattr(result, 'errors', []) or []
            logger.info(f"Graphiti ingestion complete: {successful}/{total} successful, {failed} failed")
            # Surface per-episode failures so LLM extraction problems (the usual
            # cause of a sparse graph) are visible instead of silently swallowed.
            for err in errors[:5]:
                logger.warning(f"[{task_id}] Episode ingestion failure: {err}")
            return successful > 0

        except ImportError:
            logger.warning("graphiti_integration not available, skipping KG ingestion")
            return False
        except Exception as e:
            logger.error(f"Knowledge graph ingestion failed: {e}", exc_info=True)
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

    async def analyze_event_clusters(
        self,
        events_db: str,
        case_description: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Identify and analyze the most frequent event clusters.
        """
        if not self._llm_service:
            return []

        # 1. Get the top N clusters by event count
        clusters = []
        try:
            import sqlite3
            with sqlite3.connect(events_db, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                # Use same grouping logic as C++ Timeline
                sql = """
                    SELECT
                        (timestamp / 60) as time_window,
                        event_type,
                        COUNT(*) as cluster_count,
                        CASE WHEN file_path LIKE '%/%' THEN SUBSTR(file_path, 1, LENGTH(file_path) - INSTR(REPLACE(file_path, '/', char(1)), char(1)) + 1) ELSE '' END as parent_directory,
                        GROUP_CONCAT(COALESCE(description, ''), '\n') as group_desc,
                        GROUP_CONCAT(COALESCE(file_path, ''), '\n') as group_paths,
                        id as first_event_id
                    FROM events
                    WHERE llm_analyzed_at IS NULL
                    GROUP BY time_window, event_type, parent_directory
                    ORDER BY cluster_count DESC
                    LIMIT ?
                """
                cur = conn.execute(sql, (limit,))
                rows = cur.fetchall()
                clusters = [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to query top clusters: {e}")
            return []

        if not clusters:
            return []

        # 2. Analyze each cluster concurrently
        results = []
        for cluster in clusters:
            try:
                # Prepare cluster context for LLM
                content = f"### 事件簇信息\n"
                content += f"- 类型: {cluster['event_type']}\n"
                content += f"- 数量: {cluster['cluster_count']}\n"
                content += f"- 目录: {cluster['parent_directory'] or '/'}\n"
                content += f"\n### 事件详情 (样本)\n"

                paths = cluster['group_paths'].split('\n')[:10]
                descs = cluster['group_desc'].split('\n')[:10]
                for p, d in zip(paths, descs):
                    content += f"- {p}: {d}\n"

                # Analyze via LLM
                from ...prompts import EVENT_CLUSTER_CASE_ANALYSIS_TEMPLATE
                prompt = EVENT_CLUSTER_CASE_ANALYSIS_TEMPLATE.format(
                    case_description=case_description
                )

                analysis_result = await self._llm_service.analyze_event_cluster(
                    event_data={
                        "event_type": cluster['event_type'],
                        "description": content,
                        "time_window": cluster['time_window']
                    },
                    prompt=prompt
                )

                # Persist result (llm_service will handle Schema update)
                analysis = analysis_result.get("analysis", {})
                self._llm_service.persist_to_events_db(
                    db_path=events_db,
                    event_id=cluster['first_event_id'],
                    description=analysis.get("description", ""),
                    summary=analysis.get("summary") or analysis.get("description", "")[:200],
                    keywords=", ".join(analysis.get("keywords", [])) if isinstance(analysis.get("keywords"), list) else "",
                    model_used=analysis_result.get("model", "unknown")
                )

                results.append(analysis_result)
            except Exception as e:
                logger.warning(f"Failed to analyze cluster {cluster['time_window']}: {e}")

        return results
