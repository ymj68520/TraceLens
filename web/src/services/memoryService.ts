import api from './api';

/** Memory forensics — C++ backend under /api/forensics/memory/*. */

export const getMemorySummary = (taskId: string) =>
  api.get('/api/forensics/memory/summary', { params: { task_id: taskId } });

export const getMemoryProcesses = (taskId: string, search = '') =>
  api.get('/api/forensics/memory/processes', { params: { task_id: taskId, search } });

export const getMemoryNetwork = (taskId: string) =>
  api.get('/api/forensics/memory/network', { params: { task_id: taskId } });

export const getMemoryBashHistory = (taskId: string, keyword = '') =>
  api.get('/api/forensics/memory/bash-history', { params: { task_id: taskId, keyword } });

export const getMemoryBootInfo = (taskId: string) =>
  api.get('/api/forensics/memory/boot-info', { params: { task_id: taskId } });
