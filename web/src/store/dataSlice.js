import { createSlice } from '@reduxjs/toolkit';

const dataSlice = createSlice({
  name: 'data',
  initialState: {
    tasks: [],
    timeline: [],
    files: [],
    androidData: null,
    statistics: null,
    searchResults: null,
    cache: {},
  },
  reducers: {
    setTimeline: (state, action) => {
      state.timeline = action.payload;
    },
    setFiles: (state, action) => {
      state.files = action.payload;
    },
    setAndroidData: (state, action) => {
      state.androidData = action.payload;
    },
    setStatistics: (state, action) => {
      state.statistics = action.payload;
    },
    setSearchResults: (state, action) => {
      state.searchResults = action.payload;
    },
    setCache: (state, action) => {
      const { key, value } = action.payload;
      state.cache[key] = {
        value,
        timestamp: Date.now(),
      };
    },
    clearCache: (state) => {
      state.cache = {};
    },
    invalidateCache: (state, action) => {
      delete state.cache[action.payload];
    },
  },
});

export const {
  setTimeline,
  setFiles,
  setAndroidData,
  setStatistics,
  setSearchResults,
  setCache,
  clearCache,
  invalidateCache,
} = dataSlice.actions;

export default dataSlice.reducer;
