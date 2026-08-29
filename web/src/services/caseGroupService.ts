/**
 * Case grouping + multi-image analysis — Python sidecar (/api/llm/cases*).
 */
import { pythonApi } from './api';
import type { ForensicCase } from '../types/api';

export interface MultiImageAnalysisOptions {
  caseId: string;
  taskIds: string[];
  filesDbPaths: string[];
  caseDescription?: string;
  maxFilterFiles?: number;
}

export interface MultiAnalysisStatus {
  status: string;
  job_id?: string;
  case_id?: string;
  error?: string;
  [key: string]: unknown;
}

export const createCase = (name: string, description: string, taskIds: string[] = []): Promise<ForensicCase> =>
  pythonApi.post('/api/llm/cases', { name, description, task_ids: taskIds }) as unknown as Promise<ForensicCase>;

export const listCases = (): Promise<{ cases: ForensicCase[] }> =>
  pythonApi.get('/api/llm/cases') as unknown as Promise<{ cases: ForensicCase[] }>;

export const getCase = (caseId: string): Promise<ForensicCase> =>
  pythonApi.get(`/api/llm/cases/${caseId}`) as unknown as Promise<ForensicCase>;

export const addTasksToCase = (caseId: string, taskIds: string[]) =>
  pythonApi.post(`/api/llm/cases/${caseId}/tasks`, { task_ids: taskIds });

/**
 * Associate already-completed tasks to a case. The backend pre-populates
 * case-level analysis state so the next cross-image run reuses prior results.
 */
export const associateTasksToCase = (caseId: string, taskIds: string[]) =>
  pythonApi.post(`/api/llm/cases/${caseId}/associate-tasks`, { task_ids: taskIds });

export const startMultiImageAnalysis = (opts: MultiImageAnalysisOptions): Promise<MultiAnalysisStatus> =>
  pythonApi.post('/api/llm/multi-image-analysis', {
    case_id: opts.caseId,
    task_ids: opts.taskIds,
    files_db_paths: opts.filesDbPaths,
    case_description: opts.caseDescription,
    max_filter_files: opts.maxFilterFiles ?? 400,
  }) as unknown as Promise<MultiAnalysisStatus>;

export const getMultiAnalysisStatus = (jobId: string): Promise<MultiAnalysisStatus> =>
  pythonApi.get(`/api/llm/multi-image-analysis/${jobId}`) as unknown as Promise<MultiAnalysisStatus>;

export const getCaseReportByCase = (caseId: string) =>
  pythonApi.get(`/api/llm/case-report-by-case/${caseId}`);

export const pollMultiAnalysis = (
  jobId: string,
  onProgress?: (status: MultiAnalysisStatus) => void,
  interval = 5000,
): Promise<MultiAnalysisStatus> =>
  new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const status = await getMultiAnalysisStatus(jobId);
        onProgress?.(status);
        if (status.status === 'completed') return resolve(status);
        if (status.status === 'failed') return reject(new Error(status.error || '跨镜像分析失败'));
        setTimeout(tick, interval);
      } catch (err) {
        reject(err);
      }
    };
    void tick();
  });

export const deleteCase = (caseId: string) =>
  pythonApi.delete(`/api/llm/cases/${caseId}`);
