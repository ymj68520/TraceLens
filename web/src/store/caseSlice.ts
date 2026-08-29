import { createSlice, createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import type { ApiError, ForensicCase } from '../types/api';
import * as caseGroupSvc from '../services/caseGroupService';
import * as taskService from '../services/taskService';
import type { LoadState } from './taskSlice';

const rejectPayload = (error: unknown) => {
  const err = error as ApiError;
  return (err?.data as unknown) ?? err?.message ?? 'request failed';
};

export const fetchCases = createAsyncThunk('cases/fetchAll', async (_, { rejectWithValue }) => {
  try {
    return await caseGroupSvc.listCases();
  } catch (err) {
    return rejectWithValue(rejectPayload(err));
  }
});

export interface CreateCaseWithTasksArgs {
  name: string;
  description: string;
  imagePaths?: string[];
  priority?: string;
  androidAnalyze?: boolean;
  associateTaskIds?: string[];
}

/**
 * 1. Batch-create N tasks (one per new image path)
 * 2. Merge already-completed task IDs the user chose to associate
 * 3. Create the case record linking all task IDs
 * 4. Pre-populate case-level analysis state for associated tasks so the next
 *    cross-image run REUSES them instead of re-analyzing
 */
export const createCaseWithTasks = createAsyncThunk(
  'cases/createWithTasks',
  async (
    {
      name,
      description,
      imagePaths = [],
      priority = 'normal',
      androidAnalyze = false,
      associateTaskIds = [],
    }: CreateCaseWithTasksArgs,
    { rejectWithValue },
  ) => {
    try {
      const createdTasks = await Promise.all(
        imagePaths.map((path) =>
          taskService.createTask({
            image_path: path,
            priority,
            case_description: description,
            llm_analyze: true,
            llm_mode: 'smart',
            android_analyze: androidAnalyze,
          }),
        ),
      );
      const newTaskIds = createdTasks.map((t) => t.id);
      const taskIds = [...new Set([...newTaskIds, ...associateTaskIds])];
      const newCase = await caseGroupSvc.createCase(name, description, taskIds);

      if (associateTaskIds.length > 0) {
        try {
          await caseGroupSvc.associateTasksToCase(newCase.id, associateTaskIds);
        } catch (e) {
          // Non-fatal: the case exists; reuse-state can be repaired later.
          console.warn('associateTasksToCase after create failed:', e);
        }
      }

      return { case: newCase, tasks: createdTasks };
    } catch (err) {
      return rejectWithValue(rejectPayload(err));
    }
  },
);

export const startCrossAnalysis = createAsyncThunk(
  'cases/startCrossAnalysis',
  async (
    {
      caseId,
      taskIds,
      filesDbPaths,
      caseDescription,
    }: { caseId: string; taskIds: string[]; filesDbPaths: string[]; caseDescription?: string },
    { rejectWithValue },
  ) => {
    try {
      return await caseGroupSvc.startMultiImageAnalysis({ caseId, taskIds, filesDbPaths, caseDescription });
    } catch (err) {
      return rejectWithValue(rejectPayload(err));
    }
  },
);

export const associateTasks = createAsyncThunk(
  'cases/associateTasks',
  async ({ caseId, taskIds }: { caseId: string; taskIds: string[] }, { rejectWithValue }) => {
    try {
      return await caseGroupSvc.associateTasksToCase(caseId, taskIds);
    } catch (err) {
      return rejectWithValue(rejectPayload(err));
    }
  },
);

export const deleteCase = createAsyncThunk(
  'cases/delete',
  async (caseId: string, { rejectWithValue }) => {
    try {
      await caseGroupSvc.deleteCase(caseId);
      return { caseId };
    } catch (err) {
      return rejectWithValue(rejectPayload(err));
    }
  },
);

export const deleteCaseWithTasks = createAsyncThunk(
  'cases/deleteWithTasks',
  async ({ caseId, taskIds }: { caseId: string; taskIds: string[] }, { rejectWithValue }) => {
    try {
      const deleteResults = await Promise.allSettled(
        taskIds.map((taskId) => taskService.deleteTask(taskId)),
      );
      const deletedTaskIds = taskIds.filter((_, i) => deleteResults[i].status === 'fulfilled');
      await caseGroupSvc.deleteCase(caseId);
      return { caseId, deletedTaskIds };
    } catch (err) {
      return rejectWithValue(rejectPayload(err));
    }
  },
);

export interface CasesState {
  cases: ForensicCase[];
  status: LoadState;
  error: unknown;
  activeJobId: string | null;
}

const initialState: CasesState = {
  cases: [],
  status: 'idle',
  error: null,
  activeJobId: null,
};

const caseSlice = createSlice({
  name: 'cases',
  initialState,
  reducers: {
    clearCaseError: (state) => {
      state.error = null;
    },
    setActiveJobId: (state, action: PayloadAction<string | null>) => {
      state.activeJobId = action.payload;
    },
    updateCaseStatus: (
      state,
      action: PayloadAction<{ caseId: string; status: string; cross_analysis_job_id?: string }>,
    ) => {
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
      .addCase(fetchCases.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchCases.fulfilled, (state, action) => {
        state.status = 'succeeded';
        state.cases = action.payload.cases || [];
      })
      .addCase(fetchCases.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })

      .addCase(createCaseWithTasks.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(createCaseWithTasks.fulfilled, (state, action) => {
        state.status = 'succeeded';
        state.cases.push(action.payload.case);
      })
      .addCase(createCaseWithTasks.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })

      .addCase(startCrossAnalysis.fulfilled, (state, action) => {
        state.activeJobId = action.payload.job_id ?? null;
        const idx = state.cases.findIndex((c) => c.id === action.payload.case_id);
        if (idx !== -1) state.cases[idx].status = 'analysing';
      })

      .addCase(deleteCase.fulfilled, (state, action) => {
        state.cases = state.cases.filter((c) => c.id !== action.payload.caseId);
      })

      .addCase(deleteCaseWithTasks.fulfilled, (state, action) => {
        state.cases = state.cases.filter((c) => c.id !== action.payload.caseId);
      });
  },
});

export const { clearCaseError, setActiveJobId, updateCaseStatus } = caseSlice.actions;
export default caseSlice.reducer;
