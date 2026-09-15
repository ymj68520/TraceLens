/**
 * Investigation 服务 —— 与 Python FastAPI 服务 (端口 8090) 通信
 * 保留两类面：
 *   1. C8b 冻结的 GET /api/investigation/graph、snapshot / analysis / claims
 *      只读端点，与 R1 冻结的 GET /api/reports/evidence（报告链路消费）
 *   2. C7a-C10/R1/R2d 冻结的 /api/investigation/workbench/{taskId} 工作台
 *      API 族（/investigation 工作台与 Final Report Viewer 消费）
 */
import { pythonApi } from './api';

/**
 * 获取 Investigation Graph (Base KG + Investigation Overlay 只读组合)
 * @param {string} taskId - 任务 ID
 * @param {Object} options - { maxBaseNodes } 仅约束 Base KG，Overlay 永不截断
 */
export const getInvestigationGraph = async (taskId, { maxBaseNodes = 200 } = {}) => {
    return await pythonApi.get('/api/investigation/graph', {
        params: {
            task_id: taskId,
            max_base_nodes: maxBaseNodes,
        },
    });
};

/**
 * 读取单条 Evidence 的已捕获 Snapshot——Initial Analysis 的唯一来源
 * （只读：不自动 capture，不回读 files.db）
 */
export const getInvestigationSnapshot = async (taskId, evidenceKey) => {
    return await pythonApi.get('/api/investigation/evidence/snapshot', {
        params: { task_id: taskId, evidence_key: evidenceKey },
    });
};

/**
 * 按 exact analysis_id 读取一个 Secondary Analysis（不回退到 latest）
 */
export const getInvestigationAnalysis = async (taskId, analysisId) => {
    return await pythonApi.get(
        `/api/investigation/analyses/${encodeURIComponent(analysisId)}`,
        { params: { task_id: taskId } },
    );
};

/**
 * 按 exact analysis_id 读取一个 Secondary Analysis（不回退到 latest）
 */
export const listInvestigationAnalysisClaims = async (taskId, analysisId) => {
    return await pythonApi.get(
        `/api/investigation/analyses/${encodeURIComponent(analysisId)}/claims`,
        { params: { task_id: taskId } },
    );
};

/**
 * 读取单个 Event（当前 MAX-version narrative）
 */
export const getInvestigationEvent = async (taskId, eventId) => {
    return await pythonApi.get(
        `/api/investigation/events/${encodeURIComponent(eventId)}`,
        { params: { task_id: taskId } },
    );
};

/**
 * 列出任务的全部 Report Evidence（exact frozen binding + 只读的
 * newer_accepted_available 提示；绑定永不自动跟随最新 accepted 版本）
 */
export const listReportEvidence = async (taskId) => {
    return await pythonApi.get('/api/reports/evidence', {
        params: { task_id: taskId },
    });
};

const workbenchBase = (taskId) => `/api/investigation/workbench/${encodeURIComponent(taskId)}`;

export const getOverview = (taskId) => pythonApi.get(workbenchBase(taskId));
export const bootstrapInvestigation = (taskId, options = {}) =>
    pythonApi.post(`${workbenchBase(taskId)}/bootstrap`, { mode: 'cluster_seed', ...options });
export const getInvestigationEvents = (taskId, params = {}) =>
    pythonApi.get(`${workbenchBase(taskId)}/events`, { params });
export const getEventEvidence = (taskId, eventId, params = {}) =>
    pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/evidence`, { params });
export const linkEventEvidence = (taskId, eventId, payload) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/evidence/link`, payload);
export const getEvidenceDetail = (taskId, evidenceKey) =>
    pythonApi.get(`${workbenchBase(taskId)}/evidence/detail`, { params: { evidence_key: evidenceKey } });
export const getAnalystNote = (taskId, targetType, targetKey) =>
    pythonApi.get(`${workbenchBase(taskId)}/notes`, { params: { target_type: targetType, target_key: targetKey } });
export const saveAnalystNote = (taskId, targetType, targetKey, content, author = null) =>
    pythonApi.post(`${workbenchBase(taskId)}/notes`, { target_type: targetType, target_key: targetKey, content, author });
export const startEvidenceAnalysis = (taskId, payload) =>
    pythonApi.post(`${workbenchBase(taskId)}/evidence/analyze`, payload);
export const getAnalysisJob = (taskId, jobId) =>
    pythonApi.get(`${workbenchBase(taskId)}/analysis-jobs/${encodeURIComponent(jobId)}`);
export const getAnalysisVersions = (taskId, evidenceKey) =>
    pythonApi.get(`${workbenchBase(taskId)}/evidence/analysis`, { params: { evidence_key: evidenceKey } });
export const acceptAnalysis = (taskId, analysisId, acknowledgeWarnings = false) =>
    pythonApi.post(`${workbenchBase(taskId)}/analysis/${encodeURIComponent(analysisId)}/accept`, { acknowledge_warnings: acknowledgeWarnings });
export const rejectAnalysis = (taskId, analysisId) =>
    pythonApi.post(`${workbenchBase(taskId)}/analysis/${encodeURIComponent(analysisId)}/reject`);
export const refreshInvestigationEvent = (taskId, eventId, payload = {}) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/refresh`, payload);
export const getEventSemanticVersions = (taskId, eventId) =>
    pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions`);
export const acceptEventSemanticVersion = (taskId, eventId, versionId) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/accept`);
export const rejectEventSemanticVersion = (taskId, eventId, versionId) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/reject`);
export const getEventClaims = (taskId, eventId, versionId) =>
    pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/claims`);
export const acceptEventClaim = (taskId, eventId, versionId, claimId) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/claims/${encodeURIComponent(claimId)}/accept`);
export const rejectEventClaim = (taskId, eventId, versionId, claimId) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/versions/${encodeURIComponent(versionId)}/claims/${encodeURIComponent(claimId)}/reject`);
export const getEffectiveEventClaims = (taskId, eventId) =>
    pythonApi.get(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/claims/effective`);
export const reviewInvestigationEvent = (taskId, eventId, status) =>
    pythonApi.post(`${workbenchBase(taskId)}/events/${encodeURIComponent(eventId)}/review`, { status });
export const setReportEvidence = (taskId, payload) =>
    pythonApi.put(`${workbenchBase(taskId)}/report-evidence`, payload);
export const removeReportEvidence = (taskId, evidenceKey) =>
    pythonApi.post(`${workbenchBase(taskId)}/report-evidence/remove`, { evidence_key: evidenceKey });
export const getReportEvidence = (taskId) => pythonApi.get(`${workbenchBase(taskId)}/report-evidence`);
export const getLocalGraph = (taskId, params = {}) =>
    pythonApi.get(`${workbenchBase(taskId)}/graph/local`, { params });
export const getFinalReports = (taskId) => pythonApi.get(`${workbenchBase(taskId)}/final-reports`);
export const getFinalReport = (taskId, reportId) =>
    pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}`);
export const getFinalReportMarkdown = (taskId, reportId) =>
    pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/markdown`, { responseType: 'text' });
export const getFinalReportHtml = (taskId, reportId) =>
    pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/html`, { responseType: 'text' });
export const getFinalReportPrint = (taskId, reportId) =>
    pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/print`, { responseType: 'text' });
export const getFinalReportPublication = (taskId, reportId) =>
    pythonApi.get(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/publication`);
export const publishFinalReport = (taskId, reportId) =>
    pythonApi.post(`${workbenchBase(taskId)}/final-reports/${encodeURIComponent(reportId)}/publish`);
export const getClaimProvenance = (taskId, claimId) =>
    pythonApi.get(`${workbenchBase(taskId)}/claims/${encodeURIComponent(claimId)}`);
export const pollAnalysisJob = async (taskId, jobId, onProgress, interval = 1500) => {
    const poll = async () => {
        const response = await getAnalysisJob(taskId, jobId);
        const job = response.job;
        onProgress?.(job);
        if (job.status === 'completed') return job;
        if (['failed', 'invalid'].includes(job.status)) throw new Error(job.error || '二次分析失败');
        await new Promise((resolve) => setTimeout(resolve, interval));
        return poll();
    };
    return poll();
};

export default {
    getInvestigationGraph,
    getInvestigationSnapshot,
    getInvestigationAnalysis,
    listInvestigationAnalysisClaims,
    getInvestigationEvent,
    listReportEvidence,
    getOverview,
    bootstrapInvestigation,
    getInvestigationEvents,
    getEventEvidence,
    linkEventEvidence,
    getEvidenceDetail,
    getAnalystNote,
    saveAnalystNote,
    startEvidenceAnalysis,
    getAnalysisJob,
    getAnalysisVersions,
    acceptAnalysis,
    rejectAnalysis,
    refreshInvestigationEvent,
    getEventSemanticVersions,
    acceptEventSemanticVersion,
    rejectEventSemanticVersion,
    getEventClaims,
    acceptEventClaim,
    rejectEventClaim,
    getEffectiveEventClaims,
    reviewInvestigationEvent,
    setReportEvidence,
    removeReportEvidence,
    getReportEvidence,
    getLocalGraph,
    getFinalReports,
    getFinalReport,
    getFinalReportMarkdown,
    getFinalReportHtml,
    getFinalReportPrint,
    getFinalReportPublication,
    publishFinalReport,
    getClaimProvenance,
    pollAnalysisJob,
};
