import { configureStore } from '@reduxjs/toolkit';
import taskReducer from './taskSlice';
import uiReducer from './uiSlice';
import dataReducer from './dataSlice';
import settingsReducer from './settingsSlice';

export const store = configureStore({
  reducer: {
    tasks: taskReducer,
    ui: uiReducer,
    data: dataReducer,
    settings: settingsReducer,
  },
});

export default store;
