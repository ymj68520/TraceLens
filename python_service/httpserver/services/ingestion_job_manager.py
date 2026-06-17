"""
Ingestion Job Manager - Background job queue for Graphiti ingestion operations.

This service manages asynchronous ingestion jobs with persistent state tracking,
supporting different ingestion modes and providing status polling capabilities.
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import Settings

logger = logging.getLogger(__name__)


from .ingestion_job_parts import (
    IngestionJobManagerMixin,
    IngestionJobWorkerMixin,
)
# Re-export the dataclasses/enums for backward compatibility
# (they used to live directly in this module).
from .ingestion_job_models import (  # noqa: F401
    IngestionMode,
    JobStatus,
    IngestionJob,
    JobSummary,
)


class IngestionJobManager(
    IngestionJobManagerMixin,
    IngestionJobWorkerMixin,
):
    """Background job queue for Graphiti ingestion operations.

    NOTE: Method implementations are split into mixins under the
    ``ingestion_job_parts`` subpackage for maintainability:
      - IngestionJobManagerMixin : lifecycle, persistence, queue/status APIs
      - IngestionJobWorkerMixin  : background worker + per-mode processing
    The dataclasses/enums (IngestionMode, JobStatus, IngestionJob, JobSummary)
    live in ingestion_job_models.py and are re-exported here for compatibility.
    Public surface (class name, all method signatures) is unchanged.
    """
