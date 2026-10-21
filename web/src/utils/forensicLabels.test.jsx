import { beforeEach, expect, test, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import TaskTable from '../components/tasks/TaskTable';

beforeEach(() => { localStorage.clear(); vi.resetModules(); });

test('legacy English settings migrate to Chinese while retaining other preferences', async () => {
  localStorage.setItem('forensics_settings', JSON.stringify({ language: 'en', theme: 'dark' }));
  const { default: reducer, updateSettings } = await import('../store/settingsSlice');
  const state = reducer(undefined, { type: 'init' });
  expect(state.language).toBe('zh');
  expect(state.theme).toBe('dark');
  expect(reducer(state, updateSettings({ language: 'en' })).language).toBe('zh');
});

test('task status, priority and progress are Chinese; source filenames stay verbatim', () => {
  const store = configureStore({ reducer: { settings: () => ({ language: 'zh' }) } });
  render(<Provider store={store}><MemoryRouter><TaskTable tasks={[{
    id: 'abc12345', image_path: '/case/Original Evidence.img', status: 'running', priority: 'high',
    progress: { current_phase: 'platform_analysis', phase_description: 'Analyzing Android artifacts', overall_percentage: 30 },
  }]} /></MemoryRouter></Provider>);
  expect(screen.getByText('运行中')).toBeInTheDocument();
  expect(screen.getByText('高')).toBeInTheDocument();
  expect(screen.getByText('正在解析平台记录')).toBeInTheDocument();
  expect(screen.getByText('/case/Original Evidence.img')).toBeInTheDocument();
  expect(screen.queryByText('Analyzing Android artifacts')).not.toBeInTheDocument();
});
