/**
 * Bidirectional cluster ↔ file association with time-anomaly detection.
 */
import { pythonApi } from './api';

export interface ClusterRef {
  time_window: number;
  event_type: string;
  parent_directory?: string;
}

export const getClusterRelatedFiles = async (taskId: string, cluster: ClusterRef, limit = 100) => {
  const response = await pythonApi.post('/api/associations/cluster-files', {
    task_id: taskId,
    time_window: cluster.time_window,
    event_type: cluster.event_type,
    parent_directory: cluster.parent_directory || '',
    limit,
  });
  return response;
};

export const getFileRelatedClusters = async (taskId: string, file: { file_path: string }, limit = 100) => {
  const response = await pythonApi.post('/api/associations/file-clusters', {
    task_id: taskId,
    file_path: file.file_path,
    limit,
  });
  return response;
};

const ANOMALY_MESSAGES: Record<string, string> = {
  mtime_mismatch: '修改时间与事件时间差异过大',
  crtime_after_mtime: '创建时间晚于修改时间（异常）',
  atime_before_mtime: '访问时间早于修改时间（可能回溯）',
  high_time_variance: '时间戳离散度过大',
};

export const formatAnomalyType = (anomalyType: string): string =>
  ANOMALY_MESSAGES[anomalyType] || anomalyType;

export type AnomalySeverity = 'critical' | 'warning' | 'info';

const ANOMALY_SEVERITY: Record<string, AnomalySeverity> = {
  crtime_after_mtime: 'critical',
  mtime_mismatch: 'warning',
  atime_before_mtime: 'info',
  high_time_variance: 'warning',
};

export const getAnomalySeverity = (anomalyType: string): AnomalySeverity =>
  ANOMALY_SEVERITY[anomalyType] || 'info';
