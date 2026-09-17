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
    for key in ("GRAPHITI_LLM_MODEL", "LLM_TEXT_MODEL"):
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
