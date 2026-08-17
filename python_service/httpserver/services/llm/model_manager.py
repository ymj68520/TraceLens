"""
Model Manager Module - LLM model status and health monitoring.

This module handles:
- Model availability checking
- Health status monitoring
- Model information retrieval
"""

import logging
from typing import Any, Dict, Optional

import httpx

from ...config import Settings

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Manages LLM model status and health checks.

    Provides:
    - Model availability checking
    - Health monitoring
    - Model information
    """

    def __init__(self, settings: Settings):
        """
        Initialize model manager.

        Args:
            settings: Application settings.
        """
        self.settings = settings

    async def check_model_status(
        self,
        model_type: str,
        text_client: Optional[httpx.AsyncClient] = None,
        vision_client: Optional[httpx.AsyncClient] = None,
    ) -> bool:
        """
        Check if a specific model is available.

        Args:
            model_type: 'text' or 'vision'.
            text_client: Optional HTTP client for text model.
            vision_client: Optional HTTP client for vision model.

        Returns:
            True if model is available.
        """
        try:
            if model_type == "text":
                if text_client:
                    response = await text_client.get("/v1/models")
                    return response.status_code == 200
                base_url = self.settings.llm_text_base_url
            else:
                if vision_client:
                    response = await vision_client.get("/v1/models")
                    return response.status_code == 200
                base_url = self.settings.llm_vision_base_url

            # No persistent client available, create temporary one
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(10.0),
            ) as tmp_client:
                response = await tmp_client.get("/v1/models")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Model status check failed for {model_type}: {e}")
            return False

    async def health_check(
        self,
        text_client: Optional[httpx.AsyncClient] = None,
        vision_client: Optional[httpx.AsyncClient] = None,
    ) -> bool:
        """
        Check if LLM service is healthy.

        Args:
            text_client: Optional HTTP client for text model.
            vision_client: Optional HTTP client for vision model.

        Returns:
            True if at least one model is available.
        """
        text_ok = await self.check_model_status("text", text_client, vision_client)
        vision_ok = await self.check_model_status("vision", text_client, vision_client)
        return text_ok or vision_ok

    async def get_status(
        self,
        text_client: Optional[httpx.AsyncClient] = None,
        vision_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Get the status of LLM services.

        Args:
            text_client: Optional HTTP client for text model.
            vision_client: Optional HTTP client for vision model.

        Returns:
            Status information dict.
        """
        text_available = await self.check_model_status("text", text_client, vision_client)
        vision_available = await self.check_model_status("vision", text_client, vision_client)

        return {
            "status": "available" if (text_available or vision_available) else "unavailable",
            "text_model": {
                "name": self.settings.llm_text_model,
                "base_url": self.settings.llm_text_base_url,
                "available": text_available,
            },
            "vision_model": {
                "name": self.settings.llm_vision_model,
                "base_url": self.settings.llm_vision_base_url,
                "available": vision_available,
            },
        }

    async def list_models(
        self,
        model_type: str,
        text_client: Optional[httpx.AsyncClient] = None,
        vision_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        List available models for a specific type.

        Args:
            model_type: 'text' or 'vision'.
            text_client: Optional HTTP client for text model.
            vision_client: Optional HTTP client for vision model.

        Returns:
            Dict with model information.
        """
        try:
            if model_type == "text":
                client = text_client
                base_url = self.settings.llm_text_base_url
                default_model = self.settings.llm_text_model
            else:
                client = vision_client
                base_url = self.settings.llm_vision_base_url
                default_model = self.settings.llm_vision_model

            if client:
                response = await client.get("/v1/models")
                response.raise_for_status()
                data = response.json()
                return {
                    "models": data.get("data", []),
                    "default_model": default_model,
                    "base_url": base_url,
                }
            else:
                # No client available, return default info
                return {
                    "models": [],
                    "default_model": default_model,
                    "base_url": base_url,
                    "note": "Client not initialized, only returning default configuration",
                }
        except Exception as e:
            logger.error(f"Failed to list {model_type} models: {e}")
            return {
                "models": [],
                "default_model": default_model if model_type == "text" else self.settings.llm_vision_model,
                "base_url": base_url,
                "error": "llm service is unavailable",
            }
