"""
LLM Response Parser - robust parsing of various LLM response formats.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result from parsing LLM filter response."""

    selected_files: List[str] = field(default_factory=list)
    raw_items: List[str] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0
    repair_actions: List[str] = field(default_factory=list)


@dataclass
class ParsedItems:
    """Intermediate parsed items from a single JSON."""

    items: List[str] = field(default_factory=list)
    reasoning: str = ""


class LLMResponseParser:
    """
    Parse LLM responses into standardized file selection results.

    Handles various formats:
    - JSON with/without markdown code blocks
    - Different field names (selected_files, filtered_files, files)
    - Array or dict format
    - Text with embedded JSON
    """

    # Supported field names for file list
    FILE_FIELD_NAMES = ["selected_files", "filtered_files", "files"]

    def __init__(self, settings=None):
        """
        Initialize parser.

        Args:
            settings: Optional application settings
        """
        self.settings = settings

    def parse_filter_response(
        self,
        response_text: str,
        batch_files: List[Dict[str, Any]]
    ) -> ParseResult:
        """
        Parse LLM response into file selection result.

        Args:
            response_text: Raw LLM response text
            batch_files: List of file dicts in the batch (for validation)

        Returns:
            ParseResult with matched files and metadata
        """
        logger.debug(f"[PARSER] Parsing response ({len(response_text)} chars)")

        result = ParseResult()

        # Extract all possible JSON blocks
        json_blocks = self._extract_json_blocks(response_text)

        if not json_blocks:
            logger.warning("[PARSER] No JSON blocks found, trying fallback")
            return self._fallback_parse(response_text, batch_files)

        # Try parsing each JSON block
        for idx, json_str in enumerate(json_blocks):
            logger.debug(f"[PARSER] Attempting JSON block {idx + 1}/{len(json_blocks)}")

            try:
                parsed = self._parse_single_json(json_str)

                if parsed.items:
                    result.raw_items.extend(parsed.items)
                    if parsed.reasoning and not result.reasoning:
                        result.reasoning = parsed.reasoning

                    logger.info(f"[PARSER] Parsed {len(parsed.items)} items from block {idx + 1}")

            except Exception as e:
                logger.warning(f"[PARSER] Failed to parse JSON block {idx + 1}: {e}")
                result.repair_actions.append(f"JSON block {idx + 1} parse failed: {str(e)[:50]}")

        # Validate items against batch files
        if result.raw_items:
            result.selected_files = self._validate_and_match(
                result.raw_items, batch_files
            )
            result.confidence = min(1.0, len(result.selected_files) / max(len(result.raw_items), 1))
        else:
            # Try aggressive fallback
            logger.warning("[PARSER] No items parsed, trying aggressive fallback")
            result = self._fallback_parse(response_text, batch_files)

        logger.info(
            f"[PARSER] Final result: {len(result.selected_files)} files, "
            f"confidence={result.confidence:.2f}"
        )

        return result

    def _extract_json_blocks(self, text: str) -> List[str]:
        """
        Extract all possible JSON blocks from text.

        Handles:
        - Markdown code blocks (```json ... ```)
        - Standalone JSON objects
        - JSON arrays
        - Embedded JSON in text

        Args:
            text: Input text

        Returns:
            List of JSON string candidates
        """
        json_blocks = []

        # Remove extra whitespace
        text = text.strip()

        # Try markdown code blocks first
        markdown_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        for match in re.finditer(markdown_pattern, text):
            json_blocks.append(match.group(1).strip())

        if json_blocks:
            logger.debug(f"[EXTRACT] Found {len(json_blocks)} markdown JSON blocks")
            return json_blocks

        # Find JSON boundaries
        start_idx = self._find_json_start(text)
        end_idx = self._find_json_end(text)

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_candidate = text[start_idx:end_idx + 1]
            json_blocks.append(json_candidate)
            logger.debug("[EXTRACT] Found JSON by boundary detection")

        return json_blocks

    def _find_json_start(self, text: str) -> int:
        """Find start of JSON (object or array)."""
        obj_start = text.find('{')
        arr_start = text.find('[')

        if obj_start == -1:
            return arr_start
        if arr_start == -1:
            return obj_start
        return min(obj_start, arr_start)

    def _find_json_end(self, text: str) -> int:
        """Find end of JSON (matching brace/bracket)."""
        # Simplified: find last closing bracket/brace
        obj_end = text.rfind('}')
        arr_end = text.rfind(']')

        if obj_end == -1:
            return arr_end
        if arr_end == -1:
            return obj_end
        return max(obj_end, arr_end)

    def _parse_single_json(self, json_str: str) -> ParsedItems:
        """
        Parse a single JSON string.

        Handles both object and array formats.

        Args:
            json_str: JSON string to parse

        Returns:
            ParsedItems with extracted items and reasoning

        Raises:
            json.JSONDecodeError: If JSON is invalid
        """
        parsed = json.loads(json_str)

        items = []
        reasoning = ""

        if isinstance(parsed, dict):
            # Try each supported field name
            for field_name in self.FILE_FIELD_NAMES:
                if field_name in parsed:
                    items = parsed[field_name]
                    if not isinstance(items, list):
                        items = [items] if items else []
                    break

            # Extract reasoning
            reasoning = parsed.get("reasoning", "")

        elif isinstance(parsed, list):
            items = parsed

        # Ensure items are strings
        items = [str(item) for item in items if item]

        return ParsedItems(items=items, reasoning=reasoning)

    def _validate_and_match(
        self,
        raw_items: List[str],
        batch_files: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Validate parsed items against actual batch files.

        Args:
            raw_items: Parsed file names/paths from LLM
            batch_files: Actual files in the batch

        Returns:
            List of validated full paths
        """
        validated = []

        # Build lookup structures
        all_paths = [f.get("path", "") for f in batch_files]
        name_to_paths: Dict[str, List[str]] = {}

        for f in batch_files:
            path = f.get("path", "")
            name = f.get("name", "")
            if name and path:
                if name not in name_to_paths:
                    name_to_paths[name] = []
                name_to_paths[name].append(path)

        for item in raw_items:
            item_clean = item.strip().strip('"').strip("'")

            # Exact path match
            if item_clean in all_paths:
                validated.append(item_clean)
                continue

            # Name match (handle duplicates later in FileMatcher)
            if item_clean in name_to_paths:
                # For now, take first match (FileMatcher will deduplicate)
                validated.extend(name_to_paths[item_clean])
                continue

            logger.debug(f"[VALIDATE] Item '{item_clean}' not found in batch")

        return validated

    def _fallback_parse(
        self,
        response_text: str,
        batch_files: List[Dict[str, Any]]
    ) -> ParseResult:
        """
        Fallback parsing when JSON extraction fails.

        Strategies:
        1. Extract quoted strings
        2. Extract list items
        3. Search for file extensions

        Args:
            response_text: Raw LLM response
            batch_files: Actual files in batch

        Returns:
            ParseResult with best-effort extraction
        """
        result = ParseResult()
        result.repair_actions.append("Used fallback parsing")

        # Strategy 1: Extract quoted filenames
        quoted_pattern = r'"([^"]+\.\w+)"'
        quoted_matches = re.findall(quoted_pattern, response_text)

        # Strategy 2: Extract list items
        list_pattern = r'^[\s*-]+([^\s]+\.\w+)'
        list_matches = re.findall(list_pattern, response_text, re.MULTILINE)

        all_candidates = quoted_matches + list_matches

        # Validate candidates
        if all_candidates:
            result.selected_files = self._validate_and_match(
                all_candidates, batch_files
            )
            result.raw_items = all_candidates

            if result.selected_files:
                result.confidence = 0.5
                result.repair_actions.append("Extracted files via regex fallback")
                logger.info(f"[FALLBACK] Found {len(result.selected_files)} files")
            else:
                # Candidates found but none validated
                result.confidence = 0.1
        else:
            # No candidates found at all
            result.confidence = 0.0

        return result
