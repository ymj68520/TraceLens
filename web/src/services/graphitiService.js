/**
 * Graphiti 知识图谱服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/**
 * 导入任务数据到知识图谱
 * @param {string} taskId - 任务 ID
 * @param {Object} options - 导入选项
 * @param {boolean} options.includeLLMDescriptions - 包含 LLM 描述
 * @param {number} options.batchSize - 批量大小
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
 * 搜索知识图谱
 * @param {string} query - 搜索查询
 * @param {Object} options - 搜索选项
 * @param {string[]} options.entityTypes - 实体类型过滤
 * @param {number} options.limit - 最大结果数
 * @param {boolean} options.includeRelationships - 包含关系
 */
export const searchGraph = async (query, options = {}) => {
    const payload = {
        query,
        entity_types: options.entityTypes,
        limit: options.limit || 100,
        include_relationships: options.includeRelationships !== false,
    };
    return await pythonApi.post('/api/graphiti/search', payload);
};

/**
 * 获取实体列表
 * @param {Object} params - 分页参数
 * @param {string} params.entityType - 实体类型过滤
 * @param {number} params.page - 页码
 * @param {number} params.pageSize - 每页数量
 */
export const listEntities = async (params = {}) => {
    return await pythonApi.get('/api/graphiti/entities', {
        params: {
            entity_type: params.entityType,
            page: params.page || 1,
            page_size: params.pageSize || 50,
        },
    });
};

/**
 * 获取关系列表
 * @param {Object} params - 分页和过滤参数
 * @param {string} params.relationshipType - 关系类型过滤
 * @param {string} params.sourceId - 源实体 ID 过滤
 * @param {string} params.targetId - 目标实体 ID 过滤
 * @param {number} params.page - 页码
 * @param {number} params.pageSize - 每页数量
 */
export const listRelationships = async (params = {}) => {
    return await pythonApi.get('/api/graphiti/relationships', {
        params: {
            relationship_type: params.relationshipType,
            source_id: params.sourceId,
            target_id: params.targetId,
            page: params.page || 1,
            page_size: params.pageSize || 50,
        },
    });
};

/**
 * 获取 Graphiti 服务状态
 */
export const getGraphitiStatus = async () => {
    return await pythonApi.get('/api/graphiti/status');
};

export default {
    ingestTaskData,
    searchGraph,
    listEntities,
    listRelationships,
    getGraphitiStatus,
};
