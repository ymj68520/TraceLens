import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface AnalysisJobState {
  jobId: string;
  status: string;
  progress: number;
  currentStep?: string;
  message?: string;
}

interface IntelligenceState {
  /** Report-generation jobs keyed by taskId. */
  activeAnalysisJobs: Record<string, AnalysisJobState>;
  /** File batch (AI description) jobs keyed by taskId. */
  activeBatchJobs: Record<string, AnalysisJobState>;
  refreshFlags: { files: boolean; clusters: boolean };
}

const initialState: IntelligenceState = {
  activeAnalysisJobs: {},
  activeBatchJobs: {},
  refreshFlags: { files: false, clusters: false },
};

const intelligenceSlice = createSlice({
  name: 'intelligence',
  initialState,
  reducers: {
    setAnalysisJob: (state, action: PayloadAction<{ taskId: string; jobId: string }>) => {
      const { taskId, jobId } = action.payload;
      state.activeAnalysisJobs[taskId] = { jobId, status: 'running', progress: 0, currentStep: '初始化' };
    },
    updateAnalysisProgress: (
      state,
      action: PayloadAction<{ taskId: string } & Partial<AnalysisJobState>>,
    ) => {
      const { taskId, ...data } = action.payload;
      if (state.activeAnalysisJobs[taskId]) {
        state.activeAnalysisJobs[taskId] = { ...state.activeAnalysisJobs[taskId], ...data };
      }
    },
    clearAnalysisJob: (state, action: PayloadAction<{ taskId: string }>) => {
      delete state.activeAnalysisJobs[action.payload.taskId];
    },

    setBatchJob: (state, action: PayloadAction<{ taskId: string; jobId: string }>) => {
      const { taskId, jobId } = action.payload;
      state.activeBatchJobs[taskId] = { jobId, status: 'running', progress: 0, message: '启动批量分析...' };
    },
    updateBatchProgress: (
      state,
      action: PayloadAction<{ taskId: string; progress?: number; message?: string; status?: string }>,
    ) => {
      const { taskId, progress, message, status } = action.payload;
      const job = state.activeBatchJobs[taskId];
      if (job) {
        if (status) job.status = status;
        if (progress !== undefined) job.progress = progress;
        if (message) job.message = message;
      }
    },
    clearBatchJob: (state, action: PayloadAction<{ taskId: string }>) => {
      delete state.activeBatchJobs[action.payload.taskId];
    },

    setRefreshFlag: (state, action: PayloadAction<{ type: 'files' | 'clusters' }>) => {
      state.refreshFlags[action.payload.type] = true;
    },
    clearRefreshFlag: (state, action: PayloadAction<{ type: 'files' | 'clusters' }>) => {
      state.refreshFlags[action.payload.type] = false;
    },
  },
});

export const {
  setAnalysisJob,
  updateAnalysisProgress,
  clearAnalysisJob,
  setBatchJob,
  updateBatchProgress,
  clearBatchJob,
  setRefreshFlag,
  clearRefreshFlag,
} = intelligenceSlice.actions;
export default intelligenceSlice.reducer;
