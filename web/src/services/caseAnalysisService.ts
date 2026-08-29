/** Case-level analysis helpers — Python sidecar. */
import { pythonApi } from './api';

export const saveCaseDescription = (taskId: string, caseDescription: string) =>
  pythonApi.post('/api/llm/case-description', {
    task_id: taskId,
    case_description: caseDescription,
  });

export interface CaseAnalysisStatus {
  status: string;
  detail?: string;
  [key: string]: unknown;
}

export const getCaseAnalysisStatus = (jobId: string): Promise<CaseAnalysisStatus> =>
  pythonApi.get(`/api/llm/case-analysis/${jobId}`) as unknown as Promise<CaseAnalysisStatus>;

export const pollCaseAnalysis = (
  jobId: string,
  onProgress?: (status: CaseAnalysisStatus) => void,
  interval = 3000,
): Promise<CaseAnalysisStatus> =>
  new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = await getCaseAnalysisStatus(jobId);
        onProgress?.(status);
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
    void poll();
  });

export const getCaseReport = (taskId: string) =>
  pythonApi.get(`/api/llm/case-report/${taskId}`);

export const getFilteredFiles = (taskId: string) =>
  pythonApi.get(`/api/llm/filtered-files/${taskId}`);

export const reanalyzeFiles = (
  taskId: string,
  filePaths: string[],
  userHint: string,
  filesDbPath: string,
  caseDescription = '',
) =>
  pythonApi.post('/api/llm/reanalyze-files', {
    task_id: taskId,
    file_paths: filePaths,
    user_hint: userHint,
    files_db_path: filesDbPath,
    case_description: caseDescription,
  });
