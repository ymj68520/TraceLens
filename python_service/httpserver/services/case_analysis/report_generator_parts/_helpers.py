"""Part of ReportGenerator (split for maintainability).

This mixin contributes the evidence-assembly / report-persistence helper
methods to the ReportGenerator class declared in report_generator.py.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReportGeneratorHelpersMixin:
    """Evidence aggregation, Windows-section rendering, dedup, persistence, getters."""

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

    def _aggregate_descriptions_from_multiple_dbs(
        self,
        files_db_paths: List[str],
        case_id: str
    ) -> List[Dict[str, Any]]:
        """
        Aggregate file descriptions from multiple databases for cross-image reporting.

        For cross-image reports, we need to collect evidence from all image databases.
        Each database contains file_descriptions table with analyzed files.

        Args:
            files_db_paths: List of _files.db paths
            case_id: Case identifier (used for logging)

        Returns:
            Aggregated list of file descriptions from all databases
        """
        from ..db_utils import ensure_file_descriptions_schema

        all_descriptions = []
        seen_paths = set()  # Deduplicate by file path

        for idx, db_path in enumerate(files_db_paths):
            try:
                if not Path(db_path).exists():
                    logger.warning(f"[{case_id}] Database {idx+1} not found: {db_path}")
                    continue

                with sqlite3.connect(db_path, timeout=10) as conn:
                    conn.row_factory = sqlite3.Row
                    ensure_file_descriptions_schema(conn)

                    # Get user-selected evidence files
                    cur = conn.execute(
                        "SELECT file_path, description, model_used FROM file_descriptions WHERE is_relevant = 1"
                    )
                    rows = cur.fetchall()

                    db_count = 0
                    for row in rows:
                        file_path = row["file_path"]
                        # Deduplicate across images
                        if file_path not in seen_paths:
                            seen_paths.add(file_path)
                            all_descriptions.append({
                                "file_path": file_path,
                                "description": row["description"],
                                "success": True,
                                "model_used": row["model_used"],
                                "source_db": db_path  # Track source for debugging
                            })
                            db_count += 1

                    logger.info(f"[{case_id}] Database {idx+1}: contributed {db_count} unique files")

            except Exception as e:
                logger.warning(f"[{case_id}] Failed to read database {idx+1} ({db_path}): {e}")

        logger.info(f"[{case_id}] Total unique files across all databases: {len(all_descriptions)}")
        return all_descriptions

    async def _include_windows_section(
        self,
        task_id: str,
        windows_db_path: str,
        case_description: str,
    ) -> str:
        """Generate Windows artifacts section for the report."""
        try:
            with sqlite3.connect(windows_db_path) as conn:
                conn.row_factory = sqlite3.Row

                # Get artifact counts by type
                cur = conn.execute("""
                    SELECT artifact_type, COUNT(*) as count,
                           SUM(CASE WHEN severity IN ('high', 'critical') THEN 1 ELSE 0 END) as high_priority
                    FROM windows_artifact_descriptions
                    GROUP BY artifact_type
                    ORDER BY count DESC
                """)
                type_stats = cur.fetchall()

                if not type_stats:
                    return ""

                # Build summary section
                lines = ["## Windows系统痕迹分析\n"]

                # Add statistics
                lines.append("### 痕迹统计\n")
                for stat in type_stats:
                    type_name = self._get_artifact_type_display_name(stat["artifact_type"])
                    lines.append(f"- **{type_name}**: {stat['count']}条 ({stat['high_priority']}条高优先级)")
                lines.append("")

                # Add high-priority findings
                cur = conn.execute("""
                    SELECT artifact_type, summary, severity
                    FROM windows_artifact_descriptions
                    WHERE severity IN ('high', 'critical')
                    ORDER BY severity DESC, relevance DESC
                    LIMIT 20
                """)
                findings = cur.fetchall()

                if findings:
                    lines.append("### 关键发现\n")
                    for finding in findings:
                        type_name = self._get_artifact_type_display_name(finding["artifact_type"])
                        severity_mark = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(finding["severity"], "⚪")
                        lines.append(f"- {severity_mark} **{type_name}**: {finding['summary']}")
                    lines.append("")

                return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Error generating Windows section: {e}")
            return ""

    def _get_artifact_type_display_name(self, artifact_type: str) -> str:
        """Get display name for artifact type."""
        display_names = {
            "registry_values": "注册表记录",
            "event_log_entries": "事件日志",
            "prefetch_files": "Prefetch文件",
            "browser_history": "浏览器历史",
            "windows_services": "Windows服务",
            "scheduled_tasks": "计划任务",
            "amcache_entries": "Amcache记录",
            "srum_entries": "SRUM记录",
            "usb_devices": "USB设备",
            "user_accounts": "用户账户",
            "lnk_files": "LNK快捷方式",
            "jump_list_entries": "跳转列表",
            "recycle_bin_entries": "回收站记录",
        }
        return display_names.get(artifact_type, artifact_type)

    def _deduplicate_search_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Deduplicate Graphiti search results by entity name.

        When searching across multiple task graphs, we may get duplicate entities.
        This method deduplicates by keeping the first occurrence of each unique name.

        Args:
            results: List of search result dictionaries

        Returns:
            Deduplicated list of search results
        """
        seen = set()
        deduped = []
        for r in results:
            name = r.get("name", "")
            if name and name not in seen:
                seen.add(name)
                deduped.append(r)
        return deduped

    def _load_event_cluster_evidence(self, task_id: str, files_db_path: str = None) -> List[Dict[str, Any]]:
        """
        Load AI-analyzed event clusters from the events database.

        Event clusters that have been analyzed by the LLM (llm_summary is not empty)
        are returned as evidence for the report. This ensures the report includes
        timeline-based findings alongside file-based evidence.

        Args:
            task_id: Task identifier for locating the database
            files_db_path: Optional _files.db path to derive the events.db location from

        Returns:
            List of event cluster evidence dicts with event_type, time_window,
            parent_dir, cluster_count, and summary fields.
        """
        # Derive events.db path from files_db_path (they share the same task directory)
        events_db = None
        if files_db_path:
            events_db = files_db_path.replace("_files.db", "_events.db")
        if not events_db or not Path(events_db).exists():
            # Fallback: try to construct from build/data/tasks/<task_id>/
            import re
            task_match = re.search(r'(tasks/[a-f0-9-]+/)', files_db_path or "")
            if task_match:
                import os
                build_dir = Path(files_db_path).parent.parent.parent.parent if files_db_path else Path.cwd()
                events_db = str(build_dir / task_match.group(1) / "events.db")
        if not events_db or not Path(events_db).exists():
            logger.debug(f"Events DB not found for task {task_id}")
            return []

        try:
            with sqlite3.connect(events_db, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                # Ensure AI columns exist (self-healing, same as C++ timeline route)
                for col, col_type in [("llm_summary", "TEXT"), ("llm_description", "TEXT"),
                                      ("llm_keywords", "TEXT"), ("llm_analyzed_at", "INTEGER"),
                                      ("llm_model_used", "TEXT"), ("llm_is_relevant", "INTEGER")]:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {col} {col_type}")
                conn.commit()

                cur = conn.execute("""
                    SELECT
                        event_type,
                        (timestamp / 60) as time_window,
                        CASE WHEN file_path LIKE '%/%'
                            THEN RTRIM(file_path, REPLACE(file_path, '/', ''))
                            ELSE ''
                        END as parent_dir,
                        COUNT(*) as cluster_count,
                        llm_summary,
                        llm_description,
                        llm_is_relevant
                    FROM events
                    WHERE llm_summary IS NOT NULL AND llm_summary != ''
                    GROUP BY parent_dir, time_window, event_type
                    ORDER BY cluster_count DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()

                result = []
                for row in rows:
                    result.append({
                        "event_type": row["event_type"],
                        "time_window": row["time_window"],
                        "parent_dir": row["parent_dir"] or "/",
                        "cluster_count": row["cluster_count"],
                        "summary": row["llm_summary"],
                        "description": row["llm_description"],
                        "is_relevant": row["llm_is_relevant"],
                    })

                logger.info(f"Loaded {len(result)} analyzed event clusters for report from task {task_id}")
                return result
        except Exception as e:
            logger.warning(f"Failed to load event cluster evidence: {e}")
            return []

    def _persist_case_report(
        self, db_path: str, task_id: str,
        case_description: str, report: str
    ):
        """Persist the case report to database."""
        from ..db_utils import persist_case_report
        persist_case_report(db_path, task_id, case_description, report)

    def get_case_report(self, files_db_path: str, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a persisted case report from the database.

        Args:
            files_db_path: Path to _files.db.
            task_id: Task identifier.

        Returns:
            Report dict or None if not found.
        """
        from ..db_utils import get_case_report_from_db
        return get_case_report_from_db(files_db_path, task_id)

    def get_cross_image_report(self, case_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a persisted cross-image report for a case.

        Cross-image reports are persisted to the case-level database
        (data/cases/{case_id}/{case_id}.db) keyed by the case_id, so they
        can be retrieved independently of any single task.

        Args:
            case_id: Case identifier.

        Returns:
            Report dict or None if not found.
        """
        from ..db_utils import get_case_db_path, get_case_report_from_db
        case_db = get_case_db_path(case_id)
        return get_case_report_from_db(case_db, case_id)

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """
        Retrieve the list of case-relevant files.
        Prioritizes files that already have LLM descriptions in the database.
        """
        from ..db_utils import get_filtered_files_from_db
        return get_filtered_files_from_db(files_db_path, task_id)

