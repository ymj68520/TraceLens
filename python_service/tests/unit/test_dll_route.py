"""Tests for DLL analysis route."""

import pytest
from unittest.mock import AsyncMock, patch
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from httpserver.routes.dll import normalize_threat_level, DLLAnalysisRequest, DLLAnalysisResponse


class TestNormalizeThreatLevel:
    """Test threat level normalization."""

    def test_normalize_low(self):
        assert normalize_threat_level("low", 10) == "low"
        assert normalize_threat_level("低", 10) == "low"
        assert normalize_threat_level("低风险", 10) == "low"

    def test_normalize_medium(self):
        assert normalize_threat_level("medium", 45) == "medium"
        assert normalize_threat_level("中", 45) == "medium"

    def test_normalize_high(self):
        assert normalize_threat_level("high", 70) == "high"
        assert normalize_threat_level("高", 70) == "high"

    def test_normalize_critical(self):
        assert normalize_threat_level("critical", 90) == "critical"
        assert normalize_threat_level("严重", 90) == "critical"

    def test_fallback_based_on_score(self):
        assert normalize_threat_level("unknown", 10) == "low"
        assert normalize_threat_level("unknown", 45) == "medium"
        assert normalize_threat_level("unknown", 70) == "high"
        assert normalize_threat_level("unknown", 90) == "critical"

    def test_case_insensitive(self):
        assert normalize_threat_level("LOW", 10) == "low"
        assert normalize_threat_level("MEDIUM", 45) == "medium"


class TestDLLAnalysisRequest:
    """Test DLLAnalysisRequest model."""

    def test_valid_request(self):
        req = DLLAnalysisRequest(file_path="/path/to/test.dll")
        assert req.file_path == "/path/to/test.dll"
        assert req.files_db_path is None

    def test_request_with_all_fields(self):
        req = DLLAnalysisRequest(
            file_path="/path/to/test.dll",
            files_db_path="/path/to/files.db",
            prompt="Custom prompt",
        )
        assert req.file_path == "/path/to/test.dll"
        assert req.files_db_path == "/path/to/files.db"


class TestDLLAnalysisResponse:
    """Test DLLAnalysisResponse model."""

    def test_valid_response(self):
        resp = DLLAnalysisResponse(
            success=True,
            analysis={"threat_level": "low"},
            model_used="gpt-4",
            tokens_used=500,
            processing_time_ms=1234.5,
            timestamp="2024-01-01T00:00:00",
        )
        assert resp.success is True
        assert resp.analysis == {"threat_level": "low"}
        assert resp.model_used == "gpt-4"
