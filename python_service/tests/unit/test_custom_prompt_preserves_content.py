"""Tests for FileAnalyzer.analyze_file prompt assembly (A8).

Validates the S0-6 fix: when a custom prompt is supplied, the Evidence content is
STILL sent to the LLM (together with the analyst instruction), and when no prompt
is supplied the original default template is used unchanged.

No real LLM call is made: httpx.AsyncClient.post is faked to capture the request.
"""

from types import SimpleNamespace

import pytest

from httpserver.services.llm.file_analyzer import FileAnalyzer


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "OUT"}}], "usage": {"total_tokens": 1}}


class _FakeClient:
    def __init__(self):
        self.captured = None

    async def post(self, url, json=None, headers=None):
        self.captured = json
        return _FakeResponse()


def _make_analyzer() -> FileAnalyzer:
    settings = SimpleNamespace(
        llm_text_model="m",
        llm_text_max_tokens=100,
        llm_text_temperature=0.1,
        llm_text_base_url="http://x",
        llm_endpoint="/x",
        llm_api_key=None,
    )
    return FileAnalyzer(settings)


@pytest.mark.asyncio
async def test_A8_custom_prompt_keeps_evidence_content():
    fa = _make_analyzer()
    client = _FakeClient()

    await fa.analyze_file(
        "SECRET_EVIDENCE_CONTENT", client, None, "text",
        prompt="请重点查找账号凭据",
    )

    user_msg = client.captured["messages"][1]["content"]
    assert "SECRET_EVIDENCE_CONTENT" in user_msg
    assert "请重点查找账号凭据" in user_msg


@pytest.mark.asyncio
async def test_A8_no_prompt_uses_default_template():
    fa = _make_analyzer()
    client = _FakeClient()

    await fa.analyze_file("PLAIN_CONTENT", client, None, "text")

    user_msg = client.captured["messages"][1]["content"]
    assert "PLAIN_CONTENT" in user_msg
    # default template must NOT carry the instruction section
    assert "调查人员补充要求" not in user_msg
