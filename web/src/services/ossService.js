/**
 * OSS 对象存储分析服务
 * 与 C++ 后端 (端口 8080) 通信
 */
import api from './api';

/** 启动 OSS 分析任务 */
export const startAnalysis = async (taskId, options = {}) => {
    return await api.post('/api/forensics/oss/analyze', {
        task_id: taskId,
        export_type: options.exportType || 'local',
        source_path: options.sourcePath || '',
    });
};

/** 获取分析任务状态 */
export const getAnalysisStatus = async (jobId) => {
    return await api.get('/api/forensics/oss/analyze/status', {
        params: { job_id: jobId },
    });
};

/** 获取 OSS 对象列表 */
export const getObjects = async (taskId, params = {}) => {
    return await api.get('/api/forensics/oss/objects', {
        params: { task_id: taskId, ...params },
    });
};

/** 获取 OSS 访问日志 */
export const getAccessLogs = async (taskId, params = {}) => {
    return await api.get('/api/forensics/oss/logs', {
        params: { task_id: taskId, ...params },
    });
};

/** 获取 OSS 分析摘要 */
export const getSummary = async (taskId) => {
    return await api.get('/api/forensics/oss/summary', {
        params: { task_id: taskId },
    });
};

/** 按存储类型统计对象 */
export const getStorageClassStats = async (taskId) => {
    return await api.get('/api/forensics/oss/statistics/storage-class', {
        params: { task_id: taskId },
    });
};

/** 按扩展名统计对象 */
export const getExtensionStats = async (taskId) => {
    return await api.get('/api/forensics/oss/statistics/extensions', {
        params: { task_id: taskId },
    });
};

/** 获取 Bucket 信息列表 */
export const getBuckets = async (taskId) => {
    return await api.get('/api/forensics/oss/buckets', {
        params: { task_id: taskId },
    });
};

/** 轮询分析任务状态 */
export const pollAnalysisStatus = async (jobId, onProgress, interval = 2000) => {
    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const status = await getAnalysisStatus(jobId);
                if (onProgress) onProgress(status);
                if (status.status === 'COMPLETED') resolve(status);
                else if (status.status === 'FAILED') reject(new Error(status.error_message || 'OSS analysis failed'));
                else setTimeout(poll, interval);
            } catch (err) {
                reject(err);
            }
        };
        poll();
    });
};

export default {
    startAnalysis,
    getAnalysisStatus,
    getObjects,
    getAccessLogs,
    getSummary,
    getStorageClassStats,
    getExtensionStats,
    getBuckets,
    pollAnalysisStatus,
};
