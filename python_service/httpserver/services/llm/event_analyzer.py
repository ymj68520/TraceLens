"""
Event Analyzer Module - Event cluster analysis operations.

This module handles:
- Event cluster analysis using LLM
- Parsing structured analysis from LLM responses
- Event-specific prompt management
"""

import logging
import re
from typing import Any, Dict, Optional

import httpx

from ...config import Settings
from ...prompts import (
    EVENT_CLUSTER_ANALYSIS_SYSTEM,
    EVENT_CLUSTER_ANALYSIS_DEFAULT,
    EVENT_CLUSTER_REANALYSIS_PROMPT,
)

logger = logging.getLogger(__name__)


class EventAnalyzer:
    """
    Handles event cluster analysis operations.

    Provides:
    - Event cluster analysis with LLM
    - Structured response parsing
    - Custom prompt support for reanalysis
    """

    def __init__(self, settings: Settings):
        """
        Initialize event analyzer.

        Args:
            settings: Application settings.
        """
        self.settings = settings

    # Max characters for event description before sending to LLM
    MAX_DESCRIPTION_CHARS = 8000

    async def analyze_event_cluster(
        self,
        event_data: Dict[str, Any],
        text_client: httpx.AsyncClient,
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an event cluster using LLM.

        Args:
            event_data: Event cluster data with event_type, file_path, description, etc.
            text_client: HTTP client for text model.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).

        Returns:
            Analysis result dict.
        """
        # Build event cluster content for analysis
        event_type = event_data.get("event_type", "UNKNOWN")
        file_path = event_data.get("file_path", "")
        description = event_data.get("description", "")
        timestamp = event_data.get("timestamp", 0)
        time_window = event_data.get("time_window", 0)

        # Truncate description to avoid exceeding model context window
        if len(description) > self.MAX_DESCRIPTION_CHARS:
            logger.info(
                f"Truncating event description from {len(description)} to {self.MAX_DESCRIPTION_CHARS} chars"
            )
            description = description[:self.MAX_DESCRIPTION_CHARS] + "\n... [truncated]"

        # Count events in description for context
        event_count = description.count('\n') + 1 if description else 0

        # Select model settings
        if not text_client:
            raise RuntimeError("Text model client not initialized")
        model = self.settings.llm_text_model
        default_max_tokens = self.settings.llm_text_max_tokens
        default_temperature = self.settings.llm_text_temperature
        logger.info(f"Using text model: {model} for event cluster analysis")

        # Build prompt using professional Chinese prompts
        system_prompt = EVENT_CLUSTER_ANALYSIS_SYSTEM

        # Use custom prompt if provided, otherwise use default template
        if prompt and "重新" in prompt:
            # Reanalysis mode
            user_prompt = EVENT_CLUSTER_REANALYSIS_PROMPT.format(
                case_context=prompt,
                event_type=event_type,
                time_window=time_window,
                event_count=event_count,
                description=description
            )
        elif prompt:
            # Custom prompt provided
            user_prompt = f"{prompt}\n\n事件类型：{event_type}\n时间窗口：{time_window}\n事件数量：{event_count}\n事件描述：\n{description}"
        else:
            # Default analysis mode
            user_prompt = EVENT_CLUSTER_ANALYSIS_DEFAULT.format(
                event_type=event_type,
                time_window=time_window,
                event_count=event_count,
                description=description
            )

        # Make API request
        try:
            response = await text_client.post(
                self.settings.llm_endpoint,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": max_tokens or default_max_tokens,
                    "temperature": temperature or default_temperature,
                },
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {},
            )
            response.raise_for_status()

            result = response.json()

            # Extract response
            analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)

            # Parse structured analysis from LLM response
            parsed_analysis = self._parse_event_cluster_analysis(analysis_text)

            return {
                "analysis": {
                    "summary": parsed_analysis.get("summary", ""),
                    "description": parsed_analysis.get("description", analysis_text),
                    "keywords": parsed_analysis.get("keywords", []),
                    "is_relevant": parsed_analysis.get("is_relevant", True),
                },
                "model": model,
                "tokens_used": tokens_used,
            }
        except httpx.ReadTimeout as e:
            logger.error(f"LLM request timed out after {self.settings.llm_timeout_seconds}s for event cluster analysis")
            raise RuntimeError(
                f"LLM request timed out after {self.settings.llm_timeout_seconds}s. "
                "Consider increasing LLM_TIMEOUT_SECONDS or reducing input size."
            ) from e
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"LLM request failed with status {e.response.status_code}: {e.response.text}") from e
        except httpx.ConnectError as e:
            logger.error(f"LLM connection error: {e}")
            raise RuntimeError(f"Cannot connect to LLM service at {self.settings.llm_text_base_url}") from e
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}", exc_info=True)
            raise

    def _parse_event_cluster_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """
        Parse LLM analysis response into structured fields.

        Args:
            analysis_text: Raw LLM response text.

        Returns:
            Dict with keys: summary, description, keywords, is_relevant.
        """
        result = {
            "summary": "",
            "description": analysis_text,
            "keywords": [],
            "is_relevant": True,
        }

        if not analysis_text:
            return result

        lines = analysis_text.split('\n')
        current_section = None
        content_parts = []

        for line in lines:
            line = line.strip()

            # Detect summary section
            if re.match(r'^(简要总结|总结|摘要|summary)', line, re.IGNORECASE):
                if content_parts:
                    if current_section == "description":
                        result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "summary"
                continue

            # Detect detailed description section
            elif re.match(r'^(详细分析|描述|详细描述|description|分析)', line, re.IGNORECASE):
                if content_parts and current_section == "summary":
                    result["summary"] = '\n'.join(content_parts).strip()
                    content_parts = []
                elif content_parts and current_section == "description":
                    result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "description"
                continue

            # Detect keywords section
            elif re.match(r'^(关键词|keywords)', line, re.IGNORECASE):
                if content_parts:
                    if current_section == "summary":
                        result["summary"] = '\n'.join(content_parts).strip()
                    elif current_section == "description":
                        result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "keywords"
                keywords_match = re.search(r'[:：]\s*(.+)', line)
                if keywords_match:
                    keywords_text = keywords_match.group(1)
                    result["keywords"] = [kw.strip() for kw in re.split(r'[,，、]', keywords_text) if kw.strip()]
                continue

            # Detect forensic value section
            elif re.match(r'^(取证价值|价值评估|forensic.*value)', line, re.IGNORECASE):
                if content_parts and current_section == "description":
                    result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "value"
                continue

            # Process content based on current section
            if current_section == "keywords":
                if line and not line.startswith('-') and not line.startswith('•'):
                    keywords_match = re.search(r'[:：]\s*(.+)', line)
                    if keywords_match:
                        keywords_text = keywords_match.group(1)
                        result["keywords"].extend([kw.strip() for kw in re.split(r'[,，、]', keywords_text) if kw.strip()])
                    else:
                        result["keywords"].extend([kw.strip() for kw in re.split(r'[,，、]', line) if kw.strip()])
            elif current_section == "value":
                if '低' in line or '无关' in line:
                    result["is_relevant"] = False
            elif current_section in ["summary", "description"]:
                content_parts.append(line)

        # Handle remaining content
        if content_parts:
            if current_section == "summary":
                result["summary"] = '\n'.join(content_parts).strip()
            elif current_section == "description" or not current_section:
                result["description"] = '\n'.join(content_parts).strip()

        # Fallback: if no summary found, use first 200 chars of description
        if not result["summary"] and result["description"]:
            result["summary"] = result["description"][:200] + ("..." if len(result["description"]) > 200 else "")

        # Clean up keywords (deduplicate and limit)
        if result["keywords"]:
            seen = set()
            unique_keywords = []
            for kw in result["keywords"]:
                if kw.lower() not in seen:
                    seen.add(kw.lower())
                    unique_keywords.append(kw)
            result["keywords"] = unique_keywords[:5]

        return result
