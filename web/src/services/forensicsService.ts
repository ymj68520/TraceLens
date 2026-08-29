import api, { pythonApi } from './api';
import type { ClusterDescriptor, EventCluster } from '../types/api';

// ── Timeline ────────────────────────────────────────────────────────────────

export const getComprehensiveTimeline = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/timeline/comprehensive', { params: { task_id: taskId, ...params } });

/**
 * The backend requires a fully-formed group descriptor; reject anything
 * malformed before it crosses the wire.
 */
const getClusterDescriptor = (cluster: EventCluster | null | undefined): ClusterDescriptor => {
  const descriptor = cluster?.group_descriptor;
  if (!descriptor || typeof descriptor !== 'object') {
    throw new Error('Invalid cluster: backend group descriptor is required');
  }
  if (!Number.isInteger(Number(descriptor.bucket_index)) || !Number.isInteger(Number(descriptor.bucket_seconds))) {
    throw new Error('Invalid cluster: backend group descriptor bucket values are required');
  }
  if (!descriptor.event_type || typeof descriptor.event_type !== 'string') {
    throw new Error('Invalid cluster: backend group descriptor event_type is required');
  }
  return {
    bucket_index: Number(descriptor.bucket_index),
    bucket_seconds: Number(descriptor.bucket_seconds),
    event_type: descriptor.event_type,
    parent_directory: descriptor.parent_directory || '',
  };
};

export const analyzeEventCluster = (taskId: string, cluster: EventCluster) => {
  const groupDescriptor = getClusterDescriptor(cluster);
  return pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    group_descriptor: groupDescriptor,
  });
};

export const analyzeEventClustersBatch = (taskId: string, clusters: EventCluster[]) =>
  Promise.all(clusters.map((cluster) => analyzeEventCluster(taskId, cluster)));

export const reanalyzeEventCluster = (taskId: string, cluster: EventCluster) => {
  const groupDescriptor = getClusterDescriptor(cluster);
  return pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    group_descriptor: groupDescriptor,
    prompt: '请重新审视该事件簇，深度挖掘潜在威胁。',
  });
};

export const getAnalyzedEventClusters = (taskId: string) =>
  api.get('/api/forensics/timeline/clusters/analyzed', { params: { task_id: taskId } });

export const getTimelineDetails = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/timeline/details', { params: { task_id: taskId, ...params } });

export const getTimelineDistribution = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/timeline/distribution', { params: { task_id: taskId, ...params } });

export const getFileActivity = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/timeline/file-activity', { params: { task_id: taskId, ...params } });

export const getSuspiciousPatterns = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/timeline/suspicious-patterns', { params: { task_id: taskId, ...params } });

export const getUserActivity = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/timeline/user-activity', { params: { task_id: taskId, ...params } });

// ── Files ───────────────────────────────────────────────────────────────────

export const getLargestFiles = (taskId: string, limit = 50) =>
  api.get('/api/forensics/files/largest', { params: { task_id: taskId, limit } });

export const getRecentFiles = (taskId: string, hours = 24) =>
  api.get('/api/forensics/files/recent', { params: { task_id: taskId, hours } });

export const getSuspiciousFiles = (taskId: string) =>
  api.get('/api/forensics/files/suspicious', { params: { task_id: taskId } });

export const getDuplicateFiles = (taskId: string) =>
  api.get('/api/forensics/files/duplicates', { params: { task_id: taskId } });

export const getExtensionAnalysis = (taskId: string) =>
  api.get('/api/forensics/files/extensions-analysis', { params: { task_id: taskId } });

// ── Android ─────────────────────────────────────────────────────────────────

export const getAndroidCommunication = (taskId: string) =>
  api.get('/api/forensics/android/communication-summary', { params: { task_id: taskId } });

export const getAndroidAppUsage = (taskId: string) =>
  api.get('/api/forensics/android/app-usage', { params: { task_id: taskId } });

export const getAndroidDeviceInfo = (taskId: string) =>
  api.get('/api/forensics/android/device-info', { params: { task_id: taskId } });

export const getAndroidMediaAnalysis = (taskId: string) =>
  api.get('/api/forensics/android/media-analysis', { params: { task_id: taskId } });

// MIUI offline-backup tables (populated only by the miui-backup source mode)
export const getMiuiOverview = (taskId: string) =>
  api.get('/api/forensics/android/miui-overview', { params: { task_id: taskId } });

export const getMiuiInstalledApps = (taskId: string) =>
  api.get('/api/forensics/android/miui-installed-apps', { params: { task_id: taskId } });

export const getMiuiDbInventory = (taskId: string) =>
  api.get('/api/forensics/android/miui-db-inventory', { params: { task_id: taskId } });

export const getMiuiQqntOverview = (taskId: string) =>
  api.get('/api/forensics/android/miui-qqnt-overview', { params: { task_id: taskId } });

export const getMiuiQqntArtifacts = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/android/miui-qqnt-artifacts', { params: { task_id: taskId, ...params } });

export const getMiuiQqntRecords = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/android/miui-qqnt-records', { params: { task_id: taskId, ...params } });

export const getMiuiWechatOverview = (taskId: string) =>
  api.get('/api/forensics/android/miui-wechat-overview', { params: { task_id: taskId } });

export const getMiuiWechatArtifacts = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/android/miui-wechat-artifacts', { params: { task_id: taskId, ...params } });

export const getMiuiWechatRecords = (taskId: string, params: Record<string, unknown> = {}) =>
  api.get('/api/forensics/android/miui-wechat-records', { params: { task_id: taskId, ...params } });

export const getAndroidLlmSummary = (taskId: string) =>
  api.get('/api/forensics/android/llm-summary', { params: { task_id: taskId } });

// ── Statistics ──────────────────────────────────────────────────────────────

export const getStatisticsOverview = (taskId: string) =>
  api.get('/api/forensics/statistics/overview', { params: { task_id: taskId } });

export const getFileDistribution = (taskId: string) =>
  api.get('/api/forensics/statistics/file-distribution', { params: { task_id: taskId } });

export const getActivityPatterns = (taskId: string) =>
  api.get('/api/forensics/statistics/activity-patterns', { params: { task_id: taskId } });

export const getDeletedFilesAnalysis = (taskId: string) =>
  api.get('/api/forensics/statistics/deleted-files-analysis', { params: { task_id: taskId } });
