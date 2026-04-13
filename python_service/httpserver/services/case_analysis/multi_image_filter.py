"""
MultiImageFilter — LLM-driven file filtering across multiple disk images.

Extends the single-image FileFilter to aggregate file lists from N _files.db
databases, deduplicate across images (by full path), then run the same
streaming LLM batch-filter pipeline used for single-image analysis.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .file_filter import FileFilter
from .llm_response_parser import LLMResponseParser
from .file_matcher import FileMatcher
from .filter_validator import FilterResultValidator
from ...config import Settings

logger = logging.getLogger(__name__)


class MultiImageFilter(FileFilter):
    """Aggregates file lists from multiple images before LLM filtering."""

    def __init__(self, settings: Settings):
        """Initialize multi-image filter with enhanced components."""
        super().__init__(settings)
        self._parser = LLMResponseParser(settings)
        self._matcher = FileMatcher(settings)
        self._validator = FilterResultValidator(settings)

    # ── Public API ────────────────────────────────────────────────────────────

    async def filter_files_multi(
        self,
        files_db_paths: List[str],
        case_description: str,
        max_files: int = 400,
        batch_size: int = 50,
        task_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Filter files across multiple _files.db databases.

        Returns the same structure as FileFilter.filter_files_by_case(), plus:
            source_counts: {db_path: file_count}   — per-image file count
            dedup_removed: int                      — cross-image duplicates removed
        """
        if not files_db_paths:
            return {"filtered_files": [], "total_files": 0, "selected_count": 0}

        # Step 1: load + tag all files from every db
        all_tagged: List[Dict[str, str]] = []
        source_counts: Dict[str, int] = {}

        for idx, db_path in enumerate(files_db_paths):
            records = self._get_file_list_from_db(db_path)
            source_counts[db_path] = len(records)
            tag = f"[IMG{idx+1}]"
            for r in records:
                r["tagged_path"] = f"{tag} {r['path']}"
                r["source_db"]   = db_path
            all_tagged.extend(records)
            logger.info(f"[MULTI_FILTER] DB {idx+1}: {len(records)} files from {db_path}")

        total_before_dedup = len(all_tagged)

        # Step 2: deduplicate by (filename, size) across images
        deduped = self._cross_image_dedup(all_tagged)
        dedup_removed = total_before_dedup - len(deduped)
        logger.info(f"[MULTI_FILTER] Dedup: {total_before_dedup} → {len(deduped)} "
                    f"(-{dedup_removed} cross-image duplicates)")

        # Step 3: build TOON lines and run streaming LLM filter
        toon_lines = self._build_toon_lines(deduped)
        schema = "name | tagged_path | size | category"

        filter_result = await self._run_streaming_filter(
            schema=schema,
            data_lines=toon_lines,
            case_description=case_description,
            max_files=max_files,
            batch_size=batch_size,
        )

        # Step 4: persist per-db filtered lists for downstream pipeline
        selected = filter_result.get("filtered_files", [])
        self._distribute_and_persist(selected, deduped, files_db_paths, task_ids)

        return {
            **filter_result,
            "source_counts":  source_counts,
            "dedup_removed":  dedup_removed,
            "total_files":    len(deduped),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _cross_image_dedup(self, records: List[Dict]) -> List[Dict]:
        """
        Deduplicate file records across images.
        Key = (filename, size).  First occurrence wins.
        """
        seen: set = set()
        unique: List[Dict] = []
        for r in records:
            key = (Path(r["path"]).name, r.get("size", 0))
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    def _build_toon_lines(self, records: List[Dict]) -> List[str]:
        """Build TOON-format lines (name | tagged_path | size | category)."""
        lines = []
        for r in records:
            name = Path(r["path"]).name
            tagged = r.get("tagged_path", r["path"])
            size = r.get("size", 0)
            ftype = r.get("file_type", "")
            lines.append(f"{name} | {tagged} | {size} | {ftype}")
        return lines

    async def _run_streaming_filter(
        self,
        schema: str,
        data_lines: List[str],
        case_description: str,
        max_files: int,
        batch_size: int,
    ) -> Dict[str, Any]:
        """Run the streaming batch LLM filter on pre-built TOON data using enhanced pipeline."""
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        batches = [data_lines[i:i + batch_size] for i in range(0, len(data_lines), batch_size)]
        all_selected: List[str] = []
        reasonings: List[str] = []

        for idx, batch in enumerate(batches):
            batch_toon = f"{schema}\n" + "\n".join(batch)
            prompt = self._build_batch_filter_prompt(
                case_description=case_description,
                batch_toon=batch_toon,
                batch_number=idx + 1,
                total_batches=len(batches),
                max_files=max_files,
                already_selected=len(all_selected),
            )
            try:
                result = await self._llm_service.analyze(
                    content=batch_toon,
                    model_type="text",
                    prompt=prompt,
                    max_tokens=self.settings.llm_text_max_tokens,
                )
                text = result.get("analysis", {}).get("description", "")

                # Use enhanced parsing pipeline
                parsed = self._parser.parse_filter_response(text, batch)
                validated = self._validator.validate_and_repair(parsed, batch)

                all_selected.extend(validated["selected_files"])
                if validated.get("reasoning"):
                    reasonings.append(validated["reasoning"])
                if len(all_selected) >= max_files:
                    break
            except Exception as e:
                logger.warning(f"[MULTI_FILTER] Batch {idx+1} failed: {e}")

        # Use enhanced duplicate resolution
        final = self._matcher.match_files(all_selected)

        return {
            "filtered_files": final,
            "reasoning": " | ".join(reasonings),
            "selected_count": len(final),
            "streaming_used": True,
        }

    def _distribute_and_persist(
        self,
        selected_tagged: List[str],
        deduped: List[Dict],
        db_paths: List[str],
        task_ids: Optional[List[str]],
    ) -> None:
        """Map selected tagged paths back to per-db file paths and persist."""
        path_to_record = {r.get("tagged_path", r["path"]): r for r in deduped}

        per_db: Dict[str, List[str]] = {db: [] for db in db_paths}
        for tagged in selected_tagged:
            rec = path_to_record.get(tagged)
            if rec:
                per_db[rec["source_db"]].append(rec["path"])

        for idx, (db_path, file_list) in enumerate(per_db.items()):
            tid = (task_ids[idx] if task_ids and idx < len(task_ids) else
                   re.search(r'tasks/([a-f0-9-]+)/', db_path))
            tid = tid.group(1) if hasattr(tid, "group") else (tid or "_latest")
            self._persist_filtered_files(db_path, tid, file_list)
            logger.info(f"[MULTI_FILTER] Persisted {len(file_list)} files for DB {idx+1}")
