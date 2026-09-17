"""GRAPHITI_LLM_MODEL separation (llm-throughput-hardening SPEC B).

The Graphiti extraction model must come from GRAPHITI_LLM_MODEL when set, and
fall back to LLM_TEXT_MODEL when the variable is unset, empty, or whitespace —
byte-for-byte the pre-SPEC behavior in the fallback case.
"""

from __future__ import annotations

import pytest

_DEFAULT_TEXT_MODEL = "openai/gpt-oss-20b"


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


def test_empty_graphiti_model_falls_back_to_text_model(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_MODEL="",
        LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni",
    )
    assert cfg.llm_model == "nvidia/nemotron-3-nano-omni"


def test_whitespace_graphiti_model_falls_back(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GRAPHITI_LLM_MODEL="   ",
        LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni",
    )
    assert cfg.llm_model == "nvidia/nemotron-3-nano-omni"


def test_unset_graphiti_model_matches_legacy_behavior(monkeypatch):
    cfg = _load_config(monkeypatch, LLM_TEXT_MODEL="nvidia/nemotron-3-nano-omni")
    assert cfg.llm_model == "nvidia/nemotron-3-nano-omni"


def test_both_unset_uses_hardcoded_default(monkeypatch):
    cfg = _load_config(monkeypatch)
    assert cfg.llm_model == _DEFAULT_TEXT_MODEL
