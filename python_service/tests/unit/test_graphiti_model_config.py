"""GRAPHITI_LLM_MODEL pinned to phi-4 (mvp-phase1-acceptance SPEC §3).

The Graphiti ingestion model is pinned: GRAPHITI_LLM_MODEL overrides the pin,
and empty/unset/whitespace falls back to the pin itself — the pipeline
analysis model (LLM_TEXT_MODEL) must never leak into ingestion.
"""

from __future__ import annotations

import pytest


def _load_config(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Call GraphitiConfig.from_env with dotenv search disabled."""
    from graphiti_integration import config as config_module

    graphiti_config = config_module.GraphitiConfig
    # Collection-time imports load_dotenv the repo .env into os.environ, so
    # every key from_env reads must be scrubbed before applying explicit env.
    for key in ("GRAPHITI_LLM_MODEL", "LLM_TEXT_MODEL",
                "GRAPHITI_LLM_BASE_URL", "LLM_TEXT_BASE_URL",
                "LLM_API_KEY", "LLM_TEXT_API_KEY", "GRAPHITI_LLM_API_KEY",
                "EMBEDDING_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # A nonexistent env_path keeps from_env from walking up to the repo .env.
    return graphiti_config.from_env(env_path="/nonexistent/.env.spec-test")


def test_explicit_graphiti_model_wins(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_MODEL="microsoft/phi-4",
        LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni",
    )
    assert cfg.llm_model == "microsoft/phi-4"


def test_explicit_override_other_model_wins(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_MODEL="other/model",
        LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni",
    )
    assert cfg.llm_model == "other/model"


def test_empty_graphiti_model_falls_back_to_pin(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_MODEL="",
        LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni",
    )
    assert cfg.llm_model == "microsoft/phi-4"


def test_whitespace_graphiti_model_falls_back_to_pin(monkeypatch):
    cfg = _load_config(monkeypatch, GRAPHITI_LLM_MODEL="   ")
    assert cfg.llm_model == "microsoft/phi-4"


def test_unset_graphiti_model_uses_pin_even_with_text_model_set(monkeypatch):
    cfg = _load_config(monkeypatch, LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni")
    assert cfg.llm_model == "microsoft/phi-4"


def test_both_unset_uses_pin(monkeypatch):
    cfg = _load_config(monkeypatch)
    assert cfg.llm_model == "microsoft/phi-4"


def test_pinned_constant_matches(monkeypatch):
    from graphiti_integration.config import PINNED_GRAPHITI_MODEL

    cfg = _load_config(monkeypatch)
    assert cfg.llm_model == PINNED_GRAPHITI_MODEL


# ---------------------------------------------------------------------------
# GRAPHITI_LLM_BASE_URL: ingestion server override (cloud text + local phi-4)
# ---------------------------------------------------------------------------

def test_graphiti_base_url_override_wins(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_BASE_URL="http://localhost:9999",
        LLM_TEXT_BASE_URL="http://cloud.example/step_plan",
    )
    assert cfg.llm_base_url == "http://localhost:9999/v1"


def test_graphiti_base_url_override_appends_v1_once(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_BASE_URL="http://localhost:9999/v1",
        LLM_TEXT_BASE_URL="http://cloud.example/step_plan",
    )
    assert cfg.llm_base_url == "http://localhost:9999/v1"


def test_graphiti_base_url_blank_falls_back_to_text_base(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_BASE_URL="   ",
        LLM_TEXT_BASE_URL="http://cloud.example/step_plan",
    )
    assert cfg.llm_base_url == "http://cloud.example/step_plan/v1"


def test_graphiti_api_key_override_wins(monkeypatch):
    """Ingestion authenticates on its own when given its own key."""
    cfg = _load_config(
        monkeypatch,
        LLM_API_KEY="shared-key",
        LLM_TEXT_API_KEY="text-key",
        GRAPHITI_LLM_API_KEY="graph-key",
    )
    assert cfg.llm_api_key == "graph-key"


def test_graphiti_api_key_blank_override_follows_text_channel(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        LLM_API_KEY="shared-key",
        LLM_TEXT_API_KEY="text-key",
        GRAPHITI_LLM_API_KEY="   ",
    )
    assert cfg.llm_api_key == "text-key"


def test_embedder_api_key_override_wins(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        LLM_API_KEY="shared-key",
        GRAPHITI_LLM_API_KEY="graph-key",
        EMBEDDING_API_KEY="embed-key",
    )
    assert cfg.embedder_api_key == "embed-key"


def test_embedder_api_key_blank_follows_ingestion_key(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        LLM_API_KEY="shared-key",
        LLM_TEXT_API_KEY="text-key",
        GRAPHITI_LLM_API_KEY="graph-key",
        EMBEDDING_API_KEY="   ",
    )
    assert cfg.embedder_api_key == "graph-key"


def test_embedder_api_key_falls_back_to_shared_key(monkeypatch):
    cfg = _load_config(monkeypatch, LLM_API_KEY="shared-key")
    assert cfg.embedder_api_key == "shared-key"


def test_graphiti_api_key_follows_text_channel(monkeypatch):
    """Without its own key, ingestion takes the text channel's key."""
    cfg = _load_config(
        monkeypatch,
        LLM_API_KEY="shared-key",
        LLM_TEXT_API_KEY="text-key",
    )
    assert cfg.llm_api_key == "text-key"


def test_graphiti_api_key_falls_back_to_shared_key(monkeypatch):
    cfg = _load_config(monkeypatch, LLM_API_KEY="shared-key")
    assert cfg.llm_api_key == "shared-key"


def test_graphiti_base_url_unset_falls_back_to_text_base(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        LLM_TEXT_BASE_URL="http://localhost:1234",
    )
    assert cfg.llm_base_url == "http://localhost:1234/v1"
