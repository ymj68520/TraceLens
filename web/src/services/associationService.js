import { pythonApi } from './api';

/**
 * Association Service
 *
 * Provides bidirectional linking between event clusters and files
 * with time-based anomaly detection.
 */

/**
 * Get files related to an event cluster
 *
 * @param {string} taskId - Task ID
 * @param {Object} cluster - Cluster object with time_window, event_type, parent_directory
 * @param {number} cluster.time_window - Cluster time window (timestamp / 60)
 * @param {string} cluster.event_type - Event type (CREATED, MODIFIED, DELETED, etc.)
 * @param {string} cluster.parent_directory - Parent directory of events
 * @param {number} limit - Maximum results (default: 100)
 * @returns {Promise<Object>} Response with files array and anomaly detection
 */
export const getClusterRelatedFiles = async (taskId, cluster, limit = 100) => {
  try {
    console.log('[associationService] getClusterRelatedFiles called with:', { taskId, cluster, limit });
    console.log('[associationService] cluster keys:', Object.keys(cluster));
    console.log('[associationService] cluster.time_window:', cluster.time_window);
    console.log('[associationService] cluster.event_type:', cluster.event_type);

    const response = await pythonApi.post('/api/associations/cluster-files', {
      task_id: taskId,
      time_window: cluster.time_window,  // Use time_window from C++ API
      event_type: cluster.event_type,
      parent_directory: cluster.parent_directory || '',
      limit
    });

    console.log('[associationService] Response received:', response);
    return response;
  } catch (error) {
    console.error('[associationService] Request failed:', error);
    console.error('[associationService] Error response:', error.response);
    console.error('[associationService] Error status:', error.response?.status);
    console.error('[associationService] Error data:', error.response?.data);
    throw error;
  }
};

/**
 * Get event clusters related to a file
 *
 * @param {string} taskId - Task ID
 * @param {Object} file - File object (only needs file_path)
 * @param {string} file.file_path - Full file path
 * @param {number} limit - Maximum results (default: 100)
 * @returns {Promise<Object>} Response with clusters array
 */
export const getFileRelatedClusters = async (taskId, file, limit = 100) => {
  try {
    const response = await pythonApi.post('/api/associations/file-clusters', {
      task_id: taskId,
      file_path: file.file_path,
      limit
    });
    return response;
  } catch (error) {
    console.error('Failed to get file related clusters:', error);
    throw error;
  }
};

/**
 * Format anomaly type to human-readable message
 *
 * @param {string} anomalyType - Anomaly type code
 * @returns {string} Human-readable anomaly description
 */
export const formatAnomalyType = (anomalyType) => {
  const anomalyMessages = {
    'mtime_mismatch': '修改时间与事件时间差异过大',
    'crtime_after_mtime': '创建时间晚于修改时间（异常）',
    'atime_before_mtime': '访问时间早于修改时间（可能回溯）',
    'high_time_variance': '时间戳离散度过大'
  };
  return anomalyMessages[anomalyType] || anomalyType;
};

/**
 * Get severity level for an anomaly
 *
 * @param {string} anomalyType - Anomaly type code
 * @returns {string} Severity level: 'critical', 'warning', or 'info'
 */
export const getAnomalySeverity = (anomalyType) => {
  const severityMap = {
    'crtime_after_mtime': 'critical',
    'mtime_mismatch': 'warning',
    'atime_before_mtime': 'info',
    'high_time_variance': 'warning'
  };
  return severityMap[anomalyType] || 'info';
};

/**
 * Get color class for anomaly severity
 *
 * @param {string} severity - Severity level
 * @returns {string} Tailwind CSS color classes
 */
export const getAnomalyColorClass = (severity) => {
  const colorMap = {
    'critical': 'bg-red-100 text-red-700 border-red-200',
    'warning': 'bg-amber-100 text-amber-700 border-amber-200',
    'info': 'bg-blue-100 text-blue-700 border-blue-200'
  };
  return colorMap[severity] || colorMap['info'];
};

/**
 * Check if file has any anomalies
 *
 * @param {Object} file - File object with anomalies array
 * @returns {boolean} True if file has anomalies
 */
export const hasAnomalies = (file) => {
  return file.anomalies && file.anomalies.length > 0;
};

/**
 * Get highest severity level from file anomalies
 *
 * @param {Object} file - File object with anomalies array
 * @returns {string|null} Highest severity level or null
 */
export const getHighestAnomalySeverity = (file) => {
  if (!hasAnomalies(file)) return null;

  const severities = file.anomalies.map(getAnomalySeverity);
  if (severities.includes('critical')) return 'critical';
  if (severities.includes('warning')) return 'warning';
  return 'info';
};

export default {
  getClusterRelatedFiles,
  getFileRelatedClusters,
  formatAnomalyType,
  getAnomalySeverity,
  getAnomalyColorClass,
  hasAnomalies,
  getHighestAnomalySeverity
};
