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
        Make an HTTP request to the C++ backend.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path
            **kwargs: Additional arguments for httpx
        
        Returns:
            Response JSON data.
        
        Raises:
            httpx.HTTPError: On request failure.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await self.client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
    
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
        
        return await self._request("GET", "/api/tasks", params=params)
    
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific task."""
        try:
            result = await self._request("GET", f"/api/tasks/{task_id}")
            return result.get("data", result)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
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
        """Get files from a task."""
        params = {"limit": limit}
        if file_types:
            params["file_type"] = ",".join(file_types)
        
        result = await self._request("GET", f"/api/forensics/files/{task_id}", params=params)
        return result.get("data", {}).get("files", [])
    
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
        """Get paginated files from a task."""
        params = {
            "page": page,
            "page_size": page_size,
            "include_llm": include_llm,
        }
        if file_type:
            params["file_type"] = file_type
        if extension:
            params["extension"] = extension
        if deleted_only:
            params["deleted_only"] = True
        
        result = await self._request("GET", f"/api/forensics/files/{task_id}", params=params)
        return {
            "files": result.get("data", {}).get("files", []),
            "total_count": result.get("data", {}).get("total_count", 0),
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
        """Get events from a task."""
        params = {"page": page, "page_size": page_size}
        if event_type:
            params["event_type"] = event_type
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        
        result = await self._request("GET", f"/api/forensics/timeline/{task_id}", params=params)
        return {
            "events": result.get("data", {}).get("events", []),
            "total_count": result.get("data", {}).get("total_count", 0),
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
    
    async def export_json(
        self,
        task_id: str,
        database_type: str,
        include_llm: bool = True,
    ) -> Dict[str, Any]:
        """Export task data in JSON format."""
        params = {
            "task_id": task_id,
            "database_type": database_type,
            "include_llm": include_llm,
        }
        result = await self._request("GET", "/api/forensics/export/json", params=params)
        return result.get("data", {})
