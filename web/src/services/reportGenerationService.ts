/**
 * Report generation / narrative viewer (R2d).
 *
 * Client contract, per R2c freeze:
 *  - POST /api/reports/generate body is task_id + requested_by only; evidence
 *    sets, analysis bindings, prompt/model versions are frozen server-side.
 *  - GET /api/reports/generations/{generation_id} polls by exact id (task_id
 *    as a scope check) — never a "latest" fallback.
 *  - GET /api/reports/narrative/versions/{report_id} reads a published
 *    narrative version with its persisted citation manifest.
 */
import { pythonApi } from './api';

export const generateReport = (taskId: string, { requestedBy }: { requestedBy?: string } = {}) =>
  pythonApi.post('/api/reports/generate', {
    task_id: taskId,
    requested_by: requestedBy,
  });

export const getReportGeneration = (taskId: string, generationId: string) =>
  pythonApi.get(`/api/reports/generations/${encodeURIComponent(generationId)}`, {
    params: { task_id: taskId },
  });

export const getNarrativeReport = (taskId: string, reportId: string) =>
  pythonApi.get(`/api/reports/narrative/versions/${encodeURIComponent(reportId)}`, {
    params: { task_id: taskId },
  });
