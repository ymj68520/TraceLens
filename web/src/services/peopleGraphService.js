import { pythonApi } from './api';

const root = '/api/graphiti/people-analysis/runs';
export const listPeopleRuns = taskId => pythonApi.get(root, { params: { task_id: taskId } });
export const startPeopleRun = body => pythonApi.post(root, body);
export const getPeopleRun = (taskId, runId) => pythonApi.get(`${root}/${encodeURIComponent(runId)}`, { params: { task_id: taskId } });
export const getPeopleGraph = (taskId, runId, filters) => pythonApi.get(`${root}/${encodeURIComponent(runId)}/graph`, { params: { task_id: taskId, ...filters } });
export const getPeopleTarget = (taskId, runId, targetId) => pythonApi.get(`${root}/${encodeURIComponent(runId)}/targets/${encodeURIComponent(targetId)}`, { params: { task_id: taskId } });
export const reviewPeopleIdentity = (taskId, runId, body) => pythonApi.post(`${root}/${encodeURIComponent(runId)}/identity/review`, body, { params: { task_id: taskId } });
export const cancelPeopleRun = (taskId, runId) => pythonApi.post(`${root}/${encodeURIComponent(runId)}/cancel`, {}, { params: { task_id: taskId } });
