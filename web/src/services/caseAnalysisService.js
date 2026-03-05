/**
 * 案情分析服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/**
 * 保存案情描述
 * @param {string} taskId - 任务 ID
 * @param {string} caseDescription - 案情描述
 */
export const saveCaseDescription = async (taskId, caseDescription) => {
    return await pythonApi.post('/api/llm/case-description', {
        task_id: taskId,
        case_description: caseDescription,
    });
};

/**
 * 启动完整案情分析
 * @param {Object} options
 * @param {string} options.taskId - 任务 ID
 * @param {string} options.filesDbPath - _files.db 路径
 * @param {string} options.caseDescription - 案情描述
 * @param {number} options.maxFilterFiles - 最大筛选文件数
 */
export const startCaseAnalysis = async (options) => {
    return await pythonApi.post('/api/llm/case-analysis', {
        task_id: options.taskId,
        files_db_path: options.filesDbPath,
        case_description: options.caseDescription,
        max_filter_files: options.maxFilterFiles || 200,
    });
};

/**
 * 获取案情分析任务状态
 * @param {string} jobId - 任务 ID
 */
export const getCaseAnalysisStatus = async (jobId) => {
    return await pythonApi.get(`/api/llm/case-analysis/${jobId}`);
};

/**
 * 轮询案情分析状态直到完成
 * @param {string} jobId
 * @param {Function} onProgress - 进度回调
 * @param {number} interval - 轮询间隔 (ms)
 */
export const pollCaseAnalysis = async (jobId, onProgress, interval = 3000) => {
    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const status = await getCaseAnalysisStatus(jobId);

                if (onProgress) {
                    onProgress(status);
                }

                if (status.status === 'completed') {
                    resolve(status);
                } else if (status.status === 'failed') {
                    reject(new Error(status.detail || '案情分析失败'));
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
 * 获取案情报告
 * @param {string} taskId - 任务 ID
 */
export const getCaseReport = async (taskId) => {
    return await pythonApi.get(`/api/llm/case-report/${taskId}`);
};

/**
 * 获取 LLM 筛选后的文件列表
 * @param {string} taskId - 任务 ID
 */
export const getFilteredFiles = async (taskId) => {
    return await pythonApi.get(`/api/llm/filtered-files/${taskId}`);
};

/**
 * 重新分析文件（二次分析）
 * @param {string} taskId - 任务 ID
 * @param {string[]} filePaths - 要重新分析的文件路径
 * @param {string} userHint - 用户补充描述
 * @param {string} filesDbPath - _files.db 路径
 * @param {string} caseDescription - 案情描述（可选）
 */
export const reanalyzeFiles = async (taskId, filePaths, userHint, filesDbPath, caseDescription = '') => {
    return await pythonApi.post('/api/llm/reanalyze-files', {
        task_id: taskId,
        file_paths: filePaths,
        user_hint: userHint,
        files_db_path: filesDbPath,
        case_description: caseDescription,
    });
};

export default {
    saveCaseDescription,
    startCaseAnalysis,
    getCaseAnalysisStatus,
    pollCaseAnalysis,
    getCaseReport,
    getFilteredFiles,
    reanalyzeFiles,
};
