"""Tests for deterministic file filter configuration settings."""

import pytest


def test_file_filter_mode_defaults_to_deterministic():
    from httpserver.config import Settings
    settings = Settings()
    assert settings.file_filter_mode == "deterministic"


def test_filter_max_files_defaults_to_zero_unlimited():
    from httpserver.config import Settings
    settings = Settings()
    assert settings.filter_max_files == 0


def test_file_filter_mode_accepts_llm(monkeypatch):
    from httpserver.config import Settings
    monkeypatch.setenv("FILE_FILTER_MODE", "llm")
    settings = Settings()
    assert settings.file_filter_mode == "llm"


def test_file_filter_mode_rejects_invalid_value(monkeypatch):
    from httpserver.config import Settings
    monkeypatch.setenv("FILE_FILTER_MODE", "invalid_mode")
    with pytest.raises(Exception):
        Settings()

