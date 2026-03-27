import { createSlice } from '@reduxjs/toolkit';

const intelligenceSlice = createSlice({
  name: 'intelligence',
  initialState: {
    // Report generation jobs: { [taskId]: { jobId, status, progress, currentStep, detail } }
    activeAnalysisJobs: {},
    // File batch analysis jobs: { [taskId]: { jobId, status, progress, message } }
    activeBatchJobs: {},
    // Refresh flags for case intelligence
    refreshFlags: {
      files: false, // 当文件描述变化时设置为true
      clusters: false // 当事件簇描述变化时设置为true
    },
  },
  reducers: {
    // --- Case Analysis Jobs ---
    setAnalysisJob: (state, action) => {
      const { taskId, jobId } = action.payload;
      state.activeAnalysisJobs[taskId] = { jobId, status: 'running', progress: 0, currentStep: '初始化' };
    },
    updateAnalysisProgress: (state, action) => {
      const { taskId, ...data } = action.payload;
      if (state.activeAnalysisJobs[taskId]) {
        state.activeAnalysisJobs[taskId] = { ...state.activeAnalysisJobs[taskId], ...data };
      }
    },
    clearAnalysisJob: (state, action) => {
      delete state.activeAnalysisJobs[action.payload.taskId];
    },

    // --- File Batch Jobs (AI Descriptions) ---
    setBatchJob: (state, action) => {
      const { taskId, jobId } = action.payload;
      state.activeBatchJobs[taskId] = {
        jobId,
        status: 'running',
        progress: 0,
        message: '启动批量分析...',
      };
    },
    updateBatchProgress: (state, action) => {
      const { taskId, progress, message, status } = action.payload;
      if (state.activeBatchJobs[taskId]) {
        if (status) state.activeBatchJobs[taskId].status = status;
        if (progress !== undefined) state.activeBatchJobs[taskId].progress = progress;
        if (message) state.activeBatchJobs[taskId].message = message;
      }
    },
    clearBatchJob: (state, action) => {
      delete state.activeBatchJobs[action.payload.taskId];
    },

    // --- Refresh Flags ---    
    setRefreshFlag: (state, action) => {
      const { type } = action.payload;
      if (type === 'files') {
        state.refreshFlags.files = true;
      } else if (type === 'clusters') {
        state.refreshFlags.clusters = true;
      }
    },
    clearRefreshFlag: (state, action) => {
      const { type } = action.payload;
      if (type === 'files') {
        state.refreshFlags.files = false;
      } else if (type === 'clusters') {
        state.refreshFlags.clusters = false;
      }
    },
  },
});

export const { 
  setAnalysisJob, updateAnalysisProgress, clearAnalysisJob,
  setBatchJob, updateBatchProgress, clearBatchJob,
  setRefreshFlag, clearRefreshFlag
} = intelligenceSlice.actions;

export default intelligenceSlice.reducer;
