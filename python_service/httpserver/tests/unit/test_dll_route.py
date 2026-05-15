"""Tests for DLL analysis route."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import Request
from pydantic import ValidationError

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from httpserver.routes.dll import (
    router,
    analyze_dll,
    DLLAnalysisRequest,
    DLLAnalysisResponse,
)


@pytest.fixture
def mock_request():
    """Create a mock FastAPI Request."""
    return MagicMock(spec=Request)


@pytest.mark.asyncio
async def test_analyze_dll_route_success():
    """Test successful DLL analysis via route handler."""
    mock_dll_data = {
        "success": True,
        "file_name": "test.dll",
        "file_size": 1024,
        "format": "PE",
        "machine_type": 0x8664,
        "threat_score": 50,
        "signature_status": "Unsigned",
        "md5": "abc123",
        "sha256": "def456",
        "sections": [{"name": ".text", "virtual_address": 0x1000, "virtual_size": 0x500, "raw_size": 0x400}],
        "imports": [{"dll": "kernel32.dll", "function": "CreateFileW"}],
        "exports": [{"name": "DllMain", "address": 0x2000}],
        "anomalies": ["High entropy section .data"],
    }

    expected_markdown = """# DLL Analysis Report: test.dll

## File Information
- **Format**: PE
- **Size**: 1024 bytes
- **MD5**: `abc123`
- **SHA256**: `def456`
- **Signature Status**: Unsigned

## Threat Assessment
- **Score**: 50/100
- **Level**: MEDIUM
"""

    mock_llm_result = {
        "success": True,
        "analysis": {
            "threat_level": "中",
            "confidence": "中",
            "function_assessment": "Suspicious DLL with file operations",
            "suspicious_behaviors": ["File manipulation", "Registry access"],
            "mitre_attack_techniques": ["T1055", "T1012"],
            "iocs": ["suspicious_ip_1", "suspicious_domain_1"],
            "recommendations": "Quarantine and analyze further",
        },
        "model": "test-model",
        "tokens_used": 500,
    }

    request = DLLAnalysisRequest(
        file_path="/path/to/test.dll",
        files_db_path="/tmp/test.db",
    )

    mock_settings = MagicMock()
    mock_settings.cpp_backend_base_url = "http://localhost:8080"

    mock_sm = MagicMock()
    mock_llm_service = AsyncMock()
    mock_llm_service.analyze.return_value = mock_llm_result
    mock_llm_service.persist_to_files_db.return_value = True
    mock_sm.llm_service = mock_llm_service

    with patch('httpserver.routes.dll.DLLAnalyzerClient') as MockClientClass, \
         patch('httpserver.routes.dll.DLLMarkdownGenerator') as MockGenClass, \
         patch('httpserver.routes.dll.get_service_manager', return_value=mock_sm):

        mock_dll_client = AsyncMock()
        mock_dll_client.analyze_dll.return_value = mock_dll_data
        mock_dll_client.__aenter__.return_value = mock_dll_client
        mock_dll_client.__aexit__.return_value = None
        MockClientClass.return_value = mock_dll_client
        MockGenClass.generate.return_value = expected_markdown

        response = await analyze_dll(request, settings=mock_settings)

        assert isinstance(response, DLLAnalysisResponse)
        assert response.success is True
        assert response.analysis["threat_level"] == "中"
        assert response.analysis["confidence"] == "中"
        assert "suspicious_behaviors" in response.analysis
        assert response.tokens_used == 500
        assert response.model_used == "test-model"
        assert response.processing_time_ms >= 0
        assert "timestamp" in response.__dict__

        # Verify C++ backend was called
        mock_dll_client.analyze_dll.assert_called_once_with("/path/to/test.dll")

        # Verify persistence was called
        mock_llm_service.persist_to_files_db.assert_called_once()
        persist_kwargs = mock_llm_service.persist_to_files_db.call_args[1]
        assert persist_kwargs["db_path"] == "/tmp/test.db"
        assert persist_kwargs["file_path"] == "/path/to/test.dll"


@pytest.mark.asyncio
async def test_analyze_dll_route_without_db_persist():
    """Test DLL analysis without database persistence."""
    mock_dll_data = {
        "success": True,
        "file_name": "test.dll",
        "file_size": 1024,
        "format": "PE",
        "machine_type": 0x8664,
        "threat_score": 50,
        "signature_status": "Unsigned",
        "md5": "abc123",
        "sha256": "def456",
        "sections": [],
        "imports": [],
        "exports": [],
        "anomalies": [],
    }

    mock_llm_result = {
        "success": True,
        "analysis": {
            "threat_level": "低",
            "confidence": "高",
            "function_assessment": "Normal system DLL",
            "suspicious_behaviors": [],
            "mitre_attack_techniques": [],
            "iocs": [],
            "recommendations": "No action needed",
        },
        "model": "test-model",
        "tokens_used": 200,
    }

    request = DLLAnalysisRequest(file_path="/path/to/test.dll")

    mock_settings = MagicMock()
    mock_settings.cpp_backend_base_url = "http://localhost:8080"

    mock_sm = MagicMock()
    mock_llm_service = AsyncMock()
    mock_llm_service.analyze.return_value = mock_llm_result
    mock_sm.llm_service = mock_llm_service

    with patch('httpserver.routes.dll.DLLAnalyzerClient') as MockClientClass, \
         patch('httpserver.routes.dll.DLLMarkdownGenerator') as MockGenClass, \
         patch('httpserver.routes.dll.get_service_manager', return_value=mock_sm):

        mock_dll_client = AsyncMock()
        mock_dll_client.analyze_dll.return_value = mock_dll_data
        mock_dll_client.__aenter__.return_value = mock_dll_client
        mock_dll_client.__aexit__.return_value = None
        MockClientClass.return_value = mock_dll_client
        MockGenClass.generate.return_value = "# Report"

        response = await analyze_dll(request, settings=mock_settings)

        assert isinstance(response, DLLAnalysisResponse)
        assert response.success is True
        assert response.analysis["threat_level"] == "低"

        # Persistence should NOT be called when no files_db_path
        mock_llm_service.persist_to_files_db.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_dll_route_cpp_backend_error():
    """Test DLL analysis when C++ backend raises exception."""
    request = DLLAnalysisRequest(file_path="/path/to/bad.dll")

    mock_settings = MagicMock()
    mock_settings.cpp_backend_base_url = "http://localhost:8080"

    with patch('httpserver.routes.dll.DLLAnalyzerClient') as MockClientClass, \
         patch('httpserver.routes.dll.get_service_manager'):

        mock_dll_client = AsyncMock()
        mock_dll_client.analyze_dll.side_effect = Exception("C++ backend unavailable")
        mock_dll_client.__aenter__.return_value = mock_dll_client
        mock_dll_client.__aexit__.return_value = None
        MockClientClass.return_value = mock_dll_client

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await analyze_dll(request, settings=mock_settings)

        assert exc_info.value.status_code == 500
        assert "DLL analysis failed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_analyze_dll_route_missing_file_path():
    """Test DLL analysis request validation rejects missing file_path."""
    with pytest.raises(ValidationError) as exc_info:
        DLLAnalysisRequest(files_db_path="/tmp/test.db")

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("file_path",) for e in errors)


@pytest.mark.asyncio
async def test_analyze_dll_with_custom_prompt():
    """Test DLL analysis with custom prompt."""
    mock_dll_data = {
        "success": True,
        "file_name": "custom.dll",
        "file_size": 2048,
        "format": "PE",
        "machine_type": 0x8664,
        "threat_score": 75,
        "signature_status": "Signed",
        "md5": "xyz789",
        "sha256": "abc012",
        "sections": [],
        "imports": [],
        "exports": [],
        "anomalies": [],
    }

    mock_llm_result = {
        "success": True,
        "analysis": {"threat_level": "高"},
        "model": "custom-model",
        "tokens_used": 300,
    }

    custom_prompt = "Custom analysis prompt: {markdown_report}"

    request = DLLAnalysisRequest(
        file_path="/path/to/custom.dll",
        prompt=custom_prompt,
    )

    mock_settings = MagicMock()
    mock_settings.cpp_backend_base_url = "http://localhost:8080"

    mock_sm = MagicMock()
    mock_llm_service = AsyncMock()
    mock_llm_service.analyze.return_value = mock_llm_result
    mock_sm.llm_service = mock_llm_service

    with patch('httpserver.routes.dll.DLLAnalyzerClient') as MockClientClass, \
         patch('httpserver.routes.dll.DLLMarkdownGenerator') as MockGenClass, \
         patch('httpserver.routes.dll.get_service_manager', return_value=mock_sm):

        mock_dll_client = AsyncMock()
        mock_dll_client.analyze_dll.return_value = mock_dll_data
        mock_dll_client.__aenter__.return_value = mock_dll_client
        mock_dll_client.__aexit__.return_value = None
        MockClientClass.return_value = mock_dll_client
        MockGenClass.generate.return_value = "# Custom Report"

        response = await analyze_dll(request, settings=mock_settings)

        assert isinstance(response, DLLAnalysisResponse)
        assert response.success is True
        assert response.analysis["threat_level"] == "高"

        # Verify custom prompt was used
        call_kwargs = mock_llm_service.analyze.call_args[1]
        assert "Custom analysis prompt:" in call_kwargs["prompt"]


@pytest.mark.asyncio
async def test_analyze_dll_persist_failure_does_not_fail_request():
    """Test that database persistence failure doesn't fail the analysis."""
    mock_dll_data = {
        "success": True,
        "file_name": "test.dll",
        "file_size": 1024,
        "format": "PE",
        "machine_type": 0x8664,
        "threat_score": 50,
        "signature_status": "Unsigned",
        "md5": "abc123",
        "sha256": "def456",
        "sections": [],
        "imports": [],
        "exports": [],
        "anomalies": [],
    }

    mock_llm_result = {
        "success": True,
        "analysis": {"threat_level": "中"},
        "model": "test-model",
        "tokens_used": 200,
    }

    request = DLLAnalysisRequest(
        file_path="/path/to/test.dll",
        files_db_path="/tmp/test.db",
    )

    mock_settings = MagicMock()
    mock_settings.cpp_backend_base_url = "http://localhost:8080"

    mock_sm = MagicMock()
    mock_llm_service = AsyncMock()
    mock_llm_service.analyze.return_value = mock_llm_result
    # Simulate persistence failure (returns False but doesn't raise)
    mock_llm_service.persist_to_files_db.return_value = False
    mock_sm.llm_service = mock_llm_service

    with patch('httpserver.routes.dll.DLLAnalyzerClient') as MockClientClass, \
         patch('httpserver.routes.dll.DLLMarkdownGenerator') as MockGenClass, \
         patch('httpserver.routes.dll.get_service_manager', return_value=mock_sm):

        mock_dll_client = AsyncMock()
        mock_dll_client.analyze_dll.return_value = mock_dll_data
        mock_dll_client.__aenter__.return_value = mock_dll_client
        mock_dll_client.__aexit__.return_value = None
        MockClientClass.return_value = mock_dll_client
        MockGenClass.generate.return_value = "# Report"

        # Should succeed despite persistence failure
        response = await analyze_dll(request, settings=mock_settings)

        assert isinstance(response, DLLAnalysisResponse)
        assert response.success is True
        mock_llm_service.persist_to_files_db.assert_called_once()
