"""
LLM routes — Pydantic request/response models.

Extracted from llm.py so the per-domain endpoint modules under llm_endpoints/
can import the same types without circular imports.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from pydantic import BaseModel, Field




# Request/Response Models

class AnalyzeRequest(BaseModel):
    """Request model for file analysis."""
    task_id: Optional[str] = Field(None, description="Task ID owning the persistence target (required to persist)")
    file_path: Optional[str] = Field(None, description="Path to file to analyze")
    db_file_path: Optional[str] = Field(None, description="Path to file in DB (for persistence)")
    content: Optional[str] = Field(None, description="Direct content to analyze")
    model_type: str = Field(default="text", description="Model type: 'text' or 'vision'")
    prompt: Optional[str] = Field(None, description="Custom analysis prompt")
    max_tokens: Optional[int] = Field(None, ge=1, le=8192, description="Max response tokens")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Model temperature")
    files_db_path: Optional[str] = Field(None, description="Path to _files.db for persisting result")


class AnalyzeResponse(BaseModel):
    """Response model for analysis."""
    success: bool
    analysis: Dict[str, Any]
    model_used: str
    tokens_used: int
    processing_time_ms: float


class BatchAnalyzeRequest(BaseModel):
    """Request model for batch analysis."""
    task_id: str = Field(..., description="Task ID to analyze files from")
    file_types: Optional[List[str]] = Field(None, description="Filter by file types")
    file_paths: Optional[List[str]] = Field(None, description="Explicit list of file paths to analyze")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum files to analyze")
    model_type: str = Field(default="text", description="Model type: 'text' or 'vision'")


class BatchAnalyzeResponse(BaseModel):
    """Response model for batch analysis."""
    success: bool
    task_id: str
    job_id: str
    message: str
    total_files: int


class BatchStatusResponse(BaseModel):
    """Response model for batch job status."""
    success: bool
    job_id: str
    status: str
    progress: float
    files_processed: int
    files_total: int
    errors: List[str]
    results: List[Dict[str, Any]] = []


class ModelInfo(BaseModel):
    """Model information."""
    name: str
    type: str
    base_url: str
    max_tokens: int
    temperature: float
    status: str


class ModelsResponse(BaseModel):
    """Response model for models listing."""
    success: bool
    models: List[ModelInfo]


class LLMStatusResponse(BaseModel):
    """Response model for LLM service status."""
    status: str
    text_model: Dict[str, Any]
    vision_model: Dict[str, Any]

class ToggleRelevanceRequest(BaseModel):
    """Request model for toggling file evidence relevance."""
    task_id: str
    file_path: str
    is_relevant: bool


class EventClusterAnalyzeRequest(BaseModel):
    """Request model for event cluster analysis."""
    task_id: str = Field(..., description="Task ID")
    time_window: Optional[int] = Field(None, description="Legacy bucket index (timestamp / bucket_seconds)")
    event_type: Optional[str] = Field(None, description="Legacy event type")
    parent_directory: Optional[str] = Field("", description="Legacy parent directory")
    group_descriptor: Optional[Dict[str, Any]] = Field(
        None, description="Backend-emitted Timeline Group descriptor"
    )
    prompt: Optional[str] = Field(None, description="Custom prompt")
    bucket_seconds: int = Field(60, description="Legacy clustering window in seconds")


class ToggleClusterRelevanceRequest(BaseModel):
    """Request model for toggling event cluster relevance."""
    task_id: str = Field(..., description="Task ID")
    time_window: int = Field(..., description="Time window (timestamp / 60)")
    event_type: str = Field(..., description="Event type")
    is_relevant: bool = Field(..., description="Relevance status")


# Routes

