import api from './api';

// Memory forensics API service.
// Wraps the C++ backend endpoints under /api/forensics/memory/*.

export const getMemorySummary = (taskId) =>
  api.get('/api/forensics/memory/summary', { params: { task_id: taskId } });

export const getMemoryProcesses = (taskId, search = '') =>
  api.get('/api/forensics/memory/processes', {
    params: { task_id: taskId, search },
  });

export const getMemoryNetwork = (taskId) =>
  api.get('/api/forensics/memory/network', { params: { task_id: taskId } });

export const getMemoryBashHistory = (taskId, keyword = '') =>
  api.get('/api/forensics/memory/bash-history', {
    params: { task_id: taskId, keyword },
  });

export const getMemoryBootInfo = (taskId) =>
  api.get('/api/forensics/memory/boot-info', { params: { task_id: taskId } });
