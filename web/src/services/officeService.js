/**
 * Office 文档解析服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/** 解析 Office 文件 (通过路径) */
export const parseFile = async (filePath) => {
    return await pythonApi.post('/api/office/parse', { file_path: filePath });
};

/** 上传并解析 Office 文件 */
export const parseUploadedFile = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return await pythonApi.post('/api/office/parse/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
    });
};

/** 获取支持的文件格式 */
export const getSupportedFormats = async () => {
    return await pythonApi.get('/api/office/formats');
};

export default { parseFile, parseUploadedFile, getSupportedFormats };
