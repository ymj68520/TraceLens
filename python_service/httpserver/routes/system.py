
import os
import logging
import json
import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from ..config import Settings, get_settings, get_data_root

logger = logging.getLogger(__name__)
router = APIRouter()


def _service_log_path(service: str, *, stream: bool = False) -> str | None:
    name = {"cpp": "cpp_server.log", "python": "python_service.log"}.get(service)
    if name is None:
        return None
    configured = os.environ.get("TRACELENS_LOG_ROOT", "")
    if configured:
        root = Path(configured)
        data_root = get_data_root().resolve(strict=False)
        if (not root.is_absolute() or root.is_symlink() or
                not root.resolve(strict=False).is_relative_to(data_root)):
            return None
        return str(root / name)
    if os.environ.get("TRACELENS_REQUIRE_RELEASE_LAYOUT") == "1":
        return None  # a release must never fall back into a source-worktree log
    if stream:
        return os.path.join(os.getcwd(), "..", "build", "logs", name)
    project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
    if not os.path.exists(os.path.join(project_root, "build")):
        project_root = os.getcwd()
    return os.path.join(project_root, "build", "logs", name)


@router.get("/features")
async def get_feature_flags(settings: Settings = Depends(get_settings)):
    """Feature switches for the web frontend (mvp-phase1-acceptance SPEC §2).

    Single source of truth so the UI trims (hidden nav entries, removed LLM
    actions) follow the backend flags instead of a build-time constant."""
    return {
        "event_llm_analysis_enabled": settings.event_llm_analysis_enabled,
        "combined_case_enabled": settings.combined_case_enabled,
        "workbench_llm_enabled": settings.workbench_llm_enabled,
        "secondary_analysis_enabled": settings.secondary_analysis_active,
        "memory_forensics_enabled": settings.memory_forensics_enabled,
        "oss_analysis_enabled": settings.oss_analysis_enabled,
        "agent_execution_enabled": settings.agent_execution_enabled,
    }


@router.get("/logs")
async def get_all_logs(
    lines: int = Query(default=100, ge=1, le=2000),
    settings: Settings = Depends(get_settings),
):
    """Fallback for old components requesting /logs without service name."""
    return await get_service_logs("python", lines, settings)

def _parse_line(line: str) -> dict:
    """Helper to parse any log line into a structured object without failing."""
    line = line.strip()
    if not line:
        return {"timestamp": "", "level": "INFO", "message": ""}

    # Default values
    timestamp = datetime.now().isoformat()
    level = "INFO"
    message = line

    try:
        # Format 1: 2026-03-06 14:42:47,477 - NAME - LEVEL - MSG
        import re
        match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})[,\d]*\s-\s\S+\s-\s(\w+)\s-\s(.*)', line)
        if match:
            timestamp = match.group(1).replace(' ', 'T')
            level = match.group(2)
            message = match.group(3)
        # Format 2: 14:55:04 [INFO] MSG (as seen in user output)
        else:
            match2 = re.search(r'(\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.*)', line)
            if match2:
                timestamp = f"2026-03-06T{match2.group(1)}"
                level = match2.group(2)
                message = match2.group(3)
            # Format 3: INFO: ...
            elif ":" in line[:10]:
                parts = line.split(":", 1)
                level = parts[0].strip().upper()
                message = parts[1].strip()
    except:
        pass

    return {
        "timestamp": timestamp,
        "level": level,
        "message": message
    }

@router.get("/logs/{service}")
async def get_service_logs(
    service: str,
    lines: int = Query(default=100, ge=1, le=2000),
    settings: Settings = Depends(get_settings),
):
    """Get the last N lines of logs for a specific service."""
    log_path = _service_log_path(service)
    if not log_path or not os.path.exists(log_path):
        return {"service": service, "logs": [{"timestamp": "", "level": "WARN", "message": "Log file not found"}]}
        
    try:
        with open(log_path, 'r', errors='replace') as f:
            content = f.readlines()
            last_lines = content[-lines:] if len(content) > lines else content
            structured_logs = [_parse_line(line) for line in last_lines]
            return {"service": service, "logs": structured_logs, "total_lines": len(content)}
    except Exception as e:
        logger.error(f"Failed to read logs for {service}: {e}", exc_info=True)
        return {"service": service, "logs": [{"timestamp": "", "level": "ERROR", "message": "log file read failed"}]}

@router.get("/logs-stream/{service}")
async def stream_service_logs(
    service: str,
    window: int = 0,
    settings: Settings = Depends(get_settings),
):
    """
    Stream logs for a specific service (Server-Sent Events).

    ``window`` (seconds, optional) bounds the stream: the connection closes
    cleanly after the window elapses and the browser EventSource reconnects
    automatically (the file is re-seeked to EOF per connection, so no line is
    lost or duplicated). Required behind gateways that buffer responses and
    cannot flush SSE incrementally — an unbounded tail would hang those
    clients forever. 0 keeps the legacy unbounded tail.
    """
    log_path = _service_log_path(service, stream=True)
    if not log_path or not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail=f"Log file for {service} not found")

    async def log_generator():
        import json
        import time
        deadline = time.monotonic() + window if window and window > 0 else None
        with open(log_path, 'r', errors='replace') as f:
            # Start at the end
            f.seek(0, os.SEEK_END)
            if deadline is not None:
                # Reconnect hint so the next window starts promptly.
                yield "retry: 3000\n\n"
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    return
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                # Parse to JSON
                structured = _parse_line(line)
                yield f"data: {json.dumps(structured)}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")
