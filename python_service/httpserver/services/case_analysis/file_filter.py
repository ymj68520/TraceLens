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
from .llm_response_parser import LLMResponseParser
from .file_matcher import FileMatcher
from .filter_validator import FilterResultValidator
from .concurrent_filter import FilterLockManager

logger = logging.getLogger(__name__)



from .file_filter_parts import FileFilterLegacyMixin


class FileFilter(FileFilterLegacyMixin):
    """Filters files by case relevance using LLM.

    NOTE: legacy (pre-streaming) response parsers live in FileFilterLegacyMixin
    (file_filter_parts/_legacy.py). Public surface unchanged.
    """

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

        # Initialize enhanced components
        self._parser = LLMResponseParser(settings)
        self._matcher = FileMatcher(settings)
        self._validator = FilterResultValidator(settings)
        self._lock_manager = FilterLockManager.instance() if settings else None

    async def filter_files_by_case(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int = 200,
        batch_size: int = 50,
        use_streaming: bool = True,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Select files for case analysis.

        Dispatches on settings.file_filter_mode:
        - 'deterministic' (default): read all paths from the C++-filtered
          files.db. No LLM, fully reproducible.
        - 'llm': legacy LLM selection by case_description.
        """
        mode = getattr(self.settings, "file_filter_mode", "deterministic")
        if mode != "llm":
            return await self._filter_files_deterministic(
                files_db_path, max_files, task_id
            )

        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # If streaming is disabled, fall back to old method
        if not use_streaming:
            return await self._filter_files_by_case_legacy(
                files_db_path, case_description, max_files, task_id
            )

        # Extract task_id if not provided
        if not task_id:
            task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
            task_id = task_match.group(1) if task_match else "_latest"

        # Use concurrent lock if enabled
        if self._lock_manager and hasattr(self.settings, 'llm_filter_config') and self.settings.llm_filter_config.enable_concurrent_lock:
            return await self._lock_manager.filter_with_lock(
                task_id,
                self._do_filter_files_by_case,
                files_db_path,
                case_description,
                max_files,
                batch_size,
                use_streaming,
            )
        else:
            return await self._do_filter_files_by_case(
                files_db_path,
                case_description,
                max_files,
                batch_size,
                use_streaming,
            )

    async def _filter_files_deterministic(
        self,
        files_db_path: str,
        max_files: int,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic file selection: read all paths from files.db.

        files.db is already the product of the C++ FileFilter (scenario profile
        applied at task creation). This method performs NO LLM call and NO
        rule-based filtering - it selects every file the C++ filter kept, so the
        selection is reproducible across runs.
        """
        records = self._get_file_list_from_db(files_db_path)
        paths = sorted({r.get("path", "") for r in records if r.get("path")})
        total_files = len(paths)

        cap = int(getattr(self.settings, "filter_max_files", 0) or 0)
        if cap > 0:
            selected = paths[:cap]
            logger.info(
                f"[FILE_FILTER] Deterministic cap applied: {len(selected)}/{total_files} "
                f"(filter_max_files={cap})"
            )
        else:
            selected = paths

        if max_files and max_files > 0:
            logger.info(
                f"[FILE_FILTER] max_files={max_files} ignored in deterministic mode; "
                f"using settings.filter_max_files={cap}"
            )

        resolved_task_id = task_id or "_latest"
        self._persist_filtered_files(files_db_path, resolved_task_id, selected)

        return {
            "filtered_files": selected,
            "reasoning": f"Deterministic selection from C++-filtered files.db ({total_files} files)",
            "total_files": total_files,
            "selected_count": len(selected),
            "model_used": "deterministic_cpp_filter",
            "streaming_used": False,
        }

    async def _do_filter_files_by_case(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int,
        batch_size: int,
        use_streaming: bool,
    ) -> Dict[str, Any]:
        """Internal filtering method."""
        if not use_streaming:
            return await self._filter_files_by_case_legacy(
                files_db_path, case_description, max_files
            )

        return await self._filter_files_by_case_streaming(
            files_db_path, case_description, max_files, batch_size
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
                logger.warning(f"[FILE_FILTER] Task {task_id_extracted}: This will cause extraction and analysis steps to be SKIPPED!")

            # Persist filtered file list to database
            self._persist_filtered_files(files_db_path, task_id_extracted, final_selected)
            logger.info(f"[FILE_FILTER] Task {task_id_extracted}: Persisted {len(final_selected)} filtered files to database")

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
        """Parse LLM response using enhanced pipeline with fallback."""

        # Build batch_files dict for matching
        batch_files = []
        for line in batch_lines:
            parts = line.split(" | ")
            if len(parts) >= 2:
                batch_files.append({
                    "name": parts[0].strip(),
                    "path": parts[1].strip(),
                    "size": int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else 0,
                    "category": parts[3] if len(parts) > 3 else "",
                })

        # Try enhanced pipeline
        try:
            logger.info("[ENHANCED_PARSE] Using new parser pipeline")

            # Step 1: Parse response
            parse_result = self._parser.parse_filter_response(
                response_text, batch_files
            )

            logger.info(f"[ENHANCED_PARSE] Parse result: {len(parse_result.selected_files)} files selected, confidence={parse_result.confidence:.2f}")

            # Step 2: Validate and repair
            validated = self._validator.validate_and_repair(
                parse_result, batch_files, max_files=1000
            )

            logger.info(f"[ENHANCED_PARSE] Validation result: is_valid={validated.is_valid}, items={len(validated.items)}")

            # CRITICAL FIX: If validation failed and we have no items, fall back to legacy
            if not validated.is_valid and len(validated.items) == 0:
                logger.warning("[ENHANCED_PARSE] Validation failed with no items, falling back to legacy parser")
                return self._parse_toon_filter_response_legacy(
                    response_text, batch_lines, batch_files
                )

            # Step 3: Match files (handles duplicates)
            matched = self._matcher.match_files(
                validated.items, batch_files, ""
            )

            logger.info(f"[ENHANCED_PARSE] Pipeline completed: {len(matched.files)} files, {matched.duplicates_resolved} duplicates resolved")

            # Additional fallback: if no files matched, try legacy
            if len(matched.files) == 0:
                logger.warning("[ENHANCED_PARSE] No files matched after validation, falling back to legacy parser")
                return self._parse_toon_filter_response_legacy(
                    response_text, batch_lines, batch_files
                )

            return {
                "selected_files": matched.files,
                "reasoning": parse_result.reasoning,
                "confidence": parse_result.confidence,
                "duplicates_resolved": matched.duplicates_resolved,
            }

        except Exception as e:
            logger.warning(f"[ENHANCED_PARSE] Failed: {e}, using legacy parser")
            # Fall back to legacy implementation
            return self._parse_toon_filter_response_legacy(
                response_text, batch_lines, batch_files
            )

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

    def _persist_filtered_files(self, db_path: str, task_id: str, filtered_files: List[str]):
        """Persist the filtered file list to database using the correct task_id."""
        from .db_utils import persist_filtered_files
        persist_filtered_files(db_path, task_id, filtered_files)

