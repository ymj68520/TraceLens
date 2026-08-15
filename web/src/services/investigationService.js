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

export default {
    getInvestigationGraph,
};
