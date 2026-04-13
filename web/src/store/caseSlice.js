import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import * as caseGroupSvc from '../services/caseGroupService';
import * as taskService from '../services/taskService';

// ── Thunks ────────────────────────────────────────────────────────────────────

export const fetchCases = createAsyncThunk(
  'cases/fetchAll',
  async (_, { rejectWithValue }) => {
    try {
      return await caseGroupSvc.listCases();
    } catch (err) {
      return rejectWithValue(err.response?.data || err.message);
    }
  }
);

/**
 * createCaseWithTasks:
 *  1. Batch-create N tasks in C++ backend (one per image path)
 *  2. Create a Case record in Python/C++ linking all task IDs
 *  3. Return {case, tasks}
 */
export const createCaseWithTasks = createAsyncThunk(
  'cases/createWithTasks',
  async ({ name, description, imagePaths, priority = 'normal', androidAnalyze = false }, { rejectWithValue }) => {
    try {
      // Step 1 — create individual tasks
      const createdTasks = await Promise.all(
        imagePaths.map((path) =>
          taskService.createTask({
            image_path:      path,
            priority,
            case_description: description,
            llm_analyze:     true,
            llm_mode:        'smart',
            android_analyze: androidAnalyze,
          })
        )
      );
      const taskIds = createdTasks.map((t) => t.id);

      // Step 2 — create case linking those tasks
      const newCase = await caseGroupSvc.createCase(name, description, taskIds);

      return { case: newCase, tasks: createdTasks };
    } catch (err) {
      return rejectWithValue(err.response?.data || err.message);
    }
  }
);

export const startCrossAnalysis = createAsyncThunk(
  'cases/startCrossAnalysis',
  async ({ caseId, taskIds, filesDbPaths, caseDescription }, { rejectWithValue }) => {
    try {
      return await caseGroupSvc.startMultiImageAnalysis({
        caseId, taskIds, filesDbPaths, caseDescription,
      });
    } catch (err) {
      return rejectWithValue(err.response?.data || err.message);
    }
  }
);

// ── Slice ─────────────────────────────────────────────────────────────────────

const caseSlice = createSlice({
  name: 'cases',
  initialState: {
    cases:  [],
    status: 'idle',  // 'idle' | 'loading' | 'succeeded' | 'failed'
    error:  null,
    activeJobId: null,
  },
  reducers: {
    clearCaseError: (state) => { state.error = null; },
    setActiveJobId: (state, action) => { state.activeJobId = action.payload; },
    updateCaseStatus: (state, action) => {
      const { caseId, status, cross_analysis_job_id } = action.payload;
      const idx = state.cases.findIndex((c) => c.id === caseId);
      if (idx !== -1) {
        state.cases[idx].status = status;
        if (cross_analysis_job_id) state.cases[idx].cross_analysis_job_id = cross_analysis_job_id;
      }
    },
  },
  extraReducers: (builder) => {
    builder
      // fetchCases
      .addCase(fetchCases.pending,    (state)         => { state.status = 'loading'; })
      .addCase(fetchCases.fulfilled,  (state, action) => {
        state.status = 'succeeded';
        state.cases  = action.payload.cases || [];
      })
      .addCase(fetchCases.rejected,   (state, action) => { state.status = 'failed'; state.error = action.payload; })

      // createCaseWithTasks
      .addCase(createCaseWithTasks.pending,   (state)         => { state.status = 'loading'; })
      .addCase(createCaseWithTasks.fulfilled, (state, action) => {
        state.status = 'succeeded';
        state.cases.push(action.payload.case);
      })
      .addCase(createCaseWithTasks.rejected,  (state, action) => { state.status = 'failed'; state.error = action.payload; })

      // startCrossAnalysis
      .addCase(startCrossAnalysis.fulfilled, (state, action) => {
        state.activeJobId = action.payload.job_id;
        const idx = state.cases.findIndex((c) => c.id === action.payload.case_id);
        if (idx !== -1) state.cases[idx].status = 'analysing';
      });
  },
});

export const { clearCaseError, setActiveJobId, updateCaseStatus } = caseSlice.actions;
export default caseSlice.reducer;
