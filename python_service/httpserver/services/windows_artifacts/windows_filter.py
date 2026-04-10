"""
Windows Artifact Filter Module — LLM-driven Windows artifact filtering.

This module handles filtering of Windows forensic artifacts (registry,
event logs, browser history, prefetch, etc.) based on case description.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ...config import Settings

logger = logging.getLogger(__name__)


class WindowsArtifactFilter:
    """Handles Windows artifact filtering operations."""

    # Artifact types that can be filtered
    ARTIFACT_TYPES = [
        "registry_values",
        "event_log_entries",
        "prefetch_files",
        "browser_history",
        "windows_services",
        "scheduled_tasks",
        "amcache_entries",
        "srum_entries",
        "usb_devices",
        "user_accounts",
        "lnk_files",
        "jump_list_entries",
        "recycle_bin_entries",
    ]

    def __init__(self, settings: Settings, llm_service):
        """
        Initialize WindowsArtifactFilter.

        Args:
            settings: Application settings
            llm_service: LLM service for filtering
        """
        self.settings = settings
        self._llm_service = llm_service

    async def filter_artifacts_by_case(
        self,
        windows_db_path: str,
        case_description: str,
        max_artifacts: int = 200,
        artifact_types: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Filter Windows artifacts by case description using LLM.

        Args:
            windows_db_path: Path to _windows.db
            case_description: Case description for filtering
            max_artifacts: Maximum artifacts to select per type
            artifact_types: List of artifact types to filter (None = all)
            progress_callback: Optional progress callback

        Returns:
            Dictionary with filtered artifact IDs by type
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        from ...graphiti_integration.database_reader import WindowsDatabase

        # Use all artifact types if not specified
        if artifact_types is None:
            artifact_types = self.ARTIFACT_TYPES

        logger.info(f"Filtering Windows artifacts for case: {case_description[:100]}...")

        # Open database connection
        windows_db = WindowsDatabase(windows_db_path)
        selected_by_type = {}

        for i, artifact_type in enumerate(artifact_types):
            if progress_callback:
                await progress_callback("filtering", f"正在筛选{self._get_type_display_name(artifact_type)}...", i + 1, len(artifact_types))

            try:
                # Get artifacts of this type
                artifacts = await self._get_artifacts_by_type(windows_db, artifact_type, limit=500)

                if not artifacts:
                    logger.debug(f"No artifacts found for type: {artifact_type}")
                    continue

                # Build batch summary for LLM
                batch_summary = self._build_artifact_batch(artifacts, artifact_type)

                # Call LLM to filter
                selected_ids = await self._llm_filter_artifacts(
                    case_description=case_description,
                    artifact_type=artifact_type,
                    batch_summary=batch_summary,
                    max_artifacts=max_artifacts
                )

                selected_by_type[artifact_type] = selected_ids
                logger.info(f"Selected {len(selected_ids)} {artifact_type} artifacts")

            except Exception as e:
                logger.error(f"Error filtering {artifact_type}: {e}", exc_info=True)
                selected_by_type[artifact_type] = []

        total_selected = sum(len(ids) for ids in selected_by_type.values())
        logger.info(f"Filtering complete: {total_selected} artifacts selected across {len(selected_by_type)} types")

        return {
            "selected_by_type": selected_by_type,
            "total_selected": total_selected,
            "types_processed": list(selected_by_type.keys()),
        }

    async def _get_artifacts_by_type(
        self,
        windows_db,
        artifact_type: str,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Get artifacts of a specific type from the database."""
        try:
            if artifact_type == "registry_values":
                return windows_db.get_registry_values(limit=limit)
            elif artifact_type == "event_log_entries":
                return windows_db.get_event_logs(limit=limit)
            elif artifact_type == "prefetch_files":
                return windows_db.get_prefetch_files(limit=limit)
            elif artifact_type == "browser_history":
                return windows_db.get_browser_history(limit=limit)
            elif artifact_type == "usb_devices":
                return windows_db.get_usb_devices(limit=limit)
            elif artifact_type == "user_accounts":
                return windows_db.get_user_accounts(limit=limit)
            elif artifact_type == "windows_services":
                return windows_db.get_services(limit=limit)
            else:
                logger.warning(f"Unsupported artifact type for filtering: {artifact_type}")
                return []
        except Exception as e:
            logger.error(f"Error getting {artifact_type}: {e}", exc_info=True)
            return []

    def _build_artifact_batch(
        self,
        artifacts: List[Dict[str, Any]],
        artifact_type: str
    ) -> str:
        """Build a summary string of artifacts for LLM processing."""
        lines = [f"=== {self._get_type_display_name(artifact_type)} ==="]

        for artifact in artifacts[:100]:  # Limit to 100 for context
            summary = self._get_artifact_summary(artifact, artifact_type)
            lines.append(f"[{artifact.get('id', '?')}] {summary}")

        return "\n".join(lines)

    def _get_artifact_summary(
        self,
        artifact: Dict[str, Any],
        artifact_type: str
    ) -> str:
        """Get a brief summary of an artifact for filtering display."""
        if artifact_type == "registry_values":
            key = artifact.get("key_path", "")[:60]
            value = artifact.get("value_name", "")
            data = str(artifact.get("value_data", ""))[:40]
            return f"注册表: {key} | {value} = {data}"

        elif artifact_type == "event_log_entries":
            log = artifact.get("log_name", "")
            event_id = artifact.get("event_id", "")
            level = artifact.get("level", "")
            time = artifact.get("timestamp", 0)
            return f"事件日志: [{log}] ID={event_id} 级别={level} 时间={time}"

        elif artifact_type == "prefetch_files":
            exe = artifact.get("executable_name", "")
            runs = artifact.get("run_count", 0)
            return f"Prefetch: {exe} (运行{runs}次)"

        elif artifact_type == "browser_history":
            url = artifact.get("url", "")[:60]
            title = artifact.get("title", "")[:40]
            return f"浏览器: {url} | {title}"

        elif artifact_type == "usb_devices":
            name = artifact.get("device_name", "")
            serial = artifact.get("serial_number", "")
            return f"USB设备: {name} | 序列号: {serial}"

        elif artifact_type == "user_accounts":
            username = artifact.get("username", "")
            sid = artifact.get("sid", "")
            return f"用户账户: {username} | SID: {sid}"

        elif artifact_type == "windows_services":
            name = artifact.get("service_name", "")
            display = artifact.get("display_name", "")
            return f"服务: {name} | {display}"

        else:
            # Generic summary
            return str(artifact)[:100]

    async def _llm_filter_artifacts(
        self,
        case_description: str,
        artifact_type: str,
        batch_summary: str,
        max_artifacts: int
    ) -> List[str]:
        """Use LLM to filter artifacts based on case description."""
        system_prompt = """你是一名经验丰富的数字取证分析师，正在对Windows系统痕迹进行筛选。

你的任务是根据案情描述，从Windows系统痕迹列表中筛选出与案情最相关的记录。

筛选原则：
1. 优先级最高：直接涉案的痕迹（如可疑程序执行、异常登录、数据导出操作等）
2. 优先级高：可能包含关键证据的痕迹（如浏览器访问记录、文件操作记录、USB设备使用等）
3. 优先级中：可能提供辅助信息的痕迹（如系统服务变更、计划任务创建等）

请以严格的 JSON 格式返回结果，不要包含任何其他文字或标记。

返回格式：
{
  "selected_artifacts": ["ID1", "ID2", ...],
  "reasoning": "筛选理由的简要说明"
}"""

        user_prompt = f"""案情描述：
{case_description}

{self._get_type_display_name(artifact_type)}列表：
{batch_summary}

请从中筛选出与案情最相关的记录（最多 {max_artifacts} 条）。"""

        try:
            result = await self._llm_service.analyze(
                content=user_prompt,
                model_type="text",
                prompt=system_prompt
            )

            analysis = result.get("analysis", {})
            response_text = analysis.get("description", "")

            # Parse JSON response
            response_data = self._parse_llm_filter_response(response_text)
            selected_ids = response_data.get("selected_artifacts", [])

            # Convert to strings and limit
            return [str(sid) for sid in selected_ids[:max_artifacts]]

        except Exception as e:
            logger.error(f"LLM filtering failed for {artifact_type}: {e}", exc_info=True)
            return []

    def _parse_llm_filter_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM filter response, handling various JSON formats."""
        try:
            # Try direct JSON parse
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
            # Fallback
            logger.warning(f"Could not parse LLM filter response: {response[:200]}")
            return {"selected_artifacts": [], "reasoning": "Parse error"}

    def _get_type_display_name(self, artifact_type: str) -> str:
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
