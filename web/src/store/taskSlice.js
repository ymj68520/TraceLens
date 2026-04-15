import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import * as taskService from '../services/taskService';

// ── Thunks ──────────────────────────────────────────────────────────────────

export const createTask = createAsyncThunk(
  'tasks/create',
  async (taskData, { rejectWithValue }) => {
    try {
      return await taskService.createTask(taskData);
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

export const fetchTasks = createAsyncThunk(
  'tasks/fetchAll',
  async (params = {}, { rejectWithValue }) => {
    try {
      return await taskService.listTasks(params);
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

/**
 * Silent background refresh — does NOT set status='loading'.
 * Use this for polling so the UI doesn't flash/re-render.
 */
export const fetchTasksSilent = createAsyncThunk(
  'tasks/fetchSilent',
  async (params = {}, { rejectWithValue }) => {
    try {
      return await taskService.listTasks(params);
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

export const fetchTaskProgress = createAsyncThunk(
  'tasks/fetchProgress',
  async (taskId, { rejectWithValue }) => {
    try {
      const response = await taskService.getTaskProgress(taskId);
      return { taskId, ...response };
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

export const cancelTask = createAsyncThunk(
  'tasks/cancel',
  async ({ taskId, reason }, { rejectWithValue }) => {
    try {
      const response = await taskService.cancelTask(taskId, reason);
      return { taskId, ...response };
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

export const deleteTask = createAsyncThunk(
  'tasks/delete',
  async (taskId, { rejectWithValue }) => {
    try {
      const response = await taskService.deleteTask(taskId);
      return { taskId, ...response };
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

export const fetchTaskStatistics = createAsyncThunk(
  'tasks/fetchStatistics',
  async (_, { rejectWithValue }) => {
    try {
      return await taskService.getTaskStatistics();
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

// ── Slice ────────────────────────────────────────────────────────────────────

const taskSlice = createSlice({
  name: 'tasks',
  initialState: {
    tasks: [],
    currentTask: null,
    statistics: null,
    status: 'idle',   // 'idle' | 'loading' | 'succeeded' | 'failed'
    error: null,
    filters: { status: 'all', priority: 'all' },
    pagination: { total: 0, limit: 20, offset: 0 },
  },
  reducers: {
    setFilters: (state, action) => {
      state.filters = { ...state.filters, ...action.payload };
    },
    clearError: (state) => { state.error = null; },
    updateTaskProgress: (state, action) => {
      const idx = state.tasks.findIndex((t) => t.id === action.payload.taskId);
      if (idx !== -1) state.tasks[idx] = { ...state.tasks[idx], ...action.payload };
    },
    setCurrentTask: (state, action) => { state.currentTask = action.payload; },
  },
  extraReducers: (builder) => {
    builder
      // createTask
      .addCase(createTask.pending,    (state)          => { state.status = 'loading'; })
      .addCase(createTask.fulfilled,  (state, action)  => { state.status = 'succeeded'; state.tasks.push(action.payload); })
      .addCase(createTask.rejected,   (state, action)  => { state.status = 'failed'; state.error = action.payload; })

      // fetchTasks — shows loading spinner (initial / filter change)
      .addCase(fetchTasks.pending,    (state)          => { state.status = 'loading'; })
      .addCase(fetchTasks.fulfilled,  (state, action)  => {
        state.status = 'succeeded';
        state.tasks = action.payload.tasks || [];
        if (action.payload.pagination) state.pagination = action.payload.pagination;
      })
      .addCase(fetchTasks.rejected,   (state, action)  => { state.status = 'failed'; state.error = action.payload; })

      // fetchTasksSilent — background poll; does NOT touch status
      .addCase(fetchTasksSilent.fulfilled, (state, action) => {
        state.tasks = action.payload.tasks || [];
        if (action.payload.pagination) state.pagination = action.payload.pagination;
      })

      // fetchTaskProgress
      .addCase(fetchTaskProgress.fulfilled, (state, action) => {
        const idx = state.tasks.findIndex((t) => t.id === action.payload.taskId);
        if (idx !== -1) state.tasks[idx] = { ...state.tasks[idx], ...action.payload };
        if (state.currentTask?.id === action.payload.taskId)
          state.currentTask = { ...state.currentTask, ...action.payload };
      })

      // cancelTask
      .addCase(cancelTask.fulfilled, (state, action) => {
        const idx = state.tasks.findIndex((t) => t.id === action.payload.taskId);
        if (idx !== -1) state.tasks[idx].status = 'cancelled';
      })

      // deleteTask
      .addCase(deleteTask.fulfilled, (state, action) => {
        state.tasks = state.tasks.filter((t) => t.id !== action.payload.taskId);
      })

      // fetchTaskStatistics
      .addCase(fetchTaskStatistics.fulfilled, (state, action) => {
        state.statistics = action.payload;
      });
  },
});

export const { setFilters, clearError, updateTaskProgress, setCurrentTask } = taskSlice.actions;
export default taskSlice.reducer;
