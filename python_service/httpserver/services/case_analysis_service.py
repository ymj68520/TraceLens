"""
Case Analysis Service — LLM-driven forensic case analysis.

Workflow:
1. Save case description (persisted via C++ tasks.json through the task API)
2. Send file list + case description to LLM → filter important files
3. For each filtered file, generate LLM description
4. Generate a final comprehensive case report using all descriptions

All results are persisted to the _files.db SQLite database.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import Settings

logger = logging.getLogger(__name__)


class CaseAnalysisService:
    """Service for end-to-end LLM case analysis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # Will be injected after ServiceManager init
        self._llm_service = None

    def set_llm_service(self, llm_service):
        """Inject the LLM service dependency."""
        self._llm_service = llm_service

    # ------------------------------------------------------------------
    # 1. File Filtering — LLM selects forensically relevant files
    # ------------------------------------------------------------------
    async def filter_files_by_case(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int = 200,
    ) -> Dict[str, Any]:
        """
        Let LLM select important files based on case description.

        Args:
            files_db_path: Path to the _files.db.
            case_description: User-provided case description.
            max_files: Max number of files to select.

        Returns:
            Dict with filtered_files list and llm reasoning.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Read file list from database
        all_files = self._get_file_list_from_db(files_db_path)
        if not all_files:
            return {"filtered_files": [], "reasoning": "No files found in database."}

        # Build a concise file summary for the LLM
        file_summary = self._build_file_summary(all_files)

        system_prompt = """你是一名数字取证专家。根据案情描述，从文件列表中挑选出与案情最相关的文件。
请以严格的JSON格式返回结果，不要包含任何其他文字或markdown标记。

返回格式：
{
  "selected_files": ["文件路径1", "文件路径2", ...],
  "reasoning": "筛选理由的简要说明"
}

注意：
- 优先选择可能包含关键证据的文件（文档、聊天记录、图片、日志等）
- 排除明显无关的系统文件和二进制文件
- 选择数量适中，不超过指定上限"""

        user_prompt = f"""案情描述：
{case_description}

文件列表（共 {len(all_files)} 个文件）：
{file_summary}

请从中筛选出与案情最相关的文件（最多 {max_files} 个）。"""

        try:
            result = await self._llm_service.analyze(
                content=user_prompt,
                model_type="text",
                prompt=user_prompt,
                max_tokens=self.settings.llm_text_max_tokens,
            )

            response_text = result.get("analysis", {}).get("description", "")
            parsed = self._parse_filter_response(response_text, all_files)

            # Persist filtered file list to database
            self._persist_filtered_files(files_db_path, parsed["selected_files"])

            return {
                "filtered_files": parsed["selected_files"],
                "reasoning": parsed.get("reasoning", ""),
                "total_files": len(all_files),
                "selected_count": len(parsed["selected_files"]),
                "model_used": result.get("model", ""),
            }
        except Exception as e:
            logger.error(f"File filtering failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # 2. Per-file Description Generation
    # ------------------------------------------------------------------
    async def generate_file_descriptions(
        self,
        files_db_path: str,
        file_paths: List[str],
        case_description: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Generate LLM description for each file in the list.

        Args:
            files_db_path: Path to _files.db for persisting results.
            file_paths: List of file paths to analyze.
            case_description: Case context for better descriptions.
            progress_callback: Optional async callback(current, total, file_path).

        Returns:
            List of analysis results.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        results = []
        total = len(file_paths)

        for i, file_path in enumerate(file_paths):
            try:
                content = await self._llm_service.read_file_content(file_path)

                custom_prompt = f"""你是数字取证专家。请结合以下案情背景，分析该文件内容。

案情背景：{case_description}

文件路径：{file_path}

文件内容：
{content}

请提供：
1. 文件内容的简要描述
2. 与案情可能的关联
3. 关键发现或可疑信息
4. 推荐关注的要点"""

                result = await self._llm_service.analyze(
                    content=content,
                    model_type="text",
                    prompt=custom_prompt,
                )

                analysis = result.get("analysis", {})
                description = analysis.get("description", "")

                # Persist to _files.db
                if files_db_path and description:
                    self._llm_service.persist_to_files_db(
                        db_path=files_db_path,
                        file_path=file_path,
                        description=description,
                        summary=description[:200],
                        keywords="",
                        model_used=result.get("model", ""),
                    )

                results.append({
                    "file_path": file_path,
                    "description": description,
                    "model_used": result.get("model", ""),
                    "success": True,
                })

            except Exception as e:
                logger.warning(f"Failed to analyze file {file_path}: {e}")
                results.append({
                    "file_path": file_path,
                    "description": "",
                    "error": str(e),
                    "success": False,
                })

            if progress_callback:
                try:
                    await progress_callback(i + 1, total, file_path)
                except Exception:
                    pass

        return results

    # ------------------------------------------------------------------
    # 3. Final Case Report Generation
    # ------------------------------------------------------------------
    async def generate_case_report(
        self,
        case_description: str,
        file_descriptions: List[Dict[str, Any]],
        files_db_path: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive case analysis report.

        Args:
            case_description: Original case description.
            file_descriptions: List of per-file analysis results.
            files_db_path: Path to _files.db for persisting the report.
            task_id: Task ID for associating the report.

        Returns:
            Dict with the generated report.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Build evidence summary from file descriptions
        evidence_section = self._build_evidence_summary(file_descriptions)

        system_prompt = """你是一名资深数字取证分析师，正在撰写一份正式的案情分析报告。
请使用Markdown格式撰写报告，报告应当专业、条理清晰、逻辑严密。"""

        user_prompt = f"""请根据以下案情描述和文件分析结果，生成一份完整的数字取证案情分析报告。

## 案情描述
{case_description}

## 文件分析结果
{evidence_section}

请生成报告，包含以下章节：
1. **案件概述** — 简要描述案件背景
2. **证据分析** — 对关键文件的详细分析
3. **关键发现** — 有价值的发现和线索
4. **时间线梳理** — 如果可以从文件中推断时间线
5. **结论与建议** — 总结分析结果，提出后续建议

请确保报告语言专业、证据引用准确。"""

        try:
            result = await self._llm_service.analyze(
                content=user_prompt,
                model_type="text",
                prompt=user_prompt,
                max_tokens=self.settings.llm_text_max_tokens,
            )

            report_text = result.get("analysis", {}).get("description", "")

            # Persist report to database
            if files_db_path and report_text:
                self._persist_case_report(
                    files_db_path, task_id or "", case_description, report_text
                )

            return {
                "report": report_text,
                "case_description": case_description,
                "files_analyzed": len(file_descriptions),
                "files_successful": sum(1 for f in file_descriptions if f.get("success")),
                "model_used": result.get("model", ""),
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            logger.error(f"Case report generation failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Full Pipeline — run all steps sequentially
    # ------------------------------------------------------------------
    async def run_full_analysis(
        self,
        task_id: str,
        files_db_path: str,
        case_description: str,
        max_filter_files: int = 200,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run the complete case analysis pipeline.

        Steps:
            1. Filter files by case relevance
            2. Generate per-file descriptions
            3. Generate final case report

        Args:
            task_id: Task identifier.
            files_db_path: Path to _files.db.
            case_description: Case description text.
            max_filter_files: Max files to select in filtering step.
            progress_callback: Optional async callback(step, detail).

        Returns:
            Complete analysis result.
        """
        result = {
            "task_id": task_id,
            "case_description": case_description,
            "steps": {},
        }

        # Step 1: Filter files
        if progress_callback:
            await progress_callback("filtering", "正在使用 LLM 筛选相关文件...")
        filter_result = await self.filter_files_by_case(
            files_db_path, case_description, max_filter_files
        )
        result["steps"]["filter"] = filter_result
        filtered_files = filter_result.get("filtered_files", [])

        if not filtered_files:
            result["steps"]["descriptions"] = []
            result["steps"]["report"] = {
                "report": "未找到与案情相关的文件，无法生成报告。",
                "files_analyzed": 0,
            }
            return result

        # Step 2: Generate per-file descriptions
        if progress_callback:
            await progress_callback(
                "describing",
                f"正在分析 {len(filtered_files)} 个相关文件..."
            )
        descriptions = await self.generate_file_descriptions(
            files_db_path, filtered_files, case_description
        )
        result["steps"]["descriptions"] = descriptions

        # Step 3: Generate case report
        if progress_callback:
            await progress_callback("reporting", "正在生成综合案情分析报告...")
        report = await self.generate_case_report(
            case_description, descriptions, files_db_path, task_id
        )
        result["steps"]["report"] = report

        return result

    # ------------------------------------------------------------------
    # Report Retrieval
    # ------------------------------------------------------------------
    def get_case_report(self, files_db_path: str, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a persisted case report from the database.

        Args:
            files_db_path: Path to _files.db.
            task_id: Task identifier.

        Returns:
            Report dict or None if not found.
        """
        if not files_db_path or not Path(files_db_path).exists():
            return None

        try:
            with sqlite3.connect(files_db_path, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM case_analysis WHERE task_id = ?",
                    (task_id,),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "task_id": row["task_id"],
                        "case_description": row["case_description"],
                        "filtered_files": json.loads(row["filtered_files"] or "[]"),
                        "case_report": row["case_report"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
        except Exception as e:
            logger.warning(f"Failed to retrieve case report: {e}")
        return None

    def get_filtered_files(self, files_db_path: str) -> List[str]:
        """Retrieve the filtered file list from database."""
        if not files_db_path or not Path(files_db_path).exists():
            return []

        try:
            with sqlite3.connect(files_db_path, timeout=10) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT filtered_files FROM case_analysis ORDER BY updated_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
        except Exception as e:
            logger.warning(f"Failed to retrieve filtered files: {e}")
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_file_list_from_db(self, db_path: str) -> List[Dict[str, str]]:
        """Read file list from the _files.db."""
        if not Path(db_path).exists():
            return []

        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT path, file_type, size FROM files ORDER BY path"
                )
                rows = cur.fetchall()
                return [
                    {
                        "path": row["path"],
                        "file_type": row["file_type"] if "file_type" in row.keys() else "",
                        "size": row["size"] if "size" in row.keys() else 0,
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to read file list from {db_path}: {e}")
            return []

    def _build_file_summary(self, files: List[Dict[str, str]]) -> str:
        """Build a concise file list summary for LLM consumption."""
        lines = []
        for f in files[:2000]:  # Cap to avoid context overflow
            path = f.get("path", "")
            ftype = f.get("file_type", "")
            size = f.get("size", 0)
            size_str = self._format_size(size) if size else ""
            line = f"- {path}"
            if ftype:
                line += f" [{ftype}]"
            if size_str:
                line += f" ({size_str})"
            lines.append(line)

        if len(files) > 2000:
            lines.append(f"... 及其他 {len(files) - 2000} 个文件")

        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes) -> str:
        """Format file size to human-readable string."""
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            return ""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.0f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"

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
            parsed = json.loads(text)
            selected = parsed.get("selected_files", [])
            reasoning = parsed.get("reasoning", "")
            # Validate paths against actual file list
            valid_paths = [p for p in selected if p in all_paths]
            return {"selected_files": valid_paths, "reasoning": reasoning}
        except (json.JSONDecodeError, KeyError):
            logger.warning("Could not parse LLM filter response as JSON, falling back to line parsing")
            # Fallback: extract file paths from text
            selected = []
            for line in response_text.split("\n"):
                line = line.strip().strip("-").strip("*").strip()
                if line in all_paths:
                    selected.append(line)
            return {"selected_files": selected, "reasoning": response_text[:500]}

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

    def _ensure_case_analysis_table(self, db_path: str):
        """Create case_analysis table if it doesn't exist."""
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS case_analysis (
                        task_id TEXT PRIMARY KEY,
                        case_description TEXT,
                        filtered_files TEXT,
                        case_report TEXT,
                        created_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to create case_analysis table: {e}")

    def _persist_filtered_files(self, db_path: str, filtered_files: List[str]):
        """Persist the filtered file list to database."""
        self._ensure_case_analysis_table(db_path)
        now = int(time.time())
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO case_analysis
                        (task_id, filtered_files, created_at, updated_at)
                    VALUES
                        (?, ?, ?, ?)
                """, ("_latest", json.dumps(filtered_files), now, now))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist filtered files: {e}")

    def _persist_case_report(
        self, db_path: str, task_id: str,
        case_description: str, report: str
    ):
        """Persist the case report to database."""
        self._ensure_case_analysis_table(db_path)
        now = int(time.time())
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO case_analysis
                        (task_id, case_description, filtered_files, case_report, created_at, updated_at)
                    VALUES
                        (?, ?, COALESCE(
                            (SELECT filtered_files FROM case_analysis WHERE task_id = ?),
                            '[]'
                        ), ?, ?, ?)
                """, (task_id, case_description, task_id, report, now, now))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist case report: {e}")
