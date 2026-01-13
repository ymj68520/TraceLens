import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import * as taskService from '../services/taskService';

export const createTask = createAsyncThunk(
  'tasks/create',
  async (taskData, { rejectWithValue }) => {
    try {
      const response = await taskService.createTask(taskData);
      return response;
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

export const fetchTasks = createAsyncThunk(
  'tasks/fetchAll',
  async (params = {}, { rejectWithValue }) => {
    try {
      const response = await taskService.listTasks(params);
      return response;
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

export const fetchTaskStatistics = createAsyncThunk(
  'tasks/fetchStatistics',
  async (_, { rejectWithValue }) => {
    try {
      const response = await taskService.getTaskStatistics();
      return response;
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  }
);

const taskSlice = createSlice({
  name: 'tasks',
  initialState: {
    tasks: [],
    currentTask: null,
    statistics: null,
    status: 'idle',
    error: null,
    filters: {
      status: 'all',
      priority: 'all',
    },
    pagination: {
      total: 0,
      limit: 20,
      offset: 0,
    },
  },
  reducers: {
    setFilters: (state, action) => {
      state.filters = { ...state.filters, ...action.payload };
    },
    clearError: (state) => {
      state.error = null;
    },
    updateTaskProgress: (state, action) => {
      const index = state.tasks.findIndex((t) => t.id === action.payload.taskId);
      if (index !== -1) {
        state.tasks[index] = {
          ...state.tasks[index],
          ...action.payload,
        };
      }
    },
    setCurrentTask: (state, action) => {
      state.currentTask = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      // Create task
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
      // Fetch tasks
      .addCase(fetchTasks.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchTasks.fulfilled, (state, action) => {
        state.status = 'succeeded';
        console.log('fetchTasks fulfilled - action.payload:', JSON.stringify(action.payload, null, 2));
        console.log('fetchTasks fulfilled - tasks array:', action.payload.tasks);
        console.log('fetchTasks fulfilled - tasks length:', action.payload.tasks?.length);
        state.tasks = action.payload.tasks || [];
        if (action.payload.pagination) {
          state.pagination = action.payload.pagination;
        }
      })
      .addCase(fetchTasks.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })
      // Fetch task progress
      .addCase(fetchTaskProgress.fulfilled, (state, action) => {
        const index = state.tasks.findIndex((t) => t.id === action.payload.taskId);
        if (index !== -1) {
          state.tasks[index] = {
            ...state.tasks[index],
            ...action.payload,
          };
        }
        if (state.currentTask?.id === action.payload.taskId) {
          state.currentTask = {
            ...state.currentTask,
            ...action.payload,
          };
        }
      })
      // Cancel task
      .addCase(cancelTask.fulfilled, (state, action) => {
        const index = state.tasks.findIndex((t) => t.id === action.payload.taskId);
        if (index !== -1) {
          state.tasks[index].status = 'cancelled';
        }
      })
      // Fetch statistics
      .addCase(fetchTaskStatistics.fulfilled, (state, action) => {
        state.statistics = action.payload;
      });
  },
});

export const { setFilters, clearError, updateTaskProgress, setCurrentTask } =
  taskSlice.actions;

export default taskSlice.reducer;
