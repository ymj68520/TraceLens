import { configureStore } from '@reduxjs/toolkit';
import { useDispatch, useSelector, type TypedUseSelectorHook } from 'react-redux';
import tasksReducer from './taskSlice';
import casesReducer from './caseSlice';
import settingsReducer from './settingsSlice';
import intelligenceReducer from './intelligenceSlice';
import filterReducer from './filterSlice';

export const store = configureStore({
  reducer: {
    tasks: tasksReducer,
    cases: casesReducer,
    settings: settingsReducer,
    intelligence: intelligenceReducer,
    filter: filterReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch: () => AppDispatch = useDispatch;
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;

export default store;
