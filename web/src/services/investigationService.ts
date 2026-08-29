/**
 * Investigation workbench service — Python sidecar (:8090).
 *
 * Covers the frozen contracts: C3 evidence snapshots, C4b-2/C6 secondary
 * analyses + review, C7a-C7c investigation events, C8b graph, R1 report
 * evidence bindings, and the C9b+ workbench surface.
 */
import { pythonApi } from './api';

// ── Evidence snapshots & secondary analysis (C3 / C4b-2 / C6) ───────────────

export const captureInvestigationSnapshot = (taskId: string, evidenceKey: string) =>
  pythonApi.post('/api/investigation/snapshots', {
    task_id: taskId,
    evidence_key: evidenceKey,
  });

export const getInvestigationGraph = (taskId: string, { maxBaseNodes = 200 } = {}) =>
  pythonApi.get('/api/investigation/graph', {
    params: { task_id: taskId, max_base_nodes: maxBaseNodes },
  });

export const listInvestigationEvidence = (taskId: string) =>
  pythonApi.get('/api/investigation/evidence', { params: { task_id: taskId } });

/** Read-only snapshot fetch — never auto-captures, never falls back to files.db. */
export const getInvestigationSnapshot = (taskId: string, evidenceKey: string) =>
  pythonApi.get('/api/investigation/evidence/snapshot', {
    params: { task_id: taskId, evidence_key: evidenceKey },
  });

export const listInvestigationAnalyses = (taskId: string, evidenceKey: string) =>
  pythonApi.get('/api/investigation/analyses', {
    params: { task_id: taskId, evidence_key: evidenceKey },
  });

export const getInvestigationAnalysis = (taskId: string, analysisId: string) =>
  pythonApi.get(`/api/investigation/analyses/${encodeURIComponent(analysisId)}`, {
    params: { task_id: taskId },
  });

/**
 * Submit a secondary analysis (202 admission). The returned analysis_id is
 * the only polling identity — no "latest" fallback.
 */
export const createSecondaryAnalysis = (
  taskId: string,
  evidenceKey: string,
  {
    analystNote = null,
    caseContext = null,
    relatedEvidence = [],
  }: {
    analystNote?: string | null;
    caseContext?: string | null;
    relatedEvidence?: string[];
  } = {},
) =>
  pythonApi.post('/api/investigation/analyses', {
    task_id: taskId,
    evidence_key: evidenceKey,
    analyst_note: analystNote,
    case_context: caseContext,
    related_evidence: relatedEvidence,
  });

export const listInvestigationAnalysisClaims = (taskId: string, analysisId: string) =>
  pythonApi.get(`/api/investigation/analyses/${encodeURIComponent(analysisId)}/claims`, {
    params: { task_id: taskId },
  });

/** Record a terminal analyst decision on an exact analysis version. */
export const reviewSecondaryAnalysis = (
  taskId: string,
  analysisId: string,
  { decision, reviewer, reason = null }: { decision: string; reviewer: string; reason?: string | null },
) =>
  pythonApi.post(`/api/investigation/analyses/${encodeURIComponent(analysisId)}/review`, {
    task_id: taskId,
    decision,
    reviewer,
    reason,
  });

// ── Investigation events (C7a–C7c) ──────────────────────────────────────────

export const listInvestigationEvents = (taskId: string) =>
  pythonApi.get('/api/investigation/events', { params: { task_id: taskId } });

export const getInvestigationEvent = (taskId: string, eventId: string) =>
  pythonApi.get(`/api/investigation/events/${encodeURIComponent(eventId)}`, {
    params: { task_id: taskId },
  });

export const listInvestigationEventVersions = (taskId: string, eventId: string) =>
  pythonApi.get(`/api/investigation/events/${encodeURIComponent(eventId)}/versions`, {
    params: { task_id: taskId },
  });

export const listInvestigationEventEvidence = (taskId: string, eventId: string) =>
  pythonApi.get(`/api/investigation/events/${encodeURIComponent(eventId)}/evidence`, {
    params: { task_id: taskId },
  });

export const listInvestigationEventRefreshes = (taskId: string, eventId: string) =>
  pythonApi.get(`/api/investigation/events/${encodeURIComponent(eventId)}/refreshes`, {
    params: { task_id: taskId },
  });

export const createInvestigationEvent = (
  taskId: string,
  { title, summary = null, createdBy }: { title: string; summary?: string | null; createdBy: string },
) =>
  pythonApi.post('/api/investigation/events', {
    task_id: taskId,
    title,
    summary,
    created_by: createdBy,
  });

/** Append-only event→evidence link. No unlink by design. */
export const linkInvestigationEventEvidence = (
  taskId: string,
  eventId: string,
  evidenceKey: string,
  { linkedBy }: { linkedBy: string },
) =>
  pythonApi.post(`/api/investigation/events/${encodeURIComponent(eventId)}/evidence`, {
    task_id: taskId,
    evidence_key: evidenceKey,
    linked_by: linkedBy,
  });

/** Fire an event narrative refresh (admission only — doesn't wait for LLM). */
export const startInvestigationEventRefresh = (
  taskId: string,
  eventId: string,
  { requestedBy }: { requestedBy: string },
) =>
  pythonApi.post(`/api/investigation/events/${encodeURIComponent(eventId)}/refresh`, {
    task_id: taskId,
    requested_by: requestedBy,
  });

// ── Report evidence (R1) ────────────────────────────────────────────────────

export const listReportEvidence = (taskId: string) =>
  pythonApi.get('/api/reports/evidence', { params: { task_id: taskId } });

export const addReportEvidence = (
  taskId: string,
  evidenceKey: string,
  {
    reportStatus,
    analysisId = null,
    addedBy,
  }: { reportStatus: string; analysisId?: string | null; addedBy: string },
) =>
  pythonApi.post('/api/reports/evidence', {
    task_id: taskId,
    evidence_key: evidenceKey,
    report_status: reportStatus,
    analysis_id: analysisId,
    added_by: addedBy,
  });

/**
 * Update report evidence status or the frozen analysis binding.
 * Omitted analysisId keeps the current binding — no implicit unbind.
 */
export const updateReportEvidence = (
  taskId: string,
  evidenceKey: string,
  {
    reportStatus = null,
    analysisId,
    updatedBy,
  }: { reportStatus?: string | null; analysisId?: string | null; updatedBy: string },
) =>
  pythonApi.put('/api/reports/evidence', {
    task_id: taskId,
    evidence_key: evidenceKey,
    report_status: reportStatus,
    ...(analysisId !== undefined ? { analysis_id: analysisId } : {}),
    updated_by: updatedBy,
  });

// ── Workbench surface (C9b+) ────────────────────────────────────────────────

const workbenchBase = (taskId: string) =>
  `/api/investigation/workbench/${encodeURIComponent(taskId)}`;

export const getOverview = (taskId: string) => pythonApi.get(workbenchBase(taskId));

export const bootstrapInvestigation = (taskId: string, options: Record<string, unknown> = {}) =>
  pythonApi.post(`${workbenchBase(taskId)}/bootstrap`, { mode: 'cluster_seed', ...options });

export const getInvestigationEvents = (taskId: string, params: Record<string, unknown> = {}) =>
  pythonApi.get(`${workbenchBase(taskId)}/events`, { params });

export const getEventEvidence = (taskId: string, eventId: string, params: Record<string, unknown> = {}) =>
  pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/evidence`, { params });

export const linkEventEvidence = (taskId: string, eventId: string, payload: Record<string, unknown>) =>
  pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/evidence/link`, payload);

export const getEvidenceDetail = (taskId: string, evidenceKey: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/evidence/detail`, { params: { evidence_key: evidenceKey } });

export const getAnalystNote = (taskId: string, targetType: string, targetKey: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/notes`, {
    params: { target_type: targetType, target_key: targetKey },
  });

export const saveAnalystNote = (
  taskId: string,
  targetType: string,
  targetKey: string,
  content: string,
  author: string | null = null,
) =>
  pythonApi.post(`${workbenchBase(taskId)}/notes`, {
    target_type: targetType,
    target_key: targetKey,
    content,
    author,
  });

export const startEvidenceAnalysis = (taskId: string, payload: Record<string, unknown>) =>
  pythonApi.post(`${workbenchBase(taskId)}/evidence/analyze`, payload);

export const getAnalysisJob = (taskId: string, jobId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/analysis-jobs/${encodeURIComponent(jobId)}`);

export const getAnalysisVersions = (taskId: string, evidenceKey: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/evidence/analysis`, {
    params: { evidence_key: evidenceKey },
  });

export const acceptAnalysis = (taskId: string, analysisId: string, acknowledgeWarnings = false) =>
  pythonApi.post(`${workbenchBase(taskId)}/analysis/${encodeURIComponent(analysisId)}/accept`, {
    acknowledge_warnings: acknowledgeWarnings,
  });

export const rejectAnalysis = (taskId: string, analysisId: string) =>
  pythonApi.post(`${workbenchBase(taskId)}/analysis/${encodeURIComponent(analysisId)}/reject`);

export const refreshInvestigationEvent = (taskId: string, eventId: string, payload: Record<string, unknown> = {}) =>
  pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/refresh`, payload);

export const getEventSemanticVersions = (taskId: string, eventId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions`);

export const acceptEventSemanticVersion = (taskId: string, eventId: string, versionId: string) =>
  pythonApi.post(
    `${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/accept`,
  );

export const rejectEventSemanticVersion = (taskId: string, eventId: string, versionId: string) =>
  pythonApi.post(
    `${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/reject`,
  );

export const getEventClaims = (taskId: string, eventId: string, versionId: string) =>
  pythonApi.get(
    `${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/claims`,
  );

export const acceptEventClaim = (taskId: string, eventId: string, versionId: string, claimId: string) =>
  pythonApi.post(
    `${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/claims/${encodeURIComponent(claimId)}/accept`,
  );

export const rejectEventClaim = (taskId: string, eventId: string, versionId: string, claimId: string) =>
  pythonApi.post(
    `${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/claims/${encodeURIComponent(claimId)}/reject`,
  );

export const getEffectiveEventClaims = (taskId: string, eventId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/claims/effective`);

export const reviewInvestigationEvent = (taskId: string, eventId: string, status: string) =>
  pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/review`, { status });

export const setReportEvidence = (taskId: string, payload: Record<string, unknown>) =>
  pythonApi.put(`${workbenchBase(taskId)}/report-evidence`, payload);

export const removeReportEvidence = (taskId: string, evidenceKey: string) =>
  pythonApi.post(`${workbenchBase(taskId)}/report-evidence/remove`, { evidence_key: evidenceKey });

export const getReportEvidence = (taskId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/report-evidence`);

export const getLocalGraph = (taskId: string, params: Record<string, unknown> = {}) =>
  pythonApi.get(`${workbenchBase(taskId)}/graph/local`, { params });

export const getFinalReports = (taskId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/final-reports`);

export const getFinalReport = (taskId: string, reportId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}`);

export const getFinalReportMarkdown = (taskId: string, reportId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/markdown`, {
    responseType: 'text',
  });

export const getFinalReportHtml = (taskId: string, reportId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/html`, {
    responseType: 'text',
  });

export const getFinalReportPrint = (taskId: string, reportId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/print`, {
    responseType: 'text',
  });

export const getFinalReportPublication = (taskId: string, reportId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/publication`);

export const publishFinalReport = (taskId: string, reportId: string) =>
  pythonApi.post(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/publish`);

export const getClaimProvenance = (taskId: string, claimId: string) =>
  pythonApi.get(`${workbenchBase(taskId)}/claims/${encodeURIComponent(claimId)}`);

export interface AnalysisJob {
  status: string;
  error?: string;
  [key: string]: unknown;
}

export const pollAnalysisJob = async (
  taskId: string,
  jobId: string,
  onProgress?: (job: AnalysisJob) => void,
  interval = 1500,
): Promise<AnalysisJob> => {
  const poll = async (): Promise<AnalysisJob> => {
    const response = (await getAnalysisJob(taskId, jobId)) as { job: AnalysisJob };
    const job = response.job;
    onProgress?.(job);
    if (job.status === 'completed') return job;
    if (['failed', 'invalid'].includes(job.status)) throw new Error(job.error || '二次分析失败');
    await new Promise((resolve) => setTimeout(resolve, interval));
    return poll();
  };
  return poll();
};
