import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import AndroidReportImports from './AndroidReportImports';
import {
  attachAndroidReportToTask,
  createAndroidReportImportFromCandidate,
  detachAndroidReportFromTask,
  getAndroidReportOverview,
  getAndroidReportRecord,
  getAndroidReportRecords,
  listAndroidReportCandidates,
  listAndroidReportImports,
} from '../services/androidReportService';

vi.mock('../services/androidReportService', () => ({
  createAndroidReportImportFromCandidate: vi.fn(),
  attachAndroidReportToTask: vi.fn(),
  detachAndroidReportFromTask: vi.fn(),
  listAndroidReportCandidates: vi.fn(),
  listAndroidReportImports: vi.fn(),
  getAndroidReportOverview: vi.fn(),
  getAndroidReportRecords: vi.fn(),
  getAndroidReportRecord: vi.fn(),
  androidReportSourceUrl: (id, path) => `/source/${id}/${path}`,
  androidReportSourceLocationUrl: (id, recordId) => `/source-location/${id}/${recordId}#source-row`,
  androidReportAttachmentUrl: (id, path) => `/media/${id}/${path}`,
}));

const meta = {
  import_id: 'abc', source_path: '/case/report', source_type: 'third_party_derived_report',
  specimens: [{ specimen: '测试手机', software: 'Test Exporter', version: '1.0' }],
  page_count: 2, record_count: 3, missing_attachment_count: 1,
  status: 'PARTIAL', warning_count: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  listAndroidReportImports.mockResolvedValue({ imports: [meta] });
  listAndroidReportCandidates.mockResolvedValue({ candidates: [{ id: 'candidate-1', name: '测试报告', existing_import_id: 'abc' }] });
  attachAndroidReportToTask.mockResolvedValue({ import: { ...meta, task_ids: ['task-a'] } });
  detachAndroidReportFromTask.mockResolvedValue({ import: { ...meta, task_ids: [] } });
  getAndroidReportOverview.mockResolvedValue({ overview: {
    import: meta, categories: [{ category: '微信', count: 3 }], days: [{ day: '2026-07-17', count: 2 }],
    coverage: { successful_pages: 2, declared_pages: 2, warning_count: 1 },
    warnings: [{ code: 'MISSING_ATTACHMENT', path: 'report/phone/resource/missing.png' }],
  } });
  getAndroidReportRecords.mockResolvedValue({ total: 1, page: 1, page_size: 50, records: [{
    id: 'row1', specimen: '测试手机', category: '微信', heading: '聊天记录',
    excerpt: '测试消息', source_file: 'report/phone/content1.html', source_anchor: '4',
    source_table: 1, source_row: 1,
  }] });
  getAndroidReportRecord.mockResolvedValue({ record: {
    id: 'row1', specimen: '测试手机', category: '微信', content: '<script>文本，不执行</script>',
    fields: { 内容: '测试消息' }, source_file: 'report/phone/content1.html', source_anchor: '4',
    source_table: 1, source_row: 1, source_page: 2,
    source_locator: 'report/phone/content1.html#table-1-row-1',
    source_table_index: 1, source_row_index: 1,
    source_hash: 'digest', source_sha256: 'digest', source_matches_import: true,
    attachments: [{ path: 'report/phone/resource/a.png', available: true }],
  } });
});

test('shows derived-report overview, searchable records, and safe source trace', async () => {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={['/android?mode=report&import_id=abc']}><AndroidReportImports /></MemoryRouter>);
  expect(await screen.findByText('报告分析概览')).toBeInTheDocument();
  expect(screen.getByText('2 / 2 页 · 1 条 warning')).toBeInTheDocument();
  expect(screen.getByText('导入 warning · 1')).toBeInTheDocument();
  expect(screen.getByText(/第三方报告中的派生记录/)).toBeInTheDocument();
  expect(await screen.findByTestId('android-report-record')).toHaveTextContent('测试消息');
  await user.click(screen.getByTestId('android-report-record'));
  expect(await screen.findByTestId('android-report-detail')).toHaveTextContent('<script>文本，不执行</script>');
  expect(screen.getByText(/导入时页面 SHA-256/)).toHaveTextContent('digest');
  expect(screen.getByText(/下载原报告页/)).toHaveAttribute('href', '/source/abc/report/phone/content1.html');
  expect(screen.getByText(/查看原始报告位置/)).toHaveAttribute('href', '/source-location/abc/row1#source-row');
  expect(screen.getByText(/下载副本/)).toHaveAttribute('href', '/media/abc/report/phone/resource/a.png');
  expect(screen.getByTestId('android-report-imports').querySelector('script')).toBeNull();
});

test('imports a discovered report without typing a server path', async () => {
  const user = userEvent.setup();
  listAndroidReportImports.mockResolvedValue({ imports: [] });
  createAndroidReportImportFromCandidate.mockResolvedValue({ import: meta });
  render(<MemoryRouter initialEntries={['/android?mode=report']}><AndroidReportImports /></MemoryRouter>);
  expect(await screen.findByRole('combobox', { name: '已发现的报告' })).toHaveValue('candidate-1');
  await user.click(screen.getByRole('button', { name: /导入并建立索引/ }));
  await waitFor(() => expect(createAndroidReportImportFromCandidate).toHaveBeenCalledWith('candidate-1'));
  expect(screen.queryByPlaceholderText('/path/to/报告_案件...')).not.toBeInTheDocument();
  expect(await screen.findByText('报告分析概览')).toBeInTheDocument();
});

test('selected Task imports the discovered report and links it explicitly', async () => {
  const user = userEvent.setup();
  listAndroidReportImports.mockResolvedValue({ imports: [] });
  createAndroidReportImportFromCandidate.mockResolvedValue({ import: meta });
  render(<MemoryRouter initialEntries={['/android?mode=report&task_id=task-a']}><AndroidReportImports /></MemoryRouter>);
  await user.click(await screen.findByRole('button', { name: /导入并关联当前 Task/ }));
  await waitFor(() => expect(createAndroidReportImportFromCandidate).toHaveBeenCalledWith('candidate-1'));
  await waitFor(() => expect(attachAndroidReportToTask).toHaveBeenCalledWith('abc', 'task-a'));
  expect(await screen.findByRole('checkbox', { name: '关联当前 Task' })).toBeChecked();
});

test('checkbox explicitly links an imported report to the selected Task', async () => {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={['/android?mode=report&task_id=task-a&import_id=abc']}><AndroidReportImports /></MemoryRouter>);
  const checkbox = await screen.findByRole('checkbox', { name: '关联当前 Task' });
  expect(checkbox).not.toBeChecked();
  await user.click(checkbox);
  await waitFor(() => expect(attachAndroidReportToTask).toHaveBeenCalledWith('abc', 'task-a'));
  expect(checkbox).toBeChecked();
  await user.click(checkbox);
  await waitFor(() => expect(detachAndroidReportFromTask).toHaveBeenCalledWith('abc', 'task-a'));
  expect(checkbox).not.toBeChecked();
});

test('selecting a Task opens its already-linked report automatically', async () => {
  listAndroidReportImports.mockResolvedValue({ imports: [{ ...meta, task_ids: ['task-a'] }] });
  render(<MemoryRouter initialEntries={['/android?mode=report&task_id=task-a']}><AndroidReportImports /></MemoryRouter>);
  expect(await screen.findByText('报告分析概览')).toBeInTheDocument();
  expect(getAndroidReportOverview).toHaveBeenCalledWith('abc');
  expect(screen.getByRole('checkbox', { name: '关联当前 Task' })).toBeChecked();
});
