import { createSlice } from '@reduxjs/toolkit';

const SETTINGS_KEY = 'forensics_settings';

const loadSettings = () => {
  try {
    const saved = localStorage.getItem(SETTINGS_KEY);
    return saved ? JSON.parse(saved) : {};
  } catch (error) {
    console.error('Failed to load settings:', error);
    return {};
  }
};

const saveSettings = (settings) => {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (error) {
    console.error('Failed to save settings:', error);
  }
};

const settingsSlice = createSlice({
  name: 'settings',
  initialState: {
    apiUrl: 'http://localhost:8080',
    refreshInterval: 5000,
    autoRefresh: true,
    theme: 'light',
    language: 'en',
    itemsPerPage: 20,
    ...loadSettings(),
  },
  reducers: {
    updateSettings: (state, action) => {
      Object.assign(state, action.payload);
      saveSettings(state);
    },
    resetSettings: (state) => {
      Object.assign(state, {
        apiUrl: 'http://localhost:8080',
        refreshInterval: 5000,
        autoRefresh: true,
        theme: 'light',
        language: 'en',
        itemsPerPage: 20,
      });
      saveSettings(state);
    },
  },
});

export const { updateSettings, resetSettings } = settingsSlice.actions;

export default settingsSlice.reducer;
