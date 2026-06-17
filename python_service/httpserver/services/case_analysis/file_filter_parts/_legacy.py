"""Part of FileFilter (split for maintainability).

This mixin contributes a group of methods to the FileFilter class declared in
services/case_analysis/file_filter.py.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FileFilterLegacyMixin:
    """Legacy (pre-streaming) filter-response parsers and filter path."""

    def _parse_toon_filter_response_legacy(
        self,
        response_text: str,
        batch_lines: List[str],
        batch_files: List[Dict],
    ) -> Dict[str, Any]:
        """Legacy parsing implementation (preserved from original)."""
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

