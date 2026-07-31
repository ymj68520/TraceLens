import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import ForensicReportPage from './ForensicReportPage';
import { useReportVersion } from '../hooks/useReportVersion';

vi.mock('../hooks/useReportVersion', () => ({
  useReportVersion: vi.fn(),
}));

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
