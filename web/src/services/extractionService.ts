import api from './api';

/** Async file extraction jobs — C++ backend. */

export interface ExtractionOptions {
  mode?: 'all' | 'extension' | 'name' | 'deleted';
  pattern?: string;
  outputDir?: string;
  includeDeleted?: boolean;
  overwrite?: boolean;
  maxFiles?: number | null;
  maxTotalSize?: number | null;
  maxFileSize?: number | null;
}

export interface ExtractionJobStatus {
  status: string;
  task_id?: string;
  message?: string;
  error_details?: string;
  progress?: number;
  [key: string]: unknown;
}

export const startExtraction = (taskId: string, options: ExtractionOptions = {}) =>
  api.post('/api/forensics/extract', {
    task_id: taskId,
    mode: options.mode || 'all',
    pattern: options.pattern || '',
    output_dir: options.outputDir || 'extracted_files',
    include_deleted: options.includeDeleted || false,
    overwrite: options.overwrite || false,
    ...(options.maxFiles != null ? { max_files: options.maxFiles } : {}),
    ...(options.maxTotalSize != null ? { max_total_size: options.maxTotalSize } : {}),
    ...(options.maxFileSize != null ? { max_file_size: options.maxFileSize } : {}),
  }) as unknown as Promise<{ job_id: string }>;

export const getExtractionStatus = (jobId: string, signal?: AbortSignal) =>
  api.get(`/api/forensics/extract/status?job_id=${encodeURIComponent(jobId)}`, {
    signal,
  }) as unknown as Promise<ExtractionJobStatus>;

export interface PollOptions {
  taskId?: string;
  expectedTaskId?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  isCurrent?: (taskId?: string, jobId?: string) => boolean;
}

/** Poll with task/job identity checks, cancellation, and a hard deadline. */
export const pollExtractionStatus = (
  jobId: string,
  onProgress?: (status: ExtractionJobStatus) => void,
  interval = 1000,
  options: PollOptions = {},
): Promise<ExtractionJobStatus> => {
  const {
    taskId,
    expectedTaskId = taskId,
    signal,
    timeoutMs = 15 * 60 * 1000,
    isCurrent = () => true,
  } = options;
  const deadline = Date.now() + timeoutMs;

  return new Promise((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let settled = false;

    const finish = (callback: (v: never) => void, value: unknown) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      (callback as (v: unknown) => void)(value);
    };

    const abortError = () => {
      const error = new Error('Extraction polling cancelled');
      error.name = 'AbortError';
      return error;
    };

    const poll = async () => {
      if (signal?.aborted || !isCurrent(taskId, jobId) || Date.now() > deadline) {
        finish(reject as (v: never) => void, signal?.aborted ? abortError() : new Error('Extraction polling timed out'));
        return;
      }
      try {
        const status = await getExtractionStatus(jobId, signal);
        if (signal?.aborted || !isCurrent(expectedTaskId, jobId)) {
          finish(reject as (v: never) => void, signal?.aborted ? abortError() : new Error('Extraction job is no longer current'));
          return;
        }
        if (status.task_id && expectedTaskId && status.task_id !== expectedTaskId) {
          finish(reject as (v: never) => void, new Error('Extraction job belongs to another task'));
          return;
        }
        onProgress?.(status);
        if (status.status === 'completed') {
          finish(resolve as (v: never) => void, status);
        } else if (status.status === 'failed' || status.status === 'cancelled') {
          const error = new Error(status.error_details || status.message || 'Extraction failed') as Error & { status?: ExtractionJobStatus };
          error.status = status;
          finish(reject as (v: never) => void, error);
        } else {
          timer = setTimeout(poll, interval);
        }
      } catch (error) {
        if (signal?.aborted) finish(reject as (v: never) => void, abortError());
        else finish(reject as (v: never) => void, error);
      }
    };

    void poll();
  });
};
