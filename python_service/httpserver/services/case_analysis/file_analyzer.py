"""
File Analyzer Module — LLM-driven file description generation.

This module handles file analysis logic, including text and vision analysis.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings
from .file_schema import file_forensic_time, latest_analysis

logger = logging.getLogger(__name__)

# Image suffixes routed to the vision model (shared by analyze/reanalyze).
IMAGE_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
    '.svg', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw',
})


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
        task_id: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Generate LLM description for each file in the list using concurrency.
        Skips files that already have analysis records in the database
        (``file_analyses`` — SPEC file-analysis D4).
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Pre-check (SPEC file-analysis D4): a file counts as analyzed iff an
        # append-only ``file_analyses`` record exists. ``file_descriptions``
        # rows without a truth record (pre-Phase-2 or external writers) are
        # re-analyzed once — honest behavior, one-time cost.
        already_described = set()
        existing_descriptions = {}
        if files_db_path:
            for fp in file_paths:
                record = latest_analysis(files_db_path, fp)
                if record and record.get("description"):
                    already_described.add(fp)
                    existing_descriptions[fp] = {
                        "file_path": fp,
                        "description": record["description"],
                        "model_used": record.get("model") or "",
                        "success": True,
                    }

        files_to_analyze = [fp for fp in file_paths if fp not in already_described]
        skipped_count = len(file_paths) - len(files_to_analyze)

        if skipped_count > 0:
            logger.info(f"[FILE_ANALYZER] Skipping {skipped_count} files with existing descriptions, analyzing {len(files_to_analyze)}")

        if not files_to_analyze:
            logger.info(f"[FILE_ANALYZER] All {len(file_paths)} files already have descriptions, returning existing results")
            return [existing_descriptions.get(fp, {"file_path": fp, "description": "", "success": False}) for fp in file_paths]

        total = len(files_to_analyze)

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
                    extraction_method = ""

                    # Try document extractor first (markitdown handles images, docs, etc.)
                    from ..document_extractor import get_document_extractor_locator
                    from ...prompts import CASE_FILE_ANALYSIS_TEMPLATE, CASE_VISION_ANALYSIS_TEMPLATE
                    doc_locator = get_document_extractor_locator()
                    extractor = doc_locator.get_extractor(full_path)

                    if extractor:
                        try:
                            content, extraction_method = await extractor.extract_to_markdown_detailed(full_path)
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
                            extraction_method = ""

                    if not result and is_image:
                        extraction_method = "vision"
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
                        extraction_method = "raw_text"
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

                    # D15: prefer the structured summary/keywords; fall back to
                    # the legacy heuristics when the model ignored the format.
                    parsed_summary = analysis.get("summary") or ""
                    parsed_keywords = analysis.get("keywords") or []
                    summary = parsed_summary or description[:200].split('\n')[0]
                    keywords = ""
                    if parsed_keywords:
                        keywords = ", ".join(parsed_keywords)
                    else:
                        # re is now global
                        found_entities = re.findall(r'[\u4e00-\u9fa5]{2,6}', description[:500])
                        if found_entities:
                            keywords = ", ".join(list(set(found_entities))[:5])

                    # Persist to _files.db (append-only truth row + both caches)
                    if files_db_path and description:
                        try:
                            self._llm_service.persist_to_files_db(
                                db_path=files_db_path,
                                file_path=file_path,
                                description=description,
                                summary=summary,
                                keywords=keywords,
                                model_used=result.get("model", ""),
                                task_id=task_id,
                                trigger_source="pipeline",
                                extraction_method=extraction_method,
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

        total = len(file_paths)
        results: List[Any] = [None] * total

        # Order-preserving concurrent fan-out (SPEC file-analysis D14): the
        # same llm_max_concurrency budget as analyze_files.
        sem = asyncio.Semaphore(max(1, getattr(self.settings, "llm_max_concurrency", 3)))
        processed = 0

        async def reanalyze_one(index: int, file_path: str) -> None:
            nonlocal processed
            async with sem:
                try:
                    logger.info(f"Starting re-analysis for file {index + 1}/{total}: {file_path}")
                    results[index] = await self._reanalyze_single_file(
                        file_path=file_path,
                        user_hint=user_hint,
                        kg_context=kg_context,
                        case_description=case_description,
                        files_db_path=files_db_path,
                        task_id=task_id,
                    )
                except Exception as e:
                    logger.error(f"Re-analysis failed for {file_path}: {e}", exc_info=True)
                    results[index] = {
                        "file_path": file_path,
                        "description": "",
                        "error": str(e),
                        "success": False,
                        "reanalysis": True,
                    }
                processed += 1

        await asyncio.gather(*(reanalyze_one(i, fp) for i, fp in enumerate(file_paths)))

        # KG INCREMENTAL SYNC: Trigger ingestion for newly analyzed files
        if self._graphiti_service and any(r.get("success") for r in results):
            logger.info(f"Task {task_id}: Triggering incremental Graphiti sync for re-analyzed files...")
            asyncio.create_task(self.ingest_to_knowledge_graph(
                task_id, case_description, results, files_db_path=files_db_path
            ))

        logger.info(f"Re-analysis completed: {sum(1 for r in results if r.get('success'))}/{len(results)} files successful")
        return results

    async def _reanalyze_single_file(
        self,
        *,
        file_path: str,
        user_hint: str,
        kg_context: str,
        case_description: str,
        files_db_path: str,
        task_id: str,
    ) -> Dict[str, Any]:
        """Re-analyze one file with case + KG + user context (D14 unit).

        Content routing: document extractor → vision (images) → raw text;
        persists with trigger_source='reanalyze'.
        """
        if not Path(file_path).exists():
            logger.error(f"File not found: {file_path}")
            return {
                "file_path": file_path,
                "description": "",
                "error": f"File not found: {file_path}",
                "success": False,
                "reanalysis": True,
            }

        file_ext = Path(file_path).suffix.lower()
        is_image = file_ext in IMAGE_EXTENSIONS

        extraction_method = ""

        # Try document extractor first (markitdown handles images, docs, etc.)
        from ..document_extractor import get_document_extractor_locator
        doc_locator = get_document_extractor_locator()
        extractor = doc_locator.get_extractor(file_path)

        if extractor:
            try:
                content, extraction_method = await extractor.extract_to_markdown_detailed(file_path)
                logger.info(f"Extractor converted {file_path}: {len(content)} chars")
            except Exception as e:
                logger.warning(f"Extractor failed for {file_path}: {e}, falling back")
                extractor = None  # Trigger fallback below

        result: Dict[str, Any] = {}
        if not extractor:
            if is_image:
                # Use vision model for images with custom prompt
                logger.info(f"Using vision model for image re-analysis: {file_path}")
                extraction_method = "vision"

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
                    return {
                        "file_path": file_path,
                        "description": "",
                        "error": f"Vision analysis failed: {str(e)}",
                        "success": False,
                        "reanalysis": True,
                    }
            else:
                # Use text model for text files
                extraction_method = "raw_text"
                content = await self._llm_service.read_file_content(file_path)
                logger.info(f"Read {len(content)} characters from {file_path}")

        if extractor or not is_image:
            # Text analysis path (extractor content or raw text)
            from ...prompts import (
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
                summary=(result.get("analysis", {}) or {}).get("summary") or description[:200],
                keywords="",
                model_used=result.get("model", ""),
                task_id=task_id,
                trigger_source="reanalyze",
                extraction_method=extraction_method,
            )
            if persisted:
                logger.info(f"Successfully persisted re-analysis for {file_path}")
            else:
                logger.warning(f"Failed to persist re-analysis for {file_path} (no matching row)")
        elif not files_db_path:
            logger.warning(f"No files_db_path provided - re-analysis result for {file_path} will NOT be saved to database")

        return {
            "file_path": file_path,
            "description": description,
            "model_used": result.get("model", ""),
            "success": True,
            "reanalysis": True,
        }

    async def ingest_to_knowledge_graph(
        self,
        task_id: str,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        files_db_path: str = "",
        progress_callback=None,
    ) -> bool:
        """
        Ingest case description and file descriptions into Graphiti.

        Event-cluster episodes are owned exclusively by ClusterAnalyzer's
        SPEC-format ingestor (analysis_id naming + ingested_at state) and are
        never rebuilt here (file-analysis SPEC D7).

        This enables semantic retrieval during report generation,
        overcoming LLM context length limitations.

        Args:
            task_id: Task identifier (used as graph group_id).
            case_description: Full case description text.
            file_descriptions: List of per-file analysis results.
            files_db_path: Task files db — supplies each file's forensic time
                for the episode reference_time (D12) when available.
            progress_callback: Optional async callback(stage, message) for
                job-level progress reporting (SPEC kg-ingestion-hardening §B2).

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
            desc_chunks = self._chunk_text(case_description)
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
            ingested_ids: List[int] = []
            for desc in successful:
                file_path = desc.get("file_path", "")
                description = desc.get("description", "")
                if description:
                    # D12: episode reference_time is the file's forensic time
                    # (mtime, fallback ctime), not the ingestion instant.
                    file_time = (
                        file_forensic_time(files_db_path, file_path)
                        if files_db_path else None
                    ) or datetime.now()
                    # §9-L3: episodes cite the truth record (#fa{id}) and get
                    # the enriched body; the id feeds the ingested_at state
                    # machine after a fully successful batch.
                    record = (
                        latest_analysis(files_db_path, file_path)
                        if files_db_path else None
                    )
                    analysis_id = record.get("id") if record else None
                    ep_name = f"文件分析: {file_path}"
                    if analysis_id:
                        ep_name += f" #fa{analysis_id}"
                    # Chunk long descriptions
                    chunks = self._chunk_text(description)
                    for j, chunk in enumerate(chunks):
                        if len(chunks) > 1:
                            ep_name_j = f"{ep_name} (第{j+1}部分)"
                        else:
                            ep_name_j = ep_name
                        body = {"file_path": file_path, "analysis": chunk}
                        if record:
                            if record.get("summary"):
                                body["summary"] = record["summary"]
                            if record.get("keywords"):
                                body["keywords"] = record["keywords"]
                            if record.get("md5"):
                                body["md5"] = record["md5"]
                            if analysis_id:
                                body["analysis_id"] = analysis_id
                        episodes.append(EpisodeData(
                            name=ep_name_j,
                            episode_body=json.dumps(body, ensure_ascii=False),
                            source_description=f"LLM分析结果 - {file_path}",
                            reference_time=file_time,
                            file_path=file_path,
                            file_id=0,
                            category="file_description"
                        ))
                    if analysis_id:
                        ingested_ids.append(analysis_id)

            if not episodes:
                logger.info("No episodes to ingest")
                return True

            # Batch ingest
            logger.info(f"Ingesting {len(episodes)} episodes into Graphiti for task {task_id}")
            # batch_ingest invokes its callback synchronously; bridge to the
            # async job-progress callback without blocking the ingest loop.
            ingest_progress = None
            if progress_callback is not None:
                def ingest_progress(cur, total):
                    asyncio.create_task(progress_callback("ingesting", f"正在摄入 {cur}/{total} 个分析结果"))
            async with self._graphiti_service.lock_for_group(task_id):
                result = await ingestor.batch_ingest(
                    episodes=episodes,
                    group_id=task_id,
                    progress_callback=ingest_progress,
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
            # §9-L3 state machine: mark rows ingested only when EVERY episode
            # made it — partial batches stay NULL for the next gap-fill.
            if ingested_ids and files_db_path and total and successful == total:
                from .file_schema import mark_analyses_ingested
                mark_analyses_ingested(files_db_path, ingested_ids)
            return successful > 0

        except ImportError:
            logger.warning("graphiti_integration not available, skipping KG ingestion")
            return False
        except Exception as e:
            logger.error(f"Knowledge graph ingestion failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _chunk_text(text: str, max_chars: Optional[int] = None) -> List[str]:
        """Split text into chunks (shared episode budget by default, D11)."""
        if max_chars is None:
            from ..graphiti_parts.episode_budget import episode_chunk_chars
            max_chars = episode_chunk_chars()
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

