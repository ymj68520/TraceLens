/**
 * Office 文档解析服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/** 解析 Office 文件 (通过受任务约束的路径) */
export const parseFile = async (taskId, filePath, sourceId) => {
    return await pythonApi.post('/api/office/parse', {
        task_id: taskId,
        file_path: filePath,
        source_id: sourceId,
    });
};

/** 获取物化后的 Office 文件字节 (供 docx-preview 等客户端渲染) */
export const fetchOfficeFile = async (taskId, filePath, sourceId) => {
    const params = new URLSearchParams();
    params.set('task_id', taskId || '');
    params.set('file_path', filePath || '');
    if (sourceId) params.set('source_id', sourceId);
    return await pythonApi.get(`/api/office/file?${params.toString()}`, {
        responseType: 'blob',
    });
};

/** 获取支持的文件格式 */
export const getSupportedFormats = async () => {
    return await pythonApi.get('/api/office/supported-types');
};

export default { parseFile, fetchOfficeFile, getSupportedFormats };
