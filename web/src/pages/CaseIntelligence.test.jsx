import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CaseIntelligence from './CaseIntelligence';

vi.mock('../components/case-intelligence/report-reader/IntelligenceReportReader', () => ({
  default: ({ taskId }) => <div data-testid="legacy-reader">legacy:{taskId}</div>,
}));

vi.mock('./ForensicReportPage', () => ({
  default: ({ scopeType, scopeId }) => (
    <div data-testid="forensic-page">forensic:{scopeType}:{scopeId}</div>
  ),
}));

function renderPage(route) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <CaseIntelligence />
    </MemoryRouter>,
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
});
