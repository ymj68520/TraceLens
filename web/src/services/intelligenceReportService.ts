/** Intelligence report reader (证据研判) — Python sidecar. */
import { pythonApi } from './api';

export const getIntelligenceReport = (taskId: string) =>
  pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}`);

export const getIntelligenceRecords = (taskId: string, category: string, page = 1, pageSize = 50) =>
  pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/records`, {
    params: { category, page, page_size: pageSize },
  });

export const searchIntelligenceReport = (taskId: string, query: string, offset = 0, limit = 50) =>
  pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/search`, {
    params: { q: query, offset, limit },
  });

export const getReportMetadata = (taskId: string) =>
  pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/metadata`);

export const saveReportMetadata = (taskId: string, payload: Record<string, unknown>) =>
  pythonApi.put(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/metadata`, payload);
