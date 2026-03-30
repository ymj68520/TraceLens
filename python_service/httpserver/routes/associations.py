"""
Association routes for linking event clusters with files.

Provides endpoints for:
- Getting files related to an event cluster
- Getting event clusters related to a file
- Time-based anomaly detection

Note: For complete timestamp data (atime, mtime, ctime, crtime), we query:
- _files.db: files table has mtime, ctime
- _raw.db: files table has atime, mtime, ctime, crtime
"""

import logging
import os
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response Models

class ClusterFilesRequest(BaseModel):
    """Request model for getting files related to a cluster."""
    task_id: str = Field(..., description="Task ID")
    time_window: int = Field(..., description="Cluster time window (timestamp / 60)")
    timestamp: Optional[int] = Field(None, description="Cluster timestamp (original, deprecated - use time_window)")
    event_type: str = Field(..., description="Event type (CREATED, MODIFIED, DELETED, etc.)")
    parent_directory: str = Field("", description="Parent directory of the events")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results to return")


class FileClustersRequest(BaseModel):
    """Request model for getting clusters related to a file - simplified."""
    task_id: str = Field(..., description="Task ID")
    file_path: str = Field(..., description="Full file path")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results to return")


class ClusterFilesResponse(BaseModel):
    """Response model for cluster-related files."""
    success: bool
    files: List[Dict[str, Any]]
    total_count: int
    cluster_info: Dict[str, Any]


class FileClustersResponse(BaseModel):
    """Response model for file-related clusters."""
    success: bool
    clusters: List[Dict[str, Any]]
    total_count: int
    file_info: Dict[str, Any]


# Helper Functions

def extract_parent_directory(file_path: str) -> str:
    """Extract parent directory from file path."""
    if not file_path:
        return "/"
    # Normalize path separators
    normalized = file_path.replace("\\", "/")
    # Get parent directory
    parent = os.path.dirname(normalized)
    return parent or "/"


def detect_time_anomaly(file_data: Dict[str, Any], cluster_time: int) -> List[str]:
    """
    Detect time anomalies in file timestamps.

    Anomaly conditions:
    1. mtime differs from cluster_time by > 1 hour (suspicious time manipulation)
    2. crtime > mtime (creation time after modification - abnormal)
    3. atime < mtime (access time before modification - possible backdating)
    4. High variance among timestamps (> 1 day spread)

    Args:
        file_data: File record with atime, mtime, ctime, crtime
        cluster_time: Event cluster timestamp for comparison

    Returns:
        List of anomaly type strings
    """
    anomalies = []

    mtime = file_data.get('mtime')
    crtime = file_data.get('crtime')
    atime = file_data.get('atime')
    ctime = file_data.get('ctime')

    # Check 1: mtime mismatch with cluster time
    if mtime and abs(mtime - cluster_time) > 3600:
        anomalies.append('mtime_mismatch')

    # Check 2: crtime after mtime
    if crtime and mtime and crtime > mtime:
        anomalies.append('crtime_after_mtime')

    # Check 3: atime before mtime
    if atime and mtime and atime < mtime:
        anomalies.append('atime_before_mtime')

    # Check 4: High time variance (> 1 day = 86400 seconds)
    times = [t for t in [atime, mtime, ctime, crtime] if t is not None]
    if times and len(times) >= 2:
        time_variance = max(times) - min(times)
        if time_variance > 86400:
            anomalies.append('high_time_variance')

    return anomalies


def format_time_diff(seconds: int) -> str:
    """Format time difference in human-readable format."""
    if seconds is None:
        return "N/A"
    if abs(seconds) < 60:
        return f"{abs(seconds)}秒"
    if abs(seconds) < 3600:
        return f"{abs(seconds) // 60}分钟"
    if abs(seconds) < 86400:
        return f"{abs(seconds) // 3600}小时"
    return f"{abs(seconds) // 86400}天"


# Routes

@router.post("/cluster-files", response_model=ClusterFilesResponse)
async def get_cluster_related_files(
    request: ClusterFilesRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Get files related to an event cluster.

    Matching logic:
    1. File path contains the cluster's parent_directory
    2. At least one file timestamp is within ±5 minutes of cluster time
    3. Returns time differences and anomaly detection results
    """
    import sqlite3

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        logger.info(f"[Associations] cluster-files request: task_id={request.task_id}, time_window={request.time_window}, event_type={request.event_type}")

        # Get task info to find database paths
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        files_db = task_info.get("output_files_db") or ""
        # Build raw.db path from files.db path for complete timestamps (atime, mtime, ctime, crtime)
        raw_db = task_info.get("output_raw_db") or files_db.replace("_files.db", "_raw.db") if files_db else ""

        if not files_db:
            raise HTTPException(status_code=400, detail="No files database for this task")

        related_files = []
        # Calculate cluster timestamp from time_window
        if request.time_window is not None:
            cluster_timestamp = request.time_window * 60
        elif request.timestamp is not None:
            cluster_timestamp = request.timestamp
        else:
            cluster_timestamp = 0

        # Build a map of complete timestamps from raw.db (has atime, mtime, ctime, crtime)
        raw_timestamps = {}
        if raw_db and os.path.exists(raw_db):
            try:
                with sqlite3.connect(raw_db) as raw_conn:
                    raw_conn.row_factory = sqlite3.Row
                    raw_cur = raw_conn.execute("""
                        SELECT path, atime, mtime, ctime, crtime
                        FROM files
                        WHERE atime IS NOT NULL OR mtime IS NOT NULL OR ctime IS NOT NULL OR crtime IS NOT NULL
                    """)
                    for row in raw_cur.fetchall():
                        raw_timestamps[row['path']] = {
                            'atime': row['atime'],
                            'mtime': row['mtime'],
                            'ctime': row['ctime'],
                            'crtime': row['crtime']
                        }
            except sqlite3.Error as e:
                logger.warning(f"Could not read raw.db for timestamps: {e}")

        try:
            with sqlite3.connect(files_db) as conn:
                conn.row_factory = sqlite3.Row

                # Query files table for file metadata and LLM data
                files_table_sql = """
                    SELECT path as file_path, size as file_size, mtime, ctime,
                           extension, name, llm_summary, llm_description
                    FROM files
                    ORDER BY mtime DESC
                    LIMIT ?
                """

                cur = conn.execute(files_table_sql, [request.limit * 3])
                files_table_rows = cur.fetchall()

                for row in files_table_rows:
                    file_data = dict(row)

                    # Merge with raw timestamps if available (has all 4 timestamps)
                    raw_ts = raw_timestamps.get(file_data['file_path'], {})
                    if raw_ts:
                        file_data['atime'] = raw_ts.get('atime')
                        file_data['crtime'] = raw_ts.get('crtime')
                    else:
                        file_data['atime'] = None
                        file_data['crtime'] = None

                    # Calculate time differences from cluster time (now uses all 4 timestamps)
                    time_diffs = {
                        'atime_diff': abs(file_data.get('atime', 0) - cluster_timestamp) if file_data.get('atime') else None,
                        'mtime_diff': abs(file_data.get('mtime', 0) - cluster_timestamp) if file_data.get('mtime') else None,
                        'ctime_diff': abs(file_data.get('ctime', 0) - cluster_timestamp) if file_data.get('ctime') else None,
                        'crtime_diff': abs(file_data.get('crtime', 0) - cluster_timestamp) if file_data.get('crtime') else None,
                    }

                    # Find minimum time difference
                    valid_diffs = [d for d in time_diffs.values() if d is not None]
                    if not valid_diffs:
                        continue

                    min_diff = min(valid_diffs)

                    # Only include if at least one timestamp is within ±5 minutes (300 seconds)
                    if min_diff < 300:
                        file_data['time_diffs'] = time_diffs
                        file_data['min_time_diff'] = min_diff

                        # Detect anomalies
                        file_data['anomalies'] = detect_time_anomaly(file_data, cluster_timestamp)

                        # Add human-readable time difference strings
                        file_data['time_diffs_formatted'] = {
                            k: format_time_diff(v) for k, v in time_diffs.items()
                        }

                        related_files.append(file_data)

        except sqlite3.Error as e:
            logger.error(f"Database error querying files: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

        # Sort by minimum time difference (most relevant first)
        related_files.sort(key=lambda x: x.get('min_time_diff', float('inf')))

        # Limit results
        related_files = related_files[:request.limit]

        return ClusterFilesResponse(
            success=True,
            files=related_files,
            total_count=len(related_files),
            cluster_info={
                "timestamp": cluster_timestamp,
                "event_type": request.event_type,
                "parent_directory": request.parent_directory
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cluster related files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file-clusters", response_model=FileClustersResponse)
async def get_file_related_clusters(
    request: FileClustersRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Get event clusters related to a file.

    This endpoint queries the files database to get the file's timestamps,
    then finds matching event clusters from the events database.

    Matching logic:
    1. File path matches cluster's parent_directory (extracted from event file_path)
    2. At least one file timestamp is within ±5 minutes of cluster time
    """
    import sqlite3

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Get task info to find database paths
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        files_db = task_info.get("output_files_db") or ""
        # Build raw.db path from files.db path for complete timestamps (atime, mtime, ctime, crtime)
        raw_db = task_info.get("output_raw_db") or files_db.replace("_files.db", "_raw.db") if files_db else ""
        events_db = task_info.get("output_events_db") or ""

        if not events_db:
            raise HTTPException(status_code=400, detail="No events database for this task")

        file_path_normalized = request.file_path.replace("\\", "/")
        file_parent_dir = extract_parent_directory(request.file_path)

        # Get file timestamps from raw.db (has all 4: atime, mtime, ctime, crtime)
        file_timestamps = {'mtime': None, 'ctime': None, 'atime': None, 'crtime': None}
        logger.info(f"[Associations] raw_db path: {raw_db}, exists: {os.path.exists(raw_db) if raw_db else 'N/A'}")

        if raw_db and os.path.exists(raw_db):
            try:
                with sqlite3.connect(raw_db) as raw_conn:
                    raw_conn.row_factory = sqlite3.Row
                    query = "SELECT atime, mtime, ctime, crtime FROM files WHERE path = ?"
                    logger.info(f"[Associations] Query raw.db with: {query} params: [{request.file_path}]")
                    raw_cur = raw_conn.execute(query, [request.file_path])
                    row = raw_cur.fetchone()
                    logger.info(f"[Associations] raw.db row: {row}")
                    if row:
                        file_timestamps = {
                            'atime': row['atime'],
                            'mtime': row['mtime'],
                            'ctime': row['ctime'],
                            'crtime': row['crtime']
                        }
                    else:
                        logger.info(f"[Associations] No row found in raw.db for {request.file_path}")
            except sqlite3.Error as e:
                logger.warning(f"Could not read raw.db for file timestamps: {e}")

        # Fallback: query files.db if raw.db didn't have the data
        if not any(v for v in file_timestamps.values()) and files_db:
            try:
                with sqlite3.connect(files_db) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute("SELECT mtime, ctime FROM files WHERE path = ?", [request.file_path])
                    row = cur.fetchone()
                    if row:
                        file_timestamps['mtime'] = row['mtime']
                        file_timestamps['ctime'] = row['ctime']
            except sqlite3.Error as e:
                logger.warning(f"Could not query files.db for timestamps: {e}")

        # Get related clusters from events database
        related_clusters = []

        try:
            with sqlite3.connect(events_db) as conn:
                conn.row_factory = sqlite3.Row

                # Get unique event clusters (grouped by time_window and event_type)
                sql = """
                    SELECT
                        (timestamp / 60) as time_window,
                        event_type,
                        MIN(timestamp) as cluster_start,
                        MAX(timestamp) as cluster_end,
                        COUNT(*) as event_count,
                        CASE
                            WHEN MIN(timestamp) != MAX(timestamp) THEN MIN(timestamp)
                            ELSE timestamp
                        END as representative_timestamp,
                        llm_summary,
                        llm_description,
                        llm_keywords,
                        llm_is_relevant
                    FROM events
                    GROUP BY time_window, event_type
                    ORDER BY representative_timestamp DESC
                    LIMIT ?
                """

                cur = conn.execute(sql, [request.limit * 10])  # Get more candidates, filter later
                rows = cur.fetchall()

                for row in rows:
                    cluster = dict(row)
                    cluster_time = cluster['representative_timestamp']

                    # Get sample events from this cluster to extract parent directory
                    sample_sql = """
                        SELECT DISTINCT file_path
                        FROM events
                        WHERE (timestamp / 60) = ? AND event_type = ?
                        LIMIT 5
                    """
                    sample_cur = conn.execute(sample_sql, [cluster['time_window'], cluster['event_type']])
                    sample_rows = sample_cur.fetchall()

                    if not sample_rows:
                        continue

                    # Extract parent directory from sample file paths
                    cluster_parent_dirs = set()
                    cluster_sample_files = []
                    for sample_row in sample_rows:
                        sample_path = sample_row['file_path']
                        if sample_path:
                            cluster_parent_dirs.add(extract_parent_directory(sample_path))
                            cluster_sample_files.append(sample_path)

                    # Use the most common parent directory
                    if cluster_parent_dirs:
                        cluster['parent_directory'] = list(cluster_parent_dirs)[0]
                    else:
                        cluster['parent_directory'] = '/'

                    # Check if file path matches cluster directory
                    # Handle root-level files (no parent directory)
                    dir_matches = False
                    if not cluster_parent_dirs or list(cluster_parent_dirs)[0] in ['/', '']:
                        # No specific directory constraint, files match
                        dir_matches = True
                    else:
                        for cluster_dir in cluster_parent_dirs:
                            normalized_cluster_dir = cluster_dir.replace("\\", "/")
                            if file_path_normalized.startswith(normalized_cluster_dir):
                                dir_matches = True
                                break

                    # Check time matching
                    matched = False
                    matched_time = None
                    min_diff = float('inf')

                    # Check all available timestamps (from raw.db: atime, mtime, ctime, crtime)
                    for ts_name, ts_value in [
                        ('atime', file_timestamps.get('atime')),
                        ('mtime', file_timestamps.get('mtime')),
                        ('ctime', file_timestamps.get('ctime')),
                        ('crtime', file_timestamps.get('crtime'))
                    ]:
                        if ts_value is not None:
                            diff = abs(ts_value - cluster_time)
                            if diff < min_diff:
                                min_diff = diff
                            if diff < 300:  # Within 5 minutes
                                matched = True
                                matched_time = ts_name
                                cluster['matched_time'] = ts_name
                                cluster['time_diff'] = diff
                                cluster['time_diff_formatted'] = format_time_diff(diff)
                                break

                    # If no timestamps available, include cluster if directory matches
                    if not matched and not file_timestamps and dir_matches:
                        matched = True
                        cluster['matched_time'] = None
                        cluster['time_diff'] = None
                        cluster['time_diff_formatted'] = "无时间戳"

                    if matched:
                        # Add sample file
                        cluster['file_path'] = cluster_sample_files[0] if cluster_sample_files else None
                        cluster['cluster_count'] = cluster['event_count']

                        related_clusters.append(cluster)

        except sqlite3.Error as e:
            logger.error(f"Database error querying clusters: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

        # Sort by time difference (most relevant first), put null timestamp matches at end
        def sort_key(cluster):
            diff = cluster.get('time_diff')
            return diff if diff is not None else float('inf')

        related_clusters.sort(key=sort_key)

        # Limit results
        related_clusters = related_clusters[:request.limit]

        return FileClustersResponse(
            success=True,
            clusters=related_clusters,
            total_count=len(related_clusters),
            file_info={
                "file_path": request.file_path,
                "parent_directory": file_parent_dir,
                "mtime": file_timestamps.get('mtime'),
                "ctime": file_timestamps.get('ctime'),
                "atime": file_timestamps.get('atime'),
                "crtime": file_timestamps.get('crtime')
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file related clusters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
