import api from './api';

/**
 * File Extraction Service
 * Handles async file extraction operations
 */

/**
 * Start a file extraction job
 * @param {string} taskId - Analysis task ID
 * @param {Object} options - Extraction options
 * @param {string} options.mode - 'all' | 'extension' | 'name' | 'deleted'
 * @param {string} options.pattern - Pattern for extension/name mode
 * @param {string} options.outputDir - Output directory (default: 'extracted_files')
 * @param {boolean} options.includeDeleted - Include deleted files in 'all' mode
 * @returns {Promise<Object>} Job info with job_id
 */
export const startExtraction = async (taskId, options = {}) => {
  const payload = {
    task_id: taskId,
    mode: options.mode || 'all',
    pattern: options.pattern || '',
    output_dir: options.outputDir || 'extracted_files',
    include_deleted: options.includeDeleted || false,
    overwrite: options.overwrite || false,
    ...(options.maxFiles != null ? { max_files: options.maxFiles } : {}),
    ...(options.maxTotalSize != null ? { max_total_size: options.maxTotalSize } : {}),
    ...(options.maxFileSize != null ? { max_file_size: options.maxFileSize } : {}),
  };

  const response = await api.post('/api/forensics/extract', payload);
  return response;
};

/**
 * Get extraction job status
 * @param {string} jobId - Extraction job ID
 * @returns {Promise<Object>} Job status info
 */
export const getExtractionStatus = async (jobId, signal) => {
  const response = await api.get(`/api/forensics/extract/status?job_id=${encodeURIComponent(jobId)}`, {
    signal,
  });
  return response;
};

/**
 * Poll with task/job identity, cancellation, and an absolute deadline.
 */
export const pollExtractionStatus = async (
  jobId,
  onProgress,
  interval = 1000,
  options = {},
) => {
  const {
    taskId,
    expectedTaskId = taskId,
    signal,
    timeoutMs = 15 * 60 * 1000,
    isCurrent = () => true,
  } = options;
  const deadline = Date.now() + timeoutMs;

  return new Promise((resolve, reject) => {
    let timer;
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      callback(value);
    };
    const abortError = () => {
      const error = new Error('Extraction polling cancelled');
      error.name = 'AbortError';
      return error;
    };
    const poll = async () => {
      if (signal?.aborted || !isCurrent(taskId, jobId) || Date.now() > deadline) {
        finish(reject, signal?.aborted ? abortError() : new Error('Extraction polling timed out'));
        return;
      }
      try {
        const status = await getExtractionStatus(jobId, signal);
        if (signal?.aborted || !isCurrent(expectedTaskId, jobId)) {
          finish(reject, signal?.aborted ? abortError() : new Error('Extraction job is no longer current'));
          return;
        }
        if (status.task_id && expectedTaskId && status.task_id !== expectedTaskId) {
          finish(reject, new Error('Extraction job belongs to another task'));
          return;
        }
        onProgress?.(status);
        if (status.status === 'completed') {
          finish(resolve, status);
        } else if (status.status === 'failed' || status.status === 'cancelled') {
          const error = new Error(status.error_details || status.message || 'Extraction failed');
          error.status = status;
          finish(reject, error);
        } else {
          timer = setTimeout(poll, interval);
        }
      } catch (error) {
        if (signal?.aborted) finish(reject, abortError());
        else finish(reject, error);
      }
    };
    poll();
  });
};

export default {
  startExtraction,
  getExtractionStatus,
  pollExtractionStatus,
};
