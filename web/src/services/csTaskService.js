import { csApi } from './api';

// 分布式任务生命周期 — 与本地 taskService.js (C++ :8080) 区分开
export const createDistributedTask = (taskData) => csApi.post('/api/tasks', taskData);
export const listDistributedTasks = (params = {}) => csApi.get('/api/tasks', { params });
export const getDistributedTask = (taskId) => csApi.get(`/api/tasks/${taskId}`);
export const cancelDistributedTask = (taskId) => csApi.post(`/api/tasks/${taskId}/cancel`);
