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
  };

  const response = await api.post('/api/forensics/extract', payload);
  return response;
};

/**
 * Get extraction job status
 * @param {string} jobId - Extraction job ID
 * @returns {Promise<Object>} Job status info
 */
export const getExtractionStatus = async (jobId) => {
  const response = await api.get(`/api/forensics/extract/status?job_id=${jobId}`);
  return response;
};

/**
 * Poll extraction status until completion
 * @param {string} jobId - Extraction job ID
 * @param {Function} onProgress - Progress callback (receives status object)
 * @param {number} interval - Polling interval in ms (default: 1000)
 * @returns {Promise<Object>} Final job status
 */
export const pollExtractionStatus = async (jobId, onProgress, interval = 1000) => {
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = await getExtractionStatus(jobId);

        if (onProgress) {
          onProgress(status);
        }

        if (status.status === 'completed') {
          resolve(status);
        } else if (status.status === 'failed' || status.status === 'cancelled') {
          reject(new Error(status.error_details || status.message || 'Extraction failed'));
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

export default {
  startExtraction,
  getExtractionStatus,
  pollExtractionStatus,
};
