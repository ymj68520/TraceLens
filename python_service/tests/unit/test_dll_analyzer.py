"""Tests for DLL analyzer client."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import Response, HTTPStatusError, RequestError, Request

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from httpserver.services.dll.dll_analyzer import DLLAnalyzerClient


def _create_mock_response(status_code: int, json_data: dict) -> Response:
    """Create a mock Response with proper request attribute."""
    request = Request("POST", "http://localhost:8080/api/forensics/dlls/analyze")
    response = Response(status_code=status_code, json=json_data, request=request)
    return response


@pytest.mark.asyncio
async def test_analyze_dll_success():
    """Test successful DLL analysis via RPC."""
    client = DLLAnalyzerClient("http://localhost:8080")

    mock_response = _create_mock_response(200, {
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
        "anomalies": []
    })

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = await client.analyze_dll("/path/to/test.dll")

        assert result["success"] is True
        assert result["file_name"] == "test.dll"
        assert result["threat_score"] == 50
        assert result["format"] == "PE"

        # Verify correct URL and payload
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8080/api/forensics/dlls/analyze"
        assert call_args[1]["json"]["file_path"] == "/path/to/test.dll"


@pytest.mark.asyncio
async def test_analyze_dll_file_not_found():
    """Test DLL analysis with non-existent file."""
    client = DLLAnalyzerClient("http://localhost:8080")

    mock_response = _create_mock_response(404, {"error": "File not found: /nonexistent.dll"})

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(Exception) as exc_info:
            await client.analyze_dll("/nonexistent.dll")

        assert "DLL analysis failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_analyze_dll_http_error():
    """Test DLL analysis with HTTP 500 error."""
    client = DLLAnalyzerClient("http://localhost:8080")

    mock_response = _create_mock_response(500, {"error": "Internal server error"})

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(HTTPStatusError):
            await client.analyze_dll("/path/to/test.dll")


@pytest.mark.asyncio
async def test_analyze_dll_timeout():
    """Test DLL analysis with timeout."""
    client = DLLAnalyzerClient("http://localhost:8080", timeout=5.0)

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = TimeoutError("Request timeout")
        mock_client_cls.return_value = mock_client

        with pytest.raises(TimeoutError):
            await client.analyze_dll("/path/to/test.dll")


@pytest.mark.asyncio
async def test_analyze_dll_connection_error():
    """Test DLL analysis with connection error."""
    client = DLLAnalyzerClient("http://localhost:8080")

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = RequestError("Connection failed")
        mock_client_cls.return_value = mock_client

        with pytest.raises(RequestError):
            await client.analyze_dll("/path/to/test.dll")


@pytest.mark.asyncio
async def test_client_context_manager():
    """Test async context manager."""
    async with DLLAnalyzerClient("http://localhost:8080") as client:
        assert client.cpp_backend_url == "http://localhost:8080"
        assert client.timeout == 30.0

    # Client should be closed after context exit
    # (Can't easily verify internal state, but no exception = success)


@pytest.mark.asyncio
async def test_custom_timeout():
    """Test custom timeout from environment variable."""
    with patch.dict(os.environ, {"DLL_ANALYSIS_TIMEOUT": "60.0"}):
        client = DLLAnalyzerClient("http://localhost:8080")
        assert client.timeout == 60.0
