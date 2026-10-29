/**
 * 统一通讯关系图 / 案件时间线服务。
 *
 * 后端 `/api/comm/*` 把手机检材（android.db）与微信、QQ 导入（各自 graph.db）
 * 汇成一张图。导入需要在请求里显式列出，不会跨数据集凭姓名自动合并人物。
 */
import { pythonApi } from './api';

const repeat = (key, values) =>
    (values || []).filter(Boolean).map((value) => [key, value]);

/**
 * 获取统一通讯关系图。
 * @param {string} taskId
 * @param {object} options - { wechatImports, qqImports, datasets, startTime, endTime,
 *   minEdgeWeight, includeUnion, maxNodes, maxEdges, communities }
 */
export const getCommGraph = async (taskId, options = {}) => {
    const params = new URLSearchParams({ task_id: taskId });
    repeat('wechat_imports', options.wechatImports).forEach(([k, v]) => params.append(k, v));
    repeat('qq_imports', options.qqImports).forEach(([k, v]) => params.append(k, v));
    repeat('dataset', options.datasets).forEach(([k, v]) => params.append(k, v));
    if (options.startTime) params.set('start_time', String(options.startTime));
    if (options.endTime) params.set('end_time', String(options.endTime));
    if (options.minEdgeWeight) params.set('min_edge_weight', String(options.minEdgeWeight));
    if (options.includeUnion === false) params.set('include_union', 'false');
    if (options.maxNodes) params.set('max_nodes', String(options.maxNodes));
    if (options.maxEdges) params.set('max_edges', String(options.maxEdges));
    if (options.communities === false) params.set('communities', 'false');
    return pythonApi.get(`/api/comm/graph?${params.toString()}`);
};

/**
 * 获取案件/任务通讯时间线（逐条记录，非统计）。
 */
export const getCommTimeline = async (taskId, options = {}) => {
    const params = new URLSearchParams({ task_id: taskId });
    repeat('wechat_imports', options.wechatImports).forEach(([k, v]) => params.append(k, v));
    repeat('qq_imports', options.qqImports).forEach(([k, v]) => params.append(k, v));
    repeat('dataset', options.datasets).forEach(([k, v]) => params.append(k, v));
    repeat('kind', options.kinds).forEach(([k, v]) => params.append(k, v));
    if (options.startTime) params.set('start_time', String(options.startTime));
    if (options.endTime) params.set('end_time', String(options.endTime));
    if (options.limit) params.set('limit', String(options.limit));
    return pythonApi.get(`/api/comm/timeline?${params.toString()}`);
};

/** 回查一条图上边背后的原始记录。 */
export const getCommEdgeDetail = async (taskId, { source, target, relation }, options = {}) => {
    const params = new URLSearchParams({
        task_id: taskId, source, target, relation: relation || '',
    });
    repeat('wechat_imports', options.wechatImports).forEach(([k, v]) => params.append(k, v));
    repeat('qq_imports', options.qqImports).forEach(([k, v]) => params.append(k, v));
    return pythonApi.get(`/api/comm/edge?${params.toString()}`);
};

/** 列出当前可合并的数据集（含不可用项及原因）。 */
export const getCommDatasets = async (taskId, options = {}) => {
    const params = new URLSearchParams({ task_id: taskId });
    repeat('wechat_imports', options.wechatImports).forEach(([k, v]) => params.append(k, v));
    repeat('qq_imports', options.qqImports).forEach(([k, v]) => params.append(k, v));
    return pythonApi.get(`/api/comm/datasets?${params.toString()}`);
};
