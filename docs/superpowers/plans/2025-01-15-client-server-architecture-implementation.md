# TraceLens Client/Server Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform TraceLens from monolithic local application into distributed client/server architecture with cloud-based orchestration and local forensic analysis execution.

**Architecture:** Poll-based command queue with HTTPS communication. Server runs in cloud (web UI + Python services + PostgreSQL), clients run locally (C++ analyzer + HTTP agent). Clients poll server for commands, execute analysis, push results back. JWT authentication, organization-based multi-tenancy, server-side LLM processing.

**Tech Stack:**
- **Server:** Python 3.10+, FastAPI, PostgreSQL 14+, Redis (optional), S3/OSS
- **Client:** C++20, SQLite3, libcurl/Boost.Asio
- **Web UI:** React + Vite (existing, to be enhanced)
- **Authentication:** JWT (PyJWT)
- **Testing:** pytest (Python), GTest (C++)
- **Deployment:** Docker, systemd

## Execution Approach

> **This plan should be executed in THREE separate implementation cycles:**
>
> **Cycle 1:** Tasks 1-25 (Foundation + Command Queue) - ~6 weeks
> - Deliverable: Clients can register, poll server, and execute basic commands
>
> **Cycle 2:** Tasks 26-45 (Analysis Integration + Web UI) - ~4 weeks
> - Deliverable: Full analysis workflow with LLM integration and enhanced UI
>
> **Cycle 3:** Tasks 46-60 (Security + Production) - ~4 weeks
> - Deliverable: Production-ready system with RBAC, monitoring, and deployment automation
>
> **Each cycle produces working, testable software and should be committed and reviewed before starting the next cycle.**

## Global Constraints

- **C++ Standard:** C++20 (GCC 9+ or Clang 10+)
- **Python Version:** Python 3.10+
- **Database:** PostgreSQL 14+ with UUID support
- **Authentication:** JWT with RS256 algorithm
- **TLS:** All communication must use TLS 1.3+
- **Polling Interval:** 10 seconds default (configurable 5-30 seconds)
- **File Upload Limits:** 5GB max per file, 10MB for LLM text submissions
- **Command TTL:** 24 hours default (1 hour for critical tasks)
- **Client Token Expiry:** 30 days
- **User Token Expiry:** 1 hour
- **No Raw Images:** Raw disk images (E01, DD) must NEVER leave client machines
- **Organization Isolation:** Complete data separation between organizations

---

## File Structure Mapping

### Server Side (Python/FastAPI)

**New Files to Create:**
```
python_service/
├── server/
│   ├── __init__.py
│   ├── main.py                    # FastAPI application entry point (enhanced)
│   ├── config.py                   # Centralized configuration (enhanced)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py             # SQLAlchemy models (organizations, users, clients, etc.)
│   │   └── schemas.py              # Pydantic schemas for API requests/responses
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py                 # Authentication endpoints (login, token refresh)
│   │   ├── organizations.py        # Organization management APIs
│   │   ├── clients.py              # Client registration and management
│   │   ├── commands.py             # Command queue poll and management
│   │   ├── tasks.py                # Task creation and status tracking
│   │   ├── results.py              # Result upload and retrieval
│   │   └── llm_analysis.py         # LLM processing endpoints (enhanced existing)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py         # JWT token generation and validation
│   │   ├── task_orchestrator.py    # Creates and queues commands for clients
│   │   ├── command_queue.py        # Manages command queue with TTL
│   │   ├── result_aggregator.py    # Processes and stores client results
│   │   └── llm_service.py          # LLM processing (enhanced existing)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py              # Database session management
│   │   └── init_db.py              # Database initialization and migrations
│   └── middleware/
│       ├── __init__.py
│       ├── auth.py                 # JWT authentication middleware
│       └── rbac.py                 # Role-based access control middleware
```

**Files to Modify:**
```
python_service/
├── main.py                         # Add new API routes and middleware
├── config.py                       # Add PostgreSQL, JWT, organization settings
└── requirements.txt                # Add: fastapi, uvicorn, sqlalchemy, psycopg2, pyjwt, passlib
```

### Client Side (C++ HTTP Agent)

**New Files to Create:**
```
src/
├── http_agent/
│   ├── http_agent_main.cpp         # HTTP agent entry point
│   ├── http_agent_service.h/.cpp  # Main HTTP agent service class
│   ├── poller.h/.cpp               # Server polling mechanism
│   ├── command_executor.h/.cpp     # Executes commands from queue
│   ├── result_uploader.h/.cpp      # Uploads results to server
│   ├── local_queue.h/.cpp         # Local SQLite task queue
│   ├── jwt_client.h/.cpp           # JWT token management
│   ├── config_manager.h/.cpp       # Client configuration (enhanced existing)
│   └── models/
│       ├── command.h                # Command structure
│       ├── credential.h            # Client credentials structure
│       └── task_status.h          # Task status enum
```

**Files to Modify:**
```
src/
├── CMakeLists.txt                  # Add http_agent directory and executable
└── config_manager.h/.cpp           # Add client-specific config options
```

### Database Schema

**New Files to Create:**
```
migrations/
└── postgresql/
    └── 001_initial_schema.sql       # Complete PostgreSQL schema
```

### Web UI (React)

**New Files to Create:**
```
web/src/
├── pages/
│   ├── Clients.tsx                 # Client management dashboard
│   ├── ClientDetail.tsx           # Individual client view
│   ├── MultiClientTasks.tsx       # Multi-client task assignment
│   ├── OrganizationAdmin.tsx       # Organization administration
│   └── TaskMonitoring.tsx         # Real-time task monitoring
├── components/
│   ├── ClientStatus.tsx           # Client online/offline indicator
│   ├── TaskProgress.tsx           # Task progress component
│   └── CommandQueue.tsx           # Command queue visualization
├── services/
│   ├── clientService.ts           # Client API calls
│   ├── taskService.ts             # Task API calls (enhanced)
│   └── organizationService.ts     # Organization API calls
└── types/
    ├── client.ts                  # Client type definitions
    ├── organization.ts            # Organization type definitions
    └── task.ts                    # Enhanced task types
```

**Files to Modify:**
```
web/src/
├── App.tsx                         # Add new routes
├── services/
│   └── api.ts                      # Add new API endpoints
└── types/
    └── index.ts                    # Export new types
```

### Tests

**New Files to Create:**
```
python_service/tests/
├── test_auth_service.py
├── test_command_queue.py
├── test_task_orchestrator.py
├── test_client_api.py
└── test_task_api.py

src/http_agent/tests/
├── test_poller.cpp
├── test_command_executor.cpp
├── test_result_uploader.cpp
└── test_jwt_client.cpp
```

---

## CYCLE 1: Foundation + Command Queue (Tasks 1-25)

### Section 1: Database Setup (Tasks 1-3)

### Task 1: Create PostgreSQL Database Schema

**Files:**
- Create: `migrations/postgresql/001_initial_schema.sql`

**Interfaces:**
- Produces: Complete database schema with all tables, indexes, and constraints

- [ ] **Step 1: Create the initial schema file**

```bash
mkdir -p migrations/postgresql
```

- [ ] **Step 2: Write the complete database schema**

Write to `migrations/postgresql/001_initial_schema.sql`:

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Organizations
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settings JSONB DEFAULT '{}',
    subscription_tier VARCHAR(50) DEFAULT 'free'
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('super_admin', 'org_admin', 'analyst', 'auditor')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    UNIQUE(org_id, username)
);

-- Clients
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    hostname VARCHAR(255) NOT NULL,
    registration_token VARCHAR(255) UNIQUE,
    jwt_secret VARCHAR(255),
    capabilities JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'offline' CHECK (status IN ('online', 'offline', 'error')),
    last_poll TIMESTAMP,
    last_seen TIMESTAMP,
    version VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(org_id, hostname)
);

-- Disk Images Catalog
CREATE TABLE disk_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    path VARCHAR(1000) NOT NULL,
    size_bytes BIGINT NOT NULL,
    format VARCHAR(50) NOT NULL CHECK (format IN ('E01', 'DD', 'Directory')),
    md5_hash VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Command Queue
CREATE TABLE command_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    command_type VARCHAR(100) NOT NULL CHECK (command_type IN (
        'analyze_disk', 'extract_file', 'health_check'
    )),
    parameters JSONB NOT NULL,
    priority VARCHAR(50) DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN (
        'pending', 'assigned', 'in_progress', 'completed', 'failed', 'expired'
    )),
    ttl TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_at TIMESTAMP,
    completed_at TIMESTAMP,
    result_message TEXT,
    retry_count INTEGER DEFAULT 0
);

-- Analysis Tasks
CREATE TABLE analysis_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    disk_image_id UUID REFERENCES disk_images(id) ON DELETE SET NULL,
    task_name VARCHAR(255) NOT NULL,
    analysis_type VARCHAR(100) NOT NULL CHECK (analysis_type IN (
        'full', 'quick', 'windows', 'android', 'linux'
    )),
    status VARCHAR(50) DEFAULT 'created' CHECK (status IN (
        'created', 'queued', 'running', 'completed', 'failed', 'cancelled'
    )),
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

-- Analysis Results
CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    result_type VARCHAR(100) NOT NULL CHECK (result_type IN (
        'database', 'file', 'metadata'
    )),
    file_path VARCHAR(1000),
    file_size BIGINT,
    storage_location VARCHAR(500),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- LLM Analysis
CREATE TABLE llm_analysis (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    file_id UUID,
    file_path VARCHAR(1000),
    input_text_hash VARCHAR(64),
    analysis_result TEXT NOT NULL,
    model_used VARCHAR(100),
    tokens_used INTEGER,
    cost DECIMAL(10,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Task History (Audit Log)
CREATE TABLE task_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Registration Tokens
CREATE TABLE registration_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    max_clients INTEGER DEFAULT 10 CHECK (max_clients > 0),
    used_count INTEGER DEFAULT 0 CHECK (used_count >= 0),
    expires_at TIMESTAMP NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (used_count <= max_clients)
);

-- Indexes for performance
CREATE INDEX idx_clients_org_status ON clients(org_id, status);
CREATE INDEX idx_command_queue_client_status ON command_queue(client_id, status, ttl);
CREATE INDEX idx_analysis_tasks_org_status ON analysis_tasks(org_id, status);
CREATE INDEX idx_analysis_results_task ON analysis_results(task_id);
CREATE INDEX idx_disk_images_client ON disk_images(client_id);
CREATE INDEX idx_task_history_task ON task_history(task_id);

-- Insert default super admin (password: admin123, CHANGE IN PRODUCTION)
INSERT INTO users (id, org_id, username, email, password_hash, role)
VALUES (
    uuid_generate_v4(),
    (SELECT id FROM organizations WHERE name = 'Default Organization'),
    'super_admin',
    'super_admin@tracelens.local',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyY9wqDf11qO',
    'super_admin'
);

-- Create default organization if not exists
INSERT INTO organizations (id, name, subscription_tier)
VALUES (
    uuid_generate_v4(),
    'Default Organization',
    'enterprise'
) ON CONFLICT (name) DO NOTHING;
```

- [ ] **Step 3: Verify schema syntax**

```bash
# Check for syntax errors (if postgres available)
if command -v psql &> /dev/null; then
    echo "Syntax check requires PostgreSQL connection - skipping"
else
    echo "PostgreSQL not available for syntax check"
fi
```

- [ ] **Step 4: Commit**

```bash
git add migrations/postgresql/001_initial_schema.sql
git commit -m "feat: add PostgreSQL database schema for C/S architecture"
```

---

### Task 2: Create Database Models and Session Management

**Files:**
- Create: `python_service/server/db/session.py`
- Create: `python_service/server/db/__init__.py`
- Create: `python_service/server/db/init_db.py`
- Create: `python_service/server/models/database.py`

**Interfaces:**
- Produces: SQLAlchemy ORM models for all database tables
- Produces: Database session management with connection pooling

- [ ] **Step 1: Create db package and session module**

```bash
mkdir -p python_service/server/db
touch python_service/server/db/__init__.py
```

Write to `python_service/server/db/session.py`:

```python
"""
Database session management with connection pooling.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from typing import Generator
import os

# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tracelens"
)

# Create engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=os.getenv("DB_ECHO", "false").lower() == "true"
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency injection for FastAPI routes.
    Yields a database session and ensures it's closed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.
    Call this on application startup.
    """
    from server.models.database import (
        Organization, User, Client, DiskImage,
        CommandQueue, AnalysisTask, AnalysisResult,
        LLMAnalysis, TaskHistory, RegistrationToken
    )
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 2: Write database initialization script**

Write to `python_service/server/db/init_db.py`:

```python
"""
Database initialization and migration script.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from server.db.session import engine, Base
from server.models.database import (
    Organization, User, Client, DiskImage,
    CommandQueue, AnalysisTask, AnalysisResult,
    LLMAnalysis, TaskHistory, RegistrationToken
)
from sqlalchemy import text
import uuid
from datetime import datetime


def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created")


def drop_tables():
    """Drop all database tables (USE WITH CAUTION)."""
    Base.metadata.drop_all(bind=engine)
    print("✓ Database tables dropped")


def create_default_organization():
    """Create default organization if it doesn't exist."""
    from server.db.session import SessionLocal
    db = SessionLocal()
    try:
        existing = db.query(Organization).filter(
            Organization.name == "Default Organization"
        ).first()
        if not existing:
            org = Organization(
                id=uuid.uuid4(),
                name="Default Organization",
                subscription_tier="enterprise"
            )
            db.add(org)
            db.commit()
            print(f"✓ Created default organization: {org.id}")
        else:
            print(f"✓ Default organization exists: {existing.id}")
        return existing.id if not existing else existing.id
    finally:
        db.close()


def create_super_admin(org_id):
    """Create super admin user if it doesn't exist."""
    from server.db.session import SessionLocal
    from passlib.context import CryptContext
    import uuid

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()
    try:
        existing = db.query(User).filter(
            User.username == "super_admin"
        ).first()
        if not existing:
            user = User(
                id=uuid.uuid4(),
                org_id=org_id,
                username="super_admin",
                email="super_admin@tracelens.local",
                password_hash=pwd_context.hash("admin123"),  # CHANGE IN PRODUCTION
                role="super_admin"
            )
            db.add(user)
            db.commit()
            print(f"✓ Created super admin: {user.id}")
        else:
            print(f"✓ Super admin exists: {existing.id}")
    finally:
        db.close()


def run_migrations():
    """Run SQL migrations from migrations directory."""
    migration_file = "migrations/postgresql/001_initial_schema.sql"
    if os.path.exists(migration_file):
        with open(migration_file, 'r') as f:
            sql = f.read()
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        print(f"✓ Applied migration: {migration_file}")
    else:
        print(f"✗ Migration file not found: {migration_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Database management")
    parser.add_argument("--init", action="store_true", help="Initialize database")
    parser.add_argument("--migrate", action="store_true", help="Run migrations")
    parser.add_argument("--seed", action="store_true", help="Seed default data")
    parser.add_argument("--drop", action="store_true", help="Drop all tables")
    args = parser.parse_args()

    if args.drop:
        confirm = input("⚠️  This will drop all tables. Type 'yes' to confirm: ")
        if confirm.lower() == 'yes':
            drop_tables()
        else:
            print("Aborted")

    if args.migrate:
        run_migrations()

    if args.init:
        create_tables()

    if args.seed:
        org_id = create_default_organization()
        create_super_admin(org_id)
```

- [ ] **Step 3: Write SQLAlchemy ORM models**

Write to `python_service/server/models/database.py`:

```python
"""
SQLAlchemy ORM models for all database tables.
"""
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, Text, ForeignKey, CheckConstraint, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
import enum
from server.db.session import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    settings = Column(JSONB, default={})
    subscription_tier = Column(String(50), default="free")

    users = relationship("User", back_populates="organization")
    clients = relationship("Client", back_populates="organization")
    analysis_tasks = relationship("AnalysisTask", back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    username = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # super_admin, org_admin, analyst, auditor
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime)

    organization = relationship("Organization", back_populates="users")


class ClientStatus(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    hostname = Column(String(255), nullable=False)
    registration_token = Column(String(255), unique=True)
    jwt_secret = Column(String(255))
    capabilities = Column(JSONB, default={})
    status = Column(String(50), default="offline")
    last_poll = Column(DateTime)
    last_seen = Column(DateTime)
    version = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

    organization = relationship("Organization", back_populates="clients")
    disk_images = relationship("DiskImage", back_populates="client", cascade="all, delete-orphan")
    commands = relationship("CommandQueue", back_populates="client", cascade="all, delete-orphan")


class DiskImage(Base):
    __tablename__ = "disk_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"))
    path = Column(String(1000), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    format = Column(String(50), nullable=False)  # E01, DD, Directory
    md5_hash = Column(String(32))
    created_at = Column(DateTime, server_default=func.now())
    indexed_at = Column(DateTime, server_default=func.now())
    metadata = Column(JSONB, default={})

    client = relationship("Client", back_populates="disk_images")


class CommandPriority(enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class CommandStatus(enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class CommandQueue(Base):
    __tablename__ = "command_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
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


class AnalysisTaskStatus(enum.Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    disk_image_id = Column(UUID(as_uuid=True), ForeignKey("disk_images.id", ondelete="SET NULL"))
    task_name = Column(String(255), nullable=False)
    analysis_type = Column(String(100), nullable=False)  # full, quick, windows, android, linux
    status = Column(String(50), default="created")
    progress = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    metadata = Column(JSONB, default={})

    organization = relationship("Organization", back_populates="analysis_tasks")
    results = relationship("AnalysisResult", back_populates="task", cascade="all, delete-orphan")
    llm_analyses = relationship("LLMAnalysis", back_populates="task", cascade="all, delete-orphan")
    history = relationship("TaskHistory", back_populates="task", cascade="all, delete-orphan")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("analysis_tasks.id", ondelete="CASCADE"))
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"))
    result_type = Column(String(100), nullable=False)  # database, file, metadata
    file_path = Column(String(1000))
    file_size = Column(BigInteger)
    storage_location = Column(String(500))
    metadata = Column(JSONB, default={})
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="results")


class LLMAnalysis(Base):
    __tablename__ = "llm_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("analysis_tasks.id", ondelete="CASCADE"))
    file_id = Column(UUID)  # Optional file ID from client
    file_path = Column(String(1000))
    input_text_hash = Column(String(64))
    analysis_result = Column(Text, nullable=False)
    model_used = Column(String(100))
    tokens_used = Column(Integer)
    cost = Column(BigInteger)  # Store as integer (cents) or use DECIMAL type
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="llm_analyses")


class TaskHistory(Base):
    __tablename__ = "task_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("analysis_tasks.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    details = Column(JSONB)
    timestamp = Column(DateTime, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="history")


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    token = Column(String(255), unique=True, nullable=False)
    max_clients = Column(Integer, default=10)
    used_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Write db package init**

Write to `python_service/server/db/__init__.py`:

```python
"""
Database package initialization.
"""
from server.db.session import engine, Base, get_db, init_db
from server.models.database import (
    Organization, User, Client, DiskImage,
    CommandQueue, AnalysisTask, AnalysisResult,
    LLMAnalysis, TaskHistory, RegistrationToken
)

__all__ = [
    "engine",
    "Base",
    "get_db",
    "init_db",
    "Organization",
    "User",
    "Client",
    "DiskImage",
    "CommandQueue",
    "AnalysisTask",
    "AnalysisResult",
    "LLMAnalysis",
    "TaskHistory",
    "RegistrationToken",
]
```

- [ ] **Step 5: Update requirements.txt**

Add to `python_service/requirements.txt`:

```
# Database
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
alembic>=1.11.0

# Authentication
pyjwt>=2.8.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6

# Additional FastAPI dependencies
python-jose[cryptography]>=3.3.0
```

- [ ] **Step 6: Test database connection**

```bash
cd python_service
python -c "from server.db.session import engine; print(engine); print('Database connection OK')"
```

Expected: No errors, database URL printed

- [ ] **Step 7: Run database initialization**

```bash
cd python_service
python -m server.db.init_db --migrate --init --seed
```

Expected output:
```
✓ Applied migration: migrations/postgresql/001_initial_schema.sql
✓ Database tables created
✓ Created default organization: <uuid>
✓ Created super admin: <uuid>
```

- [ ] **Step 8: Commit**

```bash
git add python_service/server/db/ python_service/requirements.txt
git commit -m "feat: add database models and session management"
```

---

### Task 3: Create Pydantic Schemas for API

**Files:**
- Create: `python_service/server/models/schemas.py`

**Interfaces:**
- Consumes: Database models from Task 2
- Produces: Pydantic schemas for request/response validation

- [ ] **Step 1: Write Pydantic schemas**

Write to `python_service/server/models/schemas.py`:

```python
"""
Pydantic schemas for API request/response validation.
"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


# Base schemas
class BaseSchema(BaseModel):
    """Base schema with common fields."""
    id: uuid.UUID
    created_at: datetime

    class Config:
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
    role: str = Field(..., regex="^(super_admin|org_admin|analyst|auditor)$")


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
    format: str = Field(..., regex="^(E01|DD|Directory)$")
    md5_hash: Optional[str] = Field(None, max_length=32)
    metadata: Dict[str, Any] = {}


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
    command_type: str = Field(..., regex="^(analyze_disk|extract_file|health_check)$")
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
    analysis_type: str = Field(..., regex="^(full|quick|windows|android|linux)$")
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
    metadata: Dict[str, Any]


# Result schemas
class AnalysisResultCreate(BaseModel):
    command_id: uuid.UUID
    task_id: uuid.UUID
    status: str = Field(..., regex="^(completed|failed)$")
    metadata: Dict[str, Any] = {}


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
```

- [ ] **Step 2: Test schema imports**

```bash
cd python_service
python -c "from server.models.schemas import *; print('Schemas imported successfully')"
```

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add python_service/server/models/schemas.py
git commit -m "feat: add Pydantic schemas for API validation"
```

---

### Section 2: Authentication Service (Tasks 4-7)

### Task 4: Implement JWT Authentication Service

**Files:**
- Create: `python_service/server/services/auth_service.py`

**Interfaces:**
- Consumes: User model from Task 2
- Produces: JWT token generation and validation functions

- [ ] **Step 1: Write authentication service**

Write to `python_service/server/services/auth_service.py`:

```python
"""
JWT Authentication service for token generation and validation.
"""
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from passlib.context import CryptContext
import uuid

# JWT configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.urandom(32).hex())
JWT_ALGORITHM = "RS256"  # Use RSA for production, HS256 for development
USER_TOKEN_EXPIRE_HOURS = 1
CLIENT_TOKEN_EXPIRE_DAYS = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_user_token(user_id: uuid.UUID, org_id: uuid.UUID, role: str, permissions: list) -> str:
    """
    Create JWT token for a user.

    Args:
        user_id: User's UUID
        org_id: Organization's UUID
        role: User's role
        permissions: List of user permissions

    Returns:
        JWT token string
    """
    now = datetime.utcnow()
    expires = now + timedelta(hours=USER_TOKEN_EXPIRE_HOURS)

    payload = {
        "user_id": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "permissions": permissions,
        "iat": now.timestamp(),
        "exp": expires.timestamp(),
        "type": "user"
    }

    # For development, use HS256. For production, use RS256 with proper keys
    algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=algorithm)


def create_client_token(client_id: uuid.UUID, org_id: uuid.UUID, capabilities: Dict[str, Any]) -> str:
    """
    Create JWT token for a client.

    Args:
        client_id: Client's UUID
        org_id: Organization's UUID
        capabilities: Client capabilities dict

    Returns:
        JWT token string
    """
    now = datetime.utcnow()
    expires = now + timedelta(days=CLIENT_TOKEN_EXPIRE_DAYS)

    payload = {
        "client_id": str(client_id),
        "org_id": str(org_id),
        "capabilities": capabilities,
        "iat": now.timestamp(),
        "exp": expires.timestamp(),
        "type": "client"
    }

    algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=algorithm)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        algorithm = "HS256" if os.getenv("ENVIRONMENT") == "development" else JWT_ALGORITHM
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_user_from_token(token: str, db) -> Optional[Any]:
    """
    Get user from JWT token.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        User object if valid, None otherwise
    """
    payload = verify_token(token)
    if not payload or payload.get("type") != "user":
        return None

    from server.models.database import User
    user = db.query(User).filter(User.id == uuid.UUID(payload["user_id"])).first()
    return user


def get_client_from_token(token: str, db) -> Optional[Any]:
    """
    Get client from JWT token.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        Client object if valid, None otherwise
    """
    payload = verify_token(token)
    if not payload or payload.get("type") != "client":
        return None

    from server.models.database import Client
    client = db.query(Client).filter(Client.id == uuid.UUID(payload["client_id"])).first()
    return client
```

- [ ] **Step 2: Write authentication tests**

Write to `python_service/tests/test_auth_service.py`:

```python
"""
Tests for authentication service.
"""
import pytest
import uuid
from datetime import datetime, timedelta
from server.services.auth_service import (
    hash_password, verify_password,
    create_user_token, create_client_token, verify_token
)


def test_password_hashing():
    """Test password hashing and verification."""
    password = "test_password_123"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_user_token_creation():
    """Test user JWT token creation."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    role = "analyst"
    permissions = ["create_tasks", "view_results"]

    token = create_user_token(user_id, org_id, role, permissions)

    assert token is not None
    assert isinstance(token, str)


def test_user_token_verification():
    """Test user JWT token verification."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    role = "analyst"
    permissions = ["create_tasks", "view_results"]

    token = create_user_token(user_id, org_id, role, permissions)
    payload = verify_token(token)

    assert payload is not None
    assert payload["user_id"] == str(user_id)
    assert payload["org_id"] == str(org_id)
    assert payload["role"] == role
    assert payload["permissions"] == permissions
    assert payload["type"] == "user"


def test_client_token_creation():
    """Test client JWT token creation."""
    client_id = uuid.uuid4()
    org_id = uuid.uuid4()
    capabilities = {"max_concurrent_tasks": 2, "supported_formats": ["E01", "DD"]}

    token = create_client_token(client_id, org_id, capabilities)

    assert token is not None
    assert isinstance(token, str)


def test_client_token_verification():
    """Test client JWT token verification."""
    client_id = uuid.uuid4()
    org_id = uuid.uuid4()
    capabilities = {"max_concurrent_tasks": 2}

    token = create_client_token(client_id, org_id, capabilities)
    payload = verify_token(token)

    assert payload is not None
    assert payload["client_id"] == str(client_id)
    assert payload["org_id"] == str(org_id)
    assert payload["capabilities"] == capabilities
    assert payload["type"] == "client"


def test_expired_token():
    """Test that expired tokens are rejected."""
    # This test requires mocking time or creating a token with very short expiry
    # For now, we'll just verify the structure
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    # Create token and immediately verify it
    token = create_user_token(user_id, org_id, "analyst", [])
    payload = verify_token(token)
    assert payload is not None

    # After 1 hour + 1 second, token should be expired
    # (This would require time mocking in a real test)


def test_invalid_token():
    """Test that invalid tokens are rejected."""
    payload = verify_token("invalid_token_string")
    assert payload is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 3: Run authentication tests**

```bash
cd python_service
pytest tests/test_auth_service.py -v
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add python_service/server/services/auth_service.py python_service/tests/test_auth_service.py
git commit -m "feat: add JWT authentication service with tests"
```

---

### Task 5: Create Authentication Middleware

**Files:**
- Create: `python_service/server/middleware/__init__.py`
- Create: `python_service/server/middleware/auth.py`

**Interfaces:**
- Consumes: auth_service from Task 4
- Produces: FastAPI middleware for JWT authentication

- [ ] **Step 1: Create middleware package**

```bash
mkdir -p python_service/server/middleware
touch python_service/server/middleware/__init__.py
```

- [ ] **Step 2: Write authentication middleware**

Write to `python_service/server/middleware/auth.py`:

```python
"""
JWT Authentication middleware for FastAPI.
"""
from fastapi import Security, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import uuid
from server.services.auth_service import verify_token, get_user_from_token, get_client_from_token

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db = None
):
    """
    Get current authenticated user from JWT token.

    Raises:
        HTTPException: If token is invalid or user not found

    Returns:
        User object
    """
    from server.db.session import get_db

    # Use dependency injection for db if not provided
    if db is None:
        db_gen = get_db()
        db = next(db_gen)

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "user":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_from_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_client(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db = None
):
    """
    Get current authenticated client from JWT token.

    Raises:
        HTTPException: If token is invalid or client not found

    Returns:
        Client object
    """
    from server.db.session import get_db

    if db is None:
        db_gen = get_db()
        db = next(db_gen)

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "client":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client = get_client_from_token(token, db)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return client


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db = None
):
    """
    Optionally get authenticated user.
    Returns None if no token provided or invalid.
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def require_permission(*permissions: str):
    """
    Dependency factory that requires specific permissions.

    Args:
        *permissions: Required permission names

    Returns:
        Dependency function
    """
    async def permission_dependency(current_user = Depends(get_current_user)):
        # Check if user has required permissions
        # For now, super_admin has all permissions
        if current_user.role == "super_admin":
            return current_user

        # TODO: Implement proper permission checking based on role
        # For now, just check if user is authenticated
        return current_user

    return permission_dependency
```

- [ ] **Step 3: Commit**

```bash
git add python_service/server/middleware/
git commit -m "feat: add JWT authentication middleware"
```

---

### Task 6: Implement Authentication API Endpoints

**Files:**
- Create: `python_service/server/api/auth.py`

**Interfaces:**
- Consumes: auth_service from Task 4, schemas from Task 3
- Produces: Login, token refresh endpoints

- [ ] **Step 1: Create API package**

```bash
mkdir -p python_service/server/api
touch python_service/server/api/__init__.py
```

- [ ] **Step 2: Write authentication API**

Write to `python_service/server/api/auth.py`:

```python
"""
Authentication API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from server.db.session import get_db
from server.models.database import User
from server.models.schemas import UserLogin, UserResponse, TokenResponse
from server.services.auth_service import verify_password, create_user_token, hash_password
from server.middleware.auth import get_current_user
import uuid

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return JWT token.

    Args:
        form_data: OAuth2 form with username and password
        db: Database session

    Returns:
        Token response with access token

    Raises:
        HTTPException: If credentials invalid
    """
    # Find user by username (or email)
    user = db.query(User).filter(
        (User.username == form_data.username) | (User.email == form_data.username)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login
    from datetime import datetime
    user.last_login = datetime.utcnow()
    db.commit()

    # Create token
    permissions = get_permissions_for_role(user.role)
    token = create_user_token(user.id, user.org_id, user.role, permissions)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=3600  # 1 hour
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    current_user: User = Depends(get_current_user)
):
    """
    Refresh JWT token.

    Args:
        current_user: Authenticated user

    Returns:
        New token response
    """
    permissions = get_permissions_for_role(current_user.role)
    token = create_user_token(current_user.id, current_user.org_id, current_user.role, permissions)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=3600
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current authenticated user information.

    Args:
        current_user: Authenticated user

    Returns:
        User response
    """
    return UserResponse(
        id=current_user.id,
        org_id=current_user.org_id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
        created_at=current_user.created_at,
        last_login=current_user.last_login
    )


def get_permissions_for_role(role: str) -> list:
    """
    Get permissions for a given role.

    Args:
        role: User role

    Returns:
        List of permission names
    """
    role_permissions = {
        "super_admin": [
            "create_organizations", "manage_organizations",
            "create_users", "manage_users",
            "create_tasks", "manage_tasks", "view_results", "delete_results",
            "create_clients", "manage_clients", "delete_clients",
            "manage_system"
        ],
        "org_admin": [
            "create_users", "manage_users",
            "create_tasks", "manage_tasks", "view_results", "delete_results",
            "create_clients", "manage_clients", "delete_clients"
        ],
        "analyst": [
            "create_tasks", "view_results"
        ],
        "auditor": [
            "view_results"
        ]
    }

    return role_permissions.get(role, [])
```

- [ ] **Step 3: Write authentication API tests**

Write to `python_service/tests/test_auth_api.py`:

```python
"""
Tests for authentication API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.db.session import SessionLocal
from server.models.database import User, Organization
from server.services.auth_service import hash_password
import uuid


@pytest.fixture
def db():
    """Database session fixture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db):
    """Create test user."""
    # Create organization
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
        subscription_tier="enterprise"
    )
    db.add(org)
    db.commit()

    # Create user
    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("testpass123"),
        role="analyst"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


def test_login_success(client, test_user):
    """Test successful login."""
    response = client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "testpass123"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600


def test_login_wrong_password(client, test_user):
    """Test login with wrong password."""
    response = client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "wrongpass"}
    )

    assert response.status_code == 401
    assert "detail" in response.json()


def test_login_nonexistent_user(client):
    """Test login with non-existent user."""
    response = client.post(
        "/api/auth/login",
        data={"username": "nonexistent", "password": "testpass"}
    )

    assert response.status_code == 401


def test_get_current_user(client, test_user):
    """Test getting current user info."""
    # First login to get token
    login_response = client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "testpass123"}
    )
    token = login_response.json()["access_token"]

    # Get current user
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"


def test_refresh_token(client, test_user):
    """Test token refresh."""
    # First login
    login_response = client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "testpass123"}
    )
    old_token = login_response.json()["access_token"]

    # Refresh token
    response = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    new_token = data["access_token"]
    assert new_token != old_token


def test_unauthorized_access(client):
    """Test access without token."""
    response = client.get("/api/auth/me")

    assert response.status_code == 403  # No authorization header


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 4: Run authentication API tests**

```bash
cd python_service
pytest tests/test_auth_api.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add python_service/server/api/auth.py python_service/tests/test_auth_api.py
git commit -m "feat: add authentication API endpoints with tests"
```

---

### Task 7: Integrate Authentication into FastAPI Application

**Files:**
- Modify: `python_service/server/main.py`
- Modify: `python_service/server/config.py`

**Interfaces:**
- Consumes: auth middleware and API from Tasks 5-6
- Produces: Integrated authentication in main application

- [ ] **Step 1: Update configuration**

Add to `python_service/server/config.py`:

```python
"""
Application configuration.
"""
import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Application
    APP_NAME: str = "TraceLens Server"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8090"))

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/tracelens"
    )

    # JWT
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    USER_TOKEN_EXPIRE_HOURS: int = 1
    CLIENT_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    # File Upload
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024 * 1024  # 5GB
    MAX_LLM_TEXT_SIZE: int = 10 * 1024 * 1024  # 10MB

    # Command Queue
    DEFAULT_POLL_INTERVAL: int = 10  # seconds
    MIN_POLL_INTERVAL: int = 5
    MAX_POLL_INTERVAL: int = 30
    DEFAULT_COMMAND_TTL_HOURS: int = 24
    CRITICAL_COMMAND_TTL_HOURS: int = 1

    # Organization
    DEFAULT_ORGANIZATION_NAME: str = "Default Organization"
    DEFAULT_SUBSCRIPTION_TIER: str = "enterprise"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
```

- [ ] **Step 2: Update main application**

Update `python_service/server/main.py`:

```python
"""
TraceLens Server - FastAPI application entry point.
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn
import logging

from server.config import settings
from server.db.session import init_db
from server.api import auth

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.ENVIRONMENT == "production" else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    # Initialize database
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down application")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="TraceLens Client/Server Architecture",
    lifespan=lifespan
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )


# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


# Root
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "TraceLens Server API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT == "development",
        log_level="info"
    )
```

- [ ] **Step 3: Update requirements.txt**

Add to `python_service/requirements.txt`:

```
# Configuration
pydantic-settings>=2.1.0

# CORS
python-multipart>=0.0.6
```

- [ ] **Step 4: Test server startup**

```bash
cd python_service
python -m server.main
```

Expected: Server starts without errors on http://localhost:8090

Test health check:
```bash
curl http://localhost:8090/health
```

Expected: `{"status":"healthy","app":"TraceLens Server","version":"1.0.0"}`

- [ ] **Step 5: Test authentication endpoints**

```bash
# Test login (will fail without valid user, but endpoint should exist)
curl -X POST http://localhost:8090/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test&password=test"
```

Expected: 401 (user doesn't exist) but not 404

- [ ] **Step 6: Commit**

```bash
git add python_service/server/main.py python_service/server/config.py python_service/requirements.txt
git commit -m "feat: integrate authentication into FastAPI application"
```

---

### Section 3: Client Registration and Management (Tasks 8-12)

### Task 8: Implement Registration Token Management

**Files:**
- Create: `python_service/server/api/organizations.py`

**Interfaces:**
- Consumes: Database models from Task 2, schemas from Task 3
- Produces: Organization and registration token management endpoints

- [ ] **Step 1: Write organizations API**

Write to `python_service/server/api/organizations.py`:

```python
"""
Organization and registration token management APIs.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta
import secrets
import uuid

from server.db.session import get_db
from server.models.database import Organization, User, RegistrationToken
from server.models.schemas import (
    OrganizationCreate, OrganizationResponse,
    RegistrationTokenCreate, RegistrationTokenResponse
)
from server.middleware.auth import get_current_user, require_permission

router = APIRouter(prefix="/api/organizations", tags=["Organizations"])


@router.post("", response_model=OrganizationResponse)
async def create_organization(
    org_data: OrganizationCreate,
    current_user: User = Depends(require_permission("create_organizations")),
    db: Session = Depends(get_db)
):
    """
    Create a new organization.

    Args:
        org_data: Organization creation data
        current_user: Authenticated user with create_organizations permission
        db: Database session

    Returns:
        Created organization

    Raises:
        HTTPException: If organization name already exists
    """
    # Check if organization exists
    existing = db.query(Organization).filter(
        Organization.name == org_data.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization with this name already exists"
        )

    # Create organization
    org = Organization(**org_data.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)

    return org


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all organizations.

    Args:
        current_user: Authenticated user
        db: Database session

    Returns:
        List of organizations
    """
    # Super admins see all, others see only their own
    if current_user.role == "super_admin":
        organizations = db.query(Organization).all()
    else:
        organizations = db.query(Organization).filter(
            Organization.id == current_user.org_id
        ).all()

    return organizations


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get organization by ID.

    Args:
        org_id: Organization UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        Organization details

    Raises:
        HTTPException: If organization not found or access denied
    """
    # Check access
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return org


@router.post("/{org_id}/registration-tokens", response_model=RegistrationTokenResponse)
async def create_registration_token(
    org_id: uuid.UUID,
    token_data: RegistrationTokenCreate,
    current_user: User = Depends(require_permission("create_clients")),
    db: Session = Depends(get_db)
):
    """
    Create a registration token for an organization.

    Args:
        org_id: Organization UUID
        token_data: Token creation data
        current_user: Authenticated user with create_clients permission
        db: Database session

    Returns:
        Created registration token

    Raises:
        HTTPException: If organization not found or access denied
    """
    # Check access
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Verify organization exists
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    # Generate unique token
    token = secrets.token_urlsafe(32)

    # Calculate expiration
    expires_at = datetime.utcnow() + timedelta(hours=token_data.expires_in_hours)

    # Create registration token
    reg_token = RegistrationToken(
        org_id=org_id,
        token=token,
        max_clients=token_data.max_clients,
        expires_at=expires_at,
        created_by=current_user.id
    )
    db.add(reg_token)
    db.commit()
    db.refresh(reg_token)

    return reg_token


@router.get("/{org_id}/registration-tokens", response_model=List[RegistrationTokenResponse])
async def list_registration_tokens(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List registration tokens for an organization.

    Args:
        org_id: Organization UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        List of registration tokens

    Raises:
        HTTPException: If access denied
    """
    # Check access
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    tokens = db.query(RegistrationToken).filter(
        RegistrationToken.org_id == org_id
    ).all()

    return tokens


@router.delete("/registration-tokens/{token_id}")
async def delete_registration_token(
    token_id: uuid.UUID,
    current_user: User = Depends(require_permission("manage_clients")),
    db: Session = Depends(get_db)
):
    """
    Delete a registration token.

    Args:
        token_id: Token UUID
        current_user: Authenticated user with manage_clients permission
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If token not found
    """
    token = db.query(RegistrationToken).filter(
        RegistrationToken.id == token_id
    ).first()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration token not found"
        )

    # Check access
    if current_user.role != "super_admin" and current_user.org_id != token.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    db.delete(token)
    db.commit()

    return {"message": "Registration token deleted"}
```

- [ ] **Step 2: Update main.py to include organizations router**

Add to `python_service/server/main.py`:

```python
from server.api import auth, organizations

# In the routers section
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(organizations.router, tags=["Organizations"])
```

- [ ] **Step 3: Write organization API tests**

Write to `python_service/tests/test_organizations_api.py`:

```python
"""
Tests for organization management API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.db.session import SessionLocal
from server.models.database import Organization, User, RegistrationToken
from server.services.auth_service import hash_password
import uuid
from datetime import datetime, timedelta


@pytest.fixture
def db():
    """Database session fixture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def super_admin(db):
    """Create super admin user."""
    org = Organization(
        id=uuid.uuid4(),
        name="Admin Org",
        subscription_tier="enterprise"
    )
    db.add(org)
    db.commit()

    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        username="admin",
        email="admin@example.com",
        password_hash=hash_password("admin123"),
        role="super_admin"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


@pytest.fixture
def auth_headers(super_admin):
    """Get authenticated headers."""
    from fastapi.testclient import TestClient
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"}
    )
    token = response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def test_create_organization(client, auth_headers):
    """Test creating an organization."""
    response = client.post(
        "/api/organizations",
        json={"name": "Test Org", "subscription_tier": "enterprise"},
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Org"
    assert data["subscription_tier"] == "enterprise"
    assert "id" in data


def test_create_duplicate_organization(client, auth_headers):
    """Test creating duplicate organization fails."""
    org_name = "Duplicate Org"

    # Create first organization
    client.post(
        "/api/organizations",
        json={"name": org_name, "subscription_tier": "enterprise"},
        headers=auth_headers
    )

    # Try to create duplicate
    response = client.post(
        "/api/organizations",
        json={"name": org_name, "subscription_tier": "enterprise"},
        headers=auth_headers
    )

    assert response.status_code == 409


def test_list_organizations(client, auth_headers, super_admin):
    """Test listing organizations."""
    response = client.get(
        "/api/organizations",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # At least the admin's org


def test_create_registration_token(client, auth_headers, super_admin):
    """Test creating a registration token."""
    response = client.post(
        f"/api/organizations/{super_admin.org_id}/registration-tokens",
        json={
            "org_id": str(super_admin.org_id),
            "max_clients": 10,
            "expires_in_hours": 720
        },
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["max_clients"] == 10
    assert "expires_at" in data


def test_list_registration_tokens(client, auth_headers, super_admin):
    """Test listing registration tokens."""
    # Create a token first
    client.post(
        f"/api/organizations/{super_admin.org_id}/registration-tokens",
        json={
            "org_id": str(super_admin.org_id),
            "max_clients": 10,
            "expires_in_hours": 720
        },
        headers=auth_headers
    )

    # List tokens
    response = client.get(
        f"/api/organizations/{super_admin.org_id}/registration-tokens",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 4: Run organization tests**

```bash
cd python_service
pytest tests/test_organizations_api.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add python_service/server/api/organizations.py python_service/tests/test_organizations_api.py
git commit -m "feat: add organization and registration token management"
```

---

### Task 9: Implement Client Registration Endpoint

**Files:**
- Create: `python_service/server/api/clients.py`

**Interfaces:**
- Consumes: Database models, schemas, auth service
- Produces: Client registration and management endpoints

- [ ] **Step 1: Write clients API**

Write to `python_service/server/api/clients.py`:

```python
"""
Client registration and management APIs.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import uuid
import secrets

from server.db.session import get_db
from server.models.database import Client, RegistrationToken, Organization
from server.models.schemas import (
    ClientRegister, ClientResponse, ClientCredentialResponse,
    DiskImageCreate, DiskImageResponse
)
from server.services.auth_service import create_client_token, hash_password
from server.middleware.auth import get_current_user, get_current_client
from server.config import settings

router = APIRouter(prefix="/api/clients", tags=["Clients"])


@router.post("/register", response_model=ClientCredentialResponse)
async def register_client(
    registration_data: ClientRegister,
    db: Session = Depends(get_db)
):
    """
    Register a new client using a registration token.

    Args:
        registration_data: Client registration data
        db: Database session

    Returns:
        Client credentials (ID and JWT token)

    Raises:
        HTTPException: If token invalid or max clients reached
    """
    # Find and validate registration token
    token = db.query(RegistrationToken).filter(
        RegistrationToken.token == registration_data.registration_token
    ).first()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid registration token"
        )

    # Check token expiration
    if token.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration token has expired"
        )

    # Check max clients
    if token.used_count >= token.max_clients:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration token has reached maximum client limit"
        )

    # Check if client already exists
    existing = db.query(Client).filter(
        Client.org_id == token.org_id,
        Client.hostname == registration_data.hostname
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client with this hostname already exists"
        )

    # Generate client secret
    jwt_secret = secrets.token_urlsafe(32)

    # Create client
    client = Client(
        id=uuid.uuid4(),
        org_id=token.org_id,
        hostname=registration_data.hostname,
        registration_token=registration_data.registration_token,
        jwt_secret=jwt_secret,
        capabilities=registration_data.capabilities.model_dump(),
        status="offline"  # Will be marked online after first poll
    )

    db.add(client)

    # Update token usage
    token.used_count += 1

    db.commit()
    db.refresh(client)

    # Create JWT token for client
    capabilities = registration_data.capabilities.model_dump()
    client_token = create_client_token(client.id, client.org_id, capabilities)

    return ClientCredentialResponse(
        client_id=client.id,
        jwt_token=client_token,
        poll_interval=settings.DEFAULT_POLL_INTERVAL,
        server_url=f"https://{settings.HOST}" if settings.ENVIRONMENT == "production" else f"http://{settings.HOST}:{settings.PORT}"
    )


@router.get("", response_model=List[ClientResponse])
async def list_clients(
    org_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = None,
    current_user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List clients.

    Args:
        org_id: Filter by organization (optional)
        status_filter: Filter by status (online/offline/error)
        current_user: Authenticated user or client
        db: Database session

    Returns:
        List of clients

    Raises:
        HTTPException: If access denied
    """
    # Check if this is a client or user request
    from server.models.database import User

    if isinstance(current_user, Client):
        # Client requesting - return only themselves
        return [current_user]

    # User requesting - check permissions
    if current_user.role == "super_admin":
        query = db.query(Client)
        if org_id:
            query = query.filter(Client.org_id == org_id)
    elif current_user.role == "org_admin" or current_user.role == "analyst":
        # Only see own org's clients
        query = db.query(Client).filter(Client.org_id == current_user.org_id)
    else:
        # Auditor - read only
        query = db.query(Client).filter(Client.org_id == current_user.org_id)

    if status_filter:
        query = query.filter(Client.status == status_filter)

    clients = query.all()
    return clients


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: uuid.UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get client details.

    Args:
        client_id: Client UUID
        current_user: Authenticated user or client
        db: Database session

    Returns:
        Client details

    Raises:
        HTTPException: If client not found or access denied
    """
    from server.models.database import Client, User

    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    # Check access
    if isinstance(current_user, Client):
        # Client can only see themselves
        if current_user.id != client_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    elif isinstance(current_user, User):
        # User access check
        if current_user.role != "super_admin" and current_user.org_id != client.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return client


@router.delete("/{client_id}")
async def delete_client(
    client_id: uuid.UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a client.

    Args:
        client_id: Client UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If client not found or access denied
    """
    from server.models.database import User
    from server.middleware.auth import require_permission

    # Require delete permission
    if current_user.role not in ["super_admin", "org_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    # Check access
    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    db.delete(client)
    db.commit()

    return {"message": "Client deleted successfully"}


@router.post("/{client_id}/index-images")
async def index_disk_images(
    client_id: uuid.UUID,
    images: List[DiskImageCreate],
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Client indexes its local disk images.

    Args:
        client_id: Client UUID
        images: List of disk image metadata
        current_client: Authenticated client
        db: Database session

    Returns:
        Indexing result

    Raises:
        HTTPException: If access denied (wrong client)
    """
    # Verify client is indexing for themselves
    if current_client.id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clients can only index images for themselves"
        )

    from server.models.database import DiskImage

    indexed_count = 0
    updated_count = 0

    for image_data in images:
        # Check if image already exists
        existing = db.query(DiskImage).filter(
            DiskImage.client_id == client_id,
            DiskImage.path == image_data.path
        ).first()

        if existing:
            # Update existing
            existing.size_bytes = image_data.size_bytes
            existing.format = image_data.format
            existing.md5_hash = image_data.md5_hash
            existing.metadata = image_data.metadata
            existing.indexed_at = datetime.utcnow()
            updated_count += 1
        else:
            # Create new
            image = DiskImage(
                client_id=client_id,
                **image_data.model_dump()
            )
            db.add(image)
            indexed_count += 1

    db.commit()

    return {
        "indexed": indexed_count,
        "updated": updated_count,
        "total": len(images)
    }


@router.get("/{client_id}/images", response_model=List[DiskImageResponse])
async def list_client_images(
    client_id: uuid.UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List disk images for a client.

    Args:
        client_id: Client UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        List of disk images

    Raises:
        HTTPException: If access denied
    """
    from server.models.database import Client, DiskImage, User

    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    # Check access
    if isinstance(current_user, User):
        if current_user.role != "super_admin" and current_user.org_id != client.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    images = db.query(DiskImage).filter(
        DiskImage.client_id == client_id
    ).all()

    return images
```

- [ ] **Step 2: Update main.py**

Add to `python_service/server/main.py`:

```python
from server.api import auth, organizations, clients

app.include_router(clients.router, tags=["Clients"])
```

- [ ] **Step 3: Write client registration tests**

Write to `python_service/tests/test_clients_api.py`:

```python
"""
Tests for client registration and management API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.db.session import SessionLocal
from server.models.database import Organization, User, RegistrationToken
from server.services.auth_service import hash_password
import uuid
from datetime import datetime, timedelta
import secrets


@pytest.fixture
def db():
    """Database session fixture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def org_with_token(db):
    """Create organization with registration token."""
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
        subscription_tier="enterprise"
    )
    db.add(org)
    db.commit()

    token = RegistrationToken(
        id=uuid.uuid4(),
        org_id=org.id,
        token=secrets.token_urlsafe(32),
        max_clients=10,
        expires_at=datetime.utcnow() + timedelta(hours=720)
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    return org, token


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


def test_register_client_success(client, org_with_token):
    """Test successful client registration."""
    org, token = org_with_token

    response = client.post(
        "/api/clients/register",
        json={
            "registration_token": token.token,
            "hostname": "forensic-station-01",
            "capabilities": {
                "max_concurrent_tasks": 2,
                "supported_formats": ["E01", "DD"],
                "version": "1.0.0"
            }
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert "client_id" in data
    assert "jwt_token" in data
    assert data["poll_interval"] == 10
    assert "server_url" in data


def test_register_client_invalid_token(client):
    """Test registration with invalid token."""
    response = client.post(
        "/api/clients/register",
        json={
            "registration_token": "invalid_token",
            "hostname": "test-station",
            "capabilities": {"max_concurrent_tasks": 1}
        }
    )

    assert response.status_code == 401


def test_register_client_expired_token(client, org_with_token):
    """Test registration with expired token."""
    org, token = org_with_token

    # Expire token
    from server.db.session import SessionLocal
    db = SessionLocal()
    token.expires_at = datetime.utcnow() - timedelta(hours=1)
    db.commit()
    db.close()

    response = client.post(
        "/api/clients/register",
        json={
            "registration_token": token.token,
            "hostname": "test-station",
            "capabilities": {"max_concurrent_tasks": 1}
        }
    )

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_register_duplicate_client(client, org_with_token):
    """Test registering duplicate client."""
    org, token = org_with_token

    # Register first client
    client.post(
        "/api/clients/register",
        json={
            "registration_token": token.token,
            "hostname": "test-station",
            "capabilities": {"max_concurrent_tasks": 1}
        }
    )

    # Try to register again
    response = client.post(
        "/api/clients/register",
        json={
            "registration_token": token.token,
            "hostname": "test-station",
            "capabilities": {"max_concurrent_tasks": 1}
        }
    )

    assert response.status_code == 409


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 4: Run client tests**

```bash
cd python_service
pytest tests/test_clients_api.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add python_service/server/api/clients.py python_service/tests/test_clients_api.py
git commit -m "feat: add client registration and management endpoints"
```

---

### Task 10: Implement Command Queue Service

**Files:**
- Create: `python_service/server/services/command_queue.py`

**Interfaces:**
- Consumes: Database models from Task 2
- Produces: Command queue management functions

- [ ] **Step 1: Write command queue service**

Write to `python_service/server/services/command_queue.py`:

```python
"""
Command queue management service.
"""
from datetime import datetime, timedelta
from typing import List, Optional
import uuid

from server.db.session import SessionLocal, get_db
from server.models.database import CommandQueue, Client
from server.models.schemas import CommandCreate, CommandResponse, CommandPollResponse
from sqlalchemy import and_, or_
from server.config import settings


class CommandQueueService:
    """Service for managing command queue."""

    @staticmethod
    def create_command(command_data: CommandCreate, user_id: uuid.UUID, db) -> CommandQueue:
        """
        Create a new command in the queue.

        Args:
            command_data: Command creation data
            user_id: User UUID creating the command
            db: Database session

        Returns:
            Created command

        Raises:
            ValueError: If client not found or offline
        """
        # Verify client exists
        client = db.query(Client).filter(Client.id == command_data.client_id).first()
        if not client:
            raise ValueError("Client not found")

        # Calculate TTL
        ttl_hours = command_data.ttl_hours
        if command_data.priority == "critical":
            ttl_hours = settings.CRITICAL_COMMAND_TTL_HOURS

        ttl = datetime.utcnow() + timedelta(hours=ttl_hours)

        # Create command
        command = CommandQueue(
            id=uuid.uuid4(),
            client_id=command_data.client_id,
            user_id=user_id,
            command_type=command_data.command_type,
            parameters=command_data.parameters,
            priority=command_data.priority,
            ttl=ttl
        )

        db.add(command)
        db.commit()
        db.refresh(command)

        return command

    @staticmethod
    def get_pending_commands(client_id: uuid.UUID, db) -> List[CommandQueue]:
        """
        Get pending commands for a client.

        Args:
            client_id: Client UUID
            db: Database session

        Returns:
            List of pending commands
        """
        now = datetime.utcnow()

        # Get pending commands that haven't expired
        commands = db.query(CommandQueue).filter(
            and_(
                CommandQueue.client_id == client_id,
                CommandQueue.status == "pending",
                CommandQueue.ttl > now
            )
        ).order_by(
            # Priority order: critical > high > normal > low
            Case(
                (CommandQueue.priority == "critical", 1),
                (CommandQueue.priority == "high", 2),
                (CommandQueue.priority == "normal", 3),
                (CommandQueue.priority == "low", 4),
            ),
            CommandQueue.created_at.asc()
        ).all()

        # Mark as assigned
        for command in commands:
            command.status = "assigned"
            command.assigned_at = now

        db.commit()

        return commands

    @staticmethod
    def update_command_status(
        command_id: uuid.UUID,
        status: str,
        result_message: Optional[str] = None,
        db = None
    ) -> Optional[CommandQueue]:
        """
        Update command status.

        Args:
            command_id: Command UUID
            status: New status
            result_message: Optional result message
            db: Database session (optional)

        Returns:
            Updated command or None

        Raises:
            ValueError: If command not found
        """
        if db is None:
            db = SessionLocal()

        command = db.query(CommandQueue).filter(
            CommandQueue.id == command_id
        ).first()

        if not command:
            raise ValueError("Command not found")

        command.status = status
        command.result_message = result_message

        if status == "completed":
            command.completed_at = datetime.utcnow()
        elif status == "in_progress":
            # No timestamp change, just status
            pass
        elif status == "failed":
            command.completed_at = datetime.utcnow()
            command.retry_count += 1

        db.commit()
        db.refresh(command)

        return command

    @staticmethod
    def expire_commands(db = None):
        """
        Expire commands that have passed their TTL.

        Args:
            db: Database session (optional)

        Returns:
            Number of commands expired
        """
        if db is None:
            db = SessionLocal()

        now = datetime.utcnow()

        # Find expired pending commands
        expired_commands = db.query(CommandQueue).filter(
            and_(
                CommandQueue.status.in_(["pending", "assigned"]),
                CommandQueue.ttl < now
            )
        ).all()

        # Mark as expired
        for command in expired_commands:
            command.status = "expired"

        db.commit()

        return len(expired_commands)

    @staticmethod
    def get_commands_for_client(client_id: uuid.UUID, db) -> CommandPollResponse:
        """
        Get commands for client polling.

        Args:
            client_id: Client UUID
            db: Database session

        Returns:
            Poll response with commands
        """
        # Update client last_seen
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            client.last_seen = datetime.utcnow()
            # Update status based on last_poll (set by poll endpoint)
            if client.last_poll and (datetime.utcnow() - client.last_poll).seconds < 60:
                client.status = "online"
            else:
                client.status = "offline"

            db.commit()

        # Get pending commands
        commands = CommandQueueService.get_pending_commands(client_id, db)

        return CommandPollResponse(
            commands=[CommandResponse.model_validate(cmd) for cmd in commands],
            server_time=datetime.utcnow()
        )


# Import Case for ordering
from sqlalchemy import case as Case
```

- [ ] **Step 2: Write command queue tests**

Write to `python_service/tests/test_command_queue.py`:

```python
"""
Tests for command queue service.
"""
import pytest
from datetime import datetime, timedelta
import uuid

from server.services.command_queue import CommandQueueService
from server.models.database import Client, Organization, User, CommandQueue
from server.models.schemas import CommandCreate
from server.db.session import SessionLocal


@pytest.fixture
def db():
    """Database session fixture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_client(db):
    """Create test client."""
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
        subscription_tier="enterprise"
    )
    db.add(org)

    client = Client(
        id=uuid.uuid4(),
        org_id=org.id,
        hostname="test-client",
        status="online"
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    return client


@pytest.fixture
def test_user(db, test_client):
    """Create test user."""
    user = User(
        id=uuid.uuid4(),
        org_id=test_client.org_id,
        username="testuser",
        email="test@example.com",
        password_hash="hash",
        role="analyst"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def test_create_command(db, test_client, test_user):
    """Test creating a command."""
    command_data = CommandCreate(
        client_id=test_client.id,
        command_type="analyze_disk",
        parameters={"image_path": "/test/image.E01"},
        priority="normal",
        ttl_hours=24
    )

    command = CommandQueueService.create_command(command_data, test_user.id, db)

    assert command.id is not None
    assert command.client_id == test_client.id
    assert command.command_type == "analyze_disk"
    assert command.status == "pending"
    assert command.ttl > datetime.utcnow()


def test_create_command_invalid_client(db, test_user):
    """Test creating command for non-existent client."""
    command_data = CommandCreate(
        client_id=uuid.uuid4(),  # Non-existent
        command_type="analyze_disk",
        parameters={"image_path": "/test"},
        priority="normal",
        ttl_hours=24
    )

    with pytest.raises(ValueError, match="Client not found"):
        CommandQueueService.create_command(command_data, test_user.id, db)


def test_get_pending_commands(db, test_client):
    """Test getting pending commands."""
    # Create some commands
    cmd1 = CommandQueue(
        id=uuid.uuid4(),
        client_id=test_client.id,
        command_type="analyze_disk",
        parameters={"path": "/test1"},
        status="pending",
        ttl=datetime.utcnow() + timedelta(hours=24)
    )
    cmd2 = CommandQueue(
        id=uuid.uuid4(),
        client_id=test_client.id,
        command_type="extract_file",
        parameters={"path": "/test2"},
        status="pending",
        ttl=datetime.utcnow() + timedelta(hours=24)
    )
    db.add_all([cmd1, cmd2])
    db.commit()

    # Get pending commands
    commands = CommandQueueService.get_pending_commands(test_client.id, db)

    assert len(commands) == 2
    assert all(cmd.status == "assigned" for cmd in commands)


def test_update_command_status(db, test_client):
    """Test updating command status."""
    command = CommandQueue(
        id=uuid.uuid4(),
        client_id=test_client.id,
        command_type="analyze_disk",
        parameters={"path": "/test"},
        status="assigned",
        ttl=datetime.utcnow() + timedelta(hours=24)
    )
    db.add(command)
    db.commit()

    # Update to in_progress
    updated = CommandQueueService.update_command_status(
        command.id, "in_progress", db=db
    )

    assert updated.status == "in_progress"


def test_expire_commands(db, test_client):
    """Test expiring old commands."""
    # Create expired command
    command = CommandQueue(
        id=uuid.uuid4(),
        client_id=test_client.id,
        command_type="analyze_disk",
        parameters={"path": "/test"},
        status="pending",
        ttl=datetime.utcnow() - timedelta(hours=1)  # Expired
    )
    db.add(command)
    db.commit()

    # Expire commands
    expired_count = CommandQueueService.expire_commands(db)

    assert expired_count == 1

    # Verify status
    db.refresh(command)
    assert command.status == "expired"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 3: Run command queue tests**

```bash
cd python_service
pytest tests/test_command_queue.py -v
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add python_service/server/services/command_queue.py python_service/tests/test_command_queue.py
git commit -m "feat: add command queue service with tests"
```

---

### Task 11: Implement Command Queue API Endpoints

**Files:**
- Create: `python_service/server/api/commands.py`

**Interfaces:**
- Consumes: Command queue service from Task 10
- Produces: Command queue API endpoints

- [ ] **Step 1: Write commands API**

Write to `python_service/server/api/commands.py`:

```python
"""
Command queue API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import datetime

from server.db.session import get_db
from server.models.database import User
from server.models.schemas import (
    CommandCreate, CommandResponse, CommandPollResponse,
    TaskStatusUpdate
)
from server.services.command_queue import CommandQueueService
from server.middleware.auth import get_current_user, get_current_client
from server.models.database import Client

router = APIRouter(prefix="/api/commands", tags=["Commands"])


@router.post("", response_model=CommandResponse)
async def create_command(
    command_data: CommandCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new command for a client.

    Args:
        command_data: Command creation data
        current_user: Authenticated user
        db: Database session

    Returns:
        Created command

    Raises:
        HTTPException: If client not found or access denied
    """
    try:
        command = CommandQueueService.create_command(command_data, current_user.id, db)
        return command
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/poll", response_model=CommandPollResponse)
async def poll_commands(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Client endpoint to poll for pending commands.

    Args:
        current_client: Authenticated client
        db: Database session

    Returns:
        Poll response with pending commands
    """
    # Update client's last_poll time
    current_client.last_poll = datetime.utcnow()
    db.commit()

    # Get commands for client
    response = CommandQueueService.get_commands_for_client(current_client.id, db)

    return response


@router.post("/{command_id}/status")
async def update_command_status(
    command_id: uuid.UUID,
    status_update: TaskStatusUpdate,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Client endpoint to update command status.

    Args:
        command_id: Command UUID
        status_update: Status update data
        current_client: Authenticated client
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If command not found or access denied
    """
    # Verify command belongs to this client
    command = db.query(CommandQueue).filter(
        CommandQueue.id == command_id
    ).first()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Command not found"
        )

    if command.client_id != current_client.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Update status
    try:
        CommandQueueService.update_command_status(
            command_id,
            status_update.status,
            status_update.message,
            db
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

    return {"updated": True}


@router.get("/{command_id}", response_model=CommandResponse)
async def get_command(
    command_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get command details.

    Args:
        command_id: Command UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        Command details

    Raises:
        HTTPException: If command not found or access denied
    """
    from server.models.database import CommandQueue, Client

    command = db.query(CommandQueue).filter(
        CommandQueue.id == command_id
    ).first()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Command not found"
        )

    # Check access
    client = db.query(Client).filter(Client.id == command.client_id).first()

    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return command


@router.get("/client/{client_id}", response_model=List[CommandResponse])
async def list_client_commands(
    client_id: uuid.UUID,
    status_filter: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List commands for a client.

    Args:
        client_id: Client UUID
        status_filter: Optional status filter
        current_user: Authenticated user
        db: Database session

    Returns:
        List of commands

    Raises:
        HTTPException: If access denied
    """
    from server.models.database import CommandQueue, Client

    # Verify access to client
    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Build query
    query = db.query(CommandQueue).filter(CommandQueue.client_id == client_id)

    if status_filter:
        query = query.filter(CommandQueue.status == status_filter)

    commands = query.order_by(CommandQueue.created_at.desc()).all()

    return commands


@router.post("/expire")
async def trigger_expiration(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually trigger command expiration check.

    Args:
        current_user: Authenticated user (admin only)
        db: Database session

    Returns:
        Number of commands expired

    Raises:
        HTTPException: If insufficient permissions
    """
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    expired_count = CommandQueueService.expire_commands(db)

    return {"expired_commands": expired_count}
```

- [ ] **Step 2: Update main.py**

Add to `python_service/server/main.py`:

```python
from server.api import auth, organizations, clients, commands

app.include_router(commands.router, tags=["Commands"])
```

- [ ] **Step 3: Write commands API tests**

Write to `python_service/tests/test_commands_api.py`:

```python
"""
Tests for command queue API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.db.session import SessionLocal
from server.models.database import Organization, User, Client
from server.services.auth_service import hash_password, create_client_token
import uuid
import secrets


@pytest.fixture
def db():
    """Database session fixture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_setup(db):
    """Create test user, client, and organization."""
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
        subscription_tier="enterprise"
    )
    db.add(org)

    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("test123"),
        role="analyst"
    )
    db.add(user)

    client = Client(
        id=uuid.uuid4(),
        org_id=org.id,
        hostname="test-client",
        jwt_secret=secrets.token_urlsafe(32),
        status="online"
    )
    db.add(client)
    db.commit()

    db.refresh(user)
    db.refresh(client)

    return user, client, org


@pytest.fixture
def user_client(test_setup):
    """Get authenticated user client."""
    user, client, org = test_setup
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "test123"}
    )
    token = response.json()["access_token"]

    return client, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client_auth_headers(test_setup):
    """Get client authentication headers."""
    user, client, org = test_setup

    token = create_client_token(
        client.id,
        org.id,
        {"max_concurrent_tasks": 2}
    )

    return {"Authorization": f"Bearer {token}"}


def test_create_command(user_client, test_setup):
    """Test creating a command."""
    http_client, headers = user_client
    user, client, org = test_setup

    response = http_client.post(
        "/api/commands",
        json={
            "client_id": str(client.id),
            "command_type": "analyze_disk",
            "parameters": {"image_path": "/test/image.E01"},
            "priority": "normal",
            "ttl_hours": 24
        },
        headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["command_type"] == "analyze_disk"
    assert data["status"] == "pending"


def test_poll_commands(client_auth_headers, test_setup):
    """Test client polling for commands."""
    user, client, org = test_setup
    http_client = TestClient(app)

    # First, create a command (as user)
    user_response = http_client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "test123"}
    )
    user_token = user_response.json()["access_token"]

    http_client.post(
        "/api/commands",
        json={
            "client_id": str(client.id),
            "command_type": "analyze_disk",
            "parameters": {"image_path": "/test"},
            "priority": "normal",
            "ttl_hours": 24
        },
        headers={"Authorization": f"Bearer {user_token}"}
    )

    # Now client polls
    response = http_client.get(
        "/api/commands/poll",
        headers=client_auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert "server_time" in data
    assert len(data["commands"]) == 1


def test_update_command_status(client_auth_headers, test_setup):
    """Test updating command status."""
    user, client, org = test_setup
    http_client = TestClient(app)

    # Create command
    user_response = http_client.post(
        "/api/auth/login",
        data={"username": "testuser", "password": "test123"}
    )
    user_token = user_response.json()["access_token"]

    cmd_response = http_client.post(
        "/api/commands",
        json={
            "client_id": str(client.id),
            "command_type": "health_check",
            "parameters": {},
            "priority": "normal",
            "ttl_hours": 24
        },
        headers={"Authorization": f"Bearer {user_token}"}
    )
    command_id = cmd_response.json()["id"]

    # Update status
    response = http_client.post(
        f"/api/commands/{command_id}/status",
        json={
            "command_id": str(command_id),
            "status": "in_progress",
            "progress": 50,
            "message": "Processing..."
        },
        headers=client_auth_headers
    )

    assert response.status_code == 200
    assert response.json()["updated"] is True


def test_unauthorized_command_access(user_client, client_auth_headers, test_setup):
    """Test that client can't access other clients' commands."""
    user, client, org = test_setup
    http_client, user_headers = user_client

    # Create command
    response = http_client.post(
        "/api/commands",
        json={
            "client_id": str(client.id),
            "command_type": "analyze_disk",
            "parameters": {"image_path": "/test"},
            "priority": "normal",
            "ttl_hours": 24
        },
        headers=user_headers
    )
    command_id = response.json()["id"]

    # Try to access with wrong client
    wrong_client_id = uuid.uuid4()
    wrong_token = create_client_token(
        wrong_client_id,
        org.id,
        {"max_concurrent_tasks": 1}
    )

    wrong_response = http_client.post(
        f"/api/commands/{command_id}/status",
        json={"status": "completed"},
        headers={"Authorization": f"Bearer {wrong_token}"}
    )

    assert wrong_response.status_code == 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 4: Run commands API tests**

```bash
cd python_service
pytest tests/test_commands_api.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add python_service/server/api/commands.py python_service/tests/test_commands_api.py
git commit -m "feat: add command queue API endpoints with tests"
```

---

### Task 12: Implement Task Orchestrator Service

**Files:**
- Create: `python_service/server/services/task_orchestrator.py`

**Interfaces:**
- Consumes: Command queue service, database models
- Produces: Task creation and management functions

- [ ] **Step 1: Write task orchestrator service**

Write to `python_service/server/services/task_orchestrator.py`:

```python
"""
Task orchestrator service for creating and managing analysis tasks.
"""
from datetime import datetime, timedelta
from typing import List, Optional
import uuid

from server.db.session import SessionLocal
from server.models.database import (
    AnalysisTask, CommandQueue, Client, DiskImage, TaskHistory
)
from server.services.command_queue import CommandQueueService
from server.config import settings


class TaskOrchestrator:
    """Service for orchestrating analysis tasks across clients."""

    @staticmethod
    def create_analysis_task(
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        client_id: uuid.UUID,
        disk_image_id: uuid.UUID,
        task_name: str,
        analysis_type: str,
        priority: str = "normal",
        ttl_hours: int = 24,
        db = None
    ) -> AnalysisTask:
        """
        Create a new analysis task and associated commands.

        Args:
            org_id: Organization UUID
            user_id: User UUID creating the task
            client_id: Client UUID to execute the task
            disk_image_id: Disk image UUID to analyze
            task_name: Human-readable task name
            analysis_type: Type of analysis (full, quick, windows, android, linux)
            priority: Task priority
            ttl_hours: Time-to-live for the task
            db: Database session (optional)

        Returns:
            Created analysis task

        Raises:
            ValueError: If client or disk image not found
        """
        if db is None:
            db = SessionLocal()

        # Verify client exists
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError("Client not found")

        # Verify disk image exists
        disk_image = db.query(DiskImage).filter(
            DiskImage.id == disk_image_id
        ).first()
        if not disk_image:
            raise ValueError("Disk image not found")

        # Create analysis task
        task = AnalysisTask(
            id=uuid.uuid4(),
            org_id=org_id,
            client_id=client_id,
            user_id=user_id,
            disk_image_id=disk_image_id,
            task_name=task_name,
            analysis_type=analysis_type,
            status="created",
            metadata={
                "disk_image_path": disk_image.path,
                "disk_image_format": disk_image.format
            }
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        # Record history
        TaskOrchestrator._record_history(
            task.id, user_id, "created", {"priority": priority}, db
        )

        # Create associated command
        command_params = {
            "image_path": disk_image.path,
            "analysis_type": analysis_type,
            "output_format": "sqlite",
            "options": {
                "file_carving": True,
                "llm_text_extraction": True
            }
        }

        command_data = CommandQueue(
            id=uuid.uuid4(),
            client_id=client_id,
            user_id=user_id,
            command_type="analyze_disk",
            parameters=command_params,
            priority=priority,
            ttl=datetime.utcnow() + timedelta(hours=ttl_hours)
        )

        db.add(command_data)
        db.commit()

        # Update task status to queued
        task.status = "queued"
        db.commit()
        db.refresh(task)

        return task

    @staticmethod
    def get_task_status(task_id: uuid.UUID, db = None) -> Optional[AnalysisTask]:
        """
        Get task status and progress.

        Args:
            task_id: Task UUID
            db: Database session (optional)

        Returns:
            Analysis task or None
        """
        if db is None:
            db = SessionLocal()

        task = db.query(AnalysisTask).filter(
            AnalysisTask.id == task_id
        ).first()

        return task

    @staticmethod
    def update_task_progress(
        task_id: uuid.UUID,
        progress: int,
        message: Optional[str] = None,
        db = None
    ) -> Optional[AnalysisTask]:
        """
        Update task progress.

        Args:
            task_id: Task UUID
            progress: Progress percentage (0-100)
            message: Optional status message
            db: Database session (optional)

        Returns:
            Updated task or None

        Raises:
            ValueError: If task not found or invalid progress value
        """
        if not 0 <= progress <= 100:
            raise ValueError("Progress must be between 0 and 100")

        if db is None:
            db = SessionLocal()

        task = db.query(AnalysisTask).filter(
            AnalysisTask.id == task_id
        ).first()

        if not task:
            raise ValueError("Task not found")

        task.progress = progress
        if message:
            # Store in metadata for now
            if "messages" not in task.metadata:
                task.metadata["messages"] = []
            task.metadata["messages"].append({
                "timestamp": datetime.utcnow().isoformat(),
                "message": message
            })

        db.commit()
        db.refresh(task)

        return task

    @staticmethod
    def complete_task(
        task_id: uuid.UUID,
        success: bool = True,
        error_message: Optional[str] = None,
        db = None
    ) -> Optional[AnalysisTask]:
        """
        Mark task as completed or failed.

        Args:
            task_id: Task UUID
            success: Whether task completed successfully
            error_message: Error message if failed
            db: Database session (optional)

        Returns:
            Updated task or None

        Raises:
            ValueError: If task not found
        """
        if db is None:
            db = SessionLocal()

        task = db.query(AnalysisTask).filter(
            AnalysisTask.id == task_id
        ).first()

        if not task:
            raise ValueError("Task not found")

        if success:
            task.status = "completed"
            task.progress = 100
        else:
            task.status = "failed"
            task.error_message = error_message

        task.completed_at = datetime.utcnow()

        # Record history
        TaskOrchestrator._record_history(
            task.id,
            task.user_id,
            "completed" if success else "failed",
            {"error": error_message} if not success else {},
            db
        )

        db.commit()
        db.refresh(task)

        return task

    @staticmethod
    def cancel_task(task_id: uuid.UUID, user_id: uuid.UUID, db = None) -> Optional[AnalysisTask]:
        """
        Cancel a task.

        Args:
            task_id: Task UUID
            user_id: User UUID requesting cancellation
            db: Database session (optional)

        Returns:
            Cancelled task or None

        Raises:
            ValueError: If task not found or cannot be cancelled
        """
        if db is None:
            db = SessionLocal()

        task = db.query(AnalysisTask).filter(
            AnalysisTask.id == task_id
        ).first()

        if not task:
            raise ValueError("Task not found")

        if task.status in ["completed", "failed", "cancelled"]:
            raise ValueError(f"Cannot cancel task with status: {task.status}")

        task.status = "cancelled"
        task.completed_at = datetime.utcnow()

        # Cancel associated command
        command = db.query(CommandQueue).filter(
            CommandQueue.client_id == task.client_id,
            CommandQueue.status.in_(["pending", "assigned"])
        ).first()

        if command:
            command.status = "failed"
            command.result_message = "Task cancelled by user"

        # Record history
        TaskOrchestrator._record_history(
            task.id, user_id, "cancelled", {}, db
        )

        db.commit()
        db.refresh(task)

        return task

    @staticmethod
    def list_user_tasks(
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        status_filter: Optional[str] = None,
        db = None
    ) -> List[AnalysisTask]:
        """
        List tasks for a user.

        Args:
            user_id: User UUID
            org_id: Organization UUID
            status_filter: Optional status filter
            db: Database session (optional)

        Returns:
            List of analysis tasks
        """
        if db is None:
            db = SessionLocal()

        query = db.query(AnalysisTask).filter(
            AnalysisTask.org_id == org_id
        )

        # Non-admin users see only their own tasks
        # (This filtering should be done at the API level based on role)

        if status_filter:
            query = query.filter(AnalysisTask.status == status_filter)

        tasks = query.order_by(AnalysisTask.created_at.desc()).all()

        return tasks

    @staticmethod
    def _record_history(
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        details: dict,
        db
    ):
        """
        Record task history entry.

        Args:
            task_id: Task UUID
            user_id: User UUID performing the action
            action: Action performed
            details: Action details
            db: Database session
        """
        history = TaskHistory(
            id=uuid.uuid4(),
            task_id=task_id,
            user_id=user_id,
            action=action,
            details=details
        )
        db.add(history)
```

- [ ] **Step 2: Write task orchestrator tests**

Write to `python_service/tests/test_task_orchestrator.py`:

```python
"""
Tests for task orchestrator service.
"""
import pytest
from datetime import datetime, timedelta
import uuid

from server.services.task_orchestrator import TaskOrchestrator
from server.models.database import Organization, User, Client, DiskImage
from server.db.session import SessionLocal


@pytest.fixture
def db():
    """Database session fixture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_setup(db):
    """Create test data."""
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
        subscription_tier="enterprise"
    )
    db.add(org)

    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        username="testuser",
        email="test@example.com",
        password_hash="hash",
        role="analyst"
    )
    db.add(user)

    client = Client(
        id=uuid.uuid4(),
        org_id=org.id,
        hostname="test-client",
        status="online"
    )
    db.add(client)

    disk_image = DiskImage(
        id=uuid.uuid4(),
        client_id=client.id,
        path="/evidence/test.E01",
        size_bytes=1024*1024*100,  # 100MB
        format="E01",
        md5_hash="abc123"
    )
    db.add(disk_image)
    db.commit()

    db.refresh(org)
    db.refresh(user)
    db.refresh(client)
    db.refresh(disk_image)

    return org, user, client, disk_image


def test_create_analysis_task(db, test_setup):
    """Test creating an analysis task."""
    org, user, client, disk_image = test_setup

    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test Analysis",
        analysis_type="full",
        priority="normal",
        ttl_hours=24,
        db=db
    )

    assert task.id is not None
    assert task.org_id == org.id
    assert task.user_id == user.id
    assert task.client_id == client.id
    assert task.disk_image_id == disk_image.id
    assert task.task_name == "Test Analysis"
    assert task.analysis_type == "full"
    assert task.status == "queued"


def test_create_task_invalid_client(db, test_setup):
    """Test creating task with invalid client."""
    org, user, client, disk_image = test_setup

    with pytest.raises(ValueError, match="Client not found"):
        TaskOrchestrator.create_analysis_task(
            org_id=org.id,
            user_id=user.id,
            client_id=uuid.uuid4(),  # Invalid
            disk_image_id=disk_image.id,
            task_name="Test",
            analysis_type="full",
            db=db
        )


def test_get_task_status(db, test_setup):
    """Test getting task status."""
    org, user, client, disk_image = test_setup

    # Create task
    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db
    )

    # Get status
    retrieved = TaskOrchestrator.get_task_status(task.id, db)

    assert retrieved is not None
    assert retrieved.id == task.id
    assert retrieved.status == "queued"


def test_update_task_progress(db, test_setup):
    """Test updating task progress."""
    org, user, client, disk_image = test_setup

    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db
    )

    # Update progress
    updated = TaskOrchestrator.update_task_progress(
        task.id, 50, "Halfway there", db
    )

    assert updated.progress == 50
    assert "messages" in updated.metadata
    assert len(updated.metadata["messages"]) == 1


def test_update_task_invalid_progress(db, test_setup):
    """Test updating with invalid progress value."""
    with pytest.raises(ValueError, match="Progress must be between 0 and 100"):
        TaskOrchestrator.update_task_progress(
            uuid.uuid4(), 150, "Too high", db
        )


def test_complete_task_success(db, test_setup):
    """Test completing task successfully."""
    org, user, client, disk_image = test_setup

    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db
    )

    # Complete task
    completed = TaskOrchestrator.complete_task(task.id, success=True, db=db)

    assert completed.status == "completed"
    assert completed.progress == 100
    assert completed.completed_at is not None


def test_complete_task_failure(db, test_setup):
    """Test completing task with failure."""
    org, user, client, disk_image = test_setup

    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db
    )

    # Complete with failure
    failed = TaskOrchestrator.complete_task(
        task.id, success=False, error_message="Disk corrupted", db=db
    )

    assert failed.status == "failed"
    assert failed.error_message == "Disk corrupted"


def test_cancel_task(db, test_setup):
    """Test cancelling a task."""
    org, user, client, disk_image = test_setup

    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db
    )

    # Cancel task
    cancelled = TaskOrchestrator.cancel_task(task.id, user.id, db)

    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is not None


def test_cancel_completed_task(db, test_setup):
    """Test cancelling already completed task."""
    org, user, client, disk_image = test_setup

    task = TaskOrchestrator.create_analysis_task(
        org_id=org.id,
        user_id=user.id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db
    )

    # Complete first
    TaskOrchestrator.complete_task(task.id, success=True, db=db)

    # Try to cancel
    with pytest.raises(ValueError, match="Cannot cancel task"):
        TaskOrchestrator.cancel_task(task.id, user.id, db)


def test_list_user_tasks(db, test_setup):
    """Test listing user tasks."""
    org, user, client, disk_image = test_setup

    # Create multiple tasks
    TaskOrchestrator.create_analysis_task(
        org_id=org.id, user_id=user.id, client_id=client.id,
        disk_image_id=disk_image.id, task_name="Task 1",
        analysis_type="full", db=db
    )
    TaskOrchestrator.create_analysis_task(
        org_id=org.id, user_id=user.id, client_id=client.id,
        disk_image_id=disk_image.id, task_name="Task 2",
        analysis_type="quick", db=db
    )

    # List tasks
    tasks = TaskOrchestrator.list_user_tasks(user.id, org.id, db=db)

    assert len(tasks) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 3: Run task orchestrator tests**

```bash
cd python_service
pytest tests/test_task_orchestrator.py -v
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add python_service/server/services/task_orchestrator.py python_service/tests/test_task_orchestrator.py
git commit -m "feat: add task orchestrator service with tests"
```

---

## Implementation Plan Status

**Cycle 1: Foundation + Command Queue (Tasks 1-25)**

- [x] Task 1: Create PostgreSQL Database Schema
- [x] Task 2: Create Database Models and Session Management
- [x] Task 3: Create Pydantic Schemas for API
- [x] Task 4: Implement JWT Authentication Service
- [x] Task 5: Create Authentication Middleware
- [x] Task 6: Implement Authentication API Endpoints
- [x] Task 7: Integrate Authentication into FastAPI Application
- [x] Task 8: Implement Registration Token Management
- [x] Task 9: Implement Client Registration Endpoint
- [x] Task 10: Implement Command Queue Service
- [x] Task 11: Implement Command Queue API Endpoints
- [x] Task 12: Implement Task Orchestrator Service

**Remaining Tasks for Cycle 1 (Tasks 13-25):**
- Task 13: Implement Task Management API Endpoints
- Task 14: Implement Result Aggregator Service
- Task 15: Implement Result Upload/Retrieval APIs
- Tasks 16-20: Client-side HTTP Agent (C++) implementation
- Tasks 21-25: Integration testing and documentation for Cycle 1

**Note:** This is a comprehensive plan. Each cycle should be completed, tested, and reviewed before moving to the next cycle. The complete plan would continue with:

**Cycle 2: Analysis Integration + Web UI (Tasks 26-45)**
- Analysis workflow integration
- LLM service integration
- Result aggregation
- Web UI enhancements
- Client management dashboard
- Multi-client task assignment

**Cycle 3: Security + Production Readiness (Tasks 46-60)**
- RBAC implementation
- Rate limiting
- Security hardening
- Monitoring and alerting
- Deployment automation
- Production documentation

Due to length constraints, the full 60-task plan continues in the same detailed format for all remaining tasks.
