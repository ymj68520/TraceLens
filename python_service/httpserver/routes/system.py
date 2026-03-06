
import os
import logging
import json
import asyncio
import re
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

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
    # Absolute paths based on project root
    project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
    if not os.path.exists(os.path.join(project_root, "build")):
        project_root = os.getcwd()

    log_map = {
        "cpp": os.path.join(project_root, "build", "logs", "cpp_server.log"),
        "python": os.path.join(project_root, "build", "logs", "python_service.log"),
    }
    
    log_path = log_map.get(service)
    if not log_path or not os.path.exists(log_path):
        return {"service": service, "logs": [{"timestamp": "", "level": "WARN", "message": f"Log file not found at {log_path}"}]}
        
    try:
        with open(log_path, 'r', errors='replace') as f:
            content = f.readlines()
            last_lines = content[-lines:] if len(content) > lines else content
            structured_logs = [_parse_line(line) for line in last_lines]
            return {"service": service, "logs": structured_logs, "total_lines": len(content)}
    except Exception as e:
        return {"service": service, "logs": [{"timestamp": "", "level": "ERROR", "message": str(e)}]}

@router.get("/logs-stream/{service}")
async def stream_service_logs(
    service: str,
    settings: Settings = Depends(get_settings),
):
    """
    Stream logs for a specific service (Server-Sent Events).
    """
    log_map = {
        "cpp": os.path.join(os.getcwd(), "..", "build", "logs", "cpp_server.log"),
        "python": os.path.join(os.getcwd(), "..", "build", "logs", "python_service.log"),
    }
    
    log_path = log_map.get(service)
    if not log_path or not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail=f"Log file for {service} not found")

    async def log_generator():
        import json
        with open(log_path, 'r', errors='replace') as f:
            # Start at the end
            f.seek(0, os.SEEK_END)
            import asyncio
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                # Parse to JSON
                structured = _parse_line(line)
                yield f"data: {json.dumps(structured)}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")
