/**
 * 证据研判报告阅读器服务
 * 为 /case-intelligence 的参考报告式阅读器提供数据。
 * 与 /api/reports（结构化取证快照）和 /api/llm/case-analysis（生成器）分离。
 */
import { pythonApi } from './api';

/**
 * 获取研判报告目录与元数据
 * GET /api/llm/intelligence-report/{task_id}
 */
export const getIntelligenceReport = async (taskId) => {
  return await pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}`);
};

/**
 * 获取某分类的分页记录
 * GET /api/llm/intelligence-report/{task_id}/records?category=...&page=...&page_size=...
 */
export const getIntelligenceRecords = async (taskId, category, page = 1, pageSize = 50) => {
  return await pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/records`, {
    params: { category, page, page_size: pageSize },
  });
};

/**
 * 报告全文搜索
 * GET /api/llm/intelligence-report/{task_id}/search?q=...
 */
export const searchIntelligenceReport = async (taskId, query, offset = 0, limit = 50) => {
  return await pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/search`, {
    params: { q: query, offset, limit },
  });
};

/**
 * 获取案件信息/证据信息元数据
 * GET /api/llm/intelligence-report/{task_id}/metadata
 */
export const getReportMetadata = async (taskId) => {
  return await pythonApi.get(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/metadata`);
};

/**
 * 保存案件信息/证据信息元数据
 * PUT /api/llm/intelligence-report/{task_id}/metadata
 */
export const saveReportMetadata = async (taskId, payload) => {
  return await pythonApi.put(`/api/llm/intelligence-report/${encodeURIComponent(taskId)}/metadata`, payload);
};
