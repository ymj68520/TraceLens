import api from './api';
import type { ForensicTask, TaskListResponse, TaskStatistics } from '../types/api';

export interface TaskListParams {
  status?: string;
  priority?: string;
  limit?: number;
  offset?: number;
  [key: string]: unknown;
}

export interface CreateTaskPayload {
  image_path: string;
  priority?: string;
  case_description?: string;
  llm_analyze?: boolean;
  llm_mode?: string;
  android_analyze?: boolean;
  source_mode?: string;
  [key: string]: unknown;
}

export const fetchTasks = (params: TaskListParams = {}): Promise<TaskListResponse> =>
  api.get('/api/tasks', { params }) as unknown as Promise<TaskListResponse>;

export const listTasks = fetchTasks;

export const fetchTaskById = (taskId: string): Promise<ForensicTask> =>
  api.get(`/api/tasks/${taskId}`) as unknown as Promise<ForensicTask>;

export const getTaskProgress = (taskId: string) =>
  api.get(`/api/tasks/${taskId}/progress`);

export const getTaskResults = (taskId: string) =>
  api.get(`/api/tasks/${taskId}/results`);

export const cancelTask = (taskId: string, reason = '') =>
  api.delete(`/api/tasks/${taskId}`, { data: { reason } });

export const deleteTask = (taskId: string) =>
  api.delete(`/api/tasks/${taskId}`);

export const getTaskStatistics = (): Promise<TaskStatistics> =>
  api.get('/api/tasks/statistics') as unknown as Promise<TaskStatistics>;

export const createTask = (taskData: CreateTaskPayload): Promise<ForensicTask> =>
  api.post('/api/tasks', taskData) as unknown as Promise<ForensicTask>;

export const batchCreateTasks = (imagePaths: string[], options: Record<string, unknown> = {}) =>
  api.post('/api/tasks/batch-create', { image_paths: imagePaths, ...options });

export const batchGetTaskStatus = (taskIds: string[]) =>
  api.post('/api/tasks/batch-status', { task_ids: taskIds });

export const batchCancelTasks = (taskIds: string[]) =>
  api.post('/api/tasks/batch-cancel', { task_ids: taskIds });

export const getTaskAuditLog = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get(`/api/tasks/${taskId}/audit-log`, { params });

export const updateTaskPriority = (taskId: string, priority: string) =>
  api.put(`/api/tasks/${taskId}/priority`, { priority });

export const cleanupOldTasks = (maxAgeHours = 24) =>
  api.post('/api/tasks/cleanup', { max_age_hours: maxAgeHours });
