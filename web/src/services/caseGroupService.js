/**
 * caseGroupService.js
 *
 * Communicates with Python service (/api/llm/cases*) and
 * multi-image analysis endpoints (/api/llm/multi-image-analysis*).
 */
import { pythonApi } from './api';

// ── Case CRUD ─────────────────────────────────────────────────────────────────

export const createCase = (name, description, taskIds = []) =>
  pythonApi.post('/api/llm/cases', { name, description, task_ids: taskIds });

export const listCases = () =>
  pythonApi.get('/api/llm/cases');

export const getCase = (caseId) =>
  pythonApi.get(`/api/llm/cases/${caseId}`);

export const addTasksToCase = (caseId, taskIds) =>
  pythonApi.post(`/api/llm/cases/${caseId}/tasks`, { task_ids: taskIds });

// ── Multi-Image Analysis ──────────────────────────────────────────────────────

/**
 * Start a cross-image LLM analysis job for a case.
 * @param {Object} opts
 * @param {string} opts.caseId
 * @param {string[]} opts.taskIds
 * @param {string[]} opts.filesDbPaths  — _files.db paths (same order as taskIds)
 * @param {string} opts.caseDescription
 * @param {number} [opts.maxFilterFiles=400]
 */
export const startMultiImageAnalysis = (opts) =>
  pythonApi.post('/api/llm/multi-image-analysis', {
    case_id:          opts.caseId,
    task_ids:         opts.taskIds,
    files_db_paths:   opts.filesDbPaths,
    case_description: opts.caseDescription,
    max_filter_files: opts.maxFilterFiles ?? 400,
  });

export const getMultiAnalysisStatus = (jobId) =>
  pythonApi.get(`/api/llm/multi-image-analysis/${jobId}`);

/**
 * Poll multi-image analysis job until completion.
 * @param {string} jobId
 * @param {Function} onProgress  — called each poll with status object
 * @param {number} [interval=5000]
 */
export const pollMultiAnalysis = (jobId, onProgress, interval = 5000) =>
  new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const status = await getMultiAnalysisStatus(jobId);
        if (onProgress) onProgress(status);
        if (status.status === 'completed') return resolve(status);
        if (status.status === 'failed')    return reject(new Error(status.error || '跨镜像分析失败'));
        setTimeout(tick, interval);
      } catch (err) {
        reject(err);
      }
    };
    tick();
  });

export default {
  createCase, listCases, getCase, addTasksToCase,
  startMultiImageAnalysis, getMultiAnalysisStatus, pollMultiAnalysis,
};
