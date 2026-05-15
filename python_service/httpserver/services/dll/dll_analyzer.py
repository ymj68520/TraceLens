"""DLL analyzer client for calling C++ backend."""

import httpx
from typing import Dict, Any, Optional
import os


class DLLAnalyzerClient:
    """Client for calling C++ DLL analysis endpoint via HTTP."""

    def __init__(self, cpp_backend_url: str, timeout: float | None = None, settings = None):
        """
        Initialize DLL analyzer client.

        Args:
            cpp_backend_url: Base URL of C++ backend (e.g., "http://localhost:8080")
            timeout: Request timeout in seconds (default: from settings or env)
            settings: Optional Settings instance for configuration
        """
        self.cpp_backend_url = cpp_backend_url.rstrip('/')

        # Get timeout from settings, parameter, or environment
        if timeout is not None:
            self.timeout = timeout
        elif settings:
            self.timeout = float(settings.dll_analysis_timeout)
        else:
            self.timeout = float(os.getenv("DLL_ANALYSIS_TIMEOUT", "30.0"))
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def analyze_dll(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a DLL/PE/ELF file via C++ backend.

        Args:
            file_path: Absolute path to the DLL file

        Returns:
            Dictionary containing analysis results

        Raises:
            httpx.HTTPError: If request fails
            Exception: If analysis fails
        """
        client = await self._get_client()

        response = await client.post(
            f"{self.cpp_backend_url}/api/forensics/dlls/analyze",
            json={"file_path": file_path},
            headers={"Content-Type": "application/json"}
        )

        # For error responses, try to extract error from JSON first
        if response.status_code >= 400:
            try:
                result = response.json()
                # For client errors (4xx), check for error message in JSON
                if response.status_code < 500 and "error" in result:
                    raise Exception(f"DLL analysis failed: {result['error']}")
            except (ValueError,):
                # If JSON parsing fails, continue to raise_for_status
                pass

        # Raise for HTTP errors (including 5xx server errors)
        response.raise_for_status()

        # Parse and return successful response
        result = response.json()
        return result

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        return False
