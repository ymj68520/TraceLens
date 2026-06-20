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
 *  1. Batch-create N tasks in C++ backend (one per new image path)
 *  2. Merge any already-completed task IDs the user chose to associate
 *  3. Create a Case record in Python/C++ linking all task IDs
 *  4. Pre-populate the case-level analysis state for associated (already-analyzed)
 *     tasks so a subsequent cross-image run REUSES them instead of re-analyzing.
 *  5. Return {case, tasks}
 */
export const createCaseWithTasks = createAsyncThunk(
  'cases/createWithTasks',
  async ({ name, description, imagePaths = [], priority = 'normal', androidAnalyze = false, associateTaskIds = [] }, { rejectWithValue }) => {
    try {
      // Step 1 — create individual tasks for each NEW image path
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
      const newTaskIds = createdTasks.map((t) => t.id);

      // Step 2 — merge associated (already-completed) task IDs, de-duplicated
      const taskIds = [...new Set([...newTaskIds, ...associateTaskIds])];

      // Step 3 — create case linking all tasks
      const newCase = await caseGroupSvc.createCase(name, description, taskIds);

      // Step 4 — pre-populate analysis state so associated already-analyzed
      // tasks are reused (not re-analyzed). Safe to call with the full list:
      // the backend skips not-completed tasks and is idempotent.
      if (associateTaskIds.length > 0) {
        try {
          await caseGroupSvc.associateTasksToCase(newCase.id, associateTaskIds);
        } catch (e) {
          // Non-fatal: case was created; reuse-state can be repaired later.
          console.warn('associateTasksToCase after create failed:', e);
        }
      }

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

/**
 * associateTasksToCase — add already-completed tasks to an existing case.
 * The backend pre-populates each task's case-level analysis state, so
 * already-analyzed tasks are reused (not re-analyzed) by the next cross-image run.
 * Returns the per-task breakdown from the backend.
 */
export const associateTasks = createAsyncThunk(
  'cases/associateTasks',
  async ({ caseId, taskIds }, { rejectWithValue }) => {
    try {
      return await caseGroupSvc.associateTasksToCase(caseId, taskIds);
    } catch (err) {
      return rejectWithValue(err.response?.data || err.message);
    }
  }
);

/**
 * deleteCase — delete only the case record (tasks remain).
 */
export const deleteCase = createAsyncThunk(
  'cases/delete',
  async (caseId, { rejectWithValue }) => {
    try {
      await caseGroupSvc.deleteCase(caseId);
      return { caseId };
    } catch (err) {
      return rejectWithValue(err.response?.data || err.message);
    }
  }
);

/**
 * deleteCaseWithTasks — delete associated tasks first, then the case.
 * @param {{ caseId: string, taskIds: string[] }}
 */
export const deleteCaseWithTasks = createAsyncThunk(
  'cases/deleteWithTasks',
  async ({ caseId, taskIds }, { rejectWithValue }) => {
    try {
      // Step 1 — delete all associated tasks (best-effort, don't fail the whole op)
      const deleteResults = await Promise.allSettled(
        taskIds.map((taskId) => taskService.deleteTask(taskId))
      );
      const deletedTaskIds = taskIds.filter(
        (_, i) => deleteResults[i].status === 'fulfilled'
      );

      // Step 2 — delete the case record itself
      await caseGroupSvc.deleteCase(caseId);

      return { caseId, deletedTaskIds };
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
      })

      // deleteCase (case only)
      .addCase(deleteCase.fulfilled, (state, action) => {
        state.cases = state.cases.filter((c) => c.id !== action.payload.caseId);
      })

      // deleteCaseWithTasks
      .addCase(deleteCaseWithTasks.fulfilled, (state, action) => {
        state.cases = state.cases.filter((c) => c.id !== action.payload.caseId);
      });
  },
});

export const { clearCaseError, setActiveJobId, updateCaseStatus } = caseSlice.actions;
export default caseSlice.reducer;
