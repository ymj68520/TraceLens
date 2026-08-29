/** OSS object-storage analysis — C++ backend. */
import api from './api';

export interface OssAnalysisOptions {
  exportType?: string;
  sourcePath?: string;
}

export const startAnalysis = (taskId: string, options: OssAnalysisOptions = {}) =>
  api.post('/api/forensics/oss/analyze', {
    task_id: taskId,
    export_type: options.exportType || 'local',
    source_path: options.sourcePath || '',
  });

export const getAnalysisStatus = (jobId: string) =>
  api.get('/api/forensics/oss/analyze/status', { params: { job_id: jobId } });

export const getObjects = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/oss/objects', { params: { task_id: taskId, ...params } });

export const getAccessLogs = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/oss/logs', { params: { task_id: taskId, ...params } });

export const getSummary = (taskId: string) =>
  api.get('/api/forensics/oss/summary', { params: { task_id: taskId } });

export const getStorageClassStats = (taskId: string) =>
  api.get('/api/forensics/oss/stats/storage-class', { params: { task_id: taskId } });

export const getExtensionStats = (taskId: string) =>
  api.get('/api/forensics/oss/stats/extensions', { params: { task_id: taskId } });

export const getBuckets = (taskId: string) =>
  api.get('/api/forensics/oss/buckets', { params: { task_id: taskId } });

export interface OssJobStatus {
  status: string;
  error?: string;
  [key: string]: unknown;
}

export const pollAnalysisStatus = (
  jobId: string,
  onProgress?: (status: OssJobStatus) => void,
  interval = 2000,
): Promise<OssJobStatus> =>
  new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = (await getAnalysisStatus(jobId)) as OssJobStatus;
        onProgress?.(status);
        if (status.status === 'completed') return resolve(status);
        if (status.status === 'failed') return reject(new Error(status.error || 'OSS 分析失败'));
        setTimeout(poll, interval);
      } catch (err) {
        reject(err);
      }
    };
    void poll();
  });
