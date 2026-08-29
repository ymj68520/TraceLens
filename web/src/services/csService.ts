/** Distributed C/S server client (:8091). Auth token is separate from local mode. */
import { csApi } from './api';

// OAuth2 password flow: form-encoded body, NOT JSON (a JSON body 422s).
export const csLogin = (username: string, password: string) => {
  const form = new URLSearchParams();
  form.append('username', username);
  form.append('password', password);
  return csApi.post('/api/auth/login', form);
};

export const csRefresh = (token: string) =>
  csApi.post('/api/auth/refresh', {}, { headers: { Authorization: `Bearer ${token}` } });

export const csMe = () => csApi.get('/api/auth/me');

export const listClients = (params: Record<string, unknown> = {}) =>
  csApi.get('/api/clients', { params });

export const getClient = (clientId: string) => csApi.get(`/api/clients/${clientId}`);

export const createDistributedTask = (taskData: Record<string, unknown>) =>
  csApi.post('/api/tasks', taskData);

export const listDistributedTasks = (params: Record<string, unknown> = {}) =>
  csApi.get('/api/tasks', { params });

export const getDistributedTask = (taskId: string) => csApi.get(`/api/tasks/${taskId}`);

export const cancelDistributedTask = (taskId: string) =>
  csApi.post(`/api/tasks/${taskId}/cancel`);
