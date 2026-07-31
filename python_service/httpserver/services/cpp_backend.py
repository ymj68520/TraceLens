"""
C++ Backend Service - Communication with the C++ HTTP server.

This service provides HTTP-based communication with the C++ backend.
It handles:
- Task management
- Database queries
- File operations
- Health checks

The design supports future extension to other protocols:
- Current implementation: HTTP/REST
- Future: gRPC, WebSocket, etc.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class CppBackendService:
    """
    Service for communicating with the C++ HTTP backend.
    
    Uses httpx for async HTTP requests with connection pooling.
    Implements retry logic and error handling.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize the C++ backend service.
        
        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.base_url = settings.cpp_backend_url
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the HTTP client."""
        if self._initialized:
            return
        
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        self._initialized = True
        logger.info(f"C++ backend service initialized: {self.base_url}")
    
    async def shutdown(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._initialized = False
    
    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, creating if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0),
            )
        return self._client
    
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the C++ backend with detailed logging.
        """
        payload_preview = kwargs.get('json') or kwargs.get('params')
        logger.info(f"C++ Request: {method} {path} - Payload: {payload_preview}")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await self.client.request(method, path, **kwargs)
                
                # Check for HTML content (usually means 404 or SPA fallback)
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    logger.error(f"C++ API returned HTML instead of JSON! Status: {response.status_code}")
                    return {"success": False, "error": "Backend returned HTML", "status": response.status_code}

                if response.status_code >= 400:
                    logger.error(f"C++ API Error ({response.status_code}): {response.text}")
                    return {"success": False, "error": response.text, "status": response.status_code}
                
                if not response.content:
                    return {}
                    
                result = response.json()
                logger.info(f"C++ Response from {path}: {str(result)[:200]}...")
                return result
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"C++ backend request failed after {max_retries} attempts: {e}")
                    return {"success": False, "error": str(e)}
                await asyncio.sleep(1)
        return {"success": False, "error": "Max retries exceeded"}
    
    async def health_check(self) -> bool:
        """
        Check if the C++ backend is healthy.
        
        Returns:
            True if healthy, False otherwise.
        """
        try:
            response = await self.client.get("/api/health")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"C++ backend health check failed: {e}")
            return False
    
    # Task Management
    
    async def list_tasks(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """List all tasks."""
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        
        return await self._request("GET", "/api/tasks/list", params=params)
    
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific task through the backend's direct lookup route."""
        result = await self._request("GET", f"/api/tasks/{task_id}")
        if not isinstance(result, dict) or result.get("status") == 404:
            return None
        if result.get("success") is False and not result.get("id"):
            return None
        if "image_path" in result and "image_name" not in result:
            result["image_name"] = result["image_path"]
        return result
    
    async def check_task_exists(self, task_id: str) -> bool:
        """Check if a task exists."""
        task = await self.get_task(task_id)
        return task is not None
    
    async def get_task_databases(self, task_id: str) -> List[Dict[str, Any]]:
        """Get databases associated with a task."""
        result = await self._request("GET", f"/api/tasks/{task_id}/databases")
        return result.get("databases", [])
    
    # File Operations
    
    async def get_task_files(
        self,
        task_id: str,
        file_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get files from a task using largest files endpoint as default."""
        params = {"task_id": task_id, "limit": limit}
        # Note: file_type filter not supported by largest endpoint, use client-side filtering
        result = await self._request("GET", "/api/forensics/files/largest", params=params)
        # C++ backend may return a plain list or a wrapped {"largest_files": [...]}
        if isinstance(result, dict):
            files = result.get("largest_files") or result.get("files") or []
        elif isinstance(result, list):
            files = result
        else:
            files = []

        # Client-side filtering by file types if specified
        if file_types and files:
            files = [f for f in files if f.get("category") in file_types]
        return files
    
    async def get_task_files_paginated(
        self,
        task_id: str,
        file_type: Optional[str] = None,
        extension: Optional[str] = None,
        deleted_only: bool = False,
        include_llm: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Get paginated files from a task.

        Note: C++ backend uses largest files endpoint. Pagination is client-side.
        For proper pagination, a new C++ endpoint is needed.
        """
        # Calculate offset for client-side pagination
        offset = (page - 1) * page_size
        params = {"task_id": task_id, "limit": page_size + offset}

        # Use largest files endpoint (other endpoints could be added based on file_type)
        result = await self._request("GET", "/api/forensics/files/largest", params=params)
        # C++ backend may return a plain list or a wrapped {"largest_files": [...]}
        if isinstance(result, dict):
            all_files = result.get("largest_files") or result.get("files") or []
        elif isinstance(result, list):
            all_files = result
        else:
            all_files = []

        # Apply client-side filtering and pagination
        filtered_files = all_files
        if file_type:
            filtered_files = [f for f in filtered_files if f.get("category") == file_type]
        if extension:
            filtered_files = [f for f in filtered_files if f.get("extension") == extension]
        if deleted_only:
            filtered_files = [f for f in filtered_files if f.get("is_deleted", False)]

        # Apply pagination
        total_count = len(filtered_files)
        paginated_files = filtered_files[offset:offset + page_size]

        return {
            "files": paginated_files,
            "total_count": total_count,
        }
    
    # Event Operations
    
    async def get_task_events(
        self,
        task_id: str,
        event_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Get events from a task using comprehensive timeline endpoint."""
        params = {
            "task_id": task_id,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if event_type:
            params["event_type"] = event_type
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        result = await self._request("GET", "/api/forensics/timeline/comprehensive", params=params)

        # Handle different response formats
        if isinstance(result, dict):
            timeline = result.get("timeline", [])
            metadata = result.get("metadata", {})
            return {
                "events": timeline,
                "total_count": metadata.get("total_events", len(timeline)),
            }
        return {
            "events": result if isinstance(result, list) else [],
            "total_count": 0,
        }
    
    # Query Operations
    
    async def execute_query(
        self,
        task_id: str,
        database_type: str,
        table: Optional[str] = None,
        sql: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """Execute a query on a task's database."""
        payload = {
            "task_id": task_id,
            "database_type": database_type,
            "limit": limit,
        }
        if table:
            payload["table"] = table
        if sql:
            payload["sql"] = sql
        if parameters:
            payload["parameters"] = parameters
        
        result = await self._request("POST", "/api/database/query", json=payload)
        return {
            "columns": result.get("columns", []),
            "rows": result.get("rows", []),
        }
    
    # File Extraction Operations

    async def extract_files(
        self,
        task_id: str,
        file_paths: List[str],
        output_dir: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Extract specified file list to local disk.

        Args:
            task_id: Task ID
            file_paths: List of file paths to extract
            output_dir: Output directory (None = use default extracted_files)
            overwrite: Whether to overwrite existing files

        Returns:
            Response containing job_id for tracking extraction progress
        """
        # Use "name" mode with comma-separated file paths as pattern
        # This is the current API interface; may need C++ backend extension for true list mode
        payload = {
            "task_id": task_id,
            "mode": "name",
            "pattern": ",".join(file_paths),  # Comma-separated paths
            "output_dir": output_dir or "extracted_files",
            "overwrite": overwrite,
        }

        result = await self._request("POST", "/api/forensics/extract", json=payload)
        return result

    async def get_extraction_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get file extraction task status.

        Args:
            job_id: Extraction task ID

        Returns:
            Extraction status information including progress and results
        """
        result = await self._request("GET", "/api/forensics/extract/status", params={"job_id": job_id})
        return result

    # Export Operations

    async def export_toon(
        self,
        task_id: str,
        include_llm: bool = True,
    ) -> str:
        """Export task data in TOON format."""
        params = {"include_llm": include_llm}
        response = await self.client.get(
            f"/api/forensics/export/toon",
            params={"task_id": task_id, **params},
        )
        response.raise_for_status()
        return response.text

    async def get_files_toon_stream(
        self,
        task_id: str,
        batch_size: int = 100,
        include_llm: bool = False,
    ) -> Dict[str, Any]:
        """
        Get files in TOON format for streaming processing.

        Returns TOON data that can be split into batches for LLM processing.
        This is useful for file filtering without context overflow.

        Args:
            task_id: Task ID
            batch_size: Number of files per batch (for reference)
            include_llm: Include LLM analysis columns

        Returns:
            Dict with TOON schema and data lines
        """
        toon_data = await self.export_toon(task_id, include_llm=include_llm)

        lines = toon_data.split('\n')
        schema_line = None
        data_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('TOON.schema:'):
                schema_line = line
            else:
                data_lines.append(line)

        return {
            "schema": schema_line,
            "data_lines": data_lines,
            "total_files": len(data_lines),
            "batch_size": batch_size,
        }

    async def export_json(
        self,
        task_id: str,
        database_type: str,
        include_llm: bool = True,
    ) -> Dict[str, Any]:
        """Export task data in JSON format.

        Uses events export endpoint. For other database types,
        additional endpoints may be needed.
        """
        params = {"task_id": task_id}
        result = await self._request("GET", "/api/forensics/export/events/json", params=params)
        return result if isinstance(result, dict) else {"data": result}
