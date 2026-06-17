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
