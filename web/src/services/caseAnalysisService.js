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
 * 获取案情分析任务状态
 * （用于 reanalyze-files / windows 等后台任务轮询；legacy 一键案情分析已退役）
 * @param {string} jobId - 任务 ID
 */
export const getCaseAnalysisStatus = async (jobId) => {
    return await pythonApi.get(`/api/llm/case-analysis/${jobId}`);
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
    getCaseAnalysisStatus,
    getCaseReport,
    getFilteredFiles,
    reanalyzeFiles,
};
