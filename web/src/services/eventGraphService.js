import { pythonApi } from './api';

const root = '/api/graphiti';
export const getEventView = (taskId, filters) => pythonApi.get(`${root}/event-views`, { params: { task_id: taskId, ...filters } });
export const getEventDetail = (taskId, targetId, sourceVersion) => pythonApi.get(`${root}/event-views/detail`, { params: { task_id: taskId, target_id: targetId, source_version: sourceVersion } });
export const listEventRuns = taskId => pythonApi.get(`${root}/event-analysis/runs`, { params: { task_id: taskId } });
export const startEventRun = body => pythonApi.post(`${root}/event-analysis/runs`, body);
export const getEventRun = (taskId, runId) => pythonApi.get(`${root}/event-analysis/runs/${encodeURIComponent(runId)}`, { params: { task_id: taskId } });
export const getEventRunGraph = (taskId, runId, filters) => pythonApi.get(`${root}/event-analysis/runs/${encodeURIComponent(runId)}/graph`, { params: { task_id: taskId, ...filters } });
export const getEventRunDetail = (taskId, runId, targetId) => pythonApi.get(`${root}/event-analysis/runs/${encodeURIComponent(runId)}/detail`, { params: { task_id: taskId, target_id: targetId } });
export const cancelEventRun = (taskId, runId) => pythonApi.post(`${root}/event-analysis/runs/${encodeURIComponent(runId)}/cancel`, {}, { params: { task_id: taskId } });
