import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import CaseIntelligence from './CaseIntelligence';
import taskReducer from '../store/taskSlice';

vi.mock('../components/case-intelligence/report-reader/IntelligenceReportReader', () => ({
  default: ({ taskId }) => <div data-testid="legacy-reader">legacy:{taskId}</div>,
}));

vi.mock('./ForensicReportPage', () => ({
  default: ({ scopeType, scopeId }) => (
    <div data-testid="forensic-page">forensic:{scopeType}:{scopeId}</div>
  ),
}));

const getCaseMock = vi.fn().mockResolvedValue({ id: 'case-1', task_ids: [] });
vi.mock('../services/caseGroupService', () => ({
  getCase: (...args) => getCaseMock(...args),
}));

function makeStore(taskIdsById) {
  return configureStore({
    reducer: { tasks: taskReducer },
    preloadedState: {
      tasks: {
        tasks: Object.entries(taskIdsById).flatMap(([id, meta]) => [{ id, status: 'completed', ...meta }]),
        currentTask: null,
        statistics: null,
        status: 'idle',
        error: null,
        filters: { status: 'all', priority: 'all' },
        pagination: { total: 0, limit: 20, offset: 0 },
      },
    },
  });
}

function renderPage(route, store = makeStore({})) {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <CaseIntelligence />
      </MemoryRouter>
    </Provider>,
  );
}

describe('CaseIntelligence report workflow', () => {
  test('defaults to the R2 forensic report for task context', () => {
    renderPage('/case-intelligence?taskId=task-1');

    expect(screen.getByTestId('forensic-page')).toHaveTextContent('forensic:task:task-1');
    expect(screen.queryByTestId('legacy-reader')).not.toBeInTheDocument();
  });

  test('keeps the historical reader behind the explicit intelligence tab', () => {
    renderPage('/case-intelligence?taskId=task-1&tab=intelligence');

    expect(screen.getByTestId('legacy-reader')).toHaveTextContent('legacy:task-1');
    expect(screen.queryByTestId('forensic-page')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /历史研判报告/ })).toBeInTheDocument();
  });

  test('passes case scope to the current forensic report view', () => {
    renderPage('/case-intelligence?case_id=case-1');

    expect(screen.getByTestId('forensic-page')).toHaveTextContent('forensic:case:case-1');
  });

  test('case context resolves case tasks and feeds the historical reader', async () => {
    getCaseMock.mockResolvedValue({
      id: 'case-1',
      task_ids: ['task-9', 'task-2'],
    });
    renderPage(
      '/case-intelligence?case_id=case-1&tab=intelligence',
      makeStore({
        'task-9': { name: 'b.img' },
        'task-2': { name: 'a.img' },
      }),
    );

    // case 下默认选第一个 completed 任务并传给阅读器
    await waitFor(() => {
      expect(screen.getByTestId('legacy-reader')).toHaveTextContent('legacy:task-9');
    });
    expect(screen.getByTestId('case-task-select')).toBeInTheDocument();
    expect(getCaseMock).toHaveBeenCalledWith('case-1');
  });
});
