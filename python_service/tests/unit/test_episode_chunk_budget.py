"""
Unit tests for the CJK-aware episode budget (phi-4 context adaptation).

The legacy estimator counted 4 characters per token regardless of script, so
Chinese evidence bodies were undershot by ~4x and overflowed the local model's
context window mid-generation (LM Studio: "Context size has been exceeded",
2026-10-15: 3/12 episodes failed on raw_llm.img). Chunking now splits on the
CJK-aware estimate against the probed per-episode token budget.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from graphiti_integration.toon_transformer import TOONTransformer
from httpserver.services.graphiti_parts.episode_budget import (
    effective_episode_tokens,
)
from httpserver.services.graphiti_service import GraphitiService


class TestCjkAwareEstimator:
    def test_chinese_counts_about_one_token_per_char(self):
        # 400 CJK chars ≈ 400 tokens, not the legacy ~125 (400*1.25/4)
        assert TOONTransformer.estimate_episode_tokens("中" * 400) >= 400

    def test_ascii_keeps_the_legacy_ratio(self):
        # 'a'*400: 400/4 + 400/20 = 120 — identical to the legacy estimator
        assert TOONTransformer.estimate_episode_tokens("a" * 400) == 120

    def test_mixed_text_sums_both_parts(self):
        text = "中" * 100 + "a" * 400
        assert TOONTransformer.estimate_episode_tokens(text) == 100 + 120

    def test_empty_body_is_zero(self):
        assert TOONTransformer.estimate_episode_tokens("") == 0


class TestTokenBasedChunking:
    def _chunker(self, max_episode_tokens=2500):
        from types import SimpleNamespace

        svc = GraphitiService.__new__(GraphitiService)
        svc.settings = SimpleNamespace(graphiti_max_episode_tokens=max_episode_tokens)
        return svc

    def test_short_text_is_single_chunk(self):
        svc = self._chunker()
        assert svc._chunk_text_for_graph("短文本") == ["短文本"]

    def test_chinese_text_splits_by_token_estimate(self):
        # 6000 CJK chars ≈ 6000 tokens > 2500 budget → multiple chunks,
        # each within budget (the legacy 3000-char chunks would return ONE
        # 6000-char chunk ≈ 6000 tokens — a guaranteed context overflow)
        svc = self._chunker()
        chunks = svc._chunk_text_for_graph("涉案资金转账记录。" * 500)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert TOONTransformer.estimate_episode_tokens(chunk) <= 2500

    def test_oversize_single_paragraph_is_hard_split(self):
        svc = self._chunker()
        one_blob = "无段落长文本" * 1000  # no "\n\n" anywhere, ~6000 tokens
        chunks = svc._chunk_text_for_graph(one_blob)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert TOONTransformer.estimate_episode_tokens(chunk) <= 2500
        assert "".join(chunks).replace("\n", "") == one_blob

    def test_explicit_budget_overrides_settings(self):
        svc = self._chunker(max_episode_tokens=2500)
        chunks = svc._chunk_text_for_graph("字" * 600, max_tokens=100)
        assert len(chunks) >= 6
        for chunk in chunks:
            assert TOONTransformer.estimate_episode_tokens(chunk) <= 100


class TestBudgetAccessor:
    def test_falls_back_to_settings_without_probe(self):
        from types import SimpleNamespace

        settings = SimpleNamespace(graphiti_max_episode_tokens=1234)
        assert effective_episode_tokens(settings) == 1234

    def test_falls_back_to_spec_default_without_settings(self):
        assert effective_episode_tokens() == 3000
