/**
 * Graphiti 知识图谱服务 (任务特定)
 * 与 Python FastAPI 服务 (端口 8090) 通信
 * 每个任务有独立的知识图谱命名空间
 */
import { pythonApi } from './api';

/**
 * 导入任务数据到知识图谱
 * @param {string} taskId - 任务 ID (同时作为图谱命名空间)
 * @param {Object} options - 导入选项
 */
export const ingestTaskData = async (taskId, options = {}) => {
    const payload = {
        task_id: taskId,
        include_llm_descriptions: options.includeLLMDescriptions !== false,
        batch_size: options.batchSize || 50,
    };
    return await pythonApi.post('/api/graphiti/ingest', payload);
};

/**
 * 搜索知识图谱 (任务特定)
 * @param {string} query - 搜索查询
 * @param {string} taskId - 任务 ID
 * @param {Object} options - 搜索选项
 */
export const searchGraph = async (query, taskId, options = {}) => {
    const payload = {
        query,
        task_id: taskId,
        entity_types: options.entityTypes,
        limit: options.limit || 100,
        include_relationships: options.includeRelationships !== false,
    };
    return await pythonApi.post('/api/graphiti/search', payload);
};

/**
 * 获取实体列表 (任务特定)
 * @param {string} taskId - 任务 ID
 * @param {Object} params - 分页参数
 */
export const listEntities = async (taskId, params = {}) => {
    return await pythonApi.get('/api/graphiti/entities', {
        params: {
            task_id: taskId,
            entity_type: params.entityType,
            page: params.page || 1,
            page_size: params.pageSize || 50,
        },
    });
};

/**
 * 获取关系列表 (任务特定)
 * @param {string} taskId - 任务 ID
 * @param {Object} params - 分页和过滤参数
 */
export const listRelationships = async (taskId, params = {}) => {
    return await pythonApi.get('/api/graphiti/relationships', {
        params: {
            task_id: taskId,
            relationship_type: params.relationshipType,
            source_id: params.sourceId,
            target_id: params.targetId,
            page: params.page || 1,
            page_size: params.pageSize || 50,
        },
    });
};

/**
 * 获取 Graphiti 服务状态 (可选任务特定)
 * @param {string} taskId - 任务 ID (可选)
 */
export const getGraphitiStatus = async (taskId = null) => {
    const params = taskId ? { task_id: taskId } : {};
    return await pythonApi.get('/api/graphiti/status', { params });
};

/**
 * 列出所有有知识图谱数据的任务
 */
export const listTaskGraphs = async () => {
    return await pythonApi.get('/api/graphiti/tasks');
};

/**
 * 删除任务的知识图谱
 * @param {string} taskId - 任务 ID
 */
export const deleteTaskGraph = async (taskId) => {
    return await pythonApi.delete(`/api/graphiti/tasks/${taskId}`);
};

/**
 * 获取图谱可视化数据 (节点 + 关系)
 * @param {string} taskId - 任务 ID
 * @param {number} maxNodes - 最多返回节点数量
 */
export const getGraphData = async (taskId, maxNodes = 200) => {
    return await pythonApi.get('/api/graphiti/graph', {
        params: { task_id: taskId, max_nodes: maxNodes },
    });
};

export default {
    ingestTaskData,
    searchGraph,
    listEntities,
    listRelationships,
    getGraphitiStatus,
    listTaskGraphs,
    deleteTaskGraph,
    getGraphData,
};
