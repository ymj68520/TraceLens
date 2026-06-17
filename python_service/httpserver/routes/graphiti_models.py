"""
Graphiti routes — Pydantic request/response models.

Extracted from graphiti.py so the per-domain endpoint modules under
graphiti_endpoints/ can import the same types without circular imports.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field




# ==============================================================================
# Enums
# ==============================================================================

class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"


# ==============================================================================
# Request/Response Models
# ==============================================================================

class IngestRequest(BaseModel):
    """Request model for data ingestion."""
    task_id: str = Field(..., description="Task ID to ingest data from (also used as graph namespace)")
    mode: IngestionMode = Field(default=IngestionMode.FULL, description="Ingestion mode")
    include_llm_descriptions: bool = Field(default=True, description="Include LLM-generated descriptions")
    batch_size: int = Field(default=50, ge=1, le=500, description="Batch size for processing")
    max_episodes: int = Field(default=100, ge=0, le=10000, description="Maximum episodes to process (0 = unlimited)")


class FileIngestRequest(BaseModel):
    """Request model for single file ingestion."""
    file_id: int = Field(..., description="Database ID of the file")
    task_id: str = Field(..., description="Task ID")
    update_analysis: bool = Field(default=False, description="Force LLM re-analysis before ingest")


class EventSyncRequest(BaseModel):
    """Request model for event synchronization."""
    task_id: str = Field(..., description="Task ID")
    events: List[Dict[str, Any]] = Field(..., description="List of event dictionaries")


class IngestionResponse(BaseModel):
    """Response model for ingestion operation."""
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Response model for job status query."""
    job_id: str
    status: str
    progress: int
    current_phase: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class IngestResponse(BaseModel):
    """Response model for ingestion operation."""
    success: bool
    task_id: str
    job_id: Optional[str] = None
    message: str
    entities_created: int = 0
    relationships_created: int = 0
    timestamp: str


class SearchRequest(BaseModel):
    """Request model for graph search."""
    query: str = Field(..., min_length=1, description="Search query")
    task_id: str = Field(..., description="Task ID to search within")
    entity_types: Optional[List[str]] = Field(default=None, description="Filter by entity types")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    include_relationships: bool = Field(default=True, description="Include related entities")


class SearchResult(BaseModel):
    """Single search result."""
    entity_id: str
    entity_type: str
    name: str
    properties: Dict[str, Any]
    score: float
    relationships: Optional[List[Dict[str, Any]]] = None


class SearchResponse(BaseModel):
    """Response model for search operation."""
    success: bool
    query: str
    task_id: str
    results: List[SearchResult]
    total_count: int
    timestamp: str


class EntityListResponse(BaseModel):
    """Response model for entity listing."""
    success: bool
    task_id: str
    entities: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class RelationshipListResponse(BaseModel):
    """Response model for relationship listing."""
    success: bool
    task_id: str
    relationships: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class GraphitiStatusResponse(BaseModel):
    """Response model for Graphiti service status."""
    status: str
    neo4j_connected: bool
    total_entities: int
    total_relationships: int
    task_id: Optional[str] = None
    timestamp: str


class TaskGraphsResponse(BaseModel):
    """Response model for listing task graphs."""
    success: bool
    task_ids: List[str]
    count: int
    timestamp: str

