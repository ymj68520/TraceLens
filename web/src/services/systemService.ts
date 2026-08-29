import api, { pythonApi } from './api';

export const getSystemHealth = () => api.get('/api/system/health');
export const getSystemInfo = () => api.get('/api/system/info');

export const getDatabases = (params: Record<string, unknown> = {}) =>
  api.get('/api/system/databases', { params });

export const getDatabaseSchema = (type: string) =>
  api.get(`/api/system/database-schema/${type}`);

export const getEndpoints = () => api.get('/api/docs/endpoints');
export const getDatabaseSchemaDocs = () => api.get('/api/docs/database-schema');

export const exportResults = (taskId: string, format = 'json') =>
  api.post(`/api/export/${taskId}`, { format });

/** K8s-style health checks */
export const getHealthDependencies = () => api.get('/api/health/dependencies');
export const getLivenessCheck = () => api.get('/api/health/live');

/** Python sidecar */
export const getPythonHealth = () => pythonApi.get('/health');
export const getRedisStatus = () => pythonApi.get('/api/system/redis/status');

/** TOON data export */
export const exportToon = (taskId: string) =>
  api.post('/api/forensics/export/toon', { task_id: taskId });
