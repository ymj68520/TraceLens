"""Tests for deterministic file filter configuration settings."""


def test_file_filter_mode_defaults_to_deterministic():
    from httpserver.config import Settings
    settings = Settings()
    assert settings.file_filter_mode == "deterministic"


def test_filter_max_files_defaults_to_zero_unlimited():
    from httpserver.config import Settings
    settings = Settings()
    assert settings.filter_max_files == 0
