/**
 * Office 文档解析服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/** 解析 Office 文件 (通过受任务约束的路径) */
export const parseFile = async (taskId, filePath) => {
    return await pythonApi.post('/api/office/parse', {
        task_id: taskId,
        file_path: filePath,
    });
};

/** 获取支持的文件格式 */
export const getSupportedFormats = async () => {
    return await pythonApi.get('/api/office/supported-types');
};

export default { parseFile, getSupportedFormats };
