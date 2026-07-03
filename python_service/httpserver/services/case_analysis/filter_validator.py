"""
Filter Result Validator - validate and repair parsing results.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm_response_parser import ParseResult

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result from validation."""
    items: List[str] = field(default_factory=list)
    is_valid: bool = True
    repairs_made: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence: float = 1.0


class FilterResultValidator:
    """
    Validate and repair filter results.

    Handles edge cases:
    - Invalid LLM responses
    - Ambiguous path matches
    - Empty results
    - Truncated results
    """

    def __init__(self, settings=None):
        self.settings = settings
        # Access confidence threshold from nested LLMFilterConfig
        if settings and hasattr(settings, 'llm_filter_config'):
            self.confidence_threshold = settings.llm_filter_config.match_confidence_threshold
        else:
            self.confidence_threshold = 0.3

    def validate_and_repair(
        self,
        parse_result: ParseResult,
        batch_files: List[Dict[str, Any]],
        max_files: int
    ) -> ValidationResult:
        """Validate and repair parsing result."""
        result = ValidationResult(
            items=parse_result.selected_files.copy(),
            confidence=parse_result.confidence
        )

        # Check if result is empty
        if not parse_result.selected_files and not parse_result.raw_items:
            result.is_valid = False
            result.warnings.append("No files selected from LLM response")
            return result

        # Check confidence threshold (but still return items for fallback)
        # IMPORTANT: Don't return early - let the matching logic try its best
        if parse_result.confidence < self.confidence_threshold:
            result.is_valid = False
            result.warnings.append(
                f"Low confidence: {parse_result.confidence:.2f} < {self.confidence_threshold}"
            )
            # DO NOT RETURN HERE - continue to try matching the items we have
            logger.warning(f"[VALIDATOR] Low confidence {parse_result.confidence:.2f}, but will try matching {len(result.items)} items")

        # Trim to max_files
        if len(result.items) > max_files:
            original_count = len(result.items)
            result.items = result.items[:max_files]
            result.repairs_made.append(
                f"Trimmed from {original_count} to {max_files} files"
            )

        # Validate all items exist in batch
        validated_items = []
        batch_paths = {f.get("path", "") for f in batch_files}

        for item in result.items:
            if item in batch_paths:
                validated_items.append(item)
            else:
                result.warnings.append(f"Item not in batch: {item}")

        if len(validated_items) < len(result.items):
            result.repairs_made.append(
                f"Removed {len(result.items) - len(validated_items)} invalid items"
            )
            result.items = validated_items

        # Mark as valid only if we still have items AND confidence met the
        # threshold. Items are kept regardless (callers may still match them as a
        # fallback), but a low-confidence result must not report itself valid.
        result.is_valid = (len(result.items) > 0) and \
            (parse_result.confidence >= self.confidence_threshold)

        return result

    def handle_invalid_response(
        self,
        response_text: str,
        batch_files: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Handle completely invalid LLM responses."""
        result = ValidationResult(is_valid=False)

        logger.warning("[VALIDATOR] Attempting to repair invalid response")

        # Strategy 1: Aggressive regex extract
        extracted = self._aggressive_regex_extract(response_text, batch_files)
        if extracted:
            result.items = extracted
            result.is_valid = True
            result.repairs_made.append("Recovered via regex extraction")
            result.confidence = 0.4
            return result

        # Strategy 2: Fuzzy matching
        fuzzy = self._fuzzy_match(response_text, batch_files)
        if fuzzy:
            result.items = fuzzy
            result.is_valid = True
            result.repairs_made.append("Recovered via fuzzy matching")
            result.confidence = 0.3
            return result

        # Strategy 3: Return empty
        result.warnings.append("Could not extract any files from response")
        return result

    def _aggressive_regex_extract(
        self,
        text: str,
        batch_files: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract filenames using aggressive regex patterns."""
        batch_names = {f.get("name", "") for f in batch_files}
        batch_paths = {f.get("path", "") for f in batch_files}

        found = []

        # Pattern 1: Filenames in quotes
        for name in batch_names:
            if re.search(rf'\b{re.escape(name)}\b', text):
                path = self._find_path_for_name(name, batch_files)
                if path:
                    found.append(path)

        # Pattern 2: Paths in quotes
        for path in batch_paths:
            if re.search(rf'{re.escape(path)}', text):
                found.append(path)

        return found

    def _fuzzy_match(
        self,
        text: str,
        batch_files: List[Dict[str, Any]]
    ) -> List[str]:
        """Fuzzy match based on partial strings."""
        found = []
        text_lower = text.lower()

        for f in batch_files:
            name = f.get("name", "").lower()
            path = f.get("path", "").lower()

            # Check if filename is in text
            if name and name in text_lower:
                found.append(f["path"])
                continue

            # Check if path is in text
            if path and path in text_lower:
                found.append(f["path"])
                continue

            # Check if extension is mentioned (e.g., "PDF documents" matches ".pdf")
            if name and "." in name:
                ext = name.rsplit(".", 1)[-1].lower()
                # Match if extension word appears in text (e.g., "pdf" in "PDF documents")
                if ext and ext in text_lower:
                    found.append(f["path"])

        return found

    def _find_path_for_name(
        self,
        name: str,
        batch_files: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Find path for given filename."""
        for f in batch_files:
            if f.get("name", "") == name:
                return f.get("path")
        return None
