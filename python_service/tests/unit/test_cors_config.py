"""Tests for CORS configuration."""

import pytest
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpserver.config import Settings


class TestCORSSettings:
    """Test CORS origins configuration."""

    def test_default_cors_origins_wildcard(self):
        """Test that default CORS origins is wildcard for development."""
        settings = Settings()
        assert settings.cors_origins == ["*"]

    def test_cors_origins_from_json_array(self, monkeypatch):
        """Test parsing CORS origins from JSON array format."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", '["https://example.com", "https://app.example.com"]')
        settings = Settings()
        assert settings.cors_origins == ["https://example.com", "https://app.example.com"]

    def test_cors_origins_from_single_json(self, monkeypatch):
        """Test parsing CORS origins from single JSON origin."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", '["https://example.com"]')
        settings = Settings()
        assert settings.cors_origins == ["https://example.com"]

    def test_cors_origins_from_comma_separated(self, monkeypatch):
        """Test fallback to comma-separated format."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", "https://example.com, https://app.example.com")
        settings = Settings()
        assert settings.cors_origins == ["https://example.com", "https://app.example.com"]

    def test_cors_origins_from_single_comma_separated(self, monkeypatch):
        """Test single origin in comma-separated format."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", "https://example.com")
        settings = Settings()
        assert settings.cors_origins == ["https://example.com"]

    def test_cors_origins_with_localhost(self, monkeypatch):
        """Test CORS origins with localhost for development."""
        monkeypatch.setenv(
            "PYTHON_CORS_ORIGINS",
            '["http://localhost:3000", "http://localhost:5173", "http://localhost:8080"]'
        )
        settings = Settings()
        assert settings.cors_origins == [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080"
        ]

    def test_cors_origins_empty_string_defaults_to_wildcard(self, monkeypatch):
        """Test that empty string falls back to wildcard."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", "")
        settings = Settings()
        assert settings.cors_origins == ["*"]

    def test_cors_origins_explicit_wildcard(self, monkeypatch):
        """Test that explicit wildcard is handled correctly."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", "*")
        settings = Settings()
        assert settings.cors_origins == ["*"]

    def test_cors_origins_json_single_string(self, monkeypatch):
        """Test JSON array with single string without brackets treated as single origin."""
        monkeypatch.setenv("PYTHON_CORS_ORIGINS", "https://example.com")
        settings = Settings()
        assert settings.cors_origins == ["https://example.com"]


class TestCORSMiddlewareIntegration:
    """Test CORS middleware integration with FastAPI app."""

    def test_cors_middleware_uses_settings(self, test_settings, monkeypatch):
        """Test that FastAPI app uses CORS settings from configuration."""
        from fastapi.testclient import TestClient
        from httpserver.main import create_app

        # Override CORS origins in test settings by setting the raw value
        test_settings.cors_origins_raw = '["https://example.com", "https://app.example.com"]'

        app = create_app(test_settings)

        # Check that middleware was added with correct origins
        cors_middleware = None
        for middleware in app.user_middleware:
            # Check the middleware class name
            if middleware.cls.__name__ == 'CORSMiddleware':
                cors_middleware = middleware
                break

        assert cors_middleware is not None, "CORSMiddleware not found"
        assert cors_middleware.kwargs == {
            'allow_origins': ["https://example.com", "https://app.example.com"],
            'allow_credentials': True,
            'allow_methods': ["*"],
            'allow_headers': ["*"]
        }

    def test_cors_middleware_default_wildcard(self, test_settings):
        """Test that default CORS uses wildcard."""
        from httpserver.main import create_app

        # Ensure test settings has default cors_origins
        assert test_settings.cors_origins == ["*"]

        app = create_app(test_settings)

        # Check that middleware was added with wildcard origins
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == 'CORSMiddleware':
                cors_middleware = middleware
                break

        assert cors_middleware is not None, "CORSMiddleware not found"
        assert cors_middleware.kwargs == {
            'allow_origins': ["*"],
            'allow_credentials': True,
            'allow_methods': ["*"],
            'allow_headers': ["*"]
        }

