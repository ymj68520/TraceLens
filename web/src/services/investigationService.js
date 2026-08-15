/**
 * Investigation 服务 (只读)
 * 与 Python FastAPI 服务 (端口 8090) 通信
 * 消费 C8b 冻结的 GET /api/investigation/graph
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
 * 读取一个 exact analysis 的已持久化 Claims（含 evidence refs / grounding）
 */
export const listInvestigationAnalysisClaims = async (taskId, analysisId) => {
    return await pythonApi.get(
        `/api/investigation/analyses/${encodeURIComponent(analysisId)}/claims`,
        { params: { task_id: taskId } },
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
    listInvestigationAnalysisClaims,
    listInvestigationEvents,
    getInvestigationEvent,
    listInvestigationEventVersions,
    listInvestigationEventEvidence,
    listInvestigationEventRefreshes,
};
