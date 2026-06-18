"""Part of OSSFilterService (split for maintainability).

This mixin contributes the legacy filter path and helper methods to the
OSSFilterService class declared in oss_filter_service.py.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OSSFilterLegacyHelpersMixin:
    """Legacy filter path + object-summary/format/persist helpers + DB getter."""

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

