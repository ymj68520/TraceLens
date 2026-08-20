import api, { pythonApi } from './api';

// Timeline Analysis
export const getComprehensiveTimeline = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/comprehensive', {
    params: { task_id: taskId, ...params },
  });
};

/**
 * 分析事件簇 (AI 研判)
 * 彻底切换到 Python 服务执行，不再使用 C++ 侧的 LLM 逻辑
 */
const getClusterDescriptor = (cluster) => {
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

export const analyzeEventCluster = async (taskId, cluster) => {
  if (!cluster || typeof cluster !== 'object') {
    throw new Error('Invalid cluster: cluster object is required');
  }
  const groupDescriptor = getClusterDescriptor(cluster);

  return await pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    group_descriptor: groupDescriptor,
  });
};

/**
 * 批量分析事件簇
 */
export const analyzeEventClustersBatch = async (taskId, clusters) => {
  const promises = clusters.map(cluster => analyzeEventCluster(taskId, cluster));
  return Promise.all(promises);
};

/**
 * 重新分析事件簇
 */
export const reanalyzeEventCluster = async (taskId, cluster) => {
  if (!cluster || typeof cluster !== 'object') {
    throw new Error('Invalid cluster: cluster object is required');
  }
  const groupDescriptor = getClusterDescriptor(cluster);

  return await pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    group_descriptor: groupDescriptor,
    prompt: "请重新审视该事件簇，深度挖掘潜在威胁。",
  });
};

export const getAnalyzedEventClusters = async (taskId) => {
  return await api.get('/api/forensics/timeline/clusters/analyzed', {
    params: { task_id: taskId },
  });
};

export const getTimelineDetails = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/details', {
    params: { task_id: taskId, ...params },
  });
};

export const getTimelineDistribution = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/distribution', {
    params: { task_id: taskId, ...params },
  });
};

export const getFileActivity = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/file-activity', {
    params: { task_id: taskId, ...params },
  });
};

export const getSuspiciousPatterns = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/suspicious-patterns', {
    params: { task_id: taskId, ...params },
  });
};

export const getUserActivity = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/user-activity', {
    params: { task_id: taskId, ...params },
  });
};

// File Analysis
export const getLargestFiles = async (taskId, limit = 50) => {
  return await api.get('/api/forensics/files/largest', {
    params: { task_id: taskId, limit },
  });
};

export const getRecentFiles = async (taskId, hours = 24) => {
  return await api.get('/api/forensics/files/recent', {
    params: { task_id: taskId, hours },
  });
};

export const getSuspiciousFiles = async (taskId) => {
  return await api.get('/api/forensics/files/suspicious', {
    params: { task_id: taskId },
  });
};

export const getDuplicateFiles = async (taskId) => {
  return await api.get('/api/forensics/files/duplicates', {
    params: { task_id: taskId },
  });
};

export const getExtensionAnalysis = async (taskId) => {
  return await api.get('/api/forensics/files/extensions-analysis', {
    params: { task_id: taskId },
  });
};

// Android Forensics
export const getAndroidCommunication = async (taskId) => {
  return await api.get('/api/forensics/android/communication-summary', {
    params: { task_id: taskId },
  });
};

export const getAndroidAppUsage = async (taskId) => {
  return await api.get('/api/forensics/android/app-usage', {
    params: { task_id: taskId },
  });
};

export const getAndroidDeviceInfo = async (taskId) => {
  return await api.get('/api/forensics/android/device-info', {
    params: { task_id: taskId },
  });
};

export const getAndroidMediaAnalysis = async (taskId) => {
  return await api.get('/api/forensics/android/media-analysis', {
    params: { task_id: taskId },
  });
};

// MIUI Offline-Backup Forensics
// These tables (miui_backup_manifest / installed_apps / app_db_inventory)
// are populated only by the miui-backup source mode.
export const getMiuiOverview = async (taskId) => {
  return await api.get('/api/forensics/android/miui-overview', {
    params: { task_id: taskId },
  });
};

export const getMiuiInstalledApps = async (taskId) => {
  return await api.get('/api/forensics/android/miui-installed-apps', {
    params: { task_id: taskId },
  });
};

export const getMiuiDbInventory = async (taskId) => {
  return await api.get('/api/forensics/android/miui-db-inventory', {
    params: { task_id: taskId },
  });
};

export const getMiuiQqntOverview = async (taskId) => {
  return await api.get('/api/forensics/android/miui-qqnt-overview', {
    params: { task_id: taskId },
  });
};

export const getMiuiQqntArtifacts = async (taskId, params = {}) => {
  return await api.get('/api/forensics/android/miui-qqnt-artifacts', {
    params: { task_id: taskId, ...params },
  });
};

export const getMiuiQqntRecords = async (taskId, params = {}) => {
  return await api.get('/api/forensics/android/miui-qqnt-records', {
    params: { task_id: taskId, ...params },
  });
};

export const getMiuiWechatOverview = async (taskId) => {
  return await api.get('/api/forensics/android/miui-wechat-overview', {
    params: { task_id: taskId },
  });
};

export const getMiuiWechatArtifacts = async (taskId, params = {}) => {
  return await api.get('/api/forensics/android/miui-wechat-artifacts', {
    params: { task_id: taskId, ...params },
  });
};

export const getMiuiWechatRecords = async (taskId, params = {}) => {
  return await api.get('/api/forensics/android/miui-wechat-records', {
    params: { task_id: taskId, ...params },
  });
};

export const getAndroidLlmSummary = async (taskId) => {
  return await api.get('/api/forensics/android/llm-summary', {
    params: { task_id: taskId },
  });
};

// Statistics
export const getStatisticsOverview = async (taskId) => {
  return await api.get('/api/forensics/statistics/overview', {
    params: { task_id: taskId },
  });
};

export const getFileDistribution = async (taskId) => {
  return await api.get('/api/forensics/statistics/file-distribution', {
    params: { task_id: taskId },
  });
};

export const getActivityPatterns = async (taskId) => {
  return await api.get('/api/forensics/statistics/activity-patterns', {
    params: { task_id: taskId },
  });
};

export const getDeletedFilesAnalysis = async (taskId) => {
  return await api.get('/api/forensics/statistics/deleted-files-analysis', {
    params: { task_id: taskId },
  });
};
