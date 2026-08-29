import { createSlice, createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import type { ApiError, ForensicTask, TaskListResponse, TaskStatistics } from '../types/api';
import * as taskService from '../services/taskService';

export type LoadState = 'idle' | 'loading' | 'succeeded' | 'failed';

export interface TaskFilters {
  status: string;
  priority: string;
  [key: string]: unknown;
}

export interface TasksState {
  tasks: ForensicTask[];
  currentTask: ForensicTask | null;
  statistics: TaskStatistics | null;
  status: LoadState;
  error: unknown;
  filters: TaskFilters;
  pagination: { total: number; limit: number; offset: number };
}

const rejectPayload = (error: unknown) => {
  const err = error as ApiError;
  return (err?.data as unknown) ?? err?.message ?? 'request failed';
};

export const createTask = createAsyncThunk(
  'tasks/create',
  async (taskData: taskService.CreateTaskPayload, { rejectWithValue }) => {
    try {
      return await taskService.createTask(taskData);
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

export const fetchTasks = createAsyncThunk(
  'tasks/fetchAll',
  async (params: taskService.TaskListParams = {}, { rejectWithValue }) => {
    try {
      return await taskService.listTasks(params);
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

/** Silent background refresh — does NOT flip status to 'loading' (no spinner flash). */
export const fetchTasksSilent = createAsyncThunk(
  'tasks/fetchSilent',
  async (params: taskService.TaskListParams = {}, { rejectWithValue }) => {
    try {
      return await taskService.listTasks(params);
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

export const fetchTaskProgress = createAsyncThunk(
  'tasks/fetchProgress',
  async (taskId: string, { rejectWithValue }) => {
    try {
      const response = (await taskService.getTaskProgress(taskId)) as Record<string, unknown>;
      return { taskId, ...response };
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

export const cancelTask = createAsyncThunk(
  'tasks/cancel',
  async ({ taskId, reason }: { taskId: string; reason?: string }, { rejectWithValue }) => {
    try {
      const response = (await taskService.cancelTask(taskId, reason)) as Record<string, unknown>;
      return { taskId, ...response };
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

export const deleteTask = createAsyncThunk(
  'tasks/delete',
  async (taskId: string, { rejectWithValue }) => {
    try {
      const response = (await taskService.deleteTask(taskId)) as Record<string, unknown> | undefined;
      return { taskId, ...(response ?? {}) };
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

export const fetchTaskStatistics = createAsyncThunk(
  'tasks/fetchStatistics',
  async (_, { rejectWithValue }) => {
    try {
      return await taskService.getTaskStatistics();
    } catch (error) {
      return rejectWithValue(rejectPayload(error));
    }
  },
);

const initialState: TasksState = {
  tasks: [],
  currentTask: null,
  statistics: null,
  status: 'idle',
  error: null,
  filters: { status: 'all', priority: 'all' },
  pagination: { total: 0, limit: 20, offset: 0 },
};

const taskSlice = createSlice({
  name: 'tasks',
  initialState,
  reducers: {
    setFilters: (state, action: PayloadAction<Partial<TaskFilters>>) => {
      state.filters = { ...state.filters, ...action.payload };
    },
    clearError: (state) => {
      state.error = null;
    },
    updateTaskProgress: (state, action: PayloadAction<{ taskId: string } & Partial<ForensicTask>>) => {
      const idx = state.tasks.findIndex((t) => t.id === action.payload.taskId);
      if (idx !== -1) state.tasks[idx] = { ...state.tasks[idx], ...action.payload };
    },
    setCurrentTask: (state, action: PayloadAction<ForensicTask | null>) => {
      state.currentTask = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(createTask.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(createTask.fulfilled, (state, action) => {
        state.status = 'succeeded';
        state.tasks.push(action.payload);
      })
      .addCase(createTask.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })

      .addCase(fetchTasks.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchTasks.fulfilled, (state, action: PayloadAction<TaskListResponse>) => {
        state.status = 'succeeded';
        state.tasks = action.payload.tasks || [];
        if (action.payload.pagination) state.pagination = action.payload.pagination;
      })
      .addCase(fetchTasks.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })

      .addCase(fetchTasksSilent.fulfilled, (state, action: PayloadAction<TaskListResponse>) => {
        state.tasks = action.payload.tasks || [];
        if (action.payload.pagination) state.pagination = action.payload.pagination;
      })

      .addCase(fetchTaskProgress.fulfilled, (state, action) => {
        const idx = state.tasks.findIndex((t) => t.id === action.payload.taskId);
        if (idx !== -1) state.tasks[idx] = { ...state.tasks[idx], ...action.payload };
        if (state.currentTask?.id === action.payload.taskId) {
          state.currentTask = { ...state.currentTask, ...action.payload };
        }
      })

      .addCase(cancelTask.fulfilled, (state, action) => {
        const idx = state.tasks.findIndex((t) => t.id === action.payload.taskId);
        if (idx !== -1) state.tasks[idx].status = 'cancelled';
      })

      .addCase(deleteTask.fulfilled, (state, action) => {
        state.tasks = state.tasks.filter((t) => t.id !== action.payload.taskId);
      })

      .addCase(fetchTaskStatistics.fulfilled, (state, action) => {
        state.statistics = action.payload;
      });
  },
});

export const { setFilters, clearError, updateTaskProgress, setCurrentTask } = taskSlice.actions;
export default taskSlice.reducer;
