/**
 * Investigation 服务 (C9b 起含 Evidence Analysis mutation，
 * C9c 起含 Investigation Event 创建/链接/refresh mutation，
 * C10 起含 Evidence Snapshot capture——用户链第一步的显式入口，
 * R1 起含 Report Evidence 显式绑定——Investigation findings 进入 Report 的唯一入口)
 * 与 Python FastAPI 服务 (端口 8090) 通信
 * 消费 C8b 冻结的 GET /api/investigation/graph、C4b-2/C6 冻结的
 * POST /api/investigation/analyses(+/review) 与 C7a-C7c 冻结的
 * POST /api/investigation/events(+/evidence,+/refresh)、C3 冻结的
 * POST /api/investigation/snapshots、R1 冻结的 /api/reports/evidence
 */
import { pythonApi } from './api';

/**
 * 显式捕获一条 Evidence Snapshot（resolve + capture_if_absent 都在
 * 后端发生；key 非本任务 source 时后端 404，前端不做任何本地校验）
 */
export const captureInvestigationSnapshot = async (taskId, evidenceKey) => {
    return await pythonApi.post('/api/investigation/snapshots', {
        task_id: taskId,
        evidence_key: evidenceKey,
    });
};

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
 * 列出任务已捕获的全部 Evidence（含 C8b accepted-first selection 状态）
 */
export const listInvestigationEvidence = async (taskId) => {
    return await pythonApi.get('/api/investigation/evidence', {
        params: { task_id: taskId },
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
 * 列出一条 Evidence 的全部 Secondary Analysis 版本（exact 历史行）
 */
export const listInvestigationAnalyses = async (taskId, evidenceKey) => {
    return await pythonApi.get('/api/investigation/analyses', {
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
 * 显式提交一个 Secondary Analysis（202 admission；返回的 analysis_id 是
 * 后续唯一的 polling identity，绝不回退到 "latest"）。
 * 请求体严格对应后端 CreateAnalysisRequest（extra=forbid）：
 * task_id / evidence_key / analyst_note / case_context / related_evidence。
 */
export const createSecondaryAnalysis = async (
    taskId,
    evidenceKey,
    { analystNote = null, caseContext = null, relatedEvidence = [] } = {},
) => {
    return await pythonApi.post('/api/investigation/analyses', {
        task_id: taskId,
        evidence_key: evidenceKey,
        analyst_note: analystNote,
        case_context: caseContext,
        related_evidence: relatedEvidence,
    });
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
 * 对一个 exact analysis version 记录一次显式 analyst decision。
 * 决策 terminal 且不可更改；请求体只有后端 ReviewAnalysisRequest 的
 * task_id / decision / reviewer / reason 四个字段。
 */
export const reviewSecondaryAnalysis = async (
    taskId,
    analysisId,
    { decision, reviewer, reason = null },
) => {
    return await pythonApi.post(
        `/api/investigation/analyses/${encodeURIComponent(analysisId)}/review`,
        {
            task_id: taskId,
            decision,
            reviewer,
            reason,
        },
    );
};

/**
 * 列出任务的 Investigation Events（当前 narrative 投影）
 */
export const listInvestigationEvents = async (taskId) => {
    return await pythonApi.get('/api/investigation/events', {
        params: { task_id: taskId },
    });
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
 * 读取 Event 的不可变 narrative 版本历史
 */
export const listInvestigationEventVersions = async (taskId, eventId) => {
    return await pythonApi.get(
        `/api/investigation/events/${encodeURIComponent(eventId)}/versions`,
        { params: { task_id: taskId } },
    );
};

/**
 * 读取 Event 的 authoritative Event→Evidence 关联
 */
export const listInvestigationEventEvidence = async (taskId, eventId) => {
    return await pythonApi.get(
        `/api/investigation/events/${encodeURIComponent(eventId)}/evidence`,
        { params: { task_id: taskId } },
    );
};

/**
 * 读取 Event 的 refresh 历史（状态与错误信息）
 */
export const listInvestigationEventRefreshes = async (taskId, eventId) => {
    return await pythonApi.get(
        `/api/investigation/events/${encodeURIComponent(eventId)}/refreshes`,
        { params: { task_id: taskId } },
    );
};

/**
 * 创建一个 Investigation Event（含 immutable v1 narrative）。
 * 请求体严格对应后端 CreateInvestigationEventRequest（extra=forbid）：
 * task_id / title / summary / created_by——created_by 是必填 analyst 标识。
 * 不做任何 Timeline Cluster 自动转换（C9c §2）。
 */
export const createInvestigationEvent = async (
    taskId,
    { title, summary = null, createdBy },
) => {
    return await pythonApi.post('/api/investigation/events', {
        task_id: taskId,
        title,
        summary,
        created_by: createdBy,
    });
};

/**
 * 显式建立一条 Event→Evidence 关联（append-only，无 unlink）。
 * 请求体严格对应后端 LinkEventEvidenceRequest（extra=forbid）：
 * task_id / evidence_key / linked_by。resolve + capture 的完整性
 * 边界完全由后端 transaction 保证；前端只限制候选减少误操作。
 */
export const linkInvestigationEventEvidence = async (
    taskId,
    eventId,
    evidenceKey,
    { linkedBy },
) => {
    return await pythonApi.post(
        `/api/investigation/events/${encodeURIComponent(eventId)}/evidence`,
        {
            task_id: taskId,
            evidence_key: evidenceKey,
            linked_by: linkedBy,
        },
    );
};

/**
 * 显式发起一次 Event narrative refresh（admission 不等待 LLM）。
 * 请求体严格对应后端 CreateEventRefreshRequest（extra=forbid）：
 * task_id / requested_by——frozen envelope 完全由服务器构造。
 * 返回的 exact refresh_id 是唯一轮询身份（无 latest 回退）。
 */
export const startInvestigationEventRefresh = async (
    taskId,
    eventId,
    { requestedBy },
) => {
    return await pythonApi.post(
        `/api/investigation/events/${encodeURIComponent(eventId)}/refresh`,
        {
            task_id: taskId,
            requested_by: requestedBy,
        },
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

/**
 * 显式把一条已捕获 Evidence 加入 Report（main/appendix）。
 * analysis_id 省略 = Original Evidence only；提供时由后端三重检查。
 */
export const addReportEvidence = async (
    taskId,
    evidenceKey,
    { reportStatus, analysisId = null, addedBy },
) => {
    return await pythonApi.post('/api/reports/evidence', {
        task_id: taskId,
        evidence_key: evidenceKey,
        report_status: reportStatus,
        analysis_id: analysisId,
        added_by: addedBy,
    });
};

/**
 * 显式更新 Report Evidence 状态或 frozen analysis binding。
 * omitted analysisId 保持现有 binding，不执行隐式解绑。
 */
export const updateReportEvidence = async (
    taskId,
    evidenceKey,
    { reportStatus = null, analysisId = undefined, updatedBy },
) => {
    return await pythonApi.put('/api/reports/evidence', {
        task_id: taskId,
        evidence_key: evidenceKey,
        report_status: reportStatus,
        ...(analysisId !== undefined ? { analysis_id: analysisId } : {}),
        updated_by: updatedBy,
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
    captureInvestigationSnapshot,
    listInvestigationEvidence,
    getInvestigationSnapshot,
    listInvestigationAnalyses,
    getInvestigationAnalysis,
    createSecondaryAnalysis,
    reviewSecondaryAnalysis,
    listInvestigationAnalysisClaims,
    listInvestigationEvents,
    getInvestigationEvent,
    listInvestigationEventVersions,
    listInvestigationEventEvidence,
    listInvestigationEventRefreshes,
    createInvestigationEvent,
    linkInvestigationEventEvidence,
    startInvestigationEventRefresh,
    listReportEvidence,
    addReportEvidence,
    updateReportEvidence,
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
