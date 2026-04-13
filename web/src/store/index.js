import { configureStore } from '@reduxjs/toolkit';
import taskReducer from './taskSlice';
import uiReducer from './uiSlice';
import dataReducer from './dataSlice';
import settingsReducer from './settingsSlice';
import intelligenceReducer from './intelligenceSlice';
import caseReducer from './caseSlice';

export const store = configureStore({
  reducer: {
    tasks:        taskReducer,
    ui:           uiReducer,
    data:         dataReducer,
    settings:     settingsReducer,
    intelligence: intelligenceReducer,
    cases:        caseReducer,
  },
});

export default store;
