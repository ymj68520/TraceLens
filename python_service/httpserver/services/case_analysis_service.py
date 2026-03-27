"""
Case Analysis Service — LLM-driven forensic case analysis.

Workflow:
1. Save case description (persisted via C++ tasks.json through the task API)
2. Send file list + case description to LLM → filter important files
3. For each filtered file, generate LLM description
4. Generate a final comprehensive case report using all descriptions

All results are persisted to the _files.db SQLite database.
"""

import os
import json
import logging
import sqlite3
import asyncio
import time
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..prompts import (
    FILE_FILTER_SYSTEM,
    FILE_FILTER_USER_TEMPLATE,
    FILE_DESCRIPTION_TEMPLATE,
    FILE_REANALYSIS_HEADER,
    FILE_REANALYSIS_CONTEXT_CASE,
    FILE_REANALYSIS_CONTEXT_KG,
    FILE_REANALYSIS_CONTEXT_HINT,
    FILE_REANALYSIS_CONTEXT_FILE,
    FILE_REANALYSIS_INSTRUCTION,
    REPORT_CHAPTERS,
    REPORT_CHAPTER_TEMPLATE,
    REPORT_FALLBACK_TEMPLATE,
)

logger = logging.getLogger(__name__)


class CaseAnalysisService:
    """Service for end-to-end LLM case analysis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # Will be injected after ServiceManager init
        self._llm_service = None
        self._graphiti_service = None
        self._cpp_backend = None

    def set_llm_service(self, llm_service):
        """Inject the LLM service dependency."""
        self._llm_service = llm_service

    def set_graphiti_service(self, graphiti_service):
        """Inject the Graphiti knowledge graph service (optional)."""
        self._graphiti_service = graphiti_service

    def set_cpp_backend(self, cpp_backend):
        """Inject the C++ backend service dependency."""
        self._cpp_backend = cpp_backend

    # ------------------------------------------------------------------
    # 1. File Filtering — LLM selects forensically relevant files
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 1. File Filtering — LLM selects forensically relevant files (Streaming with TOON)
    # ------------------------------------------------------------------
    async def filter_files_by_case(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int = 200,
        batch_size: int = 50,
        use_streaming: bool = True,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Let LLM select important files based on case description.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # If streaming is disabled, fall back to old method
        if not use_streaming:
            return await self._filter_files_by_case_legacy(
                files_db_path, case_description, max_files, task_id
            )

        return await self._filter_files_by_case_streaming(
            files_db_path, case_description, max_files, batch_size, task_id
        )

    async def _filter_files_by_case_streaming(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int,
        batch_size: int,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Streaming file filtering using TOON format to avoid context overflow."""
        if not self._cpp_backend:
            raise RuntimeError("C++ backend service not initialized for TOON export")

        try:
            # Get task_id from files_db_path if not provided
            if not task_id:
                import re
                # Try new path format: .../tasks/<uuid>/files.db
                task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
                if not task_match:
                    # Try legacy format: <task_id>_files.db
                    task_match = re.search(r'(\w+)_files\.db$', files_db_path)
                
                if not task_match:
                    raise RuntimeError(f"Cannot extract task_id from {files_db_path}")
                task_id = task_match.group(1)

            logger.info(f"Fetching TOON data for task {task_id}...")
            toon_data = await self._cpp_backend.get_files_toon_stream(
                task_id=task_id,
                batch_size=batch_size,
                include_llm=False,
            )

            schema = toon_data.get("schema", "")
            data_lines = toon_data.get("data_lines", [])
            total_files = toon_data.get("total_files", 0)

            if total_files == 0:
                return {
                    "filtered_files": [],
                    "reasoning": "No files found in database.",
                    "total_files": 0,
                    "selected_count": 0,
                    "streaming_used": True,
                }

            logger.info(f"Processing {total_files} files in batches of {batch_size}")

            # Split into batches
            batches = []
            for i in range(0, len(data_lines), batch_size):
                batches.append(data_lines[i:i + batch_size])

            all_selected_files = []
            batch_reasonings = []

            # Process each batch
            for batch_idx, batch_lines in enumerate(batches):
                logger.info(f"Processing batch {batch_idx + 1}/{len(batches)} ({len(batch_lines)} files)")

                # Build TOON prompt for this batch
                batch_toon = f"{schema}\n" + "\n".join(batch_lines)

                batch_prompt = self._build_batch_filter_prompt(
                    case_description=case_description,
                    batch_toon=batch_toon,
                    batch_number=batch_idx + 1,
                    total_batches=len(batches),
                    max_files=max_files,
                    already_selected=len(all_selected_files),
                )

                try:
                    result = await self._llm_service.analyze(
                        content=batch_toon,
                        model_type="text",
                        prompt=batch_prompt,
                        max_tokens=self.settings.llm_text_max_tokens,
                    )

                    response_text = result.get("analysis", {}).get("description", "")
                    parsed = self._parse_toon_filter_response(response_text, batch_lines)

                    # Accumulate selected files
                    all_selected_files.extend(parsed["selected_files"])
                    if parsed.get("reasoning"):
                        batch_reasonings.append(parsed["reasoning"])

                    logger.info(f"Batch {batch_idx + 1}: selected {len(parsed['selected_files'])} files (total: {len(all_selected_files)})")

                    # Stop if we've reached max_files
                    if len(all_selected_files) >= max_files:
                        logger.info(f"Reached max_files limit ({max_files}), stopping early")
                        break

                except Exception as e:
                    logger.warning(f"Batch {batch_idx + 1} failed: {e}")
                    continue

            # Deduplicate while preserving order
            seen = set()
            unique_selected = []
            for f in all_selected_files:
                if f not in seen:
                    seen.add(f)
                    unique_selected.append(f)

            # Trim to max_files if needed
            final_selected = unique_selected[:max_files]

            # Persist filtered file list to database
            # Extract task_id from files_db_path
            import re
            task_id_extracted = "_latest"
            task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
            if task_match:
                task_id_extracted = task_match.group(1)
            
            self._persist_filtered_files(files_db_path, task_id_extracted, final_selected)

            logger.info(f"Task {task_id_extracted}: Filtering complete. Selected {len(final_selected)} files.")
            if not final_selected:
                logger.warning(f"Task {task_id_extracted}: No files matched case description in LLM output.")

            combined_reasoning = " | ".join(batch_reasonings) if batch_reasonings else "Streaming filtering completed"

            return {
                "filtered_files": final_selected,
                "reasoning": combined_reasoning,
                "total_files": total_files,
                "selected_count": len(final_selected),
                "model_used": "streaming_llm",
                "streaming_used": True,
                "batches_processed": len(batches),
            }

        except Exception as e:
            logger.error(f"Streaming file filtering failed: {e}", exc_info=True)
            # Fall back to legacy method
            logger.info("Falling back to legacy filtering method")
            return await self._filter_files_by_case_legacy(
                files_db_path, case_description, max_files
            )

    def _build_batch_filter_prompt(
        self,
        case_description: str,
        batch_toon: str,
        batch_number: int,
        total_batches: int,
        max_files: int,
        already_selected: int,
    ) -> str:
        """Build prompt for batch filtering with TOON format."""
        return f"""你是数字取证专家，正在分析一个案件。

## 案情描述
{case_description}

## 文件列表（TOON格式 - 第{batch_number}/{total_batches}批）
{batch_toon}

## 任务
从上述文件列表中选择与案情相关的文件。注意：
1. 这是第{batch_number}/{total_batches}批数据
2. 全局最多选择{max_files}个文件，已选择{already_selected}个
3. 返回JSON格式：{{"selected_files": ["path1", "path2", ...], "reasoning": "选择原因"}}"""

    def _parse_toon_filter_response(
        self,
        response_text: str,
        batch_lines: List[str],
    ) -> Dict[str, Any]:
        """Parse LLM response from TOON batch filtering with robustness."""
        selected_files = []
        reasoning = ""

        try:
            # 1. Pre-process text to find JSON
            text = response_text.strip()
            # Remove markdown code blocks if present
            if "```" in text:
                import re
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
                if json_match:
                    text = json_match.group(1)
            
            # Find the first '[' or '{' and last ']' or '}'
            start_idx = text.find('[')
            start_brace = text.find('{')
            if start_brace != -1 and (start_idx == -1 or start_brace < start_idx):
                start_idx = start_brace
            
            end_idx = text.rfind(']')
            end_brace = text.rfind('}')
            if end_brace != -1 and (end_idx == -1 or end_brace > end_idx):
                end_idx = end_brace
                
            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]

            # 2. Parse JSON
            parsed = json.loads(text)
            
            selected_paths = []
            if isinstance(parsed, list):
                # Format: ["path1", "path2"]
                selected_paths = parsed
            elif isinstance(parsed, dict):
                # Format: {"selected_files": [...], "reasoning": "..."}
                selected_paths = parsed.get("selected_files", []) or parsed.get("filtered_files", [])
                reasoning = parsed.get("reasoning", "")
            
            # 3. Match against batch lines
            all_paths_in_batch = []
            for line in batch_lines:
                parts = line.split(" | ")
                if parts:
                    all_paths_in_batch.append(parts[0].strip())

            for path in selected_paths:
                if not isinstance(path, str): continue
                path_clean = path.strip().strip('"').strip("'")
                # 1. Exact match in batch
                matching_paths = [p for p in all_paths_in_batch if p == path_clean]
                
                # 2. Filename match (if only filename provided)
                if not matching_paths:
                    matching_paths = [p for p in all_paths_in_batch if Path(p).name == path_clean]
                
                # 3. Partial path match (case insensitive)
                if not matching_paths:
                    matching_paths = [p for p in all_paths_in_batch if path_clean.lower() in p.lower()]
                
                selected_files.extend(matching_paths)

        except Exception as e:
            logger.warning(f"JSON parse failed for filter response: {e}. Falling back to text pattern matching.")
            # Aggressive fallback: search every filename in the response text
            for line in batch_lines:
                parts = line.split(" | ")
                if parts:
                    full_path = parts[0].strip()
                    filename = Path(full_path).name
                    # Look for filename as a separate word in the response
                    import re
                    if re.search(rf'\b{re.escape(filename)}\b', response_text) or \
                       re.search(rf'"{re.escape(filename)}"', response_text):
                        selected_files.append(full_path)

        # Deduplicate while preserving order
        seen = set()
        unique_files = []
        for f in selected_files:
            if f not in seen:
                unique_files.append(f)
                seen.add(f)

        return {
            "selected_files": unique_files,
            "reasoning": reasoning,
        }

    async def _filter_files_by_case_legacy(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int = 200,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        """
        Legacy file filtering method (single large prompt).

        NOT RECOMMENDED for large file sets due to context overflow risk.
        """
        # Read file list from database
        all_files = self._get_file_list_from_db(files_db_path)
        if not all_files:
            return {"filtered_files": [], "reasoning": "No files found in database."}

        # Build a concise file summary for the LLM
        file_summary = self._build_file_summary(all_files)

        user_prompt = FILE_FILTER_USER_TEMPLATE.format(
            case_description=case_description,
            file_count=len(all_files),
            file_summary=file_summary,
            max_files=max_files,
        )

        try:
            result = await self._llm_service.analyze(
                content=user_prompt,
                model_type="text",
                prompt=user_prompt,
                max_tokens=self.settings.llm_text_max_tokens,
            )

            response_text = result.get("analysis", {}).get("description", "")
            parsed = self._parse_filter_response(response_text, all_files)

            # Extract task_id from files_db_path if not provided
            task_id_extracted = "_latest"
            import re
            task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
            if task_match:
                task_id_extracted = task_match.group(1)

            # Persist filtered file list to database
            self._persist_filtered_files(files_db_path, task_id_extracted, parsed["selected_files"])

            return {
                "filtered_files": parsed["selected_files"],
                "reasoning": parsed.get("reasoning", ""),
                "total_files": len(all_files),
                "selected_count": len(parsed["selected_files"]),
                "model_used": result.get("model", ""),
                "streaming_used": False,
            }
        except Exception as e:
            logger.error(f"File filtering failed: {e}", exc_info=True)
            raise

    async def extract_filtered_files(
        self,
        task_id: str,
        file_paths: List[str],
        extraction_dir: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Extract filtered files to local disk.

        Calls C++ backend's file extraction API to extract selected files
        from the disk image so they can be analyzed by LLM.

        Args:
            task_id: Task ID
            file_paths: List of file paths to extract
            extraction_dir: Extraction directory (None = use default)
            progress_callback: Progress callback (current, total, file_path)

        Returns:
            Dict containing extraction results
        """
        if not file_paths:
            return {"success": True, "extracted_count": 0, "extraction_dir": ""}

        if not self._cpp_backend:
            raise RuntimeError("C++ backend service not initialized")

        try:
            # Get task info to determine extraction directory
            task_info = await self._cpp_backend.get_task(task_id)
            if not task_info:
                logger.error(f"Task {task_id} not found when trying to extract files.")
                raise RuntimeError(f"Task {task_id} not found")

            # Determine extraction directory
            # Priority: extraction_dir parameter > task's extraction_directory > default
            if not extraction_dir:
                extraction_dir = task_info.get("extraction_directory", "")
            
            # Make it absolute if it's not
            if extraction_dir and not os.path.isabs(extraction_dir):
                project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
                if not os.path.exists(os.path.join(project_root, "build")):
                    project_root = os.getcwd()
                extraction_dir = os.path.join(project_root, extraction_dir)

            if not extraction_dir:
                # Use task-specific directory under default extracted_files
                project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
                if not os.path.exists(os.path.join(project_root, "build")):
                    project_root = os.getcwd()
                extraction_dir = os.path.join(project_root, "build", "data", "tasks", task_id, "extracted_files")

            logger.info(f"Task {task_id}: Final determined extraction directory: {extraction_dir}")
            logger.info(f"Task {task_id}: Starting targeted extraction of {len(file_paths)} files")

            # Start extraction task
            extract_result = await self._cpp_backend.extract_files(
                task_id=task_id,
                file_paths=file_paths,
                output_dir=extraction_dir,
                overwrite=False,  # Don't overwrite existing files
            )

            job_id = extract_result.get("job_id")
            if not job_id:
                logger.error(f"Task {task_id}: Extraction API failed to return job_id. Result: {extract_result}")
                raise RuntimeError("Extract API did not return a job_id")

            logger.info(f"Task {task_id}: Extraction job {job_id} started. Waiting for completion...")

            # Poll for completion
            import asyncio
            max_wait = 600  # 10 minutes timeout
            start_time = asyncio.get_event_loop().time()
            poll_interval = 2  # Check every 2 seconds

            while True:
                status = await self._cpp_backend.get_extraction_status(job_id)
                state = status.get("status", "unknown")
                
                # Log progress periodically
                if state == "running":
                    logger.info(f"Job {job_id} progress: {status.get('progress', 0)}% ({status.get('extracted_files', 0)}/{status.get('total_files', len(file_paths))})")

                if state == "completed":
                    logger.info(f"Task {task_id}: Extraction job {job_id} completed successfully.")
                    return {
                        "success": True,
                        "extracted_count": status.get("extracted_files", 0),
                        "extraction_dir": status.get("output_path", extraction_dir),
                    }
                elif state == "failed":
                    error_msg = status.get("error_details", "Unknown error")
                    raise RuntimeError(f"Extraction failed: {error_msg}")
                elif state == "cancelled":
                    raise RuntimeError("Extraction was cancelled")

                # Check timeout
                if asyncio.get_event_loop().time() - start_time > max_wait:
                    raise RuntimeError("Extraction timeout after 10 minutes")

                # Report progress
                if progress_callback:
                    extracted = status.get("extracted_files", 0)
                    total_files = status.get("total_files", len(file_paths))
                    await progress_callback(extracted, total_files, f"提取中... ({extracted}/{total_files})")

                await asyncio.sleep(poll_interval)

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"File extraction failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "extracted_count": 0,
                "extraction_dir": "",
            }

    # ------------------------------------------------------------------
    # 3. Per-file Description Generation
    # ------------------------------------------------------------------
    async def generate_file_descriptions(
        self,
        files_db_path: str,
        file_paths: List[str],
        case_description: str,
        extraction_dir: Optional[str] = None,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Generate LLM description for each file in the list using concurrency.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        total = len(file_paths)
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
                    if is_image:
                        with open(full_path, 'rb') as f:
                            image_data = f.read()
                        
                        vision_prompt = f"请结合案情背景对这张图像进行深度取证分析。\n案情背景：{case_description}\n\n要求：提取文字信息、识别人物/账号、发现时间线索，并评估取证价值。"
                        
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
                        
                        custom_prompt = f"""作为资深取证专家，请对以下文件进行深度分析。

## 案情背景
{case_description}

## 待分析文件路径
{file_path}

## 文件内容
{content}

## 分析要求
请针对上述案情背景，详细分析该文件的取证价值。重点关注：
1. 文件内容与案件的关联性
2. 关键人物、账号、时间、金额等信息的提取
3. 任何可疑的活动痕迹或异常点
4. 综合评估该证据的效力

请输出纯文本，不要使用 Markdown。"""
                        
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

        # Run all tasks concurrently
        tasks = [analyze_file(fp) for fp in file_paths]
        return await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # 3. Knowledge Graph Ingestion (Graphiti)
    # ------------------------------------------------------------------
    async def ingest_to_knowledge_graph(
        self,
        task_id: str,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
    ) -> bool:
        """
        Ingest case description and file descriptions into Graphiti.

        This enables semantic retrieval during report generation,
        overcoming LLM context length limitations.

        Args:
            task_id: Task identifier (used as graph group_id).
            case_description: Full case description text.
            file_descriptions: List of per-file analysis results.

        Returns:
            True if ingestion succeeded, False otherwise.
        """
        if not self._graphiti_service:
            logger.info("Graphiti service not available, skipping KG ingestion")
            return False

        try:
            from graphiti_integration.toon_transformer import EpisodeData
            from datetime import datetime

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

            if not episodes:
                logger.info("No episodes to ingest")
                return True

            # Batch ingest
            logger.info(f"Ingesting {len(episodes)} episodes into Graphiti for task {task_id}")
            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=task_id,
            )
            logger.info(
                f"Graphiti ingestion complete: {getattr(result, 'successful', 0)}/{getattr(result, 'total_episodes', len(episodes))} successful"
            )
            return getattr(result, 'successful', 0) > 0

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

    # ------------------------------------------------------------------
    # 3b. File Re-analysis (secondary analysis with user hints)
    # ------------------------------------------------------------------
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

                if is_image:
                    # Use vision model for images with custom prompt
                    logger.info(f"Using vision model for image re-analysis: {file_path}")

                    # Build vision prompt with case context
                    vision_prompt_parts = []
                    if case_description:
                        vision_prompt_parts.append(f"案情背景：{case_description}")
                    if user_hint:
                        vision_prompt_parts.append(f"调查人员补充说明：{user_hint}")
                    if kg_context:
                        vision_prompt_parts.append(f"相关上下文：{kg_context}")

                    vision_prompt = "请根据以上信息重新分析这张图像的取证价值。\n\n" + "\n".join(vision_prompt_parts)

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

    # ------------------------------------------------------------------
    # 4. Final Case Report Generation (Graph-enhanced & Dynamic Aggregation)
    # ------------------------------------------------------------------
    async def generate_case_report(
        self,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        files_db_path: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive case analysis report.
        Aggregates ALL available file descriptions from the database.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # DYNAMIC AGGREGATION: Always pull the latest descriptions from database
        # This ensures manually re-analyzed or analyzed files are included in the report
        if files_db_path and task_id:
            logger.info(f"Task {task_id}: Aggregating all relevant evidence descriptions from database...")
            try:
                with sqlite3.connect(files_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    # CRITICAL: Include files NOT explicitly marked as irrelevant (is_relevant IS NOT 0)
                    # This handles NULL (legacy/default) and 1 (explicitly marked)
                    cur = conn.execute("SELECT file_path, description, model_used FROM file_descriptions WHERE is_relevant IS NOT 0")
                    rows = cur.fetchall()
                    if rows:
                        # Convert DB rows to the format expected by build_evidence_summary
                        file_descriptions = [
                            {
                                "file_path": row["file_path"], 
                                "description": row["description"], 
                                "success": True,
                                "model_used": row["model_used"]
                            }
                            for row in rows
                        ]
                        logger.info(f"Task {task_id}: Integrated {len(file_descriptions)} relevant evidence files into report.")
                    else:
                        file_descriptions = []
                        logger.info(f"Task {task_id}: No relevant evidence found in database.")
            except Exception as e:
                logger.warning(f"Failed to aggregate evidence from database: {e}")

        use_graph = (
            self._graphiti_service is not None
            and task_id is not None
        )

        report_text = ""
        model_used = "direct"

        if use_graph:
            try:
                logger.info(f"Task {task_id}: Attempting graph-enhanced report generation...")
                report_text = await self._generate_report_with_graph(
                    case_description, task_id, file_descriptions
                )
                if report_text:
                    model_used = "graph-enhanced"
            except Exception as e:
                logger.warning(
                    f"Graph-enhanced report generation failed, falling back: {e}"
                )
        
        # Fallback if graph failed or returned nothing
        if not report_text:
            try:
                logger.info(f"Task {task_id}: Using fallback (concatenation) report generation...")
                report_text = await self._generate_report_fallback(
                    case_description, file_descriptions
                )
                model_used = "direct"
            except Exception as e:
                logger.error(f"Fallback generation also failed: {e}", exc_info=True)
                report_text = "生成报告时发生错误：" + str(e)

        # Persist report to database
        if files_db_path and report_text and not report_text.startswith("生成报告时发生错误"):
            try:
                self._persist_case_report(
                    files_db_path, task_id or "", case_description, report_text
                )
            except Exception as e:
                logger.warning(f"Failed to persist case report to db: {e}")

        return {
            "report": report_text,
            "case_description": case_description,
            "files_analyzed": len(file_descriptions),
            "files_successful": sum(1 for f in file_descriptions if f.get("success")),
            "model_used": model_used,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def _generate_report_with_graph(
        self, case_description: str, task_id: str, file_descriptions: List[Dict[str, Any]] = None
    ) -> str:
        """
        Generate report using Graphiti RAG with optimized context management.
        
        Implementation:
        - Option A: Lightweight evidence list (paths only) to save space.
        - Option C: Tunable retrieval limits from config.py.
        """
        # [Option A] LIGHTWEIGHT CHECKLIST:
        # Since full descriptions are already in the Knowledge Graph, we only need to provide
        # a checklist of file paths to ensure the LLM includes them in the final report.
        evidence_list_str = "本案关键证据文件清单（细节请参考下文【知识图谱背景】）：\n"
        if file_descriptions:
            # Only list the file paths to save thousands of tokens
            for d in file_descriptions:
                evidence_list_str += f"- [[file:{d.file_path}]]\n"
        else:
            evidence_list_str += "（无显式证据文件，基于全局图谱分析）"

        chapters = [
            {
                "title": ch["title"],
                "query": ch["query_template"].format(
                    case_desc_short=case_description[:200]
                ),
                "instruction": ch["instruction"],
            }
            for ch in REPORT_CHAPTERS
        ]

        report_parts = []
        # [Option C] TUNABLE RETRIEVAL:
        search_limit = getattr(self.settings, 'graphiti_search_limit', 10)
        content_limit = getattr(self.settings, 'graphiti_context_item_limit', 250)

        for chapter in chapters:
            # Search the knowledge graph for relevant context
            search_results = await self._graphiti_service.search(
                query=chapter["query"],
                task_id=task_id,
                limit=search_limit,
                include_relationships=True,
            )

            # Build context from search results with dynamic truncation
            context_lines = []
            for r in search_results:
                name = r.get("name", "")
                props = r.get("properties", {})
                body = props.get("body", "") or props.get("summary", "") or name
                if body:
                    # Apply fine-tuned truncation
                    truncated_body = body[:content_limit] + "..." if len(body) > content_limit else body
                    context_lines.append(f"- {truncated_body}")

            kg_context = "\n".join(context_lines) if context_lines else "无相关图谱信息。"

            # CONSOLIDATED PROMPT: Dramatically reduced size but high information density
            combined_context = f"【核心证据清单】\n{evidence_list_str}\n\n【图谱研判背景】\n{kg_context}"

            prompt = REPORT_CHAPTER_TEMPLATE.format(
                chapter_title=chapter["title"],
                case_description=case_description,
                context=combined_context,
                chapter_instruction=chapter["instruction"] + 
                "\n\nCRITICAL INSTRUCTION: "
                "1. 你必须在分析中显式引用【核心证据清单】中的文件路径；"
                "2. 每一个引用的文件必须严格遵循 [[file:路径]] 格式（例如 [[file:/usr/bin/cmd]]）；"
                "3. 严禁虚构不存在的文件路径。",
            )

            try:
                result = await self._llm_service.analyze(
                    content=prompt,
                    model_type="text",
                    prompt=prompt,
                    max_tokens=self.settings.llm_text_max_tokens,
                )
                chapter_text = result.get("analysis", {}).get("description", "")
            except Exception as e:
                logger.warning(f"Failed to generate chapter '{chapter['title']}': {e}")
                chapter_text = f"（该章节生成失败：{e}）"

            report_parts.append(f"## {chapter['title']}\n\n{chapter_text}")

        return "\n\n---\n\n".join(report_parts)

    async def _generate_report_fallback(
        self, case_description: str, file_descriptions: List[Dict[str, Any]]
    ) -> str:
        """
        Fallback: concatenate all evidence and generate in one shot.
        Used when Graphiti is unavailable.
        """
        evidence_section = self._build_evidence_summary(file_descriptions)

        user_prompt = REPORT_FALLBACK_TEMPLATE.format(
            case_description=case_description,
            evidence_section=evidence_section,
        )

        result = await self._llm_service.analyze(
            content=user_prompt,
            model_type="text",
            prompt=user_prompt,
            max_tokens=self.settings.llm_text_max_tokens,
        )
        return result.get("analysis", {}).get("description", "")

    # ------------------------------------------------------------------
    # Full Pipeline — run all steps sequentially
    # ------------------------------------------------------------------
    async def run_full_analysis(
        self,
        task_id: str,
        files_db_path: str,
        case_description: str,
        max_filter_files: int = 200,
        run_filtering: bool = True,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run the complete case analysis pipeline.

        Steps:
            1. Filter files by case relevance (Optional)
            2. Generate per-file descriptions
            3. Generate final case report
        """
        result = {
            "task_id": task_id,
            "case_description": case_description,
            "steps": {},
        }

        filtered_files = []
        descriptions = []
        extraction_dir = ""
        
        if run_filtering:
            # --- FULL PIPELINE MODE (Initial Task or Explicit Re-scan) ---
            
            # Step 1: Filter files via LLM
            if progress_callback:
                await progress_callback("filtering", "正在使用 LLM 自动筛选关键文件...")
            filter_result = await self.filter_files_by_case(
                files_db_path, case_description, max_filter_files, task_id=task_id
            )
            result["steps"]["filter"] = filter_result
            filtered_files = filter_result.get("filtered_files", [])
            
            # Persist the list so we can recover if subsequent steps fail
            self._persist_filtered_files(files_db_path, task_id, filtered_files)

            if not filtered_files:
                msg = "LLM 未能在样本中筛选出与案情高度相关的文件。跳过文件提取和描述阶段。"
                logger.info(f"Task {task_id}: {msg}")
                result["steps"]["extraction"] = {"extraction_dir": "", "extracted_count": 0}
                result["steps"]["descriptions"] = []
            else:
                # Step 2: Extract filtered files to local disk
                if progress_callback:
                    await progress_callback("extracting", f"正在提取 {len(filtered_files)} 个文件到本地...")
                
                try:
                    extract_result = await self.extract_filtered_files(
                        task_id, filtered_files, progress_callback=progress_callback
                    )
                    result["steps"]["extraction"] = extract_result
                    extraction_dir = extract_result.get("extraction_dir", "")
                except Exception as e:
                    logger.error(f"Extraction step critical failure: {e}", exc_info=True)
                    result["steps"]["extraction"] = {"success": False, "error": str(e), "extracted_count": 0}

                # Step 3: Generate per-file descriptions
                if progress_callback:
                    await progress_callback("describing", f"正在分析 {len(filtered_files)} 个相关文件...")
                
                try:
                    descriptions = await self.generate_file_descriptions(
                        files_db_path, filtered_files, case_description, extraction_dir=extraction_dir,
                        progress_callback=progress_callback
                    )
                    result["steps"]["descriptions"] = descriptions
                except Exception as e:
                    logger.error(f"Description step failure: {e}", exc_info=True)

                # Step 3.6: Auto-analyze top event clusters for Timeline
                try:
                    if progress_callback:
                        await progress_callback("analyzing_clusters", "正在自动研判关键时间线事件簇...")
                    
                    task_info = await self._cpp_backend.get_task(task_id)
                    events_db = task_info.get("output_events_db") or ""
                    
                    if events_db and os.path.exists(events_db):
                        cluster_results = await self._analyze_high_frequency_clusters(
                            events_db, case_description, limit=5
                        )
                        result["steps"]["event_clusters"] = {
                            "analyzed_count": len(cluster_results),
                            "success": True
                        }
                    else:
                        logger.warning(f"Task {task_id}: No events database found for cluster analysis")
                except Exception as e:
                    logger.error(f"Event cluster auto-analysis failed: {e}", exc_info=True)

                # Step 3.5: Ingest into knowledge graph
                if self._graphiti_service:
                    if progress_callback:
                        await progress_callback("ingesting", "正在将分析结果摄入知识图谱...")
                    try:
                        kg_ok = await self.ingest_to_knowledge_graph(
                            task_id, case_description, descriptions
                        )
                        result["steps"]["knowledge_graph"] = {"ingested": kg_ok, "episodes": len(descriptions) + 1}
                    except Exception as e:
                        logger.warning(f"KG ingestion failed (non-fatal): {e}")

        else:
            # --- FAST REPORTING MODE (Manual Review / Refinement) ---
            if progress_callback:
                await progress_callback("reporting_init", "跳过前置分析，正在根据当前研判结论生成报告...")
            
            # When run_filtering is False, we pass an empty descriptions list
            # generate_case_report will then automatically pull ALL 'relevant' 
            # descriptions directly from the database.
            logger.info(f"Task {task_id}: Fast reporting mode. Skipping filter/extract/describe.")

        # Step 4: Final Case Report Generation (Common Path)
        if progress_callback:
            await progress_callback("reporting", "正在合成综合案情分析报告...")
        
        report = await self.generate_case_report(
            case_description, descriptions, files_db_path, task_id
        )
        result["steps"]["report"] = report

        logger.info(f"Task {task_id}: Full analysis pipeline completed.")
        logger.info(f"  - Files filtered: {len(filtered_files)}")
        logger.info(f"  - Files extracted: {extract_result.get('extracted_count', 0)}")
        logger.info(f"  - Files described: {len(descriptions)}")
        if self._graphiti_service:
            logger.info(f"  - KG ingestion: {result['steps'].get('knowledge_graph', {}).get('ingested', False)}")

        return result

    # ------------------------------------------------------------------
    # Report Retrieval
    # ------------------------------------------------------------------
    def get_case_report(self, files_db_path: str, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a persisted case report from the database.

        Args:
            files_db_path: Path to _files.db.
            task_id: Task identifier.

        Returns:
            Report dict or None if not found.
        """
        if not files_db_path or not Path(files_db_path).exists():
            return None

        try:
            with sqlite3.connect(files_db_path, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM case_analysis WHERE task_id = ?",
                    (task_id,),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "task_id": row["task_id"],
                        "case_description": row["case_description"],
                        "filtered_files": json.loads(row["filtered_files"] or "[]"),
                        "case_report": row["case_report"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
        except Exception as e:
            logger.warning(f"Failed to retrieve case report: {e}")
        return None

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """
        Retrieve the list of case-relevant files.
        Prioritizes files that already have LLM descriptions in the database.
        """
        if not files_db_path or not Path(files_db_path).exists():
            return []

        try:
            with sqlite3.connect(files_db_path, timeout=10) as conn:
                cur = conn.cursor()
                
                # 1. First, get files that have been analyzed (dynamic evidence)
                # Exclude explicitly marked irrelevant files
                cur.execute("SELECT DISTINCT file_path FROM file_descriptions WHERE is_relevant IS NOT 0")
                analyzed_files = [row[0] for row in cur.fetchall()]
                
                # 2. Also get files from the initial filter list
                cur.execute(
                    "SELECT filtered_files FROM case_analysis WHERE task_id = ?",
                    (task_id,)
                )
                row = cur.fetchone()
                initial_filtered = json.loads(row[0]) if row and row[0] else []
                
                # Combine and deduplicate
                all_relevant = list(dict.fromkeys(analyzed_files + initial_filtered))
                return all_relevant
                
        except Exception as e:
            logger.warning(f"Failed to retrieve case-relevant files: {e}")
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_file_list_from_db(self, db_path: str) -> List[Dict[str, str]]:
        """Read file list from the _files.db."""
        if not Path(db_path).exists():
            return []

        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT path, type as file_type, size FROM files ORDER BY path"
                )
                rows = cur.fetchall()
                return [
                    {
                        "path": row["path"],
                        "file_type": row["file_type"] if "file_type" in row.keys() else "",
                        "size": row["size"] if "size" in row.keys() else 0,
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to read file list from {db_path}: {e}")
            return []

    def _build_file_summary(self, files: List[Dict[str, str]]) -> str:
        """Build a concise file list summary for LLM consumption."""
        lines = []
        for f in files[:2000]:  # Cap to avoid context overflow
            path = f.get("path", "")
            ftype = f.get("file_type", "")
            size = f.get("size", 0)
            size_str = self._format_size(size) if size else ""
            line = f"- {path}"
            if ftype:
                line += f" [{ftype}]"
            if size_str:
                line += f" ({size_str})"
            lines.append(line)

        if len(files) > 2000:
            lines.append(f"... 及其他 {len(files) - 2000} 个文件")

        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes) -> str:
        """Format file size to human-readable string."""
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            return ""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.0f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"

    def _parse_filter_response(
        self, response_text: str, all_files: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Parse LLM response to extract selected files."""
        all_paths = {f["path"] for f in all_files}
        try:
            # Try to parse JSON from response
            # Handle potential markdown code block wrapping
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                text = text.rsplit("```", 1)[0]
            parsed = json.loads(text)
            selected = parsed.get("selected_files", [])
            reasoning = parsed.get("reasoning", "")
            # Validate paths against actual file list
            valid_paths = [p for p in selected if p in all_paths]
            return {"selected_files": valid_paths, "reasoning": reasoning}
        except (json.JSONDecodeError, KeyError):
            logger.warning("Could not parse LLM filter response as JSON, falling back to line parsing")
            # Fallback: extract file paths from text
            selected = []
            for line in response_text.split("\n"):
                line = line.strip().strip("-").strip("*").strip()
                if line in all_paths:
                    selected.append(line)
            return {"selected_files": selected, "reasoning": response_text[:500]}

    def _build_evidence_summary(self, file_descriptions: List[Dict[str, Any]]) -> str:
        """Build evidence summary for the final report."""
        lines = []
        successful = [f for f in file_descriptions if f.get("success")]
        for desc in successful:
            file_path = desc.get("file_path", "")
            description = desc.get("description", "")
            if description:
                lines.append(f"### 文件: {file_path}\n{description}\n")
        return "\n".join(lines) if lines else "无有效的文件分析结果。"

    async def _analyze_high_frequency_clusters(
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
            with sqlite3.connect(events_db, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                # Use same grouping logic as C++ Timeline
                sql = R"(
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
                )"
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
                prompt = f"案情背景：{case_description}\n\n请针对以上案情背景，分析这个事件簇在取证上的意义，并给出研判结论。"
                
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

    def _ensure_case_analysis_table(self, db_path: str):
        """Create case_analysis table if it doesn't exist."""
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS case_analysis (
                        task_id TEXT PRIMARY KEY,
                        case_description TEXT,
                        filtered_files TEXT,
                        case_report TEXT,
                        created_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to create case_analysis table: {e}")

    def _persist_filtered_files(self, db_path: str, task_id: str, filtered_files: List[str]):
        """Persist the filtered file list to database using the correct task_id."""
        self._ensure_case_analysis_table(db_path)
        now = int(time.time())
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO case_analysis
                        (task_id, filtered_files, created_at, updated_at)
                    VALUES
                        (?, ?, ?, ?)
                """, (task_id, json.dumps(filtered_files), now, now))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist filtered files for task {task_id}: {e}")

    def _persist_case_report(
        self, db_path: str, task_id: str,
        case_description: str, report: str
    ):
        """Persist the case report to database."""
        self._ensure_case_analysis_table(db_path)
        now = int(time.time())
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO case_analysis
                        (task_id, case_description, filtered_files, case_report, created_at, updated_at)
                    VALUES
                        (?, ?, COALESCE(
                            (SELECT filtered_files FROM case_analysis WHERE task_id = ?),
                            '[]'
                        ), ?, ?, ?)
                """, (task_id, case_description, task_id, report, now, now))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist case report: {e}")
