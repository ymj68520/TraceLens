import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, vi } from 'vitest';
import ForensicReportPage from './ForensicReportPage';
import { useReportVersion } from '../hooks/useReportVersion';
import { fetchTaskById } from '../services/taskService';

vi.mock('../hooks/useReportVersion', () => ({
  useReportVersion: vi.fn(),
}));
vi.mock('../services/taskService', () => ({ fetchTaskById: vi.fn() }));
vi.mock('../components/AndroidCoverageCard', () => ({
  default: ({ taskId }) => <div data-testid="coverage-card">{taskId}</div>,
}));
beforeEach(() => { fetchTaskById.mockResolvedValue({ android_source: 'tsk' }); });

test('Android filesystem image final-report viewer includes source coverage', async () => {
  fetchTaskById.mockResolvedValue({ android_source: 'filesystem-image' });
  useReportVersion.mockReturnValue({
    versions: [], selectedVersion: null, manifest: null, loading: false,
    error: null, generating: null, createVersion: vi.fn(), refresh: vi.fn(),
  });
  render(<MemoryRouter initialEntries={['/reports/task/task-image']}>
    <ForensicReportPage scopeType="task" scopeId="task-image" />
  </MemoryRouter>);
  expect(await screen.findByTestId('android-report-coverage-reference')).toHaveTextContent('来源覆盖清单');
  expect(screen.getByTestId('coverage-card')).toHaveTextContent('task-image');
});

test('sparse/super Task final-report viewer also includes normalization coverage', async () => {
  fetchTaskById.mockResolvedValue({ android_source: 'android-container' });
  useReportVersion.mockReturnValue({
    versions: [], selectedVersion: null, manifest: null, loading: false,
    error: null, generating: null, createVersion: vi.fn(), refresh: vi.fn(),
  });
  render(<MemoryRouter><ForensicReportPage scopeType="task" scopeId="task-super" /></MemoryRouter>);
  expect(await screen.findByTestId('coverage-card')).toHaveTextContent('task-super');
});

function manifest(reportId, categoryId) {
  const category = {
    category_id: categoryId,
    evidence_id: 'evidence-1',
    platform: 'android',
    title: categoryId,
    renderer: 'table',
    total: 1,
    deleted: 0,
    recovered: 0,
    high_risk: 0,
    relevant: 0,
    referenced: 0,
    page_size: 100,
    pages: 1,
    page_paths: ['page-1.json'],
  };
  return {
    schema_version: '1.0',
    report_id: reportId,
    title: `Report ${reportId}`,
    platforms: ['android'],
    categories: [category],
    directory: [{ id: 'evidence-1', title: 'Evidence', children: [category] }],
  };
}

function versionState(selectedVersion, currentManifest) {
  return {
    versions: [selectedVersion],
    selectedVersion,
    manifest: currentManifest,
    loading: false,
    error: null,
    generating: null,
    createVersion: vi.fn(),
    selectVersion: vi.fn(),
    selectByReportId: vi.fn().mockResolvedValue(true),
    refresh: vi.fn(),
  };
}

test('does not mount an old manifest under a newly selected report identity', async () => {
  const selected = { report_id: 'r2', version: 2, status: 'ready', title: 'Report r2' };
  const source = {
    getCategoryPage: vi.fn().mockResolvedValue({
      schema_version: '1.0', category_id: 'r2.category', page: 1,
      page_size: 100, total: 0, records: [], sha256: 'digest',
    }),
    search: vi.fn(),
  };
  useReportVersion.mockReturnValue(versionState(selected, manifest('r1', 'r1.category')));

  const view = render(
    <MemoryRouter initialEntries={['/reports/task/task-1']}>
      <ForensicReportPage scopeType="task" dataSource={source} />
    </MemoryRouter>,
  );

  expect(screen.queryByRole('main', { name: '报告正文' })).not.toBeInTheDocument();
  await waitFor(() => expect(source.getCategoryPage).not.toHaveBeenCalled());

  useReportVersion.mockReturnValue(versionState(selected, manifest('r2', 'r2.category')));
  view.rerender(
    <MemoryRouter initialEntries={['/reports/task/task-1']}>
      <ForensicReportPage scopeType="task" dataSource={source} />
    </MemoryRouter>,
  );

  await waitFor(() => expect(source.getCategoryPage).toHaveBeenCalledWith('r2', 'r2.category', 1));
  expect(screen.getByRole('main', { name: '报告正文' })).toBeInTheDocument();
  expect(source.getCategoryPage).toHaveBeenCalledTimes(1);
});

test('selects an exact report version requested by a timeline citation deep link', async () => {
  const current = { report_id: 'rep-new', version: 2, status: 'ready', report_kind: 'llm_generation' };
  const older = { report_id: 'rep-old', version: 1, status: 'ready', report_kind: 'llm_generation' };
  const state = { ...versionState(current, null), versions: [current, older] };
  useReportVersion.mockReturnValue(state);

  render(
    <MemoryRouter initialEntries={['/reports/task/task-1']}>
      <ForensicReportPage scopeType="task" scopeId="task-1" requestedReportId="rep-old" narrativeLoader={vi.fn().mockResolvedValue({ title: 'old', sections: [], citations: [] })} />
    </MemoryRouter>,
  );

  await waitFor(() => expect(state.selectByReportId).toHaveBeenCalledWith('rep-old'));
});

test('an unknown report deep link does not silently render the latest report', () => {
  const current = { report_id: 'rep-new', version: 2, status: 'ready', report_kind: 'llm_generation' };
  const state = { ...versionState(current, null), versions: [current] };
  useReportVersion.mockReturnValue(state);

  render(
    <MemoryRouter initialEntries={['/reports/task/task-1']}>
      <ForensicReportPage scopeType="task" scopeId="task-1" requestedReportId="foreign" />
    </MemoryRouter>,
  );

  expect(screen.getByRole('alert')).toHaveTextContent('不会自动改为其他版本');
  expect(screen.queryByTestId('narrative-report-view')).not.toBeInTheDocument();
  expect(state.selectByReportId).not.toHaveBeenCalled();
});
