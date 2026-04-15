# python_service/httpserver/services/case_analysis/file_matcher.py
"""
File Matcher - intelligent file matching with duplicate handling.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result from file matching."""
    files: List[str] = field(default_factory=list)
    duplicates_resolved: int = 0
    no_matches: List[str] = field(default_factory=list)
    confidence_scores: Dict[str, float] = field(default_factory=dict)


class FileMatcher:
    """
    Intelligently match LLM-returned file names to actual files.

    Features:
    - Composite scoring for duplicate resolution
    - Path semantic relevance
    - Fuzzy matching for near-misses
    """

    DEFAULT_WEIGHTS = {
        "path_semantic": 0.4,
        "freshness": 0.3,
        "size": 0.2,
        "depth": 0.1,
    }

    def __init__(self, settings=None):
        self.settings = settings
        self.weights = self._load_weights()

    def _load_weights(self) -> Dict[str, float]:
        """Load scoring weights from settings or defaults."""
        if self.settings and hasattr(self.settings, 'llm_filter_config'):
            config = self.settings.llm_filter_config
            return {
                "path_semantic": config.score_weight_path_semantic,
                "freshness": config.score_weight_freshness,
                "size": config.score_weight_size,
                "depth": config.score_weight_depth,
            }
        return self.DEFAULT_WEIGHTS.copy()

    def match_files(
        self,
        llm_items: List[str],
        batch_files: List[Dict[str, Any]],
        case_context: Optional[str] = None
    ) -> MatchResult:
        """
        Match LLM items to actual files with intelligent duplicate resolution.

        Args:
            llm_items: File names/paths from LLM
            batch_files: Actual files in the batch
            case_context: Optional case description for semantic scoring

        Returns:
            MatchResult with selected files and metadata
        """
        result = MatchResult()

        # Build lookup structures
        name_to_paths: Dict[str, List[Dict[str, Any]]] = {}
        path_lookup: Dict[str, Dict[str, Any]] = {}

        for f in batch_files:
            path = f.get("path", "")
            name = f.get("name", "")
            if path:
                path_lookup[path] = f
            if name:
                if name not in name_to_paths:
                    name_to_paths[name] = []
                name_to_paths[name].append(f)

        # Match each LLM item
        for item in llm_items:
            item_clean = item.strip().strip('"').strip("'")

            # Direct path match
            if item_clean in path_lookup:
                result.files.append(item_clean)
                result.confidence_scores[item_clean] = 1.0
                continue

            # Name match - handle duplicates
            if item_clean in name_to_paths:
                candidates = name_to_paths[item_clean]

                if len(candidates) == 1:
                    selected = candidates[0]["path"]
                    result.files.append(selected)
                    result.confidence_scores[selected] = 1.0
                else:
                    # Multiple duplicates - use composite scoring
                    selected = self._resolve_duplicate(
                        item_clean, candidates, case_context
                    )
                    result.files.append(selected["path"])
                    result.duplicates_resolved += 1
                    result.confidence_scores[selected["path"]] = selected.get("_score", 0.5)
                continue

            # No match found
            result.no_matches.append(item_clean)
            logger.debug(f"[MATCHER] No match found for: {item_clean}")

        logger.info(
            f"[MATCHER] Matched {len(result.files)} files, "
            f"resolved {result.duplicates_resolved} duplicates, "
            f"{len(result.no_matches)} unmatched"
        )

        return result

    def _resolve_duplicate(
        self,
        name: str,
        candidates: List[Dict[str, Any]],
        case_context: Optional[str]
    ) -> Dict[str, Any]:
        """Resolve duplicate files using composite scoring."""
        best_candidate = None
        best_score = -1.0

        for candidate in candidates:
            score = self._calculate_relevance_score(candidate, case_context)
            candidate["_score"] = score

            if score > best_score:
                best_score = score
                best_candidate = candidate

            logger.debug(
                f"[MATCHER] Duplicate '{name}': {candidate['path']} "
                f"score={score:.3f}"
            )

        if best_candidate:
            logger.info(
                f"[MATCHER] Selected '{best_candidate['path']}' for '{name}' "
                f"(score={best_score:.3f})"
            )

        return best_candidate

    def _calculate_relevance_score(
        self,
        file: Dict[str, Any],
        case_context: Optional[str]
    ) -> float:
        """Calculate composite relevance score for a file."""
        scores = {
            "path_semantic": self._score_path_semantic(file, case_context),
            "freshness": self._score_freshness(file),
            "size": self._score_size(file),
            "depth": self._score_depth(file),
        }

        # Weighted sum
        total = sum(
            scores[key] * self.weights[key]
            for key in scores
        )

        return max(0.0, min(1.0, total))

    def _score_path_semantic(self, file: Dict[str, Any], case_context: Optional[str]) -> float:
        """Score path semantic relevance to case context."""
        if not case_context:
            return 0.5

        path = file.get("path", "").lower()
        case_lower = case_context.lower()

        case_keywords = re.findall(r'\w+', case_lower)

        matches = 0
        for keyword in case_keywords:
            if keyword in path:
                matches += 1

        if not case_keywords:
            return 0.5

        return min(1.0, matches / max(len(case_keywords), 1))

    def _score_freshness(self, file: Dict[str, Any]) -> float:
        """Score based on file modification time."""
        mtime = file.get("mtime", 0)

        if not mtime:
            return 0.5

        try:
            mtime_int = int(mtime)
            mtime_dt = datetime.fromtimestamp(mtime_int)
            days_old = (datetime.now() - mtime_dt).days

            if days_old < 1:
                return 1.0
            elif days_old < 7:
                return 0.8
            elif days_old < 30:
                return 0.6
            elif days_old < 90:
                return 0.4
            elif days_old < 365:
                return 0.2
            else:
                return 0.1
        except (ValueError, OSError):
            return 0.5

    def _score_size(self, file: Dict[str, Any]) -> float:
        """Score based on file size."""
        size = file.get("size", 0)

        if not size:
            return 0.5

        try:
            size_int = int(size)

            if size_int < 1024:
                return 0.2
            elif size_int < 102400:
                return 0.4
            elif size_int < 1048576:
                return 0.6
            elif size_int < 10485760:
                return 0.8
            else:
                return 1.0
        except (ValueError, TypeError):
            return 0.5

    def _score_depth(self, file: Dict[str, Any]) -> float:
        """Score based on path depth."""
        path = file.get("path", "")

        try:
            depth = len(Path(path).parts)

            if depth <= 2:
                return 1.0
            elif depth <= 4:
                return 0.8
            elif depth <= 6:
                return 0.6
            elif depth <= 8:
                return 0.4
            else:
                return 0.2
        except Exception:
            return 0.5
