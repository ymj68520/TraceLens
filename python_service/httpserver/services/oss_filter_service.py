"""
OSS Filter Service — LLM-driven OSS object filtering for case analysis.

This module handles filtering of OSS (Object Storage Service) objects
based on case descriptions using LLM analysis.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import sqlite3

from ..config import Settings
from ..prompts import OSS_FILTER_SYSTEM, OSS_FILTER_USER_TEMPLATE

logger = logging.getLogger(__name__)


class OSSFilterService:
    """Handles OSS object filtering operations."""

    def __init__(self, settings: Settings, llm_service, cpp_backend):
        """
        Initialize OSSFilterService.

        Args:
            settings: Application settings
            llm_service: LLM service for analysis
            cpp_backend: C++ backend service for data access
        """
        self.settings = settings
        self._llm_service = llm_service
        self._cpp_backend = cpp_backend

    async def filter_oss_objects(
        self,
        oss_db_path: str,
        case_description: str,
        max_objects: int = 200,
        batch_size: int = 50,
        use_streaming: bool = True,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Let LLM select important OSS objects based on case description.

        Args:
            oss_db_path: Path to the _oss.db database file
            case_description: Description of the case for filtering
            max_objects: Maximum number of objects to select
            batch_size: Number of objects per batch for streaming
            use_streaming: Whether to use streaming TOON format
            task_id: Optional task ID for persistence

        Returns:
            Dict containing filtered_objects, reasoning, and metadata
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # If streaming is disabled, fall back to old method
        if not use_streaming:
            return await self._filter_oss_objects_legacy(
                oss_db_path, case_description, max_objects, task_id
            )

        return await self._filter_oss_objects_streaming(
            oss_db_path, case_description, max_objects, batch_size, task_id
        )

    async def _filter_oss_objects_streaming(
        self,
        oss_db_path: str,
        case_description: str,
        max_objects: int,
        batch_size: int,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Streaming OSS object filtering using TOON format to avoid context overflow."""
        if not self._cpp_backend:
            raise RuntimeError("C++ backend service not initialized for TOON export")

        try:
            # Get task_id from oss_db_path if not provided
            if not task_id:
                # Try new path format: .../tasks/<uuid>/oss.db
                task_match = re.search(r'tasks/([a-f0-9-]+)/', oss_db_path)
                if not task_match:
                    # Try legacy format: <task_id>_oss.db
                    task_match = re.search(r'(\w+)_oss\.db$', oss_db_path)

                if not task_match:
                    raise RuntimeError(f"Cannot extract task_id from {oss_db_path}")
                task_id = task_match.group(1)

            logger.info(f"[OSS_FILTER] Task {task_id}: Fetching OSS objects from {oss_db_path}...")

            # Get OSS objects from database
            all_objects = self._get_objects_from_db(oss_db_path)

            if not all_objects:
                logger.warning(f"[OSS_FILTER] Task {task_id}: No OSS objects found in database!")
                return {
                    "filtered_objects": [],
                    "reasoning": "No OSS objects found in database.",
                    "total_objects": 0,
                    "selected_count": 0,
                    "streaming_used": True,
                }

            total_objects = len(all_objects)
            logger.info(f"[OSS_FILTER] Task {task_id}: Found {total_objects} OSS objects")

            # Convert to TOON format
            toon_data = self._convert_to_toon_format(all_objects)

            schema = toon_data.get("schema", "")
            data_lines = toon_data.get("data_lines", [])

            logger.info(f"[OSS_FILTER] Task {task_id}: TOON data prepared - schema={len(schema)} chars, lines={len(data_lines)}")

            logger.info(f"Processing {total_objects} objects in batches of {batch_size}")

            # Split into batches
            batches = self._create_batches(data_lines, batch_size)

            all_selected_objects = []
            batch_reasonings = []

            # Process each batch
            for batch_idx, batch_lines in enumerate(batches):
                logger.info(f"Processing batch {batch_idx + 1}/{len(batches)} ({len(batch_lines)} objects)")
                logger.info(f"[OSS_FILTER] TOON schema: {schema[:200]}")
                logger.info(f"[OSS_FILTER] TOON sample data (first 3 lines): {batch_lines[:3]}")

                # Build TOON prompt for this batch
                batch_toon = f"{schema}\n" + "\n".join(batch_lines)
                logger.info(f"[OSS_FILTER] Batch TOON data length: {len(batch_toon)} chars")

                batch_prompt = self._build_filter_prompt(
                    case_description=case_description,
                    batch_toon=batch_toon,
                    batch_number=batch_idx + 1,
                    total_batches=len(batches),
                    max_objects=max_objects,
                    already_selected=len(all_selected_objects),
                )

                try:
                    result = await self._llm_service.analyze(
                        content=batch_toon,
                        model_type="text",
                        prompt=batch_prompt,
                        max_tokens=self.settings.llm_text_max_tokens,
                    )

                    response_text = result.get("analysis", {}).get("description", "")
                    logger.info(f"[OSS_FILTER] Batch {batch_idx + 1}: LLM response received, length={len(response_text)} chars")
                    logger.info(f"[OSS_FILTER] Batch {batch_idx + 1}: Full LLM response: {response_text}")
                    logger.debug(f"[OSS_FILTER] Batch {batch_idx + 1}: LLM response preview: {response_text[:500]}...")

                    parsed = self._parse_filter_response(response_text, batch_lines)
                    logger.info(f"[OSS_FILTER] Batch {batch_idx + 1}: Parsed result - selected_objects: {len(parsed['selected_objects'])}, reasoning: {parsed.get('reasoning', '')[:200]}")

                    # Accumulate selected objects
                    all_selected_objects.extend(parsed["selected_objects"])
                    if parsed.get("reasoning"):
                        batch_reasonings.append(parsed["reasoning"])

                    logger.info(f"[OSS_FILTER] Batch {batch_idx + 1}: parsed {len(parsed['selected_objects'])} objects, total so far: {len(all_selected_objects)}")

                    # Stop if we've reached max_objects
                    if len(all_selected_objects) >= max_objects:
                        logger.info(f"Reached max_objects limit ({max_objects}), stopping early")
                        break

                except Exception as e:
                    logger.warning(f"Batch {batch_idx + 1} failed: {e}")
                    continue

            # Deduplicate while preserving order
            seen = set()
            unique_selected = []
            for obj in all_selected_objects:
                if obj not in seen:
                    seen.add(obj)
                    unique_selected.append(obj)

            # Trim to max_objects if needed
            final_selected = unique_selected[:max_objects]

            logger.info(f"[OSS_FILTER] Task {task_id}: Before trimming - unique_selected: {len(unique_selected)}, final_selected: {len(final_selected)}")
            if final_selected:
                logger.info(f"[OSS_FILTER] Task {task_id}: Selected objects (first 5): {final_selected[:5]}")
            else:
                logger.warning(f"[OSS_FILTER] Task {task_id}: final_selected is EMPTY after parsing!")

            # Persist filtered object list to database
            self._persist_filtered_objects(oss_db_path, task_id, final_selected)

            logger.info(f"Task {task_id}: OSS filtering complete. Selected {len(final_selected)} objects.")
            if not final_selected:
                logger.warning(f"Task {task_id}: No objects matched case description in LLM output.")

            combined_reasoning = " | ".join(batch_reasonings) if batch_reasonings else "Streaming filtering completed"

            return {
                "filtered_objects": final_selected,
                "reasoning": combined_reasoning,
                "total_objects": total_objects,
                "selected_count": len(final_selected),
                "model_used": "streaming_llm",
                "streaming_used": True,
                "batches_processed": len(batches),
            }

        except Exception as e:
            logger.error(f"Streaming OSS object filtering failed: {e}", exc_info=True)
            # Fall back to legacy method
            logger.info("Falling back to legacy filtering method")
            return await self._filter_oss_objects_legacy(
                oss_db_path, case_description, max_objects, task_id
            )

    def _get_objects_from_db(self, db_path: str) -> List[Dict[str, Any]]:
        """Read OSS objects from the _oss.db database."""
        if not Path(db_path).exists():
            logger.warning(f"Database file does not exist: {db_path}")
            return []

        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT bucket, key, size, last_modified, storage_class,
                           content_type, owner, etag
                    FROM oss_objects
                    WHERE is_deleted = 0
                    ORDER BY bucket, key
                """)
                rows = cur.fetchall()
                objects = []
                for row in rows:
                    objects.append({
                        "bucket": row["bucket"],
                        "key": row["key"],
                        "size": row["size"] or 0,
                        "last_modified": row["last_modified"],
                        "storage_class": row["storage_class"] or "",
                        "content_type": row["content_type"] or "",
                        "owner": row["owner"] or "",
                        "etag": row["etag"] or "",
                    })
                return objects
        except Exception as e:
            logger.warning(f"Failed to read OSS objects from {db_path}: {e}")
            return []

    def _convert_to_toon_format(self, objects: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Convert OSS objects to TOON streaming format."""
        # TOON schema declaration
        schema = "TOON.schema: bucket | key | size | last_modified | storage_class | content_type | owner"

        # Convert each object to TOON format
        data_lines = []
        for obj in objects:
            # Format timestamp if available
            last_modified = ""
            if obj.get("last_modified"):
                try:
                    last_modified = str(obj["last_modified"])
                except:
                    last_modified = ""

            # Format size
            size = obj.get("size", 0)
            size_str = self._format_size(size) if size else "0"

            line = f"{obj['bucket']} | {obj['key']} | {size_str} | {last_modified} | {obj.get('storage_class', '')} | {obj.get('content_type', '')} | {obj.get('owner', '')}"
            data_lines.append(line)

        return {
            "schema": schema,
            "data_lines": data_lines,
            "total_objects": len(objects),
        }

    def _create_batches(self, data_lines: List[str], batch_size: int) -> List[List[str]]:
        """Split data lines into batches."""
        batches = []
        for i in range(0, len(data_lines), batch_size):
            batches.append(data_lines[i:i + batch_size])
        return batches

    def _build_filter_prompt(
        self,
        case_description: str,
        batch_toon: str,
        batch_number: int,
        total_batches: int,
        max_objects: int,
        already_selected: int,
    ) -> str:
        """Build prompt for batch filtering with TOON format."""
        return f"""你是数字取证专家，正在分析一个涉及OSS对象存储的案件。

## 案情描述
{case_description}

## OSS对象列表（TOON格式 - 第{batch_number}/{total_batches}批）
{batch_toon}

## 任务
从上述OSS对象列表中选择与案情相关的对象。注意：
1. 这是第{batch_number}/{total_batches}批数据
2. 全局最多选择{max_objects}个对象，已选择{already_selected}个
3. 必须严格按照以下JSON格式返回，不要有任何其他文字：

```json
{{"selected_objects": ["对象路径1", "对象路径2", ...], "reasoning": "选择原因说明"}}
```

重要提示：
- selected_objects中只填写对象路径（bucket/key格式），例如：["bucket1/file1.pdf", "bucket2/data/image.jpg"]
- 对象路径必须与TOON格式中bucket和key的组合完全匹配
- reasoning字段简要说明选择这些对象的原因"""

    def _parse_filter_response(
        self,
        response_text: str,
        batch_lines: List[str],
    ) -> Dict[str, Any]:
        """Parse LLM response from TOON batch filtering with robustness."""
        selected_objects = []
        reasoning = ""

        logger.info(f"[PARSE_OSS_FILTER] ===== STARTING PARSE =====")
        logger.info(f"[PARSE_OSS_FILTER] Raw response text (first 500 chars): {response_text[:500]}")
        logger.debug(f"[PARSE_OSS_FILTER] Batch lines count: {len(batch_lines)}")

        try:
            # 1. Pre-process text to find JSON
            text = response_text.strip()
            logger.info(f"[PARSE_OSS_FILTER] After strip, text starts with: {text[:100]}")

            # Extract reasoning from text BEFORE the JSON
            reasoning_prefix = ""
            array_start = text.find('[')
            dict_start = text.find('{')

            if array_start != -1 and (dict_start == -1 or array_start < dict_start):
                # JSON array format - extract text before it as reasoning
                reasoning_prefix = text[:array_start].strip()
                logger.info(f"[PARSE_OSS_FILTER] Found array format, reasoning prefix: {reasoning_prefix[:100]}")
            elif dict_start != -1 and (array_start == -1 or dict_start < array_start):
                # Dict format - extract text before it as reasoning
                reasoning_prefix = text[:dict_start].strip()
                logger.info(f"[PARSE_OSS_FILTER] Found dict format, reasoning prefix: {reasoning_prefix[:100]}")

            # Remove markdown code blocks if present
            if "```" in text:
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
                if json_match:
                    text = json_match.group(1)
                    logger.info(f"[PARSE_OSS_FILTER] Extracted from markdown: {text[:100]}")

            # Find the first '[' or '{' and last ']' or '}'
            start_idx = text.find('[')
            start_brace = text.find('{')
            if start_brace != -1 and (start_idx == -1 or start_brace < start_idx):
                start_idx = start_brace

            end_idx = text.rfind(']')
            end_brace = text.rfind('}')
            if end_brace != -1 and (end_idx == -1 or end_brace > end_idx):
                end_idx = end_brace

            logger.info(f"[PARSE_OSS_FILTER] Found JSON boundaries: start_idx={start_idx}, end_idx={end_idx}")

            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]
                logger.info(f"[PARSE_OSS_FILTER] Extracted JSON: {text[:200]}")
            else:
                logger.warning(f"[PARSE_OSS_FILTER] Could not find JSON boundaries!")

            # 2. Parse JSON
            parsed = json.loads(text)
            logger.info(f"[PARSE_OSS_FILTER] JSON parsed successfully, type={type(parsed).__name__}")

            selected_paths = []
            if isinstance(parsed, list):
                # Format: ["bucket/key1", "bucket/key2"]
                selected_paths = parsed
                reasoning = reasoning_prefix
                logger.info(f"[PARSE_OSS_FILTER] Parsed as list with {len(selected_paths)} items: {selected_paths[:5]}")
                logger.info(f"[PARSE_OSS_FILTER] Reasoning from prefix: {reasoning[:100]}")
            elif isinstance(parsed, dict):
                # Format: {"selected_objects": [...], "reasoning": "..."}
                selected_paths = parsed.get("selected_objects", []) or parsed.get("filtered_objects", [])
                reasoning = parsed.get("reasoning", "") or reasoning_prefix
                logger.info(f"[PARSE_OSS_FILTER] Parsed as dict, selected_objects={len(selected_paths)} items: {selected_paths[:5]}")
                logger.info(f"[PARSE_OSS_FILTER] Reasoning: {reasoning[:100]}")
            else:
                logger.warning(f"[PARSE_OSS_FILTER] Unexpected parsed type: {type(parsed)}")

            # 3. Match against batch lines
            # TOON format: bucket | key | size | ...
            # Build bucket/key combinations from batch
            all_paths_in_batch = []
            for line in batch_lines:
                parts = line.split(" | ")
                if len(parts) >= 2:
                    bucket = parts[0].strip()
                    key = parts[1].strip()
                    object_path = f"{bucket}/{key}"
                    all_paths_in_batch.append(object_path)

            logger.info(f"[PARSE_OSS_FILTER] Batch has {len(all_paths_in_batch)} objects")
            logger.info(f"[PARSE_OSS_FILTER] Sample paths in batch: {all_paths_in_batch[:5]}")
            logger.info(f"[PARSE_OSS_FILTER] LLM returned {len(selected_paths)} paths to match")

            for path in selected_paths:
                if not isinstance(path, str): continue
                path_clean = path.strip().strip('"').strip("'")
                logger.info(f"[PARSE_OSS_FILTER] Trying to match: '{path_clean}'")

                # 1. Exact match in batch
                if path_clean in all_paths_in_batch:
                    selected_objects.append(path_clean)
                    logger.info(f"[PARSE_OSS_FILTER]   ✓ Strategy 1 (exact): '{path_clean}' matched")
                    continue

                # 2. Case-insensitive match
                matching_paths = [p for p in all_paths_in_batch if p.lower() == path_clean.lower()]
                if matching_paths:
                    selected_objects.extend(matching_paths)
                    logger.info(f"[PARSE_OSS_FILTER]   ✓ Strategy 2 (case-insensitive): '{path_clean}' matched {len(matching_paths)} paths")
                    continue

                # 3. Partial path match (case insensitive)
                matching_paths = [p for p in all_paths_in_batch if path_clean.lower() in p.lower()]
                if matching_paths:
                    selected_objects.extend(matching_paths)
                    logger.info(f"[PARSE_OSS_FILTER]   ✓ Strategy 3 (partial): '{path_clean}' matched {len(matching_paths)} paths")
                    continue

                logger.warning(f"[PARSE_OSS_FILTER]   ✗ No match found for: '{path_clean}'")

            logger.info(f"[PARSE_OSS_FILTER] ===== MATCHING COMPLETE =====")
            logger.info(f"[PARSE_OSS_FILTER] Successfully matched {len(selected_objects)} objects from LLM response")

        except Exception as e:
            logger.warning(f"[PARSE_OSS_FILTER] JSON parse failed: {e}")
            logger.warning(f"[PARSE_OSS_FILTER] Response that failed (first 500 chars): {response_text[:500]}")
            logger.info(f"[PARSE_OSS_FILTER] ===== FALLBACK: TEXT PATTERN MATCHING =====")
            # Aggressive fallback: search every object key in the response text
            for line in batch_lines:
                parts = line.split(" | ")
                if len(parts) >= 2:
                    bucket = parts[0].strip()
                    key = parts[1].strip()
                    object_path = f"{bucket}/{key}"
                    # Look for object key as a separate word in the response
                    if re.search(rf'\b{re.escape(key)}\b', response_text) or \
                       re.search(rf'"{re.escape(key)}"', response_text):
                        selected_objects.append(object_path)
                        logger.info(f"[PARSE_OSS_FILTER] Fallback matched: '{key}' -> '{object_path}'")

        # Deduplicate while preserving order
        seen = set()
        unique_objects = []
        for obj in selected_objects:
            if obj not in seen:
                unique_objects.append(obj)
                seen.add(obj)

        logger.info(f"[PARSE_OSS_FILTER] ===== FINAL RESULT =====")
        logger.info(f"[PARSE_OSS_FILTER] Returning {len(unique_objects)} unique objects: {unique_objects[:5]}")
        logger.info(f"[PARSE_OSS_FILTER] Reasoning: {reasoning[:100] if reasoning else 'None'}")
        logger.info(f"[PARSE_OSS_FILTER] ===== PARSE COMPLETE =====")

        return {
            "selected_objects": unique_objects,
            "reasoning": reasoning,
        }

    async def _filter_oss_objects_legacy(
        self,
        oss_db_path: str,
        case_description: str,
        max_objects: int = 200,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Legacy OSS object filtering method (single large prompt).

        NOT RECOMMENDED for large object sets due to context overflow risk.
        """
        # Read object list from database
        all_objects = self._get_objects_from_db(oss_db_path)
        if not all_objects:
            return {"filtered_objects": [], "reasoning": "No OSS objects found in database."}

        # Build a concise object summary for the LLM
        object_summary = self._build_object_summary(all_objects)

        user_prompt = OSS_FILTER_USER_TEMPLATE.format(
            case_description=case_description,
            object_count=len(all_objects),
            object_summary=object_summary,
            max_objects=max_objects,
        )

        try:
            result = await self._llm_service.analyze(
                content=user_prompt,
                model_type="text",
                prompt=user_prompt,
                max_tokens=self.settings.llm_text_max_tokens,
            )

            response_text = result.get("analysis", {}).get("description", "")
            parsed = self._parse_filter_response(response_text, [])

            # Extract task_id from oss_db_path if not provided
            task_id_extracted = "_latest"
            task_match = re.search(r'tasks/([a-f0-9-]+)/', oss_db_path)
            if task_match:
                task_id_extracted = task_match.group(1)

            # Persist filtered object list to database
            self._persist_filtered_objects(oss_db_path, task_id_extracted, parsed["selected_objects"])

            return {
                "filtered_objects": parsed["selected_objects"],
                "reasoning": parsed.get("reasoning", ""),
                "total_objects": len(all_objects),
                "selected_count": len(parsed["selected_objects"]),
                "model_used": result.get("model", ""),
                "streaming_used": False,
            }
        except Exception as e:
            logger.error(f"OSS object filtering failed: {e}", exc_info=True)
            raise

    def _build_object_summary(self, objects: List[Dict[str, Any]]) -> str:
        """Build a concise object list summary for LLM consumption."""
        lines = []
        for obj in objects[:2000]:  # Cap to avoid context overflow
            bucket = obj.get("bucket", "")
            key = obj.get("key", "")
            size = obj.get("size", 0)
            size_str = self._format_size(size) if size else ""
            content_type = obj.get("content_type", "")
            line = f"- {bucket}/{key}"
            if size_str:
                line += f" ({size_str})"
            if content_type:
                line += f" [{content_type}]"
            lines.append(line)

        if len(objects) > 2000:
            lines.append(f"... 及其他 {len(objects) - 2000} 个对象")

        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes) -> str:
        """Format file size to human-readable string."""
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            return ""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.0f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}PB"

    def _persist_filtered_objects(self, db_path: str, task_id: str, filtered_objects: List[str]):
        """Persist the filtered object list to database."""
        self._ensure_oss_analysis_table(db_path)
        import time
        now = int(time.time())
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO oss_analysis
                        (task_id, filtered_objects, created_at, updated_at)
                    VALUES
                        (?, ?, ?, ?)
                """, (task_id, json.dumps(filtered_objects), now, now))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist filtered objects for task {task_id}: {e}")

    def _ensure_oss_analysis_table(self, db_path: str):
        """Ensure oss_analysis table exists."""
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS oss_analysis (
                        task_id TEXT PRIMARY KEY,
                        case_description TEXT,
                        filtered_objects TEXT,
                        case_report TEXT,
                        created_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to create oss_analysis table: {e}")

    def get_filtered_objects_from_db(self, db_path: str, task_id: str = "") -> List[str]:
        """Retrieve the list of case-relevant OSS objects from database."""
        if not db_path:
            return []

        try:
            if not Path(db_path).exists():
                return []

            with sqlite3.connect(db_path, timeout=10) as conn:
                cur = conn.cursor()

                # Get objects from the initial filter list
                cur.execute(
                    "SELECT filtered_objects FROM oss_analysis WHERE task_id = ?",
                    (task_id,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
                return []

        except Exception as e:
            logger.warning(f"Failed to retrieve case-relevant OSS objects: {e}")
        return []
