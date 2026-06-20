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



from .report_generator_parts import ReportGeneratorHelpersMixin


class ReportGenerator(ReportGeneratorHelpersMixin):
    """Generates LLM-powered case reports.

    NOTE: evidence-assembly / persistence helpers live in ReportGeneratorHelpersMixin
    (report_generator_parts/_helpers.py). Public surface unchanged.
    """

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
        if report_text and not report_text.startswith("生成报告时发生错误"):
            try:
                if is_cross_image_report and task_id:
                    # Cross-image reports are persisted to the case-level
                    # database (data/cases/{case_id}/{case_id}.db), keyed by
                    # the case_id, so they survive beyond the in-memory job and
                    # can be retrieved via the case-report-by-case endpoint.
                    from ..db_utils import get_case_db_path
                    case_db = get_case_db_path(task_id)
                    self._persist_case_report(case_db, task_id, case_description, report_text)
                elif files_db_path:
                    # Single-image reports persist to the task's own _files.db.
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

