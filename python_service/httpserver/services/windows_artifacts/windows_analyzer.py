"""
Windows Artifact Analyzer Module — LLM-driven Windows artifact analysis.

This module handles LLM analysis of Windows forensic artifacts including
registry, event logs, browser history, prefetch files, and more.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ...config import Settings

logger = logging.getLogger(__name__)


class WindowsArtifactAnalyzer:
    """Handles Windows artifact analysis operations."""

    def __init__(self, settings: Settings, llm_service, graphiti_service):
        """
        Initialize WindowsArtifactAnalyzer.

        Args:
            settings: Application settings
            llm_service: LLM service for analysis
            graphiti_service: Knowledge graph service (optional)
        """
        self.settings = settings
        self._llm_service = llm_service
        self._graphiti_service = graphiti_service

    async def analyze_selected_artifacts(
        self,
        windows_db_path: str,
        selected_by_type: Dict[str, List[str]],
        case_description: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Analyze selected Windows artifacts using LLM.

        Args:
            windows_db_path: Path to _windows.db
            selected_by_type: Dictionary of artifact_type -> [artifact_ids]
            case_description: Case description for context
            progress_callback: Optional progress callback

        Returns:
            List of analysis results
        """
        from graphiti_integration.database_reader import WindowsDatabase

        windows_db = WindowsDatabase(windows_db_path)
        results = []

        # Get total artifact count for progress tracking
        total_artifacts = sum(len(ids) for ids in selected_by_type.values())
        processed = 0

        # Concurrency control
        sem = asyncio.Semaphore(self.settings.llm_max_concurrency if hasattr(self.settings, "llm_max_concurrency") else 3)

        async def analyze_single(artifact_type: str, artifact_id: str) -> Dict[str, Any]:
            nonlocal processed
            async with sem:
                try:
                    # Get artifact from database
                    artifacts = await self._get_artifacts_by_type(windows_db, artifact_type)
                    artifact = next((a for a in artifacts if str(a.get("id")) == str(artifact_id)), None)

                    if not artifact:
                        return {
                            "id": artifact_id,
                            "type": artifact_type,
                            "success": False,
                            "error": "Artifact not found"
                        }

                    # Analyze
                    result = await self._analyze_single_artifact(
                        artifact=artifact,
                        artifact_type=artifact_type,
                        case_description=case_description
                    )

                    processed += 1
                    if progress_callback:
                        await progress_callback("analyzing", processed, total_artifacts, f"{artifact_type}:{artifact_id}")

                    return result

                except Exception as e:
                    logger.error(f"Error analyzing {artifact_type}:{artifact_id}: {e}")
                    return {
                        "id": artifact_id,
                        "type": artifact_type,
                        "success": False,
                        "error": str(e)
                    }

        # Build analysis tasks
        tasks = []
        for artifact_type, artifact_ids in selected_by_type.items():
            for artifact_id in artifact_ids:
                tasks.append(analyze_single(artifact_type, artifact_id))

        # Run analyses concurrently
        results = await asyncio.gather(*tasks)

        return [r for r in results if r]

    async def _analyze_single_artifact(
        self,
        artifact: Dict[str, Any],
        artifact_type: str,
        case_description: str,
        user_hint: str = "",
    ) -> Dict[str, Any]:
        """Analyze a single artifact with LLM."""
        try:
            # Build prompt for this artifact
            prompt = self._build_analysis_prompt(
                artifact=artifact,
                artifact_type=artifact_type,
                case_description=case_description,
                user_hint=user_hint
            )

            # Call LLM
            result = await self._llm_service.analyze(
                content="",
                model_type="text",
                prompt=prompt
            )

            analysis = result.get("analysis", {})
            description = analysis.get("description", "")

            # Extract structured information
            summary = self._extract_summary(description)
            keywords = self._extract_keywords(description)
            severity = self._assess_severity(description, artifact_type)
            relevance = self._assess_relevance(description, case_description)

            return {
                "id": artifact.get("id"),
                "type": artifact_type,
                "summary": summary,
                "description": description,
                "keywords": keywords,
                "severity": severity,
                "relevance": relevance,
                "model_used": result.get("model", ""),
                "analyzed_at": int(time.time()),
                "success": True
            }

        except Exception as e:
            logger.error(f"Error in _analyze_single_artifact: {e}", exc_info=True)
            return {
                "id": artifact.get("id"),
                "type": artifact_type,
                "success": False,
                "error": str(e)
            }

    def _build_analysis_prompt(
        self,
        artifact: Dict[str, Any],
        artifact_type: str,
        case_description: str,
        user_hint: str = "",
    ) -> str:
        """Build LLM prompt for artifact analysis."""
        # Format artifact data
        artifact_data = self._format_artifact_for_prompt(artifact, artifact_type)

        user_hint_section = f"\n\n## 用户补充说明\n{user_hint}" if user_hint else ""

        prompt = f"""你是一名资深数字取证分析师，正在对Windows系统痕迹进行深度分析。

案情背景：
{case_description}{user_hint_section}

待分析的{self._get_type_display_name(artifact_type)}记录：
{artifact_data}

请对该记录进行专业的取证分析，包含以下内容：

1. 痕迹概述
   简要说明该痕迹的类型、来源和基本含义

2. 内容详细分析
   分析该痕迹中的关键信息：
   - 对于注册表：分析键值含义、配置意图、潜在影响
   - 对于事件日志：分析事件含义、触发条件、异常特征
   - 对于浏览器历史：分析访问意图、URL性质、时间模式
   - 对于prefetch：分析程序执行意图、执行频率、时间特征
   - 对于服务/任务：分析功能用途、启动方式、潜在风险

3. 与案情的关联分析
   分析该痕迹与案情描述之间的关联性，指出哪些内容可能直接或间接与案件有关

4. 关键发现与可疑信息
   标注痕迹中发现的任何异常、可疑或值得特别关注的信息

5. 取证价值评估
   评估该痕迹对调查的潜在价值（高/中/低），并说明理由

注意事项：
- 请使用纯文本格式输出，不要使用任何 Markdown 标记
- 所有内容使用中文
- 保持客观专业的取证分析语气
- 对不确定的内容标注"待进一步确认"而非臆断"""

        return prompt

    def _format_artifact_for_prompt(
        self,
        artifact: Dict[str, Any],
        artifact_type: str
    ) -> str:
        """Format artifact data for LLM prompt."""
        lines = [f"类型: {artifact_type}"]

        if artifact_type == "registry_values":
            lines.append(f"注册表路径: {artifact.get('key_path', '')}")
            lines.append(f"值名称: {artifact.get('value_name', '')}")
            lines.append(f"值类型: {artifact.get('value_type', '')}")
            lines.append(f"值数据: {artifact.get('value_data', '')}")
            lines.append(f"修改时间: {artifact.get('last_modified', '')}")

        elif artifact_type == "event_log_entries":
            lines.append(f"日志名称: {artifact.get('log_name', '')}")
            lines.append(f"事件ID: {artifact.get('event_id', '')}")
            lines.append(f"级别: {artifact.get('level', '')}")
            lines.append(f"来源: {artifact.get('source', '')}")
            lines.append(f"时间戳: {artifact.get('timestamp', '')}")
            lines.append(f"计算机: {artifact.get('computer', '')}")
            lines.append(f"消息: {artifact.get('message', '')[:500]}")

        elif artifact_type == "prefetch_files":
            lines.append(f"可执行文件名: {artifact.get('executable_name', '')}")
            lines.append(f"运行次数: {artifact.get('run_count', '')}")
            lines.append(f"最后运行时间: {artifact.get('last_run_time', '')}")
            lines.append(f"文件路径: {artifact.get('file_path', '')}")

        elif artifact_type == "browser_history":
            lines.append(f"URL: {artifact.get('url', '')}")
            lines.append(f"标题: {artifact.get('title', '')}")
            lines.append(f"访问次数: {artifact.get('visit_count', '')}")
            lines.append(f"最后访问: {artifact.get('last_visit', '')}")
            lines.append(f"浏览器: {artifact.get('browser_name', '')}")

        elif artifact_type == "usb_devices":
            lines.append(f"设备名称: {artifact.get('device_name', '')}")
            lines.append(f"供应商ID: {artifact.get('vendor_id', '')}")
            lines.append(f"产品ID: {artifact.get('product_id', '')}")
            lines.append(f"序列号: {artifact.get('serial_number', '')}")
            lines.append(f"首次连接: {artifact.get('first_connected', '')}")
            lines.append(f"最后连接: {artifact.get('last_connected', '')}")

        elif artifact_type == "user_accounts":
            lines.append(f"用户名: {artifact.get('username', '')}")
            lines.append(f"SID: {artifact.get('sid', '')}")
            lines.append(f"全名: {artifact.get('full_name', '')}")
            lines.append(f"账户类型: {artifact.get('account_type', '')}")
            lines.append(f"最后登录: {artifact.get('last_login', '')}")

        elif artifact_type == "windows_services":
            lines.append(f"服务名: {artifact.get('service_name', '')}")
            lines.append(f"显示名: {artifact.get('display_name', '')}")
            lines.append(f"二进制路径: {artifact.get('binary_path', '')}")
            lines.append(f"启动类型: {artifact.get('start_type', '')}")
            lines.append(f"服务类型: {artifact.get('service_type', '')}")
            lines.append(f"状态: {artifact.get('state', '')}")

        else:
            # Generic format
            for key, value in artifact.items():
                if value and key != 'id':
                    lines.append(f"{key}: {value}")

        return "\n".join(lines)

    def _extract_summary(self, description: str) -> str:
        """Extract brief summary from description."""
        # Get first sentence or first 150 chars
        first_period = description.find('。')
        if first_period > 0 and first_period < 150:
            return description[:first_period + 1]

        lines = description.split('\n')
        for line in lines[:3]:
            line = line.strip()
            if line and not line.startswith(('1.', '2.', '3.', '4.', '5.', '-')):
                return line[:150]

        return description[:150]

    def _extract_keywords(self, description: str) -> str:
        """Extract keywords from description."""
        # Extract Chinese phrases (2-6 characters)
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,6}', description[:500])
        unique_keywords = list(set(keywords))[:8]
        return ", ".join(unique_keywords)

    def _assess_severity(self, description: str, artifact_type: str) -> str:
        """Assess severity level from description."""
        description_lower = description.lower()

        # Critical indicators
        critical_patterns = [
            '恶意', 'malware', 'virus', 'trojan', '后门', 'backdoor',
            '攻击', 'attack', 'exploit', '漏洞利用', '数据泄露'
        ]
        for pattern in critical_patterns:
            if pattern in description_lower or pattern in description:
                return "critical"

        # High indicators
        high_patterns = [
            '可疑', 'suspicious', '异常', 'abnormal', '删除', 'deleted',
            '清除', 'cleared', '未授权', 'unauthorized', '提权', 'privilege'
        ]
        for pattern in high_patterns:
            if pattern in description_lower or pattern in description:
                return "high"

        # Medium indicators
        medium_patterns = [
            '风险', 'risk', '注意', 'attention', '监控', 'monitor',
            '外设', 'usb', '远程', 'remote', '网络', 'network'
        ]
        for pattern in medium_patterns:
            if pattern in description_lower or pattern in description:
                return "medium"

        return "low"

    def _assess_relevance(self, description: str, case_description: str) -> float:
        """Assess relevance score (0.0-1.0)."""
        if not case_description:
            return 0.5

        # Simple keyword matching for relevance
        description_lower = description.lower()
        case_words = re.findall(r'[\w]+', case_description.lower())

        matches = 0
        for word in case_words:
            if len(word) >= 2 and word in description_lower:
                matches += 1

        # Base relevance on match count
        relevance = min(0.3 + (matches * 0.1), 1.0)
        return round(relevance, 2)

    async def _get_artifacts_by_type(
        self,
        windows_db,
        artifact_type: str,
        limit: int = 1000
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
                logger.warning(f"Unsupported artifact type: {artifact_type}")
                return []
        except Exception as e:
            logger.error(f"Error getting {artifact_type}: {e}")
            return []

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

    async def ingest_to_knowledge_graph(
        self,
        task_id: str,
        case_description: str,
        artifact_descriptions: List[Dict[str, Any]],
        cluster_descriptions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Ingest Windows artifact descriptions into Graphiti knowledge graph.

        Routes through GraphitiService.ingest_task_episodes (add_episode) so the
        extractor can build entities/relationships. The previous implementation
        called a non-existent ``self._graphiti_service.ingest(...)``.
        """
        if not self._graphiti_service:
            logger.warning("Graphiti service not available")
            return False

        try:
            normalized = []
            for desc in artifact_descriptions:
                if not desc.get("success"):
                    continue
                body = (desc.get("description", "") or "") + "\n\n摘要: " + (desc.get("summary", "") or "")
                normalized.append({
                    "file_path": f"Windows_{desc.get('type', 'artifact')}_{desc.get('id', '')}",
                    "description": body,
                    "category": f"windows_{desc.get('type', 'artifact')}",
                    "success": True,
                })

            if not normalized:
                return True

            result = await self._graphiti_service.ingest_task_episodes(
                task_id=task_id,
                file_descriptions=normalized,
                cluster_descriptions=cluster_descriptions,
                case_description=case_description,
            )
            logger.info(
                f"Ingested Windows artifacts: "
                f"{result.get('successful', 0)}/{result.get('total', 0)} successful"
            )
            return bool(result.get("success"))

        except Exception as e:
            logger.error(f"Error ingesting to Graphiti: {e}")
            return False
