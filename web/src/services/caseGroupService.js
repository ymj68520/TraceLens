/**
 * caseGroupService.js
 *
 * Case metadata belongs to the authenticated C++ /api/cases source of truth.
 * Only actual optional AI analysis/report calls use Python /api/llm/*.
 */
import api, { pythonApi } from './api';
import { FIELD_AUTH_ENABLED } from '../config/runtime';

const casePath = (caseId) => `/api/cases/${encodeURIComponent(caseId)}`;

// ── Case CRUD ─────────────────────────────────────────────────────────────────

export const createCase = (name, description, taskIds = []) =>
  api.post('/api/cases', { name, description, task_ids: taskIds });

export const listCases = () =>
  api.get('/api/cases');

export const getCase = (caseId) =>
  api.get(casePath(caseId));

export const addTasksToCase = async (caseId, taskIds) => {
  const result = await api.put(`${casePath(caseId)}/tasks`, { task_ids: [...new Set(taskIds)] });
  if (result?.id !== caseId || !Array.isArray(result.task_ids)
      || taskIds.some((id) => !result.task_ids.includes(id))) {
    throw new Error('案件任务关联未确认，请刷新后重试');
  }
  return result;
};

/**
 * Associate completed task IDs without starting analysis or changing any
 * evidence/result database. This is metadata, not preparation of AI reuse rows.
 *
 * @param {string} caseId
 * @param {string[]} taskIds
 * @returns {Promise<{associated, reused, pending_analysis, skipped, not_found, not_completed}>}
 */
export const associateTasksToCase = async (caseId, taskIds) => {
  if (!Array.isArray(taskIds) || !taskIds.length || taskIds.some((id) => typeof id !== 'string' || !id)) {
    throw new Error('请选择有效的已完成任务');
  }
  const current = await getCase(caseId);
  if (current?.id !== caseId || !Array.isArray(current.task_ids)) throw new Error('案件不存在或无法读取');
  const result = { case_id: caseId, associated: [], reused: [], pending_analysis: [], skipped: [],
    not_found: [], not_completed: [], analysis_state_prepared: false };
  const existing = new Set(current.task_ids);
  for (const id of [...new Set(taskIds)]) {
    if (existing.has(id)) { result.skipped.push(id); continue; }
    let task;
    try { task = await api.get(`/api/tasks/${encodeURIComponent(id)}`); }
    catch (error) {
      if ((error?.status ?? error?.response?.status) === 404) { result.not_found.push(id); continue; }
      throw error; // permissions/network failures are not an empty task list
    }
    if (task?.id !== id) throw new Error('任务身份校验失败');
    if (String(task.status).toLowerCase() !== 'completed' || !task.output_files_db) {
      result.not_completed.push(id); continue;
    }
    result.associated.push(id);
  }
  if (result.associated.length) await addTasksToCase(caseId, result.associated);
  return result;
};

// Creating a new image task must respect the active field model policy. It is
// never a reason to re-enable cloud calls just to make case metadata work.
export const caseTaskAnalysisOptions = async () => {
  if (!FIELD_AUTH_ENABLED) return { llm_analyze: true, llm_event_analyze: false };
  const policy = await pythonApi.get('/api/field-auth/status');
  if (!policy?.field_auth || !['disabled', 'local_only'].includes(policy.outbound_policy)) {
    throw new Error('无法确认当前分析配置，未创建新任务');
  }
  return { llm_analyze: policy.outbound_policy !== 'disabled', llm_event_analyze: false };
};

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
 * Get the cross-image case report persisted to the case-level database.
 * Use this when the context is a ForensicCase (case_id), not a single task.
 * @param {string} caseId
 */
export const getCaseReportByCase = (caseId) =>
  pythonApi.get(`/api/llm/case-report-by-case/${caseId}`);

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

export const deleteCase = (caseId) =>
  api.delete(casePath(caseId)); // case record only; tasks and analysis outputs stay

/**
 * Persist a case status transition to the C++ record (single source of truth
 * for the card state). Used to reconcile cases stuck in ANALYSING when the
 * cross-image job is lost (e.g. Python service restart dropped the registry).
 * @param {string} caseId
 * @param {'open'|'analysing'|'completed'|'failed'} status
 */
export const persistCaseStatus = (caseId, status) =>
  api.put(`/api/cases/${caseId}/status`, { status });

export default {
  createCase, listCases, getCase, addTasksToCase, associateTasksToCase, deleteCase,
  startMultiImageAnalysis, getMultiAnalysisStatus, pollMultiAnalysis,
  getCaseReportByCase,
};
