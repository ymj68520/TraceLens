"""Regression tests for OpenAI-compatible LLM endpoint handling."""

from unittest.mock import AsyncMock

import pytest

from httpserver.config import Settings
from httpserver.services.llm.file_analyzer import FileAnalyzer


class _Response:
    def __init__(self):
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 1},
        }


@pytest.mark.asyncio
async def test_file_analysis_uses_chat_completions_endpoint():
    settings = Settings(
        LLM_ENDPOINT="/v1/chat/completions",
        LLM_TEXT_MODEL="test-model",
    )
    client = AsyncMock()
    client.post.return_value = _Response()

    result = await FileAnalyzer(settings).analyze_file(
        "test content",
        text_client=client,
        vision_client=AsyncMock(),
    )

    assert result["analysis"]["description"] == "ok"
    assert client.post.call_args.args[0] == "/v1/chat/completions"


def test_channel_api_key_falls_back_to_shared_key():
    settings = Settings(LLM_API_KEY="shared-key", _env_file=None)

    assert settings.llm_api_key_for("text") == "shared-key"
    assert settings.llm_api_key_for("vision") == "shared-key"


def test_channel_api_key_override_wins():
    settings = Settings(
        LLM_API_KEY="shared-key",
        LLM_TEXT_API_KEY="text-key",
        LLM_VISION_API_KEY="vision-key",
        _env_file=None,
    )

    assert settings.llm_api_key_for("text") == "text-key"
    assert settings.llm_api_key_for("vision") == "vision-key"


def test_blank_channel_api_key_falls_back_to_shared_key():
    """An empty placeholder line in .env means 'not configured', not 'no auth'."""
    settings = Settings(
        LLM_API_KEY="shared-key",
        LLM_TEXT_API_KEY="",
        LLM_VISION_API_KEY="   ",
        _env_file=None,
    )

    assert settings.llm_api_key_for("text") == "shared-key"
    assert settings.llm_api_key_for("vision") == "shared-key"


@pytest.mark.asyncio
async def test_model_name_endpoint_is_normalized():
    settings = Settings(
        LLM_ENDPOINT="deepseek-v4-flash-0731",
        LLM_TEXT_MODEL="test-model",
    )

    assert settings.llm_endpoint == "/v1/chat/completions"
