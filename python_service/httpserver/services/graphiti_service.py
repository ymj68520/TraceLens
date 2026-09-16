"""
Graphiti Service - Task-specific knowledge graph integration.

This service provides integration with the Graphiti knowledge graph:
- Task-specific graph namespaces (group_id = task_id)
- Data ingestion from forensic databases
- Entity and relationship search within task scope
- Graph statistics and status per task
"""

import asyncio
import logging
import uuid
import os
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from ..config import Settings

logger = logging.getLogger(__name__)



from .graphiti_parts import (
    GraphitiCoreMixin,
    GraphitiJobsMixin,
    GraphitiQueryMixin,
    GraphitiStatusMixin,
    GraphitiIngestMixin,
)


class GraphitiService(
    GraphitiCoreMixin,
    GraphitiJobsMixin,
    GraphitiQueryMixin,
    GraphitiStatusMixin,
    GraphitiIngestMixin,
):
    """
    Service for Graphiti knowledge graph operations.
    
    Each task has its own graph namespace using task_id as group_id.

    NOTE: The method implementations are split into mixins under the
    ``graphiti_parts`` subpackage for maintainability:
      - GraphitiCoreMixin   : lifecycle / graph instance management / health
      - GraphitiJobsMixin   : background ingestion jobs
      - GraphitiQueryMixin  : search / entities / relationships / graph data
      - GraphitiStatusMixin : status / neo4j counts / task-graph admin
      - GraphitiIngestMixin : case/task data ingestion
    The public surface (class name, all method signatures) is unchanged.
    """

    def __init__(self, settings: Settings):
        """Initialize the Graphiti service."""
        self.settings = settings
        self._initialized = False
        self._graphiti = None
        
        # Background job tracking
        self._jobs: Dict[str, Dict[str, Any]] = {}
        
        # Cache for task-specific graph instances
        self._task_graphs: Dict[str, Any] = {}

        # Shared read-path Neo4j driver (SPEC kg-ingestion-hardening §A2):
        # one pooled driver instead of a fresh driver per request, created
        # lazily by _get_shared_driver() and closed in shutdown().
        self._neo_driver: Any = None

        # Short-lived cache for list_task_graphs (full Episodic scan today;
        # a 5 s TTL keeps page loads off Neo4j without going stale).
        self._task_graphs_cache: Optional[List[str]] = None
        self._task_graphs_cache_at: float = 0.0

        # Single-flight locks per graph group (SPEC kg-ingestion-hardening
        # §B1): add_episode must be sequential within a group.
        self._ingest_locks: Dict[str, asyncio.Lock] = {}
