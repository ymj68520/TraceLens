"""
SQLAlchemy ORM models for all database tables.

These models mirror the PostgreSQL schema defined in
``migrations/postgresql/001_initial_schema.sql`` (Task 1). Every table, column,
foreign key, CHECK constraint, UNIQUE constraint, and index from that schema is
represented here so the ORM metadata is a faithful reflection of the database.

Notes on faithful schema mapping
--------------------------------
* ``cost`` on ``llm_analysis`` is ``DECIMAL(10,4)`` in the schema and is mapped
  to :class:`~sqlalchemy.Numeric(10, 4)` here (the task brief's ``BigInteger``
  placeholder is replaced to match the schema exactly).
* Several tables carry a database column named ``metadata``. ``metadata`` is a
  reserved attribute on SQLAlchemy declarative classes, so it is exposed under
  a per-table Python attribute (``image_metadata`` / ``task_metadata`` /
  ``result_metadata``) mapped to the real column name ``metadata``. Reading and
  writing goes through the DB column ``metadata`` as the schema requires.
* CHECK / UNIQUE constraints and the six performance indexes are declared
  explicitly so that ``Base.metadata.create_all`` produces a schema equivalent
  to the migration. The migration SQL remains the canonical provisioning path.
"""
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from server.db.session import Base


class Organization(Base):
    """A tenant. All tenant-scoped rows reference an organization via ``org_id``."""

    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    settings = Column(JSONB, default=dict)
    subscription_tier = Column(String(50), default="free")

    users = relationship("User", back_populates="organization")
    clients = relationship("Client", back_populates="organization")
    analysis_tasks = relationship("AnalysisTask", back_populates="organization")


class User(Base):
    """A platform user. Roles: super_admin, org_admin, analyst, auditor."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "username", name="users_org_id_username_key"),
        CheckConstraint(
            "role IN ('super_admin', 'org_admin', 'analyst', 'auditor')",
            name="users_role_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    username = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # super_admin, org_admin, analyst, auditor
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime)

    organization = relationship("Organization", back_populates="users")


class ClientStatus(enum.Enum):
    """Valid values for :attr:`Client.status`."""

    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class Client(Base):
    """A registered forensic machine that polls for commands."""

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("org_id", "hostname", name="clients_org_id_hostname_key"),
        CheckConstraint(
            "status IN ('online', 'offline', 'error')", name="clients_status_check"
        ),
        Index("idx_clients_org_status", "org_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    hostname = Column(String(255), nullable=False)
    registration_token = Column(String(255), unique=True)
    jwt_secret = Column(String(255))
    capabilities = Column(JSONB, default=dict)
    status = Column(String(50), default="offline")
    last_poll = Column(DateTime)
    last_seen = Column(DateTime)
    version = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

    organization = relationship("Organization", back_populates="clients")
    disk_images = relationship(
        "DiskImage", back_populates="client", cascade="all, delete-orphan"
    )
    commands = relationship(
        "CommandQueue", back_populates="client", cascade="all, delete-orphan"
    )


class DiskImage(Base):
    """Catalog entry for a disk image. Raw image bytes never leave the client."""

    __tablename__ = "disk_images"
    __table_args__ = (
        CheckConstraint(
            "format IN ('E01', 'DD', 'Directory')", name="disk_images_format_check"
        ),
        Index("idx_disk_images_client", "client_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE")
    )
    path = Column(String(1000), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    format = Column(String(50), nullable=False)  # E01, DD, Directory
    md5_hash = Column(String(32))
    created_at = Column(DateTime, server_default=func.now())
    indexed_at = Column(DateTime, server_default=func.now())
    # ``metadata`` is reserved in SQLAlchemy; map to the real DB column name.
    image_metadata = Column("metadata", JSONB, default=dict)

    client = relationship("Client", back_populates="disk_images")


class CommandPriority(enum.Enum):
    """Valid values for :attr:`CommandQueue.priority`."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class CommandStatus(enum.Enum):
    """Valid values for :attr:`CommandQueue.status`."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class CommandQueue(Base):
    """Server-to-client command. Clients poll, claim, and report back."""

    __tablename__ = "command_queue"
    __table_args__ = (
        CheckConstraint(
            "command_type IN ('analyze_disk', 'extract_file', 'health_check')",
            name="command_queue_command_type_check",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="command_queue_priority_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'assigned', 'in_progress', 'completed', "
            "'failed', 'expired')",
            name="command_queue_status_check",
        ),
        Index("idx_command_queue_client_status", "client_id", "status", "ttl"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE")
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    # Real FK to analysis_tasks (migration 002). Nullable because some commands
    # (health_check, extract_file) are not spawned by an analysis task. The soft
    # link still lives in ``parameters`` JSONB; the orchestrator is wired to set
    # this column in Task 5.
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    command_type = Column(String(100), nullable=False)  # analyze_disk, extract_file, health_check
    parameters = Column(JSONB, nullable=False)
    priority = Column(String(50), default="normal")
    status = Column(String(50), default="pending")
    ttl = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    assigned_at = Column(DateTime)
    completed_at = Column(DateTime)
    result_message = Column(Text)
    retry_count = Column(Integer, default=0)

    client = relationship("Client", back_populates="commands")
    task = relationship("AnalysisTask", back_populates="commands")


class AnalysisTaskStatus(enum.Enum):
    """Valid values for :attr:`AnalysisTask.status`."""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisTask(Base):
    """A forensic analysis job scoped to an organization."""

    __tablename__ = "analysis_tasks"
    __table_args__ = (
        CheckConstraint(
            "analysis_type IN ('full', 'quick', 'windows', 'android', 'linux')",
            name="analysis_tasks_analysis_type_check",
        ),
        CheckConstraint(
            "status IN ('created', 'queued', 'running', 'completed', 'failed', "
            "'cancelled')",
            name="analysis_tasks_status_check",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="analysis_tasks_progress_check",
        ),
        Index("idx_analysis_tasks_org_status", "org_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    client_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL")
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    disk_image_id = Column(
        UUID(as_uuid=True), ForeignKey("disk_images.id", ondelete="SET NULL")
    )
    task_name = Column(String(255), nullable=False)
    analysis_type = Column(String(100), nullable=False)  # full, quick, windows, android, linux
    status = Column(String(50), default="created")
    progress = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    # ``metadata`` is reserved in SQLAlchemy; map to the real DB column name.
    task_metadata = Column("metadata", JSONB, default=dict)

    organization = relationship("Organization", back_populates="analysis_tasks")
    results = relationship(
        "AnalysisResult", back_populates="task", cascade="all, delete-orphan"
    )
    llm_analyses = relationship(
        "LLMAnalysis", back_populates="task", cascade="all, delete-orphan"
    )
    history = relationship(
        "TaskHistory", back_populates="task", cascade="all, delete-orphan"
    )
    # NOTE: passive_deletes delegates the cascade to the DB-level ON DELETE CASCADE on
    # command_queue.task_id. Without it, SQLAlchemy's unit of work would
    # UPDATE command_queue SET task_id=NULL for loaded children BEFORE the
    # parent DELETE, so the command would survive with a NULL FK and the DB
    # cascade would never fire. ``Client.commands`` already owns delete-orphan
    # for commands, so we cannot use delete-orphan here too; passive_deletes is
    # the idiomatic way to let the FK's ON DELETE CASCADE do the work.
    commands = relationship(
        "CommandQueue", back_populates="task", passive_deletes=True
    )


class AnalysisResult(Base):
    """An artifact produced by an analysis task (database, file, or metadata)."""

    __tablename__ = "analysis_results"
    __table_args__ = (
        CheckConstraint(
            "result_type IN ('database', 'file', 'metadata')",
            name="analysis_results_result_type_check",
        ),
        Index("idx_analysis_results_task", "task_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(
        UUID(as_uuid=True), ForeignKey("analysis_tasks.id", ondelete="CASCADE")
    )
    client_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL")
    )
    result_type = Column(String(100), nullable=False)  # database, file, metadata
    file_path = Column(String(1000))
    file_size = Column(BigInteger)
    storage_location = Column(String(500))
    # ``metadata`` is reserved in SQLAlchemy; map to the real DB column name.
    result_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="results")


class LLMAnalysis(Base):
    """An LLM-produced analysis record for a file/text within a task."""

    __tablename__ = "llm_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(
        UUID(as_uuid=True), ForeignKey("analysis_tasks.id", ondelete="CASCADE")
    )
    file_id = Column(UUID)  # Optional file ID from client
    file_path = Column(String(1000))
    input_text_hash = Column(String(64))
    analysis_result = Column(Text, nullable=False)
    model_used = Column(String(100))
    tokens_used = Column(Integer)
    # Schema defines cost as DECIMAL(10,4); mapped to Numeric to match exactly.
    cost = Column(Numeric(10, 4))
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="llm_analyses")


class TaskHistory(Base):
    """Audit log of actions performed on an analysis task."""

    __tablename__ = "task_history"
    __table_args__ = (Index("idx_task_history_task", "task_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(
        UUID(as_uuid=True), ForeignKey("analysis_tasks.id", ondelete="CASCADE")
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    details = Column(JSONB)
    timestamp = Column(DateTime, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="history")


class RegistrationToken(Base):
    """A token that lets a client register into an organization."""

    __tablename__ = "registration_tokens"
    __table_args__ = (
        CheckConstraint("max_clients > 0", name="registration_tokens_max_clients_check"),
        CheckConstraint(
            "used_count >= 0", name="registration_tokens_used_count_check"
        ),
        CheckConstraint(
            "used_count <= max_clients",
            name="registration_tokens_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    token = Column(String(255), unique=True, nullable=False)
    max_clients = Column(Integer, default=10)
    used_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
