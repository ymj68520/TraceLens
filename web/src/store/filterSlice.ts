import { createSlice, createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import type { FilterProfile } from '../types/api';
import {
  fetchFilterProfiles,
  fetchFilterProfileDetail,
  createFilterProfile,
  deleteFilterProfile,
} from '../services/filterService';
import type { LoadState } from './taskSlice';

export const fetchProfiles = createAsyncThunk('filter/fetchProfiles', async (_, { rejectWithValue }) => {
  try {
    const response = (await fetchFilterProfiles()) as { data?: { profiles?: FilterProfile[] } };
    return response?.data?.profiles || [];
  } catch (err) {
    return rejectWithValue((err as Error).message || 'Failed to fetch filter profiles');
  }
});

export const fetchProfileDetail = createAsyncThunk(
  'filter/fetchProfileDetail',
  async (name: string, { rejectWithValue }) => {
    try {
      const response = (await fetchFilterProfileDetail(name)) as { data?: unknown };
      return response?.data ?? null;
    } catch (err) {
      return rejectWithValue((err as Error).message || 'Failed to fetch profile details');
    }
  },
);

export const saveProfile = createAsyncThunk(
  'filter/saveProfile',
  async (profileData: Record<string, unknown>, { rejectWithValue }) => {
    try {
      return await createFilterProfile(profileData);
    } catch (err) {
      return rejectWithValue((err as Error).message || 'Failed to save profile');
    }
  },
);

export const removeProfile = createAsyncThunk(
  'filter/removeProfile',
  async (name: string, { rejectWithValue }) => {
    try {
      await deleteFilterProfile(name);
      return name;
    } catch (err) {
      return rejectWithValue((err as Error).message || 'Failed to delete profile');
    }
  },
);

interface FilterState {
  profiles: FilterProfile[];
  selectedProfile: string | null;
  profileDetail: unknown;
  status: LoadState;
  detailStatus: LoadState;
  error: unknown;
}

const initialState: FilterState = {
  profiles: [],
  selectedProfile: null,
  profileDetail: null,
  status: 'idle',
  detailStatus: 'idle',
  error: null,
};

const filterSlice = createSlice({
  name: 'filter',
  initialState,
  reducers: {
    setSelectedProfile(state, action: PayloadAction<string | null>) {
      state.selectedProfile = action.payload;
    },
    clearProfileDetail(state) {
      state.profileDetail = null;
    },
    clearError(state) {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchProfiles.pending, (state) => {
        state.status = 'loading';
        state.error = null;
      })
      .addCase(fetchProfiles.fulfilled, (state, action) => {
        state.status = 'succeeded';
        state.profiles = action.payload;
      })
      .addCase(fetchProfiles.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })
      .addCase(fetchProfileDetail.pending, (state) => {
        state.detailStatus = 'loading';
        state.profileDetail = null;
      })
      .addCase(fetchProfileDetail.fulfilled, (state, action) => {
        state.detailStatus = 'succeeded';
        state.profileDetail = action.payload;
      })
      .addCase(fetchProfileDetail.rejected, (state, action) => {
        state.detailStatus = 'failed';
        state.profileDetail = null;
        state.error = action.payload;
      })
      .addCase(saveProfile.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(saveProfile.fulfilled, (state) => {
        state.status = 'succeeded';
      })
      .addCase(saveProfile.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })
      .addCase(removeProfile.fulfilled, (state, action) => {
        state.profiles = state.profiles.filter((p) => p.name !== action.payload);
      });
  },
});

export const { setSelectedProfile, clearProfileDetail, clearError } = filterSlice.actions;
export default filterSlice.reducer;
