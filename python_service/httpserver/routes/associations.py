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
from ..path_utils import normalize_evidence_path

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
    """Extract parent directory from file path (canonicalized first)."""
    if not file_path:
        return "/"
    # Canonicalize separators/structure before deriving the parent.
    normalized = normalize_evidence_path(file_path)
    parent = os.path.dirname(normalized)
    return parent or "/"


def is_path_under_directory(path: str, parent: str) -> bool:
    """Segment-aware containment: True if canonical `path` equals or is inside canonical `parent`.

    An empty or "/" parent means "no directory constraint" (matches everything).
    Segment-aware so '/case/a' does NOT match '/case/abc' or '/case/a-extra'.
    """
    path_n = normalize_evidence_path(path)
    parent_n = normalize_evidence_path(parent)
    if not parent_n or parent_n == "/":
        return True
    return path_n == parent_n or path_n.startswith(parent_n + "/")


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

        # Time window: strict inequalities preserve the exact `abs(diff) < 300`
        # association semantics (BETWEEN would silently turn it into <= 300).
        lo = cluster_timestamp - 300
        hi = cluster_timestamp + 300
        parent_n = normalize_evidence_path(request.parent_directory)

        try:
            with sqlite3.connect(files_db) as conn:
                conn.row_factory = sqlite3.Row

                # Candidate union (raw atime/crtime ∪ files mtime/ctime) via
                # ATTACH + LEFT JOIN per path. files.db stays primary (metadata
                # source); a file present in files.db but absent from raw is still
                # selected by the f.mtime/f.ctime clauses — per-Evidence fallback
                # to files.db, NOT "raw entirely missing only".
                attached_raw = False
                if raw_db and os.path.exists(raw_db):
                    try:
                        conn.execute("ATTACH DATABASE ? AS raw", (raw_db,))
                        attached_raw = True
                    except sqlite3.Error as e:
                        logger.warning(f"Could not attach raw.db for timestamps: {e}")

                if attached_raw:
                    files_table_sql = """
                        SELECT f.path AS file_path, f.size AS file_size, f.mtime, f.ctime,
                               f.extension, f.name, f.llm_summary, f.llm_description,
                               r.atime AS atime, r.crtime AS crtime
                        FROM files f
                        LEFT JOIN raw.files r ON r.path = f.path
                        WHERE (f.mtime IS NOT NULL AND f.mtime > ? AND f.mtime < ?)
                           OR (f.ctime IS NOT NULL AND f.ctime > ? AND f.ctime < ?)
                           OR (r.atime IS NOT NULL AND r.atime > ? AND r.atime < ?)
                           OR (r.crtime IS NOT NULL AND r.crtime > ? AND r.crtime < ?)
                        ORDER BY f.mtime DESC
                    """
                    params = [lo, hi, lo, hi, lo, hi, lo, hi]
                else:
                    # raw.db unavailable: uniform per-path fallback to files.db
                    # mtime/ctime (atime/crtime are not stored in files.db).
                    files_table_sql = """
                        SELECT path AS file_path, size AS file_size, mtime, ctime,
                               extension, name, llm_summary, llm_description,
                               NULL AS atime, NULL AS crtime
                        FROM files
                        WHERE (mtime IS NOT NULL AND mtime > ? AND mtime < ?)
                           OR (ctime IS NOT NULL AND ctime > ? AND ctime < ?)
                        ORDER BY mtime DESC
                    """
                    params = [lo, hi, lo, hi]

                cur = conn.execute(files_table_sql, params)

                for row in cur.fetchall():
                    file_data = dict(row)

                    # B3: require the file to be inside the cluster's parent
                    # directory (segment-aware; empty/"/" = unconstrained).
                    if not is_path_under_directory(file_data['file_path'], parent_n):
                        continue

                    # Calculate time differences from cluster time (all 4 timestamps).
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

                    # Final adjudication: at least one timestamp strictly within
                    # ±5 minutes (300s). SQL already bounded candidates; this is
                    # the source of truth for the boundary.
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

        file_path_normalized = normalize_evidence_path(request.file_path)
        file_parent_dir = extract_parent_directory(file_path_normalized)

        # Get file timestamps from raw.db (has all 4: atime, mtime, ctime, crtime)
        file_timestamps = {'mtime': None, 'ctime': None, 'atime': None, 'crtime': None}
        logger.info(f"[Associations] raw_db path: {raw_db}, exists: {os.path.exists(raw_db) if raw_db else 'N/A'}")

        if raw_db and os.path.exists(raw_db):
            try:
                with sqlite3.connect(raw_db) as raw_conn:
                    raw_conn.row_factory = sqlite3.Row
                    query = "SELECT atime, mtime, ctime, crtime FROM files WHERE path = ?"
                    logger.info(f"[Associations] Query raw.db with: {query} params: [{file_path_normalized}]")
                    raw_cur = raw_conn.execute(query, [file_path_normalized])
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

        # Fallback: query files.db if raw.db didn't have the data (timestamp 0 is valid)
        if not any(v is not None for v in file_timestamps.values()) and files_db:
            try:
                with sqlite3.connect(files_db) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute("SELECT mtime, ctime FROM files WHERE path = ?", [file_path_normalized])
                    row = cur.fetchone()
                    if row:
                        file_timestamps['mtime'] = row['mtime']
                        file_timestamps['ctime'] = row['ctime']
            except sqlite3.Error as e:
                logger.warning(f"Could not query files.db for timestamps: {e}")

        # Whether the file has any usable timestamp (0 is a valid timestamp).
        has_timestamps = any(v is not None for v in file_timestamps.values())

        # Get related clusters from events database
        related_clusters = []

        try:
            with sqlite3.connect(events_db) as conn:
                conn.row_factory = sqlite3.Row

                # B5b: complete the clustering FIRST (CTE), then filter clusters by
                # the file's timestamp window. Do NOT pre-truncate event rows (that
                # would alter cluster_start/end/count/representative and cluster
                # membership) and do NOT ORDER BY ... LIMIT limit*10 (that dropped
                # valid clusters for being "not new enough").
                valid_ts = [v for v in file_timestamps.values() if v is not None]
                if valid_ts:
                    rep_lo = min(valid_ts) - 300
                    rep_hi = max(valid_ts) + 300
                    cluster_filter = "WHERE representative_timestamp > ? AND representative_timestamp < ?"
                    cluster_params = [rep_lo, rep_hi]
                else:
                    cluster_filter = ""
                    cluster_params = []

                sql = f"""
                    WITH clusters AS (
                        SELECT
                            (timestamp / 60) AS time_window,
                            event_type,
                            MIN(timestamp) AS cluster_start,
                            MAX(timestamp) AS cluster_end,
                            COUNT(*) AS event_count,
                            CASE
                                WHEN MIN(timestamp) != MAX(timestamp) THEN MIN(timestamp)
                                ELSE timestamp
                            END AS representative_timestamp,
                            llm_summary,
                            llm_description,
                            llm_keywords,
                            llm_is_relevant
                        FROM events
                        GROUP BY time_window, event_type
                    )
                    SELECT * FROM clusters
                    {cluster_filter}
                    ORDER BY representative_timestamp DESC
                """

                cur = conn.execute(sql, cluster_params)
                rows = cur.fetchall()

                for row in rows:
                    cluster = dict(row)
                    cluster_time = cluster['representative_timestamp']

                    # Derive the cluster's directories from the FULL set of event
                    # paths (no LIMIT 5) so a target directory appearing only in
                    # the 6th+ event is not missed. The response still exposes only
                    # a small sample.
                    all_paths = [
                        r['file_path'] for r in conn.execute(
                            "SELECT DISTINCT file_path FROM events "
                            "WHERE (timestamp / 60) = ? AND event_type = ?",
                            [cluster['time_window'], cluster['event_type']],
                        )
                        if r['file_path']
                    ]

                    if not all_paths:
                        continue

                    cluster_parent_dirs = {extract_parent_directory(p) for p in all_paths}
                    cluster_sample_files = all_paths[:5]

                    # Response field (kept stable; NOT used as the predicate).
                    cluster['parent_directory'] = next(iter(cluster_parent_dirs), '/')

                    # B2/B4: segment-aware directory predicate over the full dir set.
                    dir_matches = (
                        not cluster_parent_dirs
                        or any(is_path_under_directory(file_path_normalized, d) for d in cluster_parent_dirs)
                    )

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
                    if not matched and not has_timestamps and dir_matches:
                        matched = True
                        cluster['matched_time'] = None
                        cluster['time_diff'] = None
                        cluster['time_diff_formatted'] = "无时间戳"

                    # B4: require BOTH temporal and directory match.
                    if matched and dir_matches:
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
