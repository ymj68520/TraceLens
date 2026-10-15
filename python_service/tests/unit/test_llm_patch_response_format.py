"""
Unit tests for llm_patch response_format fallback.

Covers:
- A provider that rejects response_format outright with a 400 (LM Studio only
  accepts json_schema/text, not json_object) must fall through to the
  plain-text retry instead of failing the episode.
- GRAPHITI_STRUCTURED_OUTPUT_MODE=json_schema switches the first attempt to a
  json_schema response_format carrying the model's schema.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import graphiti_core  # noqa: F401
    from openai import BadRequestError
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    import graphiti_integration.llm_patch  # noqa: F401  (applies the patch)
    _HAS_GRAPHITI = True
except ImportError:
    _HAS_GRAPHITI = False


class _Answer(BaseModel):
    answer: int


def _completion(payload: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


def _bad_request() -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request('POST', 'http://test/v1/chat/completions'))
    return BadRequestError("'response_format.type' must be 'json_schema' or 'text'",
                           response=response, body={'error': 'bad response_format'})


class _StubCompletions:
    """Scripted chat.completions.create: each item is a response or an exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _make_client(completions_stub) -> OpenAIGenericClient:
    client = OpenAIGenericClient(config=LLMConfig(api_key='test', model='test-model',
                                                  base_url='http://localhost:9/v1'))
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions_stub))
    return client


@pytest.mark.skipif(not _HAS_GRAPHITI, reason='graphiti_core not installed')
@pytest.mark.asyncio
async def test_rejected_response_format_falls_back_to_plain_text(monkeypatch):
    # Pin json_object explicitly: local .env files may select json_schema.
    monkeypatch.setenv('GRAPHITI_STRUCTURED_OUTPUT_MODE', 'json_object')
    completions = _StubCompletions([
        _bad_request(),
        _completion('{"answer": 42}'),
    ])
    client = _make_client(completions)
    messages = [SimpleNamespace(role='system', content='Extract entities.'),
                SimpleNamespace(role='user', content='hello')]

    result = await OpenAIGenericClient._generate_response(client, messages, response_model=_Answer)

    assert result == {'answer': 42}
    assert len(completions.calls) == 2
    # First call carried the (rejected) structured response_format…
    assert completions.calls[0]['response_format'] == {'type': 'json_object'}
    # …the fallback must not send any response_format at all.
    assert 'response_format' not in completions.calls[1]
    # The schema must ride in the prompt so the model can still comply.
    assert 'answer' in completions.calls[1]['messages'][0]['content']


@pytest.mark.skipif(not _HAS_GRAPHITI, reason='graphiti_core not installed')
@pytest.mark.asyncio
async def test_json_schema_mode_when_env_selected(monkeypatch):
    monkeypatch.setenv('GRAPHITI_STRUCTURED_OUTPUT_MODE', 'json_schema')
    completions = _StubCompletions([_completion('{"answer": 7}')])
    client = _make_client(completions)
    messages = [SimpleNamespace(role='system', content='Extract entities.'),
                SimpleNamespace(role='user', content='hello')]

    result = await OpenAIGenericClient._generate_response(client, messages, response_model=_Answer)

    assert result == {'answer': 7}
    assert completions.calls[0]['response_format']['type'] == 'json_schema'
    assert completions.calls[0]['response_format']['json_schema']['name'] == '_Answer'
