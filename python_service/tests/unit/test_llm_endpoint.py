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


@pytest.mark.asyncio
async def test_model_name_endpoint_is_normalized():
    settings = Settings(
        LLM_ENDPOINT="deepseek-v4-flash-0731",
        LLM_TEXT_MODEL="test-model",
    )

    assert settings.llm_endpoint == "/v1/chat/completions"
