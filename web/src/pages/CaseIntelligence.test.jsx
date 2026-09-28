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
  default: ({ scopeType, scopeId, requestedReportId, focusCitationId }) => (
    <div data-testid="forensic-page" data-report-id={requestedReportId || ''} data-citation-id={focusCitationId || ''}>forensic:{scopeType}:{scopeId}</div>
  ),
}));

vi.mock('../components/case-intelligence/CrossImageReport', () => ({
  default: ({ caseId }) => <div data-testid="cross-image-report">cross-image:{caseId}</div>,
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

  test('defaults case context to the persisted cross-image report', () => {
    renderPage('/case-intelligence?case_id=case-1');

    expect(screen.getByTestId('cross-image-report')).toHaveTextContent('cross-image:case-1');
  });

  test('keeps the new forensic report view available by explicit case tab', () => {
    renderPage('/case-intelligence?case_id=case-1&tab=forensic');

    expect(screen.getByTestId('forensic-page')).toHaveTextContent('forensic:case:case-1');
  });

  test('passes an exact report and citation deep link into the task report view', () => {
    renderPage('/case-intelligence?task_id=task-1&tab=forensic&report_id=rep-old&citation_id=c001');

    expect(screen.getByTestId('forensic-page')).toHaveAttribute('data-report-id', 'rep-old');
    expect(screen.getByTestId('forensic-page')).toHaveAttribute('data-citation-id', 'c001');
    expect(screen.getByTestId('back-to-investigation')).toHaveAttribute('href', '/investigation?task_id=task-1&report_id=rep-old');
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
