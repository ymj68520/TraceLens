# TraceLens Client/Server Architecture Design

**Document Version:** 1.0
**Date:** 2025-01-15
**Status:** Design Specification
**Author:** Claude (Brainstorming Skill)

---

## Executive Summary

This document describes the transformation of TraceLens from a monolithic local application into a distributed client/server architecture. The new architecture enables:

- **Security & Privacy:** Sensitive forensic data remains on local machines while enabling centralized management
- **Resource Distribution:** Heavy forensic analysis runs locally; centralized server handles web UI and LLM processing
- **Remote Collaboration:** Cloud server coordinates analysis across distributed global client machines
- **Deployment Flexibility:** Lightweight clients can run anywhere; server provides unified management

**Architecture Pattern:** Poll-Based Command Queue with HTTPS communication

---

## Table of Contents

1. [Requirements](#requirements)
2. [Architecture Overview](#architecture-overview)
3. [Component Design](#component-design)
4. [Data Flow & Workflows](#data-flow--workflows)
5. [API Specification](#api-specification)
6. [Security Model](#security-model)
7. [Database Schema](#database-schema)
8. [Deployment Architecture](#deployment-architecture)
9. [Implementation Roadmap](#implementation-roadmap)
10. [Testing Strategy](#testing-strategy)
11. [Monitoring & Operations](#monitoring--operations)

---

## Requirements

> **Note on Scope:** This specification covers the complete C/S architecture transformation. The implementation plan that follows this specification should be decomposed into 2-3 separate implementation cycles for practical development.

### Functional Requirements

**FR-1: Client-Server Communication**
- Clients poll server every 10 seconds (default, configurable 5-30 seconds)
- All communication over HTTPS with JWT authentication
- Server supports up to 1000 concurrent clients

**FR-2: Analysis Orchestration**
- Users initiate analysis from web UI
- Server queues commands for target clients
- Clients execute analysis and push results back

**FR-3: Multi-Tenancy**
- Organization-based client and user management
- Role-based access control (Super Admin, Org Admin, Analyst, Auditor)
- Complete data isolation between organizations

**FR-4: Data Handling**
- Raw disk images NEVER leave client machines
- Analysis results (SQLite DBs, extracted files) uploaded to server
- Maximum single file upload: 5GB (configurable)
- LLM processing server-side with client-sent text content
- Maximum text submission for LLM: 10MB per request

**FR-5: Offline Handling**
- Server queues tasks with TTL (default 24 hours)
- Clients gracefully handle network failures
- Automatic retry with exponential backoff

### Non-Functional Requirements

**NFR-1: Security**
- TLS 1.3 for all communication
- JWT-based authentication for users and clients
- RBAC with audit logging
- No raw forensic data exposure to server

**NFR-2: Performance**
- API response time <500ms (p95)
- Support 100 concurrent clients
- Handle 1000 tasks in queue without degradation

**NFR-3: Availability**
- Server uptime 99.5%
- Client polling continues during network partitions
- Graceful degradation of non-critical features

**NFR-4: Scalability**
- Horizontal scaling of server instances
- Database read replicas for query scaling
- Object storage for unlimited file storage

---

## Architecture Overview

### Overall Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Cloud Server (Central)                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     Web UI (React + Vite)                        │   │
│  │                    Port 5173 / HTTPS 443                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              Python FastAPI Service (Port 8090)                 │   │
│  │  • LLM Analysis Service                                         │   │
│  │  • Task Orchestrator API                                         │   │
│  │  • Organization/User Management                                  │   │
│  │  • Command Queue API                                            │   │
│  │  • Results Aggregator API                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    PostgreSQL Database                          │   │
│  │  • Organizations, Users, Roles                                   │   │
│  │  • Client Registrations                                          │   │
│  │  • Command Queues (with TTL)                                    │   │
│  │  • Analysis Results & Metadata                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                   Object Storage (S3/OSS)                          │   │
│  │  • Analysis Results                                              │   │
│  │  • Extracted Files                                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                   ▲
                                   │ HTTPS Poll (5-30s)
                                   │ HTTPS POST (results)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Local Client (Forensic Station)                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              C++ Forensic Analyzer (Port 8080)                  │   │
│  │  • Disk Image Analysis (E01, DD)                               │   │
│  │  • File Extraction & Classification                             │   │
│  │  • SQLite Database Generation                                  │   │
│  │  • File Carving                                                 │   │
│  │  • Metadata & Text Extraction                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                  HTTP Agent Service (New)                       │   │
│  │  • Polls for commands (5-30s interval)                          │   │
│  │  • Executes commands via C++ Analyzer                          │   │
│  │  • Uploads results to server                                    │   │
│  │  • Sends extracted text for LLM processing                     │   │
│  │  • Manages local task queue                                     │   │
│  │  • JWT Authentication                                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

**Decision 1: Poll-Based Communication**
- Rationale: Firewall-friendly, works globally, simple implementation
- Trade-off: 5-30 second latency acceptable for batch forensic workflows

**Decision 2: Client-Side Analysis Only**
- Rationale: Raw images too large and sensitive for transfer
- Trade-off: LLM processing must be done with pre-extracted text

**Decision 3: Organization-Based Multi-Tenancy**
- Rationale: Natural fit for enterprise forensic teams
- Trade-off: Additional complexity in access control

**Decision 4: JWT Authentication**
- Rationale: Industry standard, scalable, no session management
- Trade-off: Token expiration handling required

---

## Component Design

### Client Side Components

#### C++ Forensic Analyzer (Existing + Modified)

**Current Functionality (Retained):**
- Disk image analysis: E01, DD formats
- File extraction and classification into SQLite databases
- File carving for deleted files
- Metadata extraction from filesystems
- Text extraction from documents, PDFs, Office files
- Platform-specific analysis (Android, Windows, Linux)

**New Additions:**
- HTTP API endpoints for local HTTP agent
- Structured text extraction output for server LLM
- Progress reporting hooks

**API Endpoints:**
```
POST /local/analyze - Start analysis
GET /local/status/{task_id} - Get progress
DELETE /local/tasks/{task_id} - Cancel task
```

#### HTTP Agent Service (New Component)

**Responsibilities:**
1. Poll server every 5-30 seconds for pending commands
2. Execute commands by calling local C++ analyzer API
3. Upload analysis results to server
4. Send extracted text content to server for LLM processing
5. Maintain local task queue for offline scenarios
6. Handle JWT authentication with server

**Technology Stack:**
- Implementation: C++ (shares analyzer codebase) or Python
- Storage: SQLite for local queue and credentials
- Networking: HTTP client with retry logic

**Local State:**
```sql
-- Local Task Queue
CREATE TABLE local_tasks (
    id INTEGER PRIMARY KEY,
    server_command_id VARCHAR(255) UNIQUE,
    command_type VARCHAR(100) NOT NULL,
    parameters TEXT NOT NULL, -- JSON
    status VARCHAR(50) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

-- Credentials
CREATE TABLE credentials (
    id INTEGER PRIMARY KEY,
    client_id VARCHAR(255) NOT NULL,
    jwt_token TEXT NOT NULL,
    server_url VARCHAR(500) NOT NULL,
    poll_interval INTEGER DEFAULT 10
);
```

### Server Side Components

#### Python FastAPI Service (Expanded)

**Existing Modules (Retained):**
- LLM Analysis Service
- Knowledge Graph (Graphiti + Neo4j)
- TOON Export
- Database Analysis

**New Modules:**

**Task Orchestrator:**
- Creates analysis tasks from user requests
- Queues commands for specific clients
- Tracks task status and completion

**Command Queue API:**
- Manages per-client command queues
- Handles TTL and expiration
- Provides poll endpoint for clients

**Client Management API:**
- Handles client registration
- Tracks client status and capabilities
- Manages client health

**Result Aggregator:**
- Receives uploaded analysis results
- Stores in PostgreSQL and object storage
- Triggers LLM processing when needed

**Organization Management:**
- Multi-tenant user and role management
- Organization isolation
- Registration token generation

#### PostgreSQL Database (New)

**Purpose:** Central data store for all server-side state

**Key Tables:**
- `organizations` - Tenant isolation
- `users` - User accounts and roles
- `clients` - Registered forensic stations
- `disk_images` - Catalog of available images
- `command_queue` - Tasks queued for clients
- `analysis_tasks` - User-initiated analysis jobs
- `analysis_results` - Completed analysis data
- `llm_analysis` - LLM processing results
- `registration_tokens` - Client enrollment tokens

#### Web UI (React - Expanded)

**New Features:**
- Client management dashboard
- Multi-client task assignment
- Organization administration
- Cross-client search and correlation
- Real-time task monitoring (poll-based)

---

## Data Flow & Workflows

### Primary Workflow: Server-Initiated Analysis

```
Step 1: Image Registration
┌─────────┐          ┌─────────┐          ┌─────────┐
│   User  │─────────▶│   Web   │─────────▶│ Server  │
└─────────┘          │   UI    │          │   DB    │
                     └─────────┘          └─────────┘
                                                   │
                                                   ▼
Step 2: Client Indexing    ┌─────────┐         ┌─────────┐
┌─────────┐               │ Client  │────────▶│ Server  │
│ Client  │──────────────▶│  Agent  │         │   API   │
│   Scan  │               └─────────┘         └─────────┘
└─────────┘
                                                   │
                                                   ▼
Step 3: Task Creation     ┌─────────┐         ┌─────────┐
┌─────────┐               │   Web   │────────▶│ Server  │
│   User  │──────────────▶│   UI    │         │   DB    │
└─────────┘               └─────────┘         └─────────┘
                                                   │
                                                   ▼
Step 4: Client Polling     ┌─────────┐         ┌─────────┐
┌─────────┐               │ Client  │◀────────│ Server  │
│ Client  │──────────────▶│  Agent  │         │   API   │
│  Poll   │               └─────────┘         └─────────┘
└─────────┘                     │
                                ▼
Step 5: Analysis          ┌─────────┐
┌─────────┐               │   C++   │
│ Client  │──────────────▶│ Analyzer│
│  Agent  │               └─────────┘
└─────────┘                     │
                                ▼
Step 6: Result Upload     ┌─────────┐         ┌─────────┐
┌─────────┐               │ Client  │────────▶│ Server  │
│ Client  │──────────────▶│  Agent  │         │   API   │
│Upload  │               └─────────┘         └─────────┘
└─────────┘                                           │
                                                     ▼
Step 7: LLM Processing  ┌─────────┐         ┌─────────┐
┌─────────┐               │ Server  │────────▶│   LLM   │
│ Server  │──────────────▶│   API   │         │ Service │
│   API   │               └─────────┘         └─────────┘
└─────────┘                     │
                                ▼
Step 8: View Results     ┌─────────┐         ┌─────────┐
┌─────────┐               │   Web   │◀────────│ Server  │
│   User  │──────────────▶│   UI    │         │   API   │
└─────────┘               └─────────┘         └─────────┘
```

### Client Registration Workflow

```
1. Admin generates registration token
   POST /api/admin/registration-tokens
   Response: {token: "reg_abc123", expiry: "2025-02-15"}

2. Operator installs client
   HTTP Agent prompts for token

3. Client registers
   POST /api/clients/register
   Body: {token, hostname, capabilities}

4. Server validates and creates record
   Response: {client_id, jwt_token, poll_interval}

5. Client stores credentials and starts polling
   GET /api/commands/poll (every 10 seconds)

6. Client indexes local disk images
   POST /api/clients/index-images
   Body: {images: [{path, size, format, md5}]}
```

### Offline/Timeout Handling

```
Scenario: Client goes offline during task execution

1. Network failure detected
   └─> Poll request fails
   └─> HTTP Agent switches to retry mode
   └─> Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s

2. Server marks client offline
   └─> 3 consecutive failed polls
   └─> Status: "offline"

3. Task execution continues on client
   └─> Local task queue maintains state
   └─> Progress tracked locally

4. Client reconnects
   └─> Resume polling
   └─> Upload queued results
   └─> Receive any new commands

5. Task expiration
   └─> If TTL expires: mark as "expired"
   └─> Notify admin for manual intervention
```

### LLM Processing Workflow

```
1. Client completes analysis
   └─> Generates SQLite databases
   └─> Extracts text from files

2. Client uploads results
   POST /api/results/analysis
   FormData: {databases, metadata}

3. Client submits text for LLM
   POST /api/llm/text-analysis
   Body: {task_id, file_id, text_content}

4. Server queues LLM processing
   └─> Python FastAPI processes queue
   └─> Calls OpenAI-compatible API

5. LLM results stored
   └─> PostgreSQL: llm_analysis table
   └─> Linked to original task

6. User views enhanced results
   └─> Web UI displays analysis + LLM insights
```

---

## API Specification

### Client → Server APIs

#### Poll for Commands
```http
GET /api/commands/poll
Authorization: Bearer <jwt_token>

Response 200:
{
  "commands": [
    {
      "command_id": "cmd_123",
      "type": "analyze_disk",
      "params": {
        "image_path": "/evidence/case1.img",
        "analysis_type": "full"
      },
      "priority": "normal",
      "created_at": "2025-01-15T10:00:00Z",
      "ttl": "2025-01-16T10:00:00Z"
    }
  ],
  "server_time": "2025-01-15T10:05:00Z"
}
```

#### Upload Analysis Results
```http
POST /api/results/analysis
Authorization: Bearer <jwt_token>
Content-Type: multipart/form-data

FormData:
- command_id: "cmd_123"
- task_id: "task_456"
- status: "completed"
- databases: [
    {name: "case1_raw.db", file: <binary>},
    {name: "case1_events.db", file: <binary>},
    {name: "case1_files.db", file: <binary>}
  ]
- metadata: {...}

Response 200:
{
  "result_id": "res_789",
  "status": "processed"
}
```

#### Submit Text for LLM
```http
POST /api/llm/text-analysis
Authorization: Bearer <jwt_token>
Content-Type: application/json

Body:
{
  "task_id": "task_456",
  "file_id": "file_101",
  "text_content": "...extracted text...",
  "metadata": {
    "file_type": "document",
    "mime_type": "application/pdf"
  }
}

Response 200:
{
  "analysis_id": "analysis_201",
  "status": "queued"
}
```

#### Update Task Status
```http
POST /api/tasks/status
Authorization: Bearer <jwt_token>
Content-Type: application/json

Body:
{
  "command_id": "cmd_123",
  "status": "in_progress",
  "progress": 45,
  "message": "Extracting files..."
}

Response 200:
{
  "updated": true
}
```

#### Client Registration
```http
POST /api/clients/register
Content-Type: application/json

Body:
{
  "registration_token": "reg_token_xyz",
  "hostname": "forensic-station-01",
  "capabilities": {
    "max_concurrent_tasks": 2,
    "supported_formats": ["E01", "DD"],
    "version": "1.0.0"
  }
}

Response 200:
{
  "client_id": "client_abc",
  "jwt_token": "eyJhbG...",
  "poll_interval": 10,
  "server_url": "https://api.tracelens.example.com"
}
```

#### Index Local Images
```http
POST /api/clients/index-images
Authorization: Bearer <jwt_token>
Content-Type: application/json

Body:
{
  "images": [
    {
      "path": "/evidence/case1.E01",
      "size_bytes": 1073741824,
      "format": "E01",
      "md5": "abc123...",
      "created_at": "2025-01-10T10:00:00Z"
    }
  ]
}

Response 200:
{
  "indexed": 1,
  "updated": 1
}
```

### Server → Client Commands

Commands are delivered through the poll endpoint. Types:

#### Analyze Disk Image
```json
{
  "command_id": "cmd_001",
  "type": "analyze_disk",
  "params": {
    "image_path": "/evidence/case1.E01",
    "analysis_type": "full|quick|windows|android|linux",
    "output_format": "sqlite",
    "options": {
      "file_carving": true,
      "llm_text_extraction": true
    }
  }
}
```

#### Extract Specific File
```json
{
  "command_id": "cmd_002",
  "type": "extract_file",
  "params": {
    "image_path": "/evidence/case1.E01",
    "file_path": "/Users/suspect/Documents/plan.docx",
    "output_to": "server"
  }
}
```

#### Health Check
```json
{
  "command_id": "cmd_003",
  "type": "health_check",
  "params": {}
}
```

### Web UI → Server APIs

#### Create Analysis Task
```http
POST /api/tasks/create
Authorization: Bearer <user_jwt>
Content-Type: application/json

Body:
{
  "client_id": "client_abc",
  "image_id": "img_123",
  "analysis_type": "full",
  "priority": "normal",
  "ttl_hours": 24
}

Response 200:
{
  "task_id": "task_456",
  "status": "queued",
  "estimated_completion": "2025-01-15T12:00:00Z"
}
```

#### List Clients
```http
GET /api/clients?org_id={org_id}&status=online
Authorization: Bearer <user_jwt>

Response 200:
{
  "clients": [
    {
      "client_id": "client_abc",
      "hostname": "forensic-station-01",
      "status": "online",
      "last_seen": "2025-01-15T10:30:00Z",
      "capabilities": {...}
    }
  ]
}
```

#### Get Task Status
```http
GET /api/tasks/{task_id}
Authorization: Bearer <user_jwt>

Response 200:
{
  "task_id": "task_456",
  "status": "completed",
  "progress": 100,
  "client_id": "client_abc",
  "created_at": "2025-01-15T10:00:00Z",
  "completed_at": "2025-01-15T11:30:00Z",
  "results": {
    "databases": ["case1_raw.db", "case1_events.db", "case1_files.db"],
    "llm_analysis": ["analysis_201"],
    "file_count": 15234
  }
}
```

---

## Security Model

### Authentication

#### User Authentication (Web UI)

**Login Flow:**
1. User submits credentials
2. Server validates against PostgreSQL
3. JWT token issued (1 hour expiry)
4. Client includes token in Authorization header

**JWT Payload:**
```json
{
  "user_id": "user_123",
  "org_id": "org_abc",
  "role": "analyst|admin",
  "permissions": ["create_tasks", "view_results"],
  "exp": 1736899200
}
```

**Token Refresh:**
- User tokens: 1 hour expiry, refresh endpoint available
- Client tokens: 30 days expiry, re-registration required after expiry

#### Client Authentication (Agent)

**Registration Flow:**
1. Admin generates registration token
2. Client registers with token
3. Server issues client JWT (30 day expiry)
4. Client uses JWT for all requests

**Client JWT Payload:**
```json
{
  "client_id": "client_xyz",
  "org_id": "org_abc",
  "capabilities": ["analyze_e01", "analyze_dd"],
  "exp": 1737504000
}
```

### Authorization (RBAC)

**Roles and Permissions:**

| Role | Create Tasks | View Results | Delete Tasks | Admin Config |
|------|-------------|-------------|-------------|--------------|
| Super Admin | ✓ | ✓ | ✓ | ✓ |
| Org Admin | ✓ | ✓ | ✓ | - |
| Analyst | ✓ | ✓ | - | - |
| Auditor | - | ✓ | - | - |

**Implementation:**
```python
def check_permission(user_id, required_permission):
    user = get_user(user_id)
    role_permissions = ROLE_PERMISSIONS[user.role]
    return required_permission in role_permissions
```

### Data Security

**Encryption:**
- In Transit: TLS 1.3 for all HTTPS
- At Rest: PostgreSQL TDE (optional)
- Client Storage: SQLite unencrypted (local control)

**Data Isolation:**
- Organization-level filtering
- Client ownership verification
- User access audit logging

**Sensitive Data Handling:**
- Raw disk images: NEVER transferred
- Extracted files: Encrypted at rest on server
- LLM content: Not logged in plain text

### Security Headers

```
Strict-Transport-Security: max-age=31536000
Content-Security-Policy: default-src 'self'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
```

### Rate Limiting

- Login attempts: 5 per minute per IP
- API calls: 100 per minute per user
- Client polling: 120 per hour (2/min)

---

## Database Schema

### PostgreSQL Schema (Server)

```sql
-- Organizations
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settings JSONB DEFAULT '{}',
    subscription_tier VARCHAR(50) DEFAULT 'free'
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    UNIQUE(org_id, username)
);

-- Clients
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    hostname VARCHAR(255) NOT NULL,
    registration_token VARCHAR(255) UNIQUE,
    jwt_secret VARCHAR(255),
    capabilities JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'offline',
    last_poll TIMESTAMP,
    last_seen TIMESTAMP,
    version VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(org_id, hostname)
);

-- Disk Images Catalog
CREATE TABLE disk_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    path VARCHAR(1000) NOT NULL,
    size_bytes BIGINT NOT NULL,
    format VARCHAR(50) NOT NULL,
    md5_hash VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Command Queue
CREATE TABLE command_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    command_type VARCHAR(100) NOT NULL,
    parameters JSONB NOT NULL,
    priority VARCHAR(50) DEFAULT 'normal',
    status VARCHAR(50) DEFAULT 'pending',
    ttl TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_at TIMESTAMP,
    completed_at TIMESTAMP,
    result_message TEXT,
    retry_count INTEGER DEFAULT 0
);

-- Analysis Tasks
CREATE TABLE analysis_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    disk_image_id UUID REFERENCES disk_images(id) ON DELETE SET NULL,
    task_name VARCHAR(255) NOT NULL,
    analysis_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'created',
    progress INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

-- Analysis Results
CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    result_type VARCHAR(100) NOT NULL,
    file_path VARCHAR(1000),
    file_size BIGINT,
    storage_location VARCHAR(500),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- LLM Analysis
CREATE TABLE llm_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

-- Task History (Audit)
CREATE TABLE task_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Registration Tokens
CREATE TABLE registration_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    max_clients INTEGER DEFAULT 10,
    used_count INTEGER DEFAULT 0,
    expires_at TIMESTAMP NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_clients_org_status ON clients(org_id, status);
CREATE INDEX idx_command_queue_client_status ON command_queue(client_id, status, ttl);
CREATE INDEX idx_analysis_tasks_org_status ON analysis_tasks(org_id, status);
CREATE INDEX idx_analysis_results_task ON analysis_results(task_id);
CREATE INDEX idx_disk_images_client ON disk_images(client_id);
```

### Client-Side SQLite Schema

```sql
-- Local Task Queue
CREATE TABLE local_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_command_id VARCHAR(255) UNIQUE,
    command_type VARCHAR(100) NOT NULL,
    parameters TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

-- Poll Status
CREATE TABLE poll_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN,
    response_time_ms INTEGER,
    error_message TEXT
);

-- Credentials
CREATE TABLE credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id VARCHAR(255) NOT NULL,
    jwt_token TEXT NOT NULL,
    server_url VARCHAR(500) NOT NULL,
    poll_interval INTEGER DEFAULT 10
);
```

---

## Deployment Architecture

### Cloud Server Infrastructure

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloud Infrastructure                     │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              Load Balancer (HTTPS)                    │ │
│  └──────────────────────────────────────────────────────┘ │
│                           │                                  │
│         ┌─────────────────┼─────────────────┐              │
│         ▼                 ▼                 ▼              │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐         │
│  │ Web UI   │      │ Python   │      │ Python   │         │
│  │ (React)  │      │ FastAPI  │      │ FastAPI  │         │
│  └──────────┘      └──────────┘      └──────────┘         │
│                           │                                  │
│         ┌─────────────────┼─────────────────┐              │
│         ▼                 ▼                 ▼              │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐         │
│  │Primary   │      │ Replica  │      │ Redis   │         │
│  │PostgreSQL│      │PostgreSQL│      │ Cache   │         │
│  └──────────┘      └──────────┘      └──────────┘         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │           Object Storage (S3/OSS)                    │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Local Client Deployment

```
┌─────────────────────────────────────────────────────────────┐
│                  Local Forensic Station                      │
│  ┌──────────────────────────────────────────────────────┐ │
│  │           C++ Forensic Analyzer                        │ │
│  │           (Systemd/Docker Service)                     │ │
│  └──────────────────────────────────────────────────────┘ │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │           HTTP Agent Service                          │ │
│  │           (Systemd/Docker Service)                     │ │
│  └──────────────────────────────────────────────────────┘ │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │           Local Storage                               │ │
│  │  • Raw Images (/evidence/images)                       │ │
│  │  • Analysis DBs (/evidence/analysis)                  │ │
│  │  • Agent State (/var/lib/tracelens)                    │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Scalability

**Server Side:**
- Horizontal scaling: Add FastAPI instances
- Database: Read replicas for queries
- Storage: Object storage unlimited

**Client Side:**
- Vertical scaling for faster analysis
- Configurable concurrent tasks (default: 2)
- Upload throttling

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)

**Server:**
- PostgreSQL database setup
- Authentication service (JWT)
- Organization/user management APIs
- Client registration flow
- Basic FastAPI structure

**Client:**
- Extract HTTP agent code
- Implement polling mechanism
- Build JWT authentication
- Create local task queue (SQLite)
- Implement registration flow

**Deliverable:** Clients can register and poll for commands

### Phase 2: Command Queue (Weeks 5-6)

**Server:**
- Command queue API
- Task orchestrator service
- Task management APIs
- TTL handling

**Client:**
- Command execution engine
- C++ analyzer integration
- Status reporting
- Result upload

**Deliverable:** Full command execution flow working

### Phase 3: Analysis Integration (Weeks 7-8)

**Server:**
- LLM service integration
- Result aggregation
- Image catalog API
- Analysis result APIs

**Client:**
- Disk image analysis integration
- Text extraction for LLM
- File extraction
- Progress reporting

**Deliverable:** Complete analysis workflow end-to-end

### Phase 4: Web UI Enhancement (Weeks 9-10)

**Web UI:**
- Client management dashboard
- Multi-client task assignment
- Organization administration
- Real-time task monitoring
- Cross-client search

**Deliverable:** Full user interface for C/S operations

### Phase 5: Security & Hardening (Weeks 11-12)

**All:**
- Implement RBAC fully
- Add rate limiting
- Security audit
- Audit logging
- Data retention policies

**Deliverable:** Production-ready security

### Phase 6: Production Readiness (Weeks 13-14)

**Operations:**
- Monitoring and alerting
- Health checks
- Performance metrics
- Deployment automation
- Documentation

**Deliverable:** Production deployment

---

## Testing Strategy

### Unit Testing

**Server:**
- API endpoint tests (pytest)
- Database model tests
- Authentication/authorization tests
- Command queue logic tests

**Client:**
- Polling mechanism tests
- Local queue tests
- Command execution tests
- Retry logic tests

### Integration Testing

**Scenarios:**
- Client registration flow
- Command polling and execution
- Result upload
- Network failures
- Offline/online transitions

### End-to-End Testing

**Workflows:**
- Create task → Execute → Results available
- Multi-client distribution
- Offline client handling
- Task expiration
- LLM integration

### Performance Testing

**Load Tests:**
- 100 concurrent clients
- 1000 queued tasks
- Large file uploads (1GB+)
- Database query performance

### Security Testing

**Areas:**
- JWT validation
- RBAC verification
- SQL injection prevention
- XSS protection
- File upload validation

---

## Monitoring & Operations

### Metrics

**Server:**
- API response times
- Command queue depth
- Active/online clients ratio
- Task completion rates
- Database connection pool usage
- LLM API latency and costs

**Client:**
- Poll success rate
- Task execution time
- Upload success rate
- Disk/CPU/memory usage

### Alerting

**Critical:**
- Server downtime (>5 min)
- Database failures
- >50% clients offline
- Queue depth >1000
- API error rate >5%

**Warning:**
- Single client offline >1 hour
- Task failure rate >10%
- Disk space >80%
- API latency >2s

### Logging

**Server:**
- Structured JSON logging
- Centralized aggregation (ELK/Loki)
- 90-day retention

**Client:**
- Local log files
- Critical errors uploaded
- Debug logs local only

---

## Appendix

### Glossary

- **Client**: Local forensic workstation running C++ analyzer + HTTP agent
- **Server**: Cloud-based FastAPI service + PostgreSQL + Web UI
- **Command**: Task instruction queued for client execution
- **Task**: User-initiated analysis job
- **JWT**: JSON Web Token for authentication
- **TTL**: Time-to-live for command expiration
- **LLM**: Large Language Model for AI-powered analysis

### References

- Current TraceLens architecture: [docs/architecture/Overview.md](../architecture/Overview.md)
- C++ REST API: [docs/api_reference/CPP_REST_API.md](../api_reference/CPP_REST_API.md)
- Python REST API: [docs/api_reference/Python_REST_API.md](../api_reference/Python_REST_API.md)

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-15 | Claude | Initial design specification |

---

**Approval Status:** Awaiting User Review
