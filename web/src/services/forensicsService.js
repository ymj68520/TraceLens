import api from './api';

// Timeline Analysis
export const getComprehensiveTimeline = async (taskId, params = {}) => {
  return await api.get('/api/forensics/timeline/comprehensive', {
    params: { task_id: taskId, ...params },
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
