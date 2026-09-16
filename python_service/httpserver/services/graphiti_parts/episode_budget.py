"""Episode budget derivation (SPEC file-analysis D11/D13).

One probe, one cache: on first resolve, the configured
``GRAPHITI_MAX_EPISODE_TOKENS`` ceiling is narrowed by the model context
reported by LM Studio's rich REST API (``/api/v0/models``); any probe
failure falls back to the configured value with no behavior change. The
episode chunk size in characters derives from the effective token budget
at toon_transformer's conservative 3 chars/token ratio.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Ratio used by graphiti_integration.toon_transformer.truncate_if_needed.
_CHARS_PER_TOKEN = 3
_MIN_EFFECTIVE_TOKENS = 256
_DEFAULT_CONFIGURED_TOKENS = 3000

_cached_chars: Optional[int] = None


def _configured_tokens(settings) -> int:
    try:
        return int(getattr(settings, "graphiti_max_episode_tokens", _DEFAULT_CONFIGURED_TOKENS)
                   or _DEFAULT_CONFIGURED_TOKENS)
    except (TypeError, ValueError):
        return _DEFAULT_CONFIGURED_TOKENS


def chars_from_tokens(tokens: int) -> int:
    return max(int(tokens), _MIN_EFFECTIVE_TOKENS) * _CHARS_PER_TOKEN


async def resolve_and_cache(settings) -> int:
    """Probe LM Studio once and cache the effective chunk size in chars.

    Never raises: probe failures are logged and the configured budget is
    used, keeping the behavior identical to the pre-probe deployment (D13).
    """
    global _cached_chars
    if _cached_chars is not None:
        return _cached_chars

    configured = _configured_tokens(settings)
    effective = configured
    try:
        base = (getattr(settings, "llm_text_base_url", "") or "").rstrip("/")
        if base:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base}/api/v0/models")
                payload = resp.json()
            models = payload.get("data") or payload.get("models") or []
            wanted = (getattr(settings, "llm_text_model", "") or "").split("/")[-1].lower()
            context = None
            for model in models:
                model_id = str(model.get("id") or model.get("key") or "").lower()
                if not wanted or wanted in model_id or model_id in wanted:
                    context = model.get("max_context_length") or model.get("context_length")
                    if context:
                        break
            if context:
                # Reserve headroom for the entity-extraction prompt and output.
                effective = min(configured, max(int(int(context) * 0.15), _MIN_EFFECTIVE_TOKENS))
                logger.info(
                    f"Episode budget: model context narrowed effective tokens "
                    f"to {effective} (configured ceiling {configured})"
                )
    except Exception as e:
        logger.warning(f"LM Studio context probe failed, using configured episode budget: {e}")

    _cached_chars = chars_from_tokens(effective)
    return _cached_chars


def episode_chunk_chars(settings=None) -> int:
    """Cached effective chunk size; falls back to the configured budget.

    Without settings (standalone builders), the SPEC default budget
    (3000 tokens × 3) applies.
    """
    if _cached_chars is not None:
        return _cached_chars
    if settings is not None:
        return chars_from_tokens(_configured_tokens(settings))
    return chars_from_tokens(_DEFAULT_CONFIGURED_TOKENS)
