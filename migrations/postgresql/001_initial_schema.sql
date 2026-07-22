-- ============================================================================
-- TraceLens C/S Architecture - Initial PostgreSQL Schema
-- Migration: 001_initial_schema.sql
--
-- Defines the server-side multi-tenant schema: organizations, users, clients,
-- disk image catalog, command queue, analysis tasks/results, LLM analysis,
-- task history (audit log), and registration tokens.
--
-- Organization isolation is enforced at the application layer; every tenant
-- table carries org_id (directly or transitively) so row-level separation is
-- possible. Raw disk images (E01/DD) never leave the client - this schema only
-- stores their metadata/catalog entries.
-- ============================================================================

-- Enable UUID extension (required for uuid_generate_v4() defaults)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------------------------------------------------------
-- Organizations
-- ----------------------------------------------------------------------------
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settings JSONB DEFAULT '{}',
    subscription_tier VARCHAR(50) DEFAULT 'free'
);

-- ----------------------------------------------------------------------------
-- Users
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Clients (registered forensic machines)
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Disk Images Catalog (metadata only; raw images stay on the client)
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Command Queue (server -> client commands)
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Analysis Tasks
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Analysis Results
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- LLM Analysis
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Task History (Audit Log)
-- ----------------------------------------------------------------------------
CREATE TABLE task_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- Registration Tokens
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Indexes for performance
-- ----------------------------------------------------------------------------
CREATE INDEX idx_clients_org_status ON clients(org_id, status);
CREATE INDEX idx_command_queue_client_status ON command_queue(client_id, status, ttl);
CREATE INDEX idx_analysis_tasks_org_status ON analysis_tasks(org_id, status);
CREATE INDEX idx_analysis_results_task ON analysis_results(task_id);
CREATE INDEX idx_disk_images_client ON disk_images(client_id);
CREATE INDEX idx_task_history_task ON task_history(task_id);

-- ----------------------------------------------------------------------------
-- Seed data
-- NOTE: The default organization MUST be created before the super_admin user,
-- because the user row references it via org_id. (Order fixed relative to an
-- earlier draft of this migration where the inserts were reversed.)
-- ----------------------------------------------------------------------------

-- Create default organization if not exists
INSERT INTO organizations (id, name, subscription_tier)
VALUES (
    uuid_generate_v4(),
    'Default Organization',
    'enterprise'
) ON CONFLICT (name) DO NOTHING;

-- Insert default super admin (password: admin123, CHANGE IN PRODUCTION)
INSERT INTO users (id, org_id, username, email, password_hash, role)
VALUES (
    uuid_generate_v4(),
    (SELECT id FROM organizations WHERE name = 'Default Organization'),
    'super_admin',
    'super_admin@tracelens.local',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyY9wqDf11qO',
    'super_admin'
) ON CONFLICT (org_id, username) DO NOTHING;
