-- Migration 002: promote the task_id soft link (parameters->>'task_id') to a
-- real FK column with referential integrity and cascade delete.
-- Idempotent: safe to re-run.

ALTER TABLE command_queue
    ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES analysis_tasks(id) ON DELETE CASCADE;

-- Backfill from the existing JSONB soft link for in-flight rows.
UPDATE command_queue
   SET task_id = (parameters->>'task_id')::uuid
 WHERE task_id IS NULL
   AND parameters ? 'task_id'
   AND parameters->>'task_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

CREATE INDEX IF NOT EXISTS idx_command_queue_task ON command_queue(task_id);
