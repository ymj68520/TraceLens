import { createSlice } from '@reduxjs/toolkit';

const SETTINGS_KEY = 'forensics_settings';

// 动态推导服务地址：跨机访问时用浏览器当前 host（如 192.168.31.50），
// 避免硬编码 localhost 导致跨机访问失败。
const host = (typeof window !== 'undefined' && window.location)
  ? window.location.hostname
  : 'localhost';
const defaultApiUrl = `http://${host}:8080`;
const defaultPythonApiUrl = `http://${host}:8090`;

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
    apiUrl: defaultApiUrl,
    pythonApiUrl: defaultPythonApiUrl,
    refreshInterval: 5000,
    autoRefresh: true,
    theme: 'light',
    language: 'en',
    itemsPerPage: 20,
    showTerminal: false,
    ...loadSettings(),
  },
  reducers: {
    updateSettings: (state, action) => {
      Object.assign(state, action.payload);
      saveSettings(state);
    },
    resetSettings: (state) => {
      Object.assign(state, {
        apiUrl: defaultApiUrl,
        pythonApiUrl: defaultPythonApiUrl,
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
