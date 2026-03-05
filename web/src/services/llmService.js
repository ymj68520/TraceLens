/**
 * LLM 分析服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/**
 * 分析内容
 * @param {Object} options - 分析选项
 * @param {string} options.content - 待分析内容
 * @param {string} options.filePath - 文件路径 (可选)
 * @param {string} options.modelType - 模型类型: 'text' 或 'vision'
 * @param {string} options.prompt - 自定义提示词 (可选)
 * @param {number} options.maxTokens - 最大令牌数 (可选)
 * @param {number} options.temperature - 温度参数 (可选)
 */
export const analyzeContent = async (options = {}) => {
    const payload = {
        content: options.content,
        file_path: options.filePath,
        db_file_path: options.dbFilePath,
        model_type: options.modelType || 'text',
        prompt: options.prompt,
        max_tokens: options.maxTokens,
        temperature: options.temperature,
        files_db_path: options.filesDbPath || null,
    };
    return await pythonApi.post('/api/llm/analyze', payload);
};

/**
 * 上传文件并分析
 * @param {File} file - 文件对象
 * @param {string} modelType - 模型类型: 'text' 或 'vision'
 * @param {string} prompt - 自定义提示词 (可选)
 */
export const analyzeFile = async (file, modelType = 'text', prompt = null) => {
    const formData = new FormData();
    formData.append('file', file);

    const params = new URLSearchParams();
    params.append('model_type', modelType);
    if (prompt) {
        params.append('prompt', prompt);
    }

    return await pythonApi.post(`/api/llm/analyze/file?${params.toString()}`, formData, {
        headers: {
            'Content-Type': 'multipart/form-data',
        },
    });
};

/**
 * 启动批量分析任务
 * @param {string} taskId - 任务 ID
 * @param {Object} options - 批量分析选项
 * @param {string[]} options.fileTypes - 文件类型过滤
 * @param {number} options.limit - 最大文件数
 * @param {string} options.modelType - 模型类型
 */
export const startBatchAnalysis = async (taskId, options = {}) => {
    const payload = {
        task_id: taskId,
        file_types: options.fileTypes,
        limit: options.limit || 100,
        model_type: options.modelType || 'text',
    };
    return await pythonApi.post('/api/llm/batch', payload);
};

/**
 * 获取批量分析任务状态
 * @param {string} jobId - 任务 ID
 */
export const getBatchStatus = async (jobId) => {
    return await pythonApi.get(`/api/llm/batch/${jobId}`);
};

/**
 * 轮询批量分析状态直到完成
 * @param {string} jobId - 任务 ID
 * @param {Function} onProgress - 进度回调
 * @param {number} interval - 轮询间隔 (毫秒)
 */
export const pollBatchStatus = async (jobId, onProgress, interval = 2000) => {
    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const status = await getBatchStatus(jobId);

                if (onProgress) {
                    onProgress(status);
                }

                if (status.status === 'completed') {
                    resolve(status);
                } else if (status.status === 'failed') {
                    reject(new Error(status.errors?.join(', ') || '批量分析失败'));
                } else {
                    setTimeout(poll, interval);
                }
            } catch (error) {
                reject(error);
            }
        };

        poll();
    });
};

/**
 * 获取可用 LLM 模型列表
 */
export const getModels = async () => {
    return await pythonApi.get('/api/llm/models');
};

/**
 * 获取 LLM 服务状态
 */
export const getLLMStatus = async () => {
    return await pythonApi.get('/api/llm/status');
};

export default {
    analyzeContent,
    analyzeFile,
    startBatchAnalysis,
    getBatchStatus,
    pollBatchStatus,
    getModels,
    getLLMStatus,
};
