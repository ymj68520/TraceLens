"""
Report Generator Module — LLM-driven forensic case report generation.

This module handles report generation logic, including graph-enhanced and fallback methods.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings
from ...prompts import REPORT_CHAPTERS, REPORT_CHAPTER_TEMPLATE, REPORT_FALLBACK_TEMPLATE

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Handles case report generation operations."""

    def __init__(self, settings: Settings, llm_service, graphiti_service):
        """
        Initialize ReportGenerator.

        Args:
            settings: Application settings
            llm_service: LLM service for report generation
            graphiti_service: Knowledge graph service (optional)
        """
        self.settings = settings
        self._llm_service = llm_service
        self._graphiti_service = graphiti_service

    async def generate_final_report(
        self,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        files_db_path: Optional[str] = None,
        task_id: Optional[str] = None,
        windows_db_path: Optional[str] = None,
        files_db_paths: Optional[List[str]] = None,
        task_ids: Optional[List[str]] = None,
        is_cross_image_report: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive case analysis report.

        For single-image reports: aggregates from single database.
        For cross-image reports: aggregates from multiple databases.

        Args:
            case_description: Case description for report context
            file_descriptions: Initial file descriptions (will be overridden by DB aggregation)
            files_db_path: Single database path (for single-image reports)
            task_id: Task identifier or case identifier
            windows_db_path: Optional Windows artifacts database path
            files_db_paths: Multiple database paths (for cross-image reports)
            is_cross_image_report: Whether this is a cross-image report

        Returns:
            Dictionary with report text and metadata
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # DYNAMIC AGGREGATION: Always pull the latest descriptions from database
        # This ensures manually re-analyzed or analyzed files are included in the report
        if is_cross_image_report and files_db_paths and task_id:
            # Cross-image report: aggregate from multiple databases
            logger.info(f"Case {task_id}: Aggregating evidence from {len(files_db_paths)} databases for cross-image report...")
            try:
                file_descriptions = self._aggregate_descriptions_from_multiple_dbs(
                    files_db_paths, task_id
                )
                logger.info(f"Case {task_id}: Integrated {len(file_descriptions)} relevant evidence files from all images.")
            except Exception as e:
                logger.warning(f"Failed to aggregate evidence from multiple databases: {e}")
                file_descriptions = []
        elif files_db_path and task_id:
            # Single-image report: aggregate from single database
            logger.info(f"Task {task_id}: Aggregating all relevant evidence descriptions from database...")
            try:
                with sqlite3.connect(files_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    # Ensure file_descriptions table exists before querying
                    from .db_utils import ensure_file_descriptions_schema
                    ensure_file_descriptions_schema(conn)
                    # Only include files explicitly marked as evidence by the user (is_relevant = 1)
                    cur = conn.execute("SELECT file_path, description, model_used FROM file_descriptions WHERE is_relevant = 1")
                    rows = cur.fetchall()
                    if rows:
                        # Convert DB rows to the format expected by build_evidence_summary
                        file_descriptions = [
                            {
                                "file_path": row["file_path"],
                                "description": row["description"],
                                "success": True,
                                "model_used": row["model_used"]
                            }
                            for row in rows
                        ]
                        logger.info(f"Task {task_id}: Integrated {len(file_descriptions)} relevant evidence files into report.")
                    else:
                        file_descriptions = []
                        logger.info(f"Task {task_id}: No relevant evidence found in database.")
            except Exception as e:
                logger.warning(f"Failed to aggregate evidence from database: {e}")

        # Gather Windows artifacts if available
        windows_section = ""
        windows_analyzed = 0
        if windows_db_path and task_id:
            try:
                windows_section = await self._include_windows_section(
                    task_id=task_id,
                    windows_db_path=windows_db_path,
                    case_description=case_description,
                )
                # Count Windows artifacts
                with sqlite3.connect(windows_db_path) as conn:
                    cur = conn.execute("SELECT COUNT(*) as count FROM windows_artifact_descriptions")
                    windows_analyzed = cur.fetchone()["count"]
            except Exception as e:
                logger.warning(f"Failed to include Windows artifacts: {e}")

        use_graph = (
            self._graphiti_service is not None
            and task_id is not None
        )

        report_text = ""
        model_used = "direct"

        if use_graph:
            try:
                if is_cross_image_report:
                    logger.info(f"Case {task_id}: Attempting cross-image graph-enhanced report generation...")
                else:
                    logger.info(f"Task {task_id}: Attempting graph-enhanced report generation...")
                report_text = await self._generate_report_with_graph(
                    case_description=case_description,
                    task_id=task_id,
                    file_descriptions=file_descriptions,
                    windows_section=windows_section,
                    task_ids=task_ids,
                    is_cross_image_report=is_cross_image_report,
                    files_db_path=files_db_path,
                )
                if report_text:
                    model_used = "graph-enhanced"
            except Exception as e:
                logger.warning(
                    f"Graph-enhanced report generation failed, falling back: {e}"
                )

        # Fallback if graph failed or returned nothing
        if not report_text:
            try:
                logger.info(f"Task {task_id}: Using fallback (concatenation) report generation...")
                report_text = await self._generate_report_fallback(
                    case_description, file_descriptions, windows_section
                )
                model_used = "direct"
            except Exception as e:
                logger.error(f"Fallback generation also failed: {e}", exc_info=True)
                report_text = "生成报告时发生错误：" + str(e)

        # Persist report to database
        if files_db_path and report_text and not report_text.startswith("生成报告时发生错误"):
            try:
                self._persist_case_report(
                    files_db_path, task_id or "", case_description, report_text
                )
            except Exception as e:
                logger.warning(f"Failed to persist case report to db: {e}")

        return {
            "report": report_text,
            "case_description": case_description,
            "files_analyzed": len(file_descriptions),
            "files_successful": sum(1 for f in file_descriptions if f.get("success")),
            "windows_analyzed": windows_analyzed,
            "model_used": model_used,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def _generate_report_with_graph(
        self,
        case_description: str,
        task_id: str,
        file_descriptions: List[Dict[str, Any]] = None,
        windows_section: str = "",
        task_ids: Optional[List[str]] = None,
        is_cross_image_report: bool = False,
        files_db_path: Optional[str] = None,
    ) -> str:
        """
        Generate report using Graphiti RAG with optimized context management.

        For cross-image reports, searches across all relevant task graphs.
        For single-image reports, searches only the specific task graph.

        Implementation:
        - Option A: Lightweight evidence list (paths only) to save space.
        - Option C: Tunable retrieval limits from config.py.
        """
        # [Option A] LIGHTWEIGHT CHECKLIST:
        # Since full descriptions are already in the Knowledge Graph, we only need to provide
        # a checklist of file paths to ensure the LLM includes them in the final report.
        evidence_list_str = "本案关键证据文件清单（细节请参考下文【知识图谱背景】）：\n"
        if file_descriptions:
            # Only list the file paths to save thousands of tokens
            for d in file_descriptions:
                evidence_list_str += f"- [[file:{d['file_path']}]]\n"
        else:
            evidence_list_str += "（无显式证据文件，基于全局图谱分析）"

        # Include analyzed event clusters as evidence
        event_evidence = self._load_event_cluster_evidence(task_id, files_db_path)
        if event_evidence:
            evidence_list_str += "\n本案关键事件簇证据清单：\n"
            for ev in event_evidence:
                evidence_list_str += (
                    f"- [[event:{ev['event_type']}@{ev['time_window']}/{ev['parent_dir']}]] "
                    f"({ev['cluster_count']}个事件) — {ev.get('summary', '')}\n"
                )

        # Include Windows artifacts summary if available
        if windows_section:
            evidence_list_str += f"\n\n{windows_section}"

        chapters = [
            {
                "title": ch["title"],
                "query": ch["query_template"].format(
                    case_desc_short=case_description[:200]
                ),
                "instruction": ch["instruction"],
            }
            for ch in REPORT_CHAPTERS
        ]

        report_parts = []
        # [Option C] TUNABLE RETRIEVAL:
        search_limit = getattr(self.settings, 'graphiti_search_limit', 10)
        content_limit = getattr(self.settings, 'graphiti_context_item_limit', 250)

        # Determine which task IDs to search
        search_task_ids = task_ids if is_cross_image_report and task_ids else [task_id]
        logger.info(f"Graphiti search will query {len(search_task_ids)} task graphs: {search_task_ids}")

        for chapter in chapters:
            # Special handling for timeline chapter: prioritize event clusters
            if chapter["title"] == "时间线梳理":
                # Use expanded query specifically for event clusters
                enhanced_query = chapter["query"] + " 事件簇 时间窗口 cluster event_type"

                # Search across all task graphs for cross-image reports
                all_search_results = []
                for tid in search_task_ids:
                    try:
                        results = await self._graphiti_service.search(
                            query=enhanced_query,
                            task_id=tid,
                            limit=search_limit * 2,  # Get more results for timeline
                            include_relationships=True,
                        )
                        all_search_results.extend(results)
                    except Exception as e:
                        logger.warning(f"Graphiti search failed for task {tid}: {e}")

                # Deduplicate and limit results
                search_results = self._deduplicate_search_results(all_search_results)[:search_limit * 2]
            else:
                # Standard search for other chapters - across all task graphs
                all_search_results = []
                for tid in search_task_ids:
                    try:
                        results = await self._graphiti_service.search(
                            query=chapter["query"],
                            task_id=tid,
                            limit=search_limit,
                            include_relationships=True,
                        )
                        all_search_results.extend(results)
                    except Exception as e:
                        logger.warning(f"Graphiti search failed for task {tid}: {e}")

                # Deduplicate and limit results
                search_results = self._deduplicate_search_results(all_search_results)[:search_limit]

            # Build context from search results with dynamic truncation
            context_lines = []
            for r in search_results:
                name = r.get("name", "")
                props = r.get("properties", {})
                body = props.get("body", "") or props.get("summary", "") or name
                if body:
                    # Apply fine-tuned truncation
                    truncated_body = body[:content_limit] + "..." if len(body) > content_limit else body
                    context_lines.append(f"- {truncated_body}")

            kg_context = "\n".join(context_lines) if context_lines else "无相关图谱信息。"

            # CONSOLIDATED PROMPT: Dramatically reduced size but high information density
            combined_context = f"【核心证据清单】\n{evidence_list_str}\n\n【图谱研判背景】\n{kg_context}"

            prompt = REPORT_CHAPTER_TEMPLATE.format(
                chapter_title=chapter["title"],
                case_description=case_description,
                context=combined_context,
                chapter_instruction=chapter["instruction"] +
                "\n\nCRITICAL INSTRUCTION: "
                "1. 你必须在分析中显式引用【核心证据清单】中的文件路径和事件簇；"
                "2. 每一个引用的文件必须严格遵循 [[file:路径]] 格式（例如 [[file:/usr/bin/cmd]]）；"
                "3. 每一个引用的事件簇必须严格遵循 [[event:事件类型@时间窗口/目录]] 格式（例如 [[event:CREATED@123456/DCIM/Camera]]）；"
                "4. 严禁虚构不存在的文件路径或事件。",
            )

            try:
                result = await self._llm_service.analyze(
                    content=prompt,
                    model_type="text",
                    prompt=prompt,
                    max_tokens=self.settings.llm_text_max_tokens,
                )
                chapter_text = result.get("analysis", {}).get("description", "")
            except Exception as e:
                logger.warning(f"Failed to generate chapter '{chapter['title']}': {e}")
                chapter_text = f"（该章节生成失败：{e}）"

            report_parts.append(f"## {chapter['title']}\n\n{chapter_text}")

        return "\n\n---\n\n".join(report_parts)

    async def _generate_report_fallback(
        self, case_description: str, file_descriptions: List[Dict[str, Any]], windows_section: str = ""
    ) -> str:
        """
        Fallback: concatenate all evidence and generate in one shot.
        Used when Graphiti is unavailable.
        """
        evidence_section = self._build_evidence_summary(file_descriptions)

        # Include Windows artifacts section if available
        if windows_section:
            evidence_section += f"\n\n{windows_section}"

        user_prompt = REPORT_FALLBACK_TEMPLATE.format(
            case_description=case_description,
            evidence_section=evidence_section,
        )

        result = await self._llm_service.analyze(
            content=user_prompt,
            model_type="text",
            prompt=user_prompt,
            max_tokens=self.settings.llm_text_max_tokens,
        )
        return result.get("analysis", {}).get("description", "")

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
        from .db_utils import ensure_file_descriptions_schema

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
        from .db_utils import persist_case_report
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
        from .db_utils import get_case_report_from_db
        return get_case_report_from_db(files_db_path, task_id)

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """
        Retrieve the list of case-relevant files.
        Prioritizes files that already have LLM descriptions in the database.
        """
        from .db_utils import get_filtered_files_from_db
        return get_filtered_files_from_db(files_db_path, task_id)
