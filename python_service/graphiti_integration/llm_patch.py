"""
Runtime patch for graphiti_core's OpenAIGenericClient.

Some local LLMs (qwen3, deepseek-r1, etc.) wrap output in <think> tags,
which breaks JSON parsing inside Graphiti's entity extraction pipeline.

This module monkey-patches _generate_response to:
1. Strip <think>/</think> tags and markdown fences before json.loads()
2. Retry without response_format if the model returns only thinking
3. Add /no_think instruction to suppress reasoning output

Import this module BEFORE any graphiti_core import:
    import graphiti_integration.llm_patch  # noqa: F401
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _strip_llm_artifacts(text: str) -> str:
    """Strip <think> tags, markdown fences, and other LLM artifacts from response."""
    # Strip <think>...</think> tags (qwen3, deepseek-r1, etc.)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Strip  channel  tags (some models)
    text = re.sub(r'<channel>.*?</channel>', '', text, flags=re.DOTALL)
    # Strip markdown code fences
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    return text.strip()


def apply_patch():
    """Apply the <think>-tag stripping patch to OpenAIGenericClient."""
    try:
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    except ImportError:
        logger.debug("graphiti_core not available, skipping LLM patch")
        return

    # Check if already patched
    if getattr(OpenAIGenericClient, '_think_patch_applied', False):
        return

    async def _patched_generate_response(self, messages, response_model=None,
                                         max_tokens=4096, model_size=None):
        """Patched version that strips <think> tags before JSON parsing."""
        from graphiti_core.llm_client.config import ModelSize
        from openai.types.chat import ChatCompletionMessageParam

        if model_size is None:
            model_size = ModelSize.medium

        openai_messages = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append({'role': 'system', 'content': m.content})

        # Prepare response format
        response_format = {'type': 'json_object'}
        if response_model is not None:
            schema_name = getattr(response_model, '__name__', 'structured_response')
            json_schema = response_model.model_json_schema()
            response_format = {
                'type': 'json_schema',
                'json_schema': {
                    'name': schema_name,
                    'schema': json_schema,
                },
            }

        # --- Attempt 1: with response_format ---
        response = await self.client.chat.completions.create(
            model=self.model or 'gpt-4.1-mini',
            messages=openai_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=response_format,
        )
        raw = response.choices[0].message.content or ''
        result = _strip_llm_artifacts(raw)

        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed after stripping artifacts: {e}. Raw snippet: {raw[:200]}")
        else:
            logger.warning(f"LLM returned only thinking/noise. Raw snippet: {raw[:300]}")

        # --- Attempt 2: retry WITHOUT response_format, add /no_think hint ---
        logger.info("Retrying without response_format and with /no_think hint")
        fallback_messages = list(openai_messages)
        # Inject /no_think into system prompt to suppress reasoning output
        if fallback_messages and fallback_messages[0]['role'] == 'system':
            fallback_messages[0] = {
                'role': 'system',
                'content': fallback_messages[0]['content']
                    + '\n/no_think\nRespond ONLY with valid JSON. No explanations, no thinking, no markdown.'
            }
        else:
            fallback_messages.insert(0, {
                'role': 'system',
                'content': '/no_think\nRespond ONLY with valid JSON. No explanations, no thinking, no markdown.'
            })

        # Add schema hint if we have a response model
        if response_model is not None:
            schema_hint = (
                f'\nYou MUST respond with valid JSON matching this schema: '
                f'{json.dumps(response_model.model_json_schema())}'
            )
            fallback_messages[0] = {
                'role': 'system',
                'content': fallback_messages[0]['content'] + schema_hint,
            }

        response = await self.client.chat.completions.create(
            model=self.model or 'gpt-4.1-mini',
            messages=fallback_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        raw2 = response.choices[0].message.content or ''
        result2 = _strip_llm_artifacts(raw2)

        if not result2:
            logger.error(f"LLM returned empty even after /no_think retry. Raw snippet: {raw2[:300]}")
            raise ValueError(
                'LLM returned an empty response after all retry attempts. '
                'Ensure the model is loaded and running.'
            )

        try:
            return json.loads(result2)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed on retry: {e}. Raw snippet: {raw2[:200]}")
            raise

    OpenAIGenericClient._generate_response = _patched_generate_response
    OpenAIGenericClient._think_patch_applied = True
    logger.info("Applied <think>-tag stripping patch to Graphiti OpenAIGenericClient")


# Auto-apply on import
apply_patch()
