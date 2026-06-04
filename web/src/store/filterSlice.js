import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import {
  fetchFilterProfiles,
  fetchFilterProfileDetail,
  createFilterProfile,
  deleteFilterProfile,
} from '../services/filterService';

// Async thunks

export const fetchProfiles = createAsyncThunk(
  'filter/fetchProfiles',
  async (_, { rejectWithValue }) => {
    try {
      const response = await fetchFilterProfiles();
      return response?.data?.profiles || [];
    } catch (err) {
      return rejectWithValue(err.message || 'Failed to fetch filter profiles');
    }
  }
);

export const fetchProfileDetail = createAsyncThunk(
  'filter/fetchProfileDetail',
  async (name, { rejectWithValue }) => {
    try {
      const response = await fetchFilterProfileDetail(name);
      return response?.data || null;
    } catch (err) {
      return rejectWithValue(err.message || 'Failed to fetch profile details');
    }
  }
);

export const saveProfile = createAsyncThunk(
  'filter/saveProfile',
  async (profileData, { rejectWithValue }) => {
    try {
      const response = await createFilterProfile(profileData);
      return response;
    } catch (err) {
      return rejectWithValue(err.message || 'Failed to save profile');
    }
  }
);

export const removeProfile = createAsyncThunk(
  'filter/removeProfile',
  async (name, { rejectWithValue }) => {
    try {
      await deleteFilterProfile(name);
      return name;
    } catch (err) {
      return rejectWithValue(err.message || 'Failed to delete profile');
    }
  }
);

// Slice

const filterSlice = createSlice({
  name: 'filter',
  initialState: {
    profiles: [],
    selectedProfile: null,
    profileDetail: null,
    status: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed'
    detailStatus: 'idle', // separate status for profile detail fetch
    error: null,
  },
  reducers: {
    setSelectedProfile(state, action) {
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
      // fetchProfiles
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
      // fetchProfileDetail
      .addCase(fetchProfileDetail.pending, (state) => {
        state.detailStatus = 'loading';
        state.profileDetail = null; // Clear stale detail immediately
      })
      .addCase(fetchProfileDetail.fulfilled, (state, action) => {
        state.detailStatus = 'succeeded';
        state.profileDetail = action.payload;
      })
      .addCase(fetchProfileDetail.rejected, (state, action) => {
        state.detailStatus = 'failed';
        state.profileDetail = null; // Clear on error to avoid showing stale data
        state.error = action.payload;
      })
      // saveProfile
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
      // removeProfile
      .addCase(removeProfile.fulfilled, (state, action) => {
        state.profiles = state.profiles.filter((p) => p.name !== action.payload);
      });
  },
});

export const { setSelectedProfile, clearProfileDetail, clearError } = filterSlice.actions;
export default filterSlice.reducer;
