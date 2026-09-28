import { pythonApi } from './api';
import { PYTHON_API_BASE_URL } from '../config/runtime';

const BASE = '/api/android-report/imports';

export const listAndroidReportCandidates = () => pythonApi.get('/api/android-report/candidates');

export const createAndroidReportImportFromCandidate = (candidateId) =>
  pythonApi.post(BASE, { candidate_id: candidateId });

export const listAndroidReportImports = (taskId) =>
  pythonApi.get(BASE, { params: taskId ? { task_id: taskId } : {} });

export const attachAndroidReportToTask = (importId, taskId) =>
  pythonApi.post(`${BASE}/${encodeURIComponent(importId)}/tasks`, { task_id: taskId });

export const detachAndroidReportFromTask = (importId, taskId) =>
  pythonApi.delete(`${BASE}/${encodeURIComponent(importId)}/tasks/${encodeURIComponent(taskId)}`);

export const getAndroidReportOverview = (importId) =>
  pythonApi.get(`${BASE}/${encodeURIComponent(importId)}/overview`);

export const getAndroidReportManifest = (importId) =>
  pythonApi.get(`${BASE}/${encodeURIComponent(importId)}/manifest`);

export const getAndroidReportCoverage = (importId) =>
  pythonApi.get(`${BASE}/${encodeURIComponent(importId)}/coverage`);

export const getAndroidReportRecords = (importId, params = {}) =>
  pythonApi.get(`${BASE}/${encodeURIComponent(importId)}/records`, { params });

export const getAndroidReportRecord = (importId, recordId) =>
  pythonApi.get(`${BASE}/${encodeURIComponent(importId)}/records/${encodeURIComponent(recordId)}`);

export const androidReportSourceUrl = (importId, sourceFile) =>
  `${PYTHON_API_BASE_URL.replace(/\/$/, '')}${BASE}/${encodeURIComponent(importId)}/source-page?path=${encodeURIComponent(sourceFile)}`;

export const androidReportSourceLocationUrl = (importId, recordId) =>
  `${PYTHON_API_BASE_URL.replace(/\/$/, '')}${BASE}/${encodeURIComponent(importId)}/source-location/${encodeURIComponent(recordId)}#source-row`;

export const androidReportAttachmentUrl = (importId, path) =>
  `${PYTHON_API_BASE_URL.replace(/\/$/, '')}${BASE}/${encodeURIComponent(importId)}/attachment?path=${encodeURIComponent(path)}`;
