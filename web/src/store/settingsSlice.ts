import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { Language } from '../types/locale';

const SETTINGS_KEY = 'forensics_settings';

const host =
  typeof window !== 'undefined' && window.location ? window.location.hostname : 'localhost';
const defaultApiUrl = `http://${host}:8080`;
const defaultPythonApiUrl = `http://${host}:8090`;

export interface SettingsState {
  apiUrl: string;
  pythonApiUrl: string;
  refreshInterval: number;
  autoRefresh: boolean;
  theme: 'light' | 'dark';
  language: Language;
  itemsPerPage: number;
  showTerminal: boolean;
}

const loadSettings = (): Partial<SettingsState> => {
  try {
    const saved = localStorage.getItem(SETTINGS_KEY);
    return saved ? (JSON.parse(saved) as Partial<SettingsState>) : {};
  } catch (error) {
    console.error('Failed to load settings:', error);
    return {};
  }
};

const saveSettings = (settings: SettingsState) => {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (error) {
    console.error('Failed to save settings:', error);
  }
};

const defaults: SettingsState = {
  apiUrl: defaultApiUrl,
  pythonApiUrl: defaultPythonApiUrl,
  refreshInterval: 5000,
  autoRefresh: true,
  theme: 'light',
  language: 'zh',
  itemsPerPage: 20,
  showTerminal: false,
};

const settingsSlice = createSlice({
  name: 'settings',
  initialState: { ...defaults, ...loadSettings() } as SettingsState,
  reducers: {
    updateSettings: (state, action: PayloadAction<Partial<SettingsState>>) => {
      Object.assign(state, action.payload);
      saveSettings(state);
    },
    resetSettings: (state) => {
      Object.assign(state, defaults);
      saveSettings(state);
    },
  },
});

export const { updateSettings, resetSettings } = settingsSlice.actions;
export default settingsSlice.reducer;
