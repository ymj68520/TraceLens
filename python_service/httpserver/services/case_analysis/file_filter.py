"""
File Filter Module — LLM-driven forensic file filtering.

This module handles file filtering logic, including streaming and legacy methods.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings
from ...prompts import FILE_FILTER_SYSTEM, FILE_FILTER_USER_TEMPLATE, FILE_FILTER_BATCH_ENHANCED_TEMPLATE

logger = logging.getLogger(__name__)


class FileFilter:
    """Handles file filtering operations."""

    def __init__(self, settings: Settings, llm_service, cpp_backend):
        """
        Initialize FileFilter.

        Args:
            settings: Application settings
            llm_service: LLM service for analysis
            cpp_backend: C++ backend service for data access
        """
        self.settings = settings
        self._llm_service = llm_service
        self._cpp_backend = cpp_backend

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
                # Try new path format: .../tasks/<uuid>/files.db
                task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
                if not task_match:
                    # Try legacy format: <task_id>_files.db
                    task_match = re.search(r'(\w+)_files\.db$', files_db_path)

                if not task_match:
                    raise RuntimeError(f"Cannot extract task_id from {files_db_path}")
                task_id = task_match.group(1)

            logger.info(f"[FILE_FILTER] Task {task_id}: Fetching TOON data from {files_db_path}...")
            toon_data = await self._cpp_backend.get_files_toon_stream(
                task_id=task_id,
                batch_size=batch_size,
                include_llm=False,
            )

            schema = toon_data.get("schema", "")
            data_lines = toon_data.get("data_lines", [])
            total_files = toon_data.get("total_files", 0)

            logger.info(f"[FILE_FILTER] Task {task_id}: TOON data received - schema={len(schema)} chars, lines={len(data_lines)}, total_files={total_files}")

            if total_files == 0:
                logger.warning(f"[FILE_FILTER] Task {task_id}: No files found in database!")
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
                logger.info(f"[FILE_FILTER] TOON schema: {schema[:200]}")
                logger.info(f"[FILE_FILTER] TOON sample data (first 3 lines): {batch_lines[:3]}")

                # Build TOON prompt for this batch
                batch_toon = f"{schema}\n" + "\n".join(batch_lines)
                logger.info(f"[FILE_FILTER] Batch TOON data length: {len(batch_toon)} chars")

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
                    logger.info(f"[FILE_FILTER] Batch {batch_idx + 1}: LLM response received, length={len(response_text)} chars")
                    logger.info(f"[FILE_FILTER] Batch {batch_idx + 1}: Full LLM response: {response_text}")
                    logger.debug(f"[FILE_FILTER] Batch {batch_idx + 1}: LLM response preview: {response_text[:500]}...")

                    parsed = self._parse_toon_filter_response(response_text, batch_lines)
                    logger.info(f"[FILE_FILTER] Batch {batch_idx + 1}: Parsed result - selected_files: {len(parsed['selected_files'])}, reasoning: {parsed.get('reasoning', '')[:200]}")

                    # Accumulate selected files
                    all_selected_files.extend(parsed["selected_files"])
                    if parsed.get("reasoning"):
                        batch_reasonings.append(parsed["reasoning"])

                    logger.info(f"[FILE_FILTER] Batch {batch_idx + 1}: parsed {len(parsed['selected_files'])} files, total so far: {len(all_selected_files)}")

                    # Stop if we've reached max_files
                    if len(all_selected_files) >= max_files:
                        logger.info(f"Reached max_files limit ({max_files}), stopping early")
                        break

                except Exception as e:
                    logger.warning(f"Batch {batch_idx + 1} failed: {e}")
                    continue

            # Extract task_id from files_db_path (moved before logging)
            task_id_extracted = "_latest"
            task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
            if task_match:
                task_id_extracted = task_match.group(1)

            # Deduplicate while preserving order
            seen = set()
            unique_selected = []
            for f in all_selected_files:
                if f not in seen:
                    seen.add(f)
                    unique_selected.append(f)

            # Trim to max_files if needed
            final_selected = unique_selected[:max_files]

            logger.info(f"[FILE_FILTER] Task {task_id_extracted}: Before trimming - unique_selected: {len(unique_selected)}, final_selected: {len(final_selected)}")
            if final_selected:
                logger.info(f"[FILE_FILTER] Task {task_id_extracted}: Selected files (first 5): {final_selected[:5]}")
            else:
                logger.warning(f"[FILE_FILTER] Task {task_id_extracted}: final_selected is EMPTY after parsing!")

            # Persist filtered file list to database
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
        """Build prompt for batch filtering with enhanced format."""
        from ...prompts import FILE_FILTER_BATCH_ENHANCED_TEMPLATE

        return FILE_FILTER_BATCH_ENHANCED_TEMPLATE.format(
            case_description=case_description,
            batch_toon=batch_toon,
            batch_number=batch_number,
            total_batches=total_batches,
            max_files=max_files,
            already_selected=already_selected,
        )

    def _parse_toon_filter_response(
        self,
        response_text: str,
        batch_lines: List[str],
    ) -> Dict[str, Any]:
        """Parse LLM response from TOON batch filtering with robustness."""
        selected_files = []
        reasoning = ""

        logger.info(f"[PARSE_FILTER] ===== STARTING PARSE =====")
        logger.info(f"[PARSE_FILTER] Raw response text (first 500 chars): {response_text[:500]}")
        logger.debug(f"[PARSE_FILTER] Batch lines count: {len(batch_lines)}")

        try:
            # 1. Pre-process text to find JSON
            text = response_text.strip()
            logger.info(f"[PARSE_FILTER] After strip, text starts with: {text[:100]}")

            # Extract reasoning from text BEFORE the JSON (for list format responses)
            # The reasoning is usually in the text before the JSON array
            reasoning_prefix = ""
            array_start = text.find('[')
            dict_start = text.find('{')

            if array_start != -1 and (dict_start == -1 or array_start < dict_start):
                # JSON array format - extract text before it as reasoning
                reasoning_prefix = text[:array_start].strip()
                logger.info(f"[PARSE_FILTER] Found array format, reasoning prefix: {reasoning_prefix[:100]}")
            elif dict_start != -1 and (array_start == -1 or dict_start < array_start):
                # Dict format - extract text before it as reasoning (in case reasoning field is missing)
                reasoning_prefix = text[:dict_start].strip()
                logger.info(f"[PARSE_FILTER] Found dict format, reasoning prefix: {reasoning_prefix[:100]}")

            # Remove markdown code blocks if present
            if "```" in text:
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
                if json_match:
                    text = json_match.group(1)
                    logger.info(f"[PARSE_FILTER] Extracted from markdown: {text[:100]}")

            # Find the first '[' or '{' and last ']' or '}'
            start_idx = text.find('[')
            start_brace = text.find('{')
            if start_brace != -1 and (start_idx == -1 or start_brace < start_idx):
                start_idx = start_brace

            end_idx = text.rfind(']')
            end_brace = text.rfind('}')
            if end_brace != -1 and (end_idx == -1 or end_brace > end_idx):
                end_idx = end_brace

            logger.info(f"[PARSE_FILTER] Found JSON boundaries: start_idx={start_idx}, end_idx={end_idx}")

            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]
                logger.info(f"[PARSE_FILTER] Extracted JSON: {text[:200]}")
            else:
                logger.warning(f"[PARSE_FILTER] Could not find JSON boundaries!")

            # 2. Parse JSON
            parsed = json.loads(text)
            logger.info(f"[PARSE_FILTER] JSON parsed successfully, type={type(parsed).__name__}")

            selected_paths = []
            if isinstance(parsed, list):
                # Format: ["path1", "path2"]
                selected_paths = parsed
                # Use the extracted reasoning prefix for list format
                reasoning = reasoning_prefix
                logger.info(f"[PARSE_FILTER] Parsed as list with {len(selected_paths)} items: {selected_paths[:5]}")
                logger.info(f"[PARSE_FILTER] Reasoning from prefix: {reasoning[:100]}")
            elif isinstance(parsed, dict):
                # Format: {"selected_files": [...], "reasoning": "..."}
                selected_paths = parsed.get("selected_files", []) or parsed.get("filtered_files", [])
                reasoning = parsed.get("reasoning", "") or reasoning_prefix
                logger.info(f"[PARSE_FILTER] Parsed as dict, selected_files={len(selected_paths)} items: {selected_paths[:5]}")
                logger.info(f"[PARSE_FILTER] Reasoning: {reasoning[:100]}")
            else:
                logger.warning(f"[PARSE_FILTER] Unexpected parsed type: {type(parsed)}")

            # 3. Match against batch lines
            # TOON format: name | path | size | category | ...
            # We need the full path (parts[1]) for extraction, not just the name (parts[0])
            all_paths_in_batch = []
            name_to_path_map = {}
            for line in batch_lines:
                parts = line.split(" | ")
                if len(parts) >= 2:
                    name = parts[0].strip()
                    path = parts[1].strip()
                    all_paths_in_batch.append(path)
                    name_to_path_map[name] = path

            logger.info(f"[PARSE_FILTER] Batch has {len(all_paths_in_batch)} files, {len(name_to_path_map)} names")
            logger.info(f"[PARSE_FILTER] Sample names in batch: {list(name_to_path_map.keys())[:5]}")
            logger.info(f"[PARSE_FILTER] LLM returned {len(selected_paths)} paths to match")

            for path in selected_paths:
                if not isinstance(path, str): continue
                path_clean = path.strip().strip('"').strip("'")
                logger.info(f"[PARSE_FILTER] Trying to match: '{path_clean}'")

                # 1. Direct name-to-path lookup (most efficient)
                if path_clean in name_to_path_map:
                    matched_path = name_to_path_map[path_clean]
                    selected_files.append(matched_path)
                    logger.info(f"[PARSE_FILTER]   ✓ Strategy 1 (direct name): '{path_clean}' -> '{matched_path}'")
                    continue

                # 2. Exact match in batch (full path)
                matching_paths = [p for p in all_paths_in_batch if p == path_clean]
                if matching_paths:
                    selected_files.extend(matching_paths)
                    logger.info(f"[PARSE_FILTER]   ✓ Strategy 2 (exact path): '{path_clean}' matched {len(matching_paths)} paths")
                    continue

                # 3. Filename match (LLM returned just filename)
                matching_paths = [p for p in all_paths_in_batch if Path(p).name == path_clean]
                if matching_paths:
                    selected_files.extend(matching_paths)
                    logger.info(f"[PARSE_FILTER]   ✓ Strategy 3 (filename): '{path_clean}' matched {len(matching_paths)} paths")
                    continue

                # 4. Partial path match (case insensitive)
                matching_paths = [p for p in all_paths_in_batch if path_clean.lower() in p.lower()]
                if matching_paths:
                    selected_files.extend(matching_paths)
                    logger.info(f"[PARSE_FILTER]   ✓ Strategy 4 (partial): '{path_clean}' matched {len(matching_paths)} paths")
                    continue

                # 5. Check if LLM returned filename that matches any name in our map
                for name, full_path in name_to_path_map.items():
                    if path_clean.lower() == name.lower() or path_clean.lower() in name.lower():
                        if full_path not in selected_files:
                            selected_files.append(full_path)
                        logger.info(f"[PARSE_FILTER]   ✓ Strategy 5 (reverse lookup): '{path_clean}' -> '{full_path}' (matched name: '{name}')")
                        break
                else:
                    logger.warning(f"[PARSE_FILTER]   ✗ No match found for: '{path_clean}'")

            logger.info(f"[PARSE_FILTER] ===== MATCHING COMPLETE =====")
            logger.info(f"[PARSE_FILTER] Successfully matched {len(selected_files)} files from LLM response")

        except Exception as e:
            logger.warning(f"[PARSE_FILTER] JSON parse failed: {e}")
            logger.warning(f"[PARSE_FILTER] Response that failed (first 500 chars): {response_text[:500]}")
            logger.info(f"[PARSE_FILTER] ===== FALLBACK: TEXT PATTERN MATCHING =====")
            # Aggressive fallback: search every filename in the response text
            for line in batch_lines:
                parts = line.split(" | ")
                if len(parts) >= 2:
                    full_path = parts[1].strip()  # Use full path, not name
                    filename = Path(full_path).name
                    # Look for filename as a separate word in the response
                    if re.search(rf'\b{re.escape(filename)}\b', response_text) or \
                       re.search(rf'"{re.escape(filename)}"', response_text):
                        selected_files.append(full_path)
                        logger.info(f"[PARSE_FILTER] Fallback matched: '{filename}' -> '{full_path}'")

        # Deduplicate while preserving order
        seen = set()
        unique_files = []
        for f in selected_files:
            if f not in seen:
                unique_files.append(f)
                seen.add(f)

        logger.info(f"[PARSE_FILTER] ===== FINAL RESULT =====")
        logger.info(f"[PARSE_FILTER] Returning {len(unique_files)} unique files: {unique_files[:5]}")
        logger.info(f"[PARSE_FILTER] Reasoning: {reasoning[:100] if reasoning else 'None'}")
        logger.info(f"[PARSE_FILTER] ===== PARSE COMPLETE =====")

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

    def _get_file_list_from_db(self, db_path: str) -> List[Dict[str, str]]:
        """Read file list from the _files.db."""
        import sqlite3
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

            # Extract JSON boundaries
            start_idx = text.find('[')
            start_brace = text.find('{')
            if start_brace != -1 and (start_idx == -1 or start_brace < start_idx):
                start_idx = start_brace

            end_idx = text.rfind(']')
            end_brace = text.rfind('}')
            if end_brace != -1 and (end_idx == -1 or end_brace > end_idx):
                end_idx = end_brace

            # Extract reasoning prefix before JSON
            reasoning_prefix = ""
            if start_idx != -1:
                reasoning_prefix = text[:start_idx].strip()

            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]

            parsed = json.loads(text)

            # Handle both dict and list formats
            if isinstance(parsed, dict):
                selected = parsed.get("selected_files", []) or parsed.get("filtered_files", [])
                reasoning = parsed.get("reasoning", "") or reasoning_prefix
            elif isinstance(parsed, list):
                selected = parsed
                reasoning = reasoning_prefix
            else:
                selected = []
                reasoning = reasoning_prefix

            # Validate paths against actual file list
            valid_paths = [p for p in selected if p in all_paths]
            logger.info(f"[PARSE_FILTER_LEGACY] Parsed {len(selected)} files, {len(valid_paths)} valid")
            return {"selected_files": valid_paths, "reasoning": reasoning}
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Could not parse LLM filter response as JSON: {e}, falling back to line parsing")
            # Fallback: extract file paths from text
            selected = []
            for line in response_text.split("\n"):
                line = line.strip().strip("-").strip("*").strip()
                if line in all_paths:
                    selected.append(line)
            return {"selected_files": selected, "reasoning": response_text[:500]}

    def _persist_filtered_files(self, db_path: str, task_id: str, filtered_files: List[str]):
        """Persist the filtered file list to database using the correct task_id."""
        from .db_utils import persist_filtered_files
        persist_filtered_files(db_path, task_id, filtered_files)
