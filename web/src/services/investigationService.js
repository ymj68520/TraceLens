/**
 * Investigation 服务 (C9b 起含 Evidence Analysis mutation，
 * C9c 起含 Investigation Event 创建/链接/refresh mutation，
 * C10 起含 Evidence Snapshot capture——用户链第一步的显式入口)
 * 与 Python FastAPI 服务 (端口 8090) 通信
 * 消费 C8b 冻结的 GET /api/investigation/graph、C4b-2/C6 冻结的
 * POST /api/investigation/analyses(+/review) 与 C7a-C7c 冻结的
 * POST /api/investigation/events(+/evidence,+/refresh)、C3 冻结的
 * POST /api/investigation/snapshots
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
};
