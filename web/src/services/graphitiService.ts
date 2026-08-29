/**
 * Graphiti knowledge-graph service (task-scoped) — Python sidecar (:8090).
 * Every task gets its own graph namespace.
 */
import { pythonApi } from './api';

export const ingestTaskData = (taskId: string, options: { includeLLMDescriptions?: boolean; batchSize?: number } = {}) =>
  pythonApi.post('/api/graphiti/ingest', {
    task_id: taskId,
    include_llm_descriptions: options.includeLLMDescriptions !== false,
    batch_size: options.batchSize || 50,
  });

export const searchGraph = (query: string, taskId: string, options: {
  entityTypes?: string[];
  limit?: number;
  includeRelationships?: boolean;
} = {}) =>
  pythonApi.post('/api/graphiti/search', {
    query,
    task_id: taskId,
    entity_types: options.entityTypes,
    limit: options.limit || 100,
    include_relationships: options.includeRelationships !== false,
  });

export const listEntities = (taskId: string, params: { entityType?: string; page?: number; pageSize?: number } = {}) =>
  pythonApi.get('/api/graphiti/entities', {
    params: {
      task_id: taskId,
      entity_type: params.entityType,
      page: params.page || 1,
      page_size: params.pageSize || 50,
    },
  });

export const listRelationships = (taskId: string, params: {
  relationshipType?: string;
  sourceId?: string;
  targetId?: string;
  page?: number;
  pageSize?: number;
} = {}) =>
  pythonApi.get('/api/graphiti/relationships', {
    params: {
      task_id: taskId,
      relationship_type: params.relationshipType,
      source_id: params.sourceId,
      target_id: params.targetId,
      page: params.page || 1,
      page_size: params.pageSize || 50,
    },
  });

export const getGraphitiStatus = (taskId: string | null = null) =>
  pythonApi.get('/api/graphiti/status', { params: taskId ? { task_id: taskId } : {} });

export const listTaskGraphs = () => pythonApi.get('/api/graphiti/tasks');

export const deleteTaskGraph = (taskId: string) =>
  pythonApi.delete(`/api/graphiti/tasks/${taskId}`);

export const getJobStatus = (jobId: string) =>
  pythonApi.get(`/api/graphiti/jobs/${jobId}`);

export const reingestAnalyzedData = (taskId: string) =>
  pythonApi.post('/api/graphiti/ingest', { task_id: taskId, mode: 'analyzed_only' });

export const getGraphData = (taskId: string, maxNodes = 200) =>
  pythonApi.get('/api/graphiti/graph', { params: { task_id: taskId, max_nodes: maxNodes } });
