"""Episode budget derivation (SPEC file-analysis D11/D13).

One probe, one cache: on first resolve, the configured
``GRAPHITI_MAX_EPISODE_TOKENS`` ceiling is narrowed by the model context
reported by LM Studio's rich REST API (``/api/v0/models``); any probe
failure falls back to the configured value with no behavior change. The
episode chunk size in characters derives from the effective token budget
at toon_transformer's conservative 3 chars/token ratio.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Ratio used by graphiti_integration.toon_transformer.truncate_if_needed.
_CHARS_PER_TOKEN = 3
_MIN_EFFECTIVE_TOKENS = 256
_DEFAULT_CONFIGURED_TOKENS = 3000

_cached_chars: Optional[int] = None
_cached_tokens: Optional[int] = None


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
        # Probe the server that actually consumes episodes — the
        # GRAPHITI_LLM_BASE_URL override when set (ingestion may ride local
        # phi-4 while the pipeline text model is cloud), else the text base.
        base = (
            (getattr(settings, "graphiti_llm_base_url", "") or "").strip()
            or (os.getenv("GRAPHITI_LLM_BASE_URL") or "").strip()
            or (getattr(settings, "llm_text_base_url", "") or "")
        ).rstrip("/")
        if base:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base}/api/v0/models")
                payload = resp.json()
            models = payload.get("data") or payload.get("models") or []
            # Match the episode consumer's context: the Graphiti ingestion
            # model (GRAPHITI_LLM_MODEL pin), not the pipeline text model.
            wanted = (
                getattr(settings, "graphiti_llm_model", "")
                or getattr(settings, "llm_text_model", "")
                or ""
            ).split("/")[-1].lower()
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

    _cached_tokens = effective
    _cached_chars = chars_from_tokens(effective)
    return _cached_chars


def effective_episode_tokens(settings=None) -> int:
    """Cached probed token budget; falls back to the configured ceiling.

    Without a probe (standalone/unit-test contexts) this is the configured
    ``GRAPHITI_MAX_EPISODE_TOKENS`` — or the SPEC default when no settings are
    available. Callers should size chunks against tokens via the CJK-aware
    ``TOONTransformer.estimate_episode_tokens``, not raw characters.
    """
    global _cached_tokens
    if _cached_tokens is not None:
        return _cached_tokens
    if settings is not None:
        return _configured_tokens(settings)
    return _DEFAULT_CONFIGURED_TOKENS


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
