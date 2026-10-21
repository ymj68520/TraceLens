import { createSlice } from '@reduxjs/toolkit';

const SETTINGS_KEY = 'forensics_settings';
const DEFAULT_SETTINGS = {
  refreshInterval: 5000,
  autoRefresh: true,
  theme: 'light',
  language: 'zh',
  itemsPerPage: 20,
  showTerminal: false,
};

const loadSettings = () => {
  try {
    const saved = localStorage.getItem(SETTINGS_KEY);
    if (!saved) return {};
    const parsed = JSON.parse(saved);
    if (!parsed || typeof parsed !== 'object') return {};
    return {
      refreshInterval: Number.isFinite(parsed.refreshInterval)
        ? Math.min(60000, Math.max(1000, parsed.refreshInterval))
        : undefined,
      itemsPerPage: Number.isFinite(parsed.itemsPerPage)
        ? Math.min(100, Math.max(5, parsed.itemsPerPage))
        : undefined,
      autoRefresh: typeof parsed.autoRefresh === 'boolean' ? parsed.autoRefresh : undefined,
      theme: parsed.theme === 'dark' ? 'dark' : parsed.theme === 'light' ? 'light' : undefined,
      language: 'zh',
      showTerminal: typeof parsed.showTerminal === 'boolean' ? parsed.showTerminal : undefined,
    };
  } catch (error) {
    console.error('Failed to load settings:', error);
    return {};
  }
};

const persistSettings = (settings) => {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (error) {
    console.error('Failed to save settings:', error);
  }
};

const settingsSlice = createSlice({
  name: 'settings',
  initialState: {
    ...DEFAULT_SETTINGS,
    ...Object.fromEntries(Object.entries(loadSettings()).filter(([, value]) => value !== undefined)),
  },
  reducers: {
    updateSettings: (state, action) => {
      Object.assign(state, action.payload);
      state.language = 'zh';
      persistSettings(state);
    },
    resetSettings: (state) => {
      Object.assign(state, DEFAULT_SETTINGS);
      persistSettings(state);
    },
  },
});

export const { updateSettings, resetSettings } = settingsSlice.actions;
export default settingsSlice.reducer;
