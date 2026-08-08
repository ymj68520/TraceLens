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
export const analyzeEventCluster = async (taskId, cluster) => {
  // 防御性验证：确保 cluster 对象有效
  if (!cluster || typeof cluster !== 'object') {
    throw new Error('Invalid cluster: cluster object is required');
  }
  if (!cluster?.timestamp || typeof cluster.timestamp !== 'number') {
    throw new Error('Invalid cluster: timestamp is required and must be a number');
  }
  if (!cluster?.event_type || typeof cluster.event_type !== 'string') {
    throw new Error('Invalid cluster: event_type is required and must be a string');
  }

  // bucket_seconds must match the window used to create the cluster. It flows
  // end-to-end: URL ?bucket= -> C++ GROUP BY -> cluster.bucket_seconds here ->
  // Python (timestamp / bucket_seconds). Default 60 preserves old behavior.
  const bucketSeconds = cluster.bucket_seconds || 60;

  return await pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    time_window: Math.floor(cluster.timestamp / bucketSeconds),
    event_type: cluster.event_type,
    parent_directory: cluster.parent_directory || "",
    bucket_seconds: bucketSeconds,
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
  // 防御性验证：确保 cluster 对象有效
  if (!cluster || typeof cluster !== 'object') {
    throw new Error('Invalid cluster: cluster object is required');
  }
  if (!cluster?.timestamp || typeof cluster.timestamp !== 'number') {
    throw new Error('Invalid cluster: timestamp is required and must be a number');
  }
  if (!cluster?.event_type || typeof cluster.event_type !== 'string') {
    throw new Error('Invalid cluster: event_type is required and must be a string');
  }

  const bucketSeconds = cluster.bucket_seconds || 60;

  return await pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    time_window: Math.floor(cluster.timestamp / bucketSeconds),
    event_type: cluster.event_type,
    parent_directory: cluster.parent_directory || "",
    bucket_seconds: bucketSeconds,
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
