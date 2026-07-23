"""
Pydantic schemas for API request/response validation.

These schemas define the shape of data exchanged between clients and the server.
They provide automatic validation, serialization, and (via FastAPI) OpenAPI
documentation generation.

Field names, types, and constraints mirror the SQLAlchemy ORM models in
:mod:`server.models.database` so that response schemas can be populated directly
from ORM objects (``from_attributes = True``).

Note on the ``metadata`` reserved name
--------------------------------------
Several ORM models store a database column named ``metadata`` but expose it
under a per-table Python attribute (``image_metadata`` / ``task_metadata`` /
``result_metadata``) because ``metadata`` is reserved by SQLAlchemy. The
Pydantic schemas below use these same attribute names so that response models
read correctly from ORM instances via ``from_attributes``.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, EmailStr, Field


# Base schemas
class BaseSchema(BaseModel):
    """Base schema with common fields shared by all response models."""

    id: uuid.UUID
    created_at: datetime

    class Config:
        # Allow constructing a schema directly from an ORM object's attributes.
        from_attributes = True


# Organization schemas
class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    subscription_tier: str = "free"
    settings: Dict[str, Any] = {}


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationResponse(OrganizationBase, BaseSchema):
    pass


# User schemas
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    role: str = Field(..., pattern="^(super_admin|org_admin|analyst|auditor)$")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    org_id: uuid.UUID


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(UserBase, BaseSchema):
    org_id: uuid.UUID
    last_login: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


# Client schemas
class ClientCapabilities(BaseModel):
    max_concurrent_tasks: int = 2
    supported_formats: List[str] = ["E01", "DD", "Directory"]
    version: str = "1.0.0"


class ClientRegister(BaseModel):
    registration_token: str
    hostname: str = Field(..., min_length=1, max_length=255)
    capabilities: ClientCapabilities


class ClientResponse(BaseSchema):
    org_id: uuid.UUID
    hostname: str
    status: str
    last_poll: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    version: Optional[str] = None
    capabilities: Dict[str, Any]


class ClientCredentialResponse(BaseModel):
    client_id: uuid.UUID
    jwt_token: str
    poll_interval: int = 10
    server_url: str


# Disk Image schemas
class DiskImageCreate(BaseModel):
    path: str = Field(..., max_length=1000)
    size_bytes: int = Field(..., gt=0)
    format: str = Field(..., pattern="^(E01|DD|Directory)$")
    md5_hash: Optional[str] = Field(None, max_length=32)
    # Matches the ORM attribute ``DiskImage.image_metadata`` (DB column
    # ``metadata``).
    image_metadata: Dict[str, Any] = {}


class DiskImageResponse(DiskImageCreate, BaseSchema):
    client_id: uuid.UUID
    indexed_at: datetime


# Command schemas
class CommandPriority(str):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class CommandStatus(str):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class CommandParameters(BaseModel):
    """Base class for command parameters."""

    pass


class AnalyzeDiskParameters(CommandParameters):
    image_path: str
    analysis_type: str = "full"
    output_format: str = "sqlite"
    options: Dict[str, bool] = {"file_carving": True, "llm_text_extraction": True}


class ExtractFileParameters(CommandParameters):
    image_path: str
    file_path: str
    output_to: str = "server"


class HealthCheckParameters(CommandParameters):
    pass


class CommandCreate(BaseModel):
    client_id: uuid.UUID
    command_type: str = Field(..., pattern="^(analyze_disk|extract_file|health_check)$")
    parameters: Dict[str, Any]  # Will be validated based on command_type
    priority: str = "normal"
    ttl_hours: int = Field(24, ge=1, le=168)  # 1 hour to 1 week


class CommandResponse(BaseSchema):
    client_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    command_type: str
    parameters: Dict[str, Any]
    priority: str
    status: str
    ttl: datetime
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_message: Optional[str] = None
    retry_count: int = 0


class CommandPollResponse(BaseModel):
    commands: List[CommandResponse]
    server_time: datetime


# Analysis Task schemas
class AnalysisTaskCreate(BaseModel):
    client_id: uuid.UUID
    disk_image_id: uuid.UUID
    task_name: str = Field(..., min_length=1, max_length=255)
    analysis_type: str = Field(..., pattern="^(full|quick|windows|android|linux)$")
    priority: str = "normal"
    ttl_hours: int = 24


class AnalysisTaskResponse(BaseSchema):
    org_id: uuid.UUID
    client_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    disk_image_id: Optional[uuid.UUID] = None
    task_name: str
    analysis_type: str
    status: str
    progress: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    # Matches the ORM attribute ``AnalysisTask.task_metadata`` (DB column
    # ``metadata``).
    task_metadata: Dict[str, Any]


# Result schemas
class AnalysisResultCreate(BaseModel):
    command_id: uuid.UUID
    task_id: uuid.UUID
    status: str = Field(..., pattern="^(completed|failed)$")
    # Matches the ORM attribute ``AnalysisResult.result_metadata`` (DB column
    # ``metadata``).
    result_metadata: Dict[str, Any] = {}


# A single artifact a client produced (forensic DB, carved file, or metadata).
class ResultArtifact(BaseModel):
    result_type: str = Field(..., pattern="^(database|file|metadata)$")
    file_path: Optional[str] = None
    file_size: Optional[int] = Field(None, ge=0)
    storage_location: Optional[str] = None
    # Matches the ORM attribute ``AnalysisResult.result_metadata`` (DB column
    # ``metadata``).
    result_metadata: Dict[str, Any] = {}


class ResultUploadRequest(BaseModel):
    """A batch of artifacts a client uploads for one analysis task."""
    artifacts: List[ResultArtifact]


class AnalysisResultResponse(BaseSchema):
    task_id: uuid.UUID
    client_id: Optional[uuid.UUID] = None
    result_type: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    storage_location: Optional[str] = None
    # Matches the ORM attribute ``AnalysisResult.result_metadata`` (DB column
    # ``metadata``).
    result_metadata: Dict[str, Any]


class LLMAnalysisResponse(BaseSchema):
    task_id: uuid.UUID
    file_id: Optional[uuid.UUID] = None
    file_path: Optional[str] = None
    input_text_hash: Optional[str] = None
    analysis_result: str
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    cost: Optional[Decimal] = None


class TaskStatusUpdate(BaseModel):
    command_id: uuid.UUID
    status: str
    progress: Optional[int] = Field(None, ge=0, le=100)
    message: Optional[str] = None


# Registration Token schemas
class RegistrationTokenCreate(BaseModel):
    org_id: uuid.UUID
    max_clients: int = Field(10, ge=1, le=1000)
    expires_in_hours: int = Field(720, ge=1, le=8760)  # 1 hour to 1 year


class RegistrationTokenResponse(BaseSchema):
    org_id: uuid.UUID
    token: str
    max_clients: int
    used_count: int
    expires_at: datetime
    created_by: Optional[uuid.UUID] = None


# Error response schema
class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
