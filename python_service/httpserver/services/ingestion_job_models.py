"""Dataclasses and enums for the ingestion job system.

Extracted from ingestion_job_manager.py so the manager mixins under
ingestion_job_parts/ can import them without circular imports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"  # Only AI-analyzed files
    # Self-running job spawned by the analysis pipeline with fresh analysis
    # results in hand (SPEC kg-ingestion-hardening §B2). Never pushed to the
    # worker queue: queue_kg_sync_job starts it immediately.
    KG_SYNC = "kg_sync"


class JobStatus(str, Enum):
    """Job status states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IngestionJob:
    """Represents an ingestion job."""
    job_id: str
    task_id: str
    mode: IngestionMode
    status: JobStatus = JobStatus.PENDING
    progress: int = 0  # 0-100
    current_phase: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None

    # Additional metadata
    file_id: Optional[int] = None  # For SINGLE_FILE mode
    events_count: int = 0  # For EVENTS_ONLY mode

    # llm-throughput-hardening SPEC A: the service boot epoch that last moved
    # this job to RUNNING. On startup the stale sweep marks RUNNING jobs whose
    # epoch differs from the current process as stale (the owning process died
    # mid-run; nothing will ever update them again).
    runner_epoch: str = ""
    #: Bypass the foreground gate (manual escape hatch, POST /ingest force).
    force: bool = False


@dataclass
class JobSummary:
    """Summary of job results."""
    job_id: str
    status: JobStatus
    progress: int
    current_phase: str
    files_created: int = 0
    files_updated: int = 0
    events_attached: int = 0
    entities_linked: int = 0
    duplicates_merged: int = 0
    error: Optional[str] = None

