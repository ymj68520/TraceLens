import { pythonApi } from './api';

const base = (taskId) => `/api/investigation/${encodeURIComponent(taskId)}`;

export const getOverview = (taskId) => pythonApi.get(base(taskId));
export const bootstrapInvestigation = (taskId, options = {}) =>
  pythonApi.post(`${base(taskId)}/bootstrap`, { mode: 'cluster_seed', ...options });

export const getInvestigationEvents = (taskId, params = {}) =>
  pythonApi.get(`${base(taskId)}/events`, { params });
export const getInvestigationEvent = (taskId, eventId) =>
  pythonApi.get(`${base(taskId)}/events/${eventId}`);
export const reviewInvestigationEvent = (taskId, eventId, status) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/review`, { status });

export const getEventEvidence = (taskId, eventId, params = {}) =>
  pythonApi.get(`${base(taskId)}/events/${eventId}/evidence`, { params });
export const linkEventEvidence = (taskId, eventId, payload) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/evidence/link`, payload);
export const unlinkEventEvidence = (taskId, eventId, evidenceKey) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/evidence/unlink`, { evidence_key: evidenceKey });

export const getEvidenceDetail = (taskId, evidenceKey) =>
  pythonApi.get(`${base(taskId)}/evidence/detail`, { params: { evidence_key: evidenceKey } });
export const getAnalystNote = (taskId, targetType, targetKey) =>
  pythonApi.get(`${base(taskId)}/notes`, { params: { target_type: targetType, target_key: targetKey } });
export const saveAnalystNote = (taskId, targetType, targetKey, content, author = null) =>
  pythonApi.post(`${base(taskId)}/notes`, {
    target_type: targetType,
    target_key: targetKey,
    content,
    author,
  });

export const startEvidenceAnalysis = (taskId, payload) =>
  pythonApi.post(`${base(taskId)}/evidence/analyze`, payload);
export const getAnalysisJob = (taskId, jobId) =>
  pythonApi.get(`${base(taskId)}/analysis-jobs/${jobId}`);
export const getAnalysisVersions = (taskId, evidenceKey) =>
  pythonApi.get(`${base(taskId)}/evidence/analysis`, { params: { evidence_key: evidenceKey } });
export const acceptAnalysis = (taskId, analysisId, acknowledgeWarnings = false) =>
  pythonApi.post(`${base(taskId)}/analysis/${analysisId}/accept`, {
    acknowledge_warnings: acknowledgeWarnings,
  });
export const rejectAnalysis = (taskId, analysisId) =>
  pythonApi.post(`${base(taskId)}/analysis/${analysisId}/reject`);

export const refreshInvestigationEvent = (taskId, eventId, payload = {}) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/refresh`, payload);
export const getEventSemanticVersions = (taskId, eventId) =>
  pythonApi.get(`${base(taskId)}/events/${eventId}/versions`);
export const acceptEventSemanticVersion = (taskId, eventId, versionId) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/versions/${versionId}/accept`);
export const rejectEventSemanticVersion = (taskId, eventId, versionId) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/versions/${versionId}/reject`);
export const getEventClaims = (taskId, eventId, versionId) =>
  pythonApi.get(`${base(taskId)}/events/${eventId}/versions/${versionId}/claims`);
export const acceptEventClaim = (taskId, eventId, versionId, claimId) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/versions/${versionId}/claims/${claimId}/accept`);
export const rejectEventClaim = (taskId, eventId, versionId, claimId) =>
  pythonApi.post(`${base(taskId)}/events/${eventId}/versions/${versionId}/claims/${claimId}/reject`);
export const getEffectiveEventClaims = (taskId, eventId) =>
  pythonApi.get(`${base(taskId)}/events/${eventId}/claims/effective`);

export const getClaimProvenance = (taskId, claimId) =>
  pythonApi.get(`${base(taskId)}/claims/${encodeURIComponent(claimId)}`);

export const setReportEvidence = (taskId, payload) =>
  pythonApi.put(`${base(taskId)}/report-evidence`, payload);
export const removeReportEvidence = (taskId, evidenceKey) =>
  pythonApi.post(`${base(taskId)}/report-evidence/remove`, { evidence_key: evidenceKey });
export const getReportEvidence = (taskId) => pythonApi.get(`${base(taskId)}/report-evidence`);

export const getLocalGraph = (taskId, params) =>
  pythonApi.get(`${base(taskId)}/graph/local`, { params });

export const getFinalReports = (taskId) =>
  pythonApi.get(`${base(taskId)}/final-reports`);

export const getFinalReport = (taskId, reportId) =>
  pythonApi.get(`${base(taskId)}/final-reports/${encodeURIComponent(reportId)}`);

export const getFinalReportMarkdown = (taskId, reportId) =>
  pythonApi.get(`${base(taskId)}/final-reports/${encodeURIComponent(reportId)}/markdown`);

export const getFinalReportHtml = (taskId, reportId) =>
  pythonApi.get(`${base(taskId)}/final-reports/${encodeURIComponent(reportId)}/html`);

export const getFinalReportPrint = (taskId, reportId) =>
  pythonApi.get(`${base(taskId)}/final-reports/${encodeURIComponent(reportId)}/print`);

export const getFinalReportPublication = (taskId, reportId) =>
  pythonApi.get(`${base(taskId)}/final-reports/${encodeURIComponent(reportId)}/publication`);

export const publishFinalReport = (taskId, reportId) =>
  pythonApi.post(`${base(taskId)}/final-reports/${encodeURIComponent(reportId)}/publish`);

export const pollAnalysisJob = (taskId, jobId, onProgress, interval = 1500) =>
  new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const response = await getAnalysisJob(taskId, jobId);
        const job = response.job;
        onProgress?.(job);
        if (job.status === 'completed') {
          resolve(job);
        } else if (['failed', 'invalid'].includes(job.status)) {
          reject(new Error(job.error || '二次分析失败'));
        } else {
          setTimeout(poll, interval);
        }
      } catch (error) {
        reject(error);
      }
    };
    poll();
  });
