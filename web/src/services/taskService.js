import api from './api';

export const fetchTasks = async (params = {}) => {
  return await api.get('/api/tasks', { params });
};

export const fetchTaskById = async (taskId) => {
  return await api.get(`/api/tasks/${taskId}`);
};

export const listTasks = async (params = {}) => {
  return await api.get('/api/tasks', { params });
};

export const getTaskProgress = async (taskId) => {
  return await api.get(`/api/tasks/${taskId}/progress`);
};

export const getTaskResults = async (taskId) => {
  return await api.get(`/api/tasks/${taskId}/results`);
};

export const cancelTask = async (taskId, reason = '') => {
  return await api.delete(`/api/tasks/${taskId}`, { data: { reason } });
};

export const deleteTask = async (taskId) => {
  return await api.delete(`/api/tasks/${taskId}`);
};

export const getTaskStatistics = async () => {
  return await api.get('/api/tasks/statistics');
};

export const batchCreateTasks = async (imagePaths, options = {}) => {
  return await api.post('/api/tasks/batch-create', {
    image_paths: imagePaths,
    ...options,
  });
};

export const batchGetTaskStatus = async (taskIds) => {
  return await api.post('/api/tasks/batch-status', { task_ids: taskIds });
};

export const batchCancelTasks = async (taskIds) => {
  return await api.post('/api/tasks/batch-cancel', { task_ids: taskIds });
};

export const getTaskAuditLog = async (taskId, params = {}) => {
  return await api.get(`/api/tasks/${taskId}/audit-log`, { params });
};

export const updateTaskPriority = async (taskId, priority) => {
  return await api.put(`/api/tasks/${taskId}/priority`, { priority });
};

export const cleanupOldTasks = async (maxAgeHours = 24) => {
  return await api.post('/api/tasks/cleanup', { max_age_hours: maxAgeHours });
};

export const createTask = async (taskData) => {
  return await api.post('/api/tasks', taskData);
};
