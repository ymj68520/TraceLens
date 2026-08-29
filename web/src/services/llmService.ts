/**
 * LLM analysis service — Python sidecar (:8090).
 */
import { pythonApi } from './api';

export interface AnalyzeOptions {
  taskId?: string | null;
  content?: string;
  filePath?: string;
  dbFilePath?: string;
  modelType?: 'text' | 'vision' | string;
  prompt?: string;
  maxTokens?: number;
  temperature?: number;
  filesDbPath?: string | null;
}

export interface BatchOptions {
  fileTypes?: string[];
  filePaths?: string[];
  limit?: number;
  modelType?: string;
}

export interface BatchStatus {
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  progress?: number;
  errors?: string[];
  [key: string]: unknown;
}

export const analyzeContent = (options: AnalyzeOptions = {}) =>
  pythonApi.post('/api/llm/analyze', {
    task_id: options.taskId ?? null,
    content: options.content,
    file_path: options.filePath,
    db_file_path: options.dbFilePath,
    model_type: options.modelType || 'text',
    prompt: options.prompt,
    max_tokens: options.maxTokens,
    temperature: options.temperature,
    files_db_path: options.filesDbPath ?? null,
  });

export const analyzeFile = (file: File, modelType = 'text', prompt: string | null = null) => {
  const formData = new FormData();
  formData.append('file', file);

  const params = new URLSearchParams();
  params.append('model_type', modelType);
  if (prompt) params.append('prompt', prompt);

  return pythonApi.post(`/api/llm/analyze/file?${params.toString()}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

export const analyzeDLL = ({ filePath, filesDbPath, prompt = null }: {
  filePath: string;
  filesDbPath?: string | null;
  prompt?: string | null;
}) =>
  pythonApi.post('/api/llm/analyze/dll', {
    file_path: filePath,
    files_db_path: filesDbPath || null,
    prompt,
  });

export const startBatchAnalysis = (taskId: string, options: BatchOptions = {}) =>
  pythonApi.post('/api/llm/batch', {
    task_id: taskId,
    file_types: options.fileTypes,
    file_paths: options.filePaths,
    limit: options.limit || 100,
    model_type: options.modelType || 'text',
  });

export const getBatchStatus = (jobId: string): Promise<BatchStatus> =>
  pythonApi.get(`/api/llm/batch/${jobId}`) as unknown as Promise<BatchStatus>;

export const pollBatchStatus = (
  jobId: string,
  onProgress?: (status: BatchStatus) => void,
  interval = 2000,
  { signal }: { signal?: AbortSignal } = {},
): Promise<BatchStatus> =>
  new Promise((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let settled = false;

    const cleanup = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      signal?.removeEventListener('abort', abort);
    };

    const abort = () => {
      if (settled) return;
      settled = true;
      cleanup();
      const error = new Error('batch polling cancelled');
      error.name = 'AbortError';
      reject(error);
    };

    const finish = (callback: (v: never) => void, value: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      (callback as (v: unknown) => void)(value);
    };

    if (signal?.aborted) {
      abort();
      return;
    }
    signal?.addEventListener('abort', abort, { once: true });

    const poll = async () => {
      if (settled || signal?.aborted) return;
      try {
        const status = await getBatchStatus(jobId);
        if (settled || signal?.aborted) return;

        onProgress?.(status);

        if (status.status === 'completed') {
          finish(resolve as (v: never) => void, status);
        } else if (status.status === 'failed') {
          finish(reject as (v: never) => void, new Error(status.errors?.join(', ') || '批量分析失败'));
        } else {
          timer = setTimeout(poll, interval);
        }
      } catch (error) {
        finish(reject as (v: never) => void, error);
      }
    };

    void poll();
  });

export const getModels = () => pythonApi.get('/api/llm/models');
export const getLLMStatus = () => pythonApi.get('/api/llm/status');

export const toggleFileRelevance = (taskId: string, filePath: string, isRelevant: boolean) =>
  pythonApi.post('/api/llm/toggle-relevance', {
    task_id: taskId,
    file_path: filePath,
    is_relevant: isRelevant,
  });
