"""
System log routes.

Provides endpoints for retrieving service logs.
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from ..config import Settings, get_settings

router = APIRouter()

logger = logging.getLogger(__name__)


class LogEntry(BaseModel):
    """Log entry model."""
    timestamp: str
    level: str
    message: str


class LogsResponse(BaseModel):
    """Logs response model."""
    service: str
    logs: List[LogEntry]
    total_count: int


def _parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a log line into structured data.

    Supports formats:
    - 2026-03-06 12:46:05,345 - module - LEVEL - message
    - [2026-03-06 12:46:05] LEVEL message
    - LEVEL message
    """
    if not line.strip():
        return None

    # Try to parse standard Python log format
    # Format: YYYY-MM-DD HH:MM:SS,mmm - module - LEVEL - message
    parts = line.split(' - ')
    if len(parts) >= 3:
        try:
            timestamp_part = parts[0].strip()
            level = parts[-2].strip()
            message = ' - '.join(parts[2:])

            # Parse timestamp
            if ' ' in timestamp_part:
                timestamp = timestamp_part.split(' ')[0] + 'T' + timestamp_part.split(' ')[1]
            else:
                timestamp = datetime.now().isoformat()

            return {
                'timestamp': timestamp,
                'level': level.upper(),
                'message': message.strip()
            }
        except:
            pass

    # Fallback: treat entire line as message with current timestamp
    return {
        'timestamp': datetime.now().isoformat(),
        'level': 'INFO',
        'message': line.strip()
    }


def _get_log_file_path(settings: Settings) -> Optional[str]:
    """Get the path to the log file."""
    # Check common log file locations
    log_paths = [
        os.path.join(os.path.dirname(__file__), '../../../logs/httpserver.log'),
        'logs/httpserver.log',
        'python_service.log',
        '/tmp/forensics_python.log',
    ]

    for path in log_paths:
        full_path = os.path.abspath(path)
        if os.path.exists(full_path):
            return full_path

    return None


def _get_recent_logs(log_file: str, lines: int = 100) -> List[str]:
    """Get recent lines from a log file."""
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            # Read last N lines efficiently
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        logger.error(f"Failed to read log file {log_file}: {e}")
        return []


@router.get("/api/system/logs", response_model=LogsResponse)
async def get_system_logs(
    lines: int = Query(100, ge=1, le=1000, description="Number of recent log lines to retrieve"),
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR)"),
    settings: Settings = Depends(get_settings)
):
    """
    Get recent system logs from the Python service.

    Returns structured log entries with timestamps and levels.
    """
    logs = []

    # Try to read from log file
    log_file = _get_log_file_path(settings)

    if log_file:
        raw_lines = _get_recent_logs(log_file, lines)
    else:
        # If no log file exists, return recent in-memory logs
        # For now, return a helpful message
        return LogsResponse(
            service="python-http-service",
            logs=[],
            total_count=0
        )

    # Parse and filter log lines
    for line in raw_lines:
        entry = _parse_log_line(line)
        if entry:
            # Filter by level if specified
            if level and entry['level'] != level.upper():
                continue
            logs.append(LogEntry(**entry))

    return LogsResponse(
        service="python-http-service",
        logs=logs,
        total_count=len(logs)
    )


@router.get("/api/system/logs/stream")
async def stream_logs():
    """
    Stream logs via Server-Sent Events (SSE).

    This endpoint provides a real-time stream of log entries.
    Note: This is a placeholder for future SSE implementation.
    """
    raise HTTPException(
        status_code=501,
        detail="Log streaming not yet implemented. Use WebSocket endpoint instead."
    )
