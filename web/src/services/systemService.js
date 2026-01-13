import api from './api';

export const getSystemHealth = async () => {
  return await api.get('/api/system/health');
};

export const getSystemInfo = async () => {
  return await api.get('/api/system/info');
};

export const getDatabases = async (params = {}) => {
  return await api.get('/api/system/databases', { params });
};

export const getDatabaseSchema = async (type) => {
  return await api.get(`/api/system/database-schema/${type}`);
};

export const getEndpoints = async () => {
  return await api.get('/api/docs/endpoints');
};

export const getDatabaseSchemaDocs = async () => {
  return await api.get('/api/docs/database-schema');
};

export const exportResults = async (taskId, format = 'json') => {
  return await api.post(`/api/export/${taskId}`, { format });
};
