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
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive case analysis report.
        Aggregates ALL available file descriptions from the database.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # DYNAMIC AGGREGATION: Always pull the latest descriptions from database
        # This ensures manually re-analyzed or analyzed files are included in the report
        if files_db_path and task_id:
            logger.info(f"Task {task_id}: Aggregating all relevant evidence descriptions from database...")
            try:
                with sqlite3.connect(files_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    # Ensure file_descriptions table exists before querying
                    from .db_utils import ensure_file_descriptions_schema
                    ensure_file_descriptions_schema(conn)
                    # CRITICAL: Include files NOT explicitly marked as irrelevant (is_relevant IS NOT 0)
                    # This handles NULL (legacy/default) and 1 (explicitly marked)
                    cur = conn.execute("SELECT file_path, description, model_used FROM file_descriptions WHERE is_relevant IS NOT 0")
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

        use_graph = (
            self._graphiti_service is not None
            and task_id is not None
        )

        report_text = ""
        model_used = "direct"

        if use_graph:
            try:
                logger.info(f"Task {task_id}: Attempting graph-enhanced report generation...")
                report_text = await self._generate_report_with_graph(
                    case_description, task_id, file_descriptions
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
                    case_description, file_descriptions
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
            "model_used": model_used,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def _generate_report_with_graph(
        self, case_description: str, task_id: str, file_descriptions: List[Dict[str, Any]] = None
    ) -> str:
        """
        Generate report using Graphiti RAG with optimized context management.

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
                evidence_list_str += f"- [[file:{d.file_path}]]\n"
        else:
            evidence_list_str += "（无显式证据文件，基于全局图谱分析）"

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

        for chapter in chapters:
            # Special handling for timeline chapter: prioritize event clusters
            if chapter["title"] == "时间线梳理":
                # Use expanded query specifically for event clusters
                enhanced_query = chapter["query"] + " 事件簇 时间窗口 cluster event_type"
                search_results = await self._graphiti_service.search(
                    query=enhanced_query,
                    task_id=task_id,
                    limit=search_limit * 2,  # Get more results for timeline
                    include_relationships=True,
                )
            else:
                # Standard search for other chapters
                search_results = await self._graphiti_service.search(
                    query=chapter["query"],
                    task_id=task_id,
                    limit=search_limit,
                    include_relationships=True,
                )

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
                "1. 你必须在分析中显式引用【核心证据清单】中的文件路径；"
                "2. 每一个引用的文件必须严格遵循 [[file:路径]] 格式（例如 [[file:/usr/bin/cmd]]）；"
                "3. 严禁虚构不存在的文件路径。",
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
        self, case_description: str, file_descriptions: List[Dict[str, Any]]
    ) -> str:
        """
        Fallback: concatenate all evidence and generate in one shot.
        Used when Graphiti is unavailable.
        """
        evidence_section = self._build_evidence_summary(file_descriptions)

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
