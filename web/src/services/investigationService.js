/**
 * Investigation 服务 (C9b 起含 Evidence Analysis mutation)
 * 与 Python FastAPI 服务 (端口 8090) 通信
 * 消费 C8b 冻结的 GET /api/investigation/graph 与 C4b-2/C6 冻结的
 * POST /api/investigation/analyses(+/review)
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

export default {
    getInvestigationGraph,
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
};
