import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import FinalReportViewer from './FinalReportViewer';
import { getClaimProvenance, getFinalReport, getFinalReportPublication, getFinalReports, publishFinalReport } from '../../services/investigationService';

vi.mock('../../services/investigationService', () => ({
  getFinalReports: vi.fn(),
  getFinalReport: vi.fn(),
  getFinalReportPublication: vi.fn(),
  publishFinalReport: vi.fn(),
  getClaimProvenance: vi.fn(),
}));

function report() {
  return {
    report_id: 'r3',
    report_version: 3,
    report_schema_version: 'final-report-v1',
    assembly_rule_version: 'final-report-assembly-v1',
    report_dataset_hash: 'dataset-hash',
    citation_graph_hash: 'graph-hash',
    section_plan_hash: 'plan-hash',
    final_report_hash: 'final-hash-1234567890',
    status: 'assembled',
    created_at: 1710000000,
    sections: [1, 2, 3, 4, 5].map((order) => ({
      section_id: `SEC-00${order}`,
      section_type: `analysis.section${order}`,
      title: `Section ${order}`,
      order,
      paragraphs: order === 1 ? [{ text: 'Immutable paragraph text', claim_ids: ['claim-1'], citation_ids: ['CIT-001'] }] : [],
    })),
    citation_manifest: [{ citation_id: 'CIT-001', evidence_key: 'file:/a', evidence_type: 'file', report_status: 'main', snapshot: { source_hash: 'abc' }, pinned_analysis: { analysis_id: 'analysis-1', version: 2 } }],
    claim_manifest: [{ claim_id: 'claim-1', section_ids: ['SEC-001'], citation_ids: ['CIT-001'] }],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  getFinalReports.mockResolvedValue({ reports: [{ report_id: 'r3', report_version: 3, status: 'assembled', final_report_hash: 'final-hash-1234567890', created_at: 1710000000 }] });
  getFinalReport.mockResolvedValue({ report: report() });
  getFinalReportPublication.mockResolvedValue({ publication: null });
  publishFinalReport.mockResolvedValue({ publication: { report_id: 'r3', status: 'published', published_at: 1710000100 } });
  getClaimProvenance.mockResolvedValue({ claim: {
    claim_id: 'claim-1',
    claim_type: 'fact',
    claim_text: 'Historical claim text',
    status: 'accepted',
    grounding_status: 'grounded',
    grounding_warnings: [],
    event_id: 'event-1',
    event_version_id: 'version-1',
    evidence_links: [
      { evidence_key: 'file:/a', relation: 'supports', rationale: 'Direct support' },
      { evidence_key: 'file:/b', relation: 'contradicts', rationale: 'Counterpoint' },
    ],
  } });
});

test('shows an explicit no-publication fact state without calling it Unpublished', async () => {
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText('此报告版本尚无发布记录。')).toBeInTheDocument());
  expect(screen.queryByText('Unpublished')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '发布此报告版本' })).toBeInTheDocument();
});

test('publishes the selected report version and re-reads the same publication', async () => {
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByRole('button', { name: '发布此报告版本' })).toBeInTheDocument(), { timeout: 5000 });
  fireEvent.click(screen.getByRole('button', { name: '发布此报告版本' }));

  await waitFor(() => expect(publishFinalReport).toHaveBeenCalledWith('task-a', 'r3'));
  expect(getFinalReportPublication).toHaveBeenLastCalledWith('task-a', 'r3');
});

test('renders selected report, sections, paragraph metadata, and only Assembled status', async () => {
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText('选中的报告版本：v3')).toBeInTheDocument());
  expect(screen.getAllByText('已编制').length).toBeGreaterThan(0);
  expect(screen.getByText('Immutable paragraph text')).toBeInTheDocument();
  expect(screen.getByText('断言 claim-1')).toBeInTheDocument();
  expect(screen.getByText('CIT-001')).toBeInTheDocument();
  expect(screen.getByText('Section 5')).toBeInTheDocument();
  expect(screen.queryByText('Published')).not.toBeInTheDocument();
  expect(screen.queryByText('Unpublished')).not.toBeInTheDocument();
});


test('shows empty state and sends no mutation request when no reports exist', async () => {
  getFinalReports.mockResolvedValue({ reports: [] });
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText('此任务尚未编制最终报告。')).toBeInTheDocument());
  expect(getFinalReport).not.toHaveBeenCalled();
});

test('shows task selection state and performs no request without task id', () => {
  render(<MemoryRouter initialEntries={['/investigation/report']}><FinalReportViewer /></MemoryRouter>);

  expect(screen.getByText('请选择任务，查看已编制的报告版本。')).toBeInTheDocument();
  expect(getFinalReports).not.toHaveBeenCalled();
  expect(getFinalReport).not.toHaveBeenCalled();
});

test('opens citation trace from the immutable report manifest without another request', async () => {
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText('选中的报告版本：v3')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'CIT-001' }));

  expect(screen.getByText('报告引用')).toBeInTheDocument();
  expect(screen.getByText('(task-a, file:/a)')).toBeInTheDocument();
  expect(screen.getByText('报告绑定的证据快照')).toBeInTheDocument();
  expect(screen.getByText('绑定的分析版本')).toBeInTheDocument();
  expect(screen.getByText('claim-1')).toBeInTheDocument();
  expect(getClaimProvenance).not.toHaveBeenCalled();
});

test('opens exact historical Claim trace and joins report usage by evidence key', async () => {
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText('选中的报告版本：v3')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '断言 claim-1' }));

  await waitFor(() => expect(screen.getByText('历史断言')).toBeInTheDocument());
  expect(getClaimProvenance).toHaveBeenCalledWith('task-a', 'claim-1');
  expect(screen.getByText('Historical claim text')).toBeInTheDocument();
  expect(screen.getByText('历史断言当前状态')).toBeInTheDocument();
  expect(screen.getByText('支持')).toBeInTheDocument();
  expect(screen.getByText('存在相反证据')).toBeInTheDocument();
  expect(screen.getByText('CIT-001 · 已在本报告引用')).toBeInTheDocument();
  expect(screen.getByText('断言来源，未被本报告引用')).toBeInTheDocument();
});

test('shows opaque Claim not-found without falling back to current claims', async () => {
  getClaimProvenance.mockRejectedValueOnce({ status: 404, message: 'hidden' });
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText('选中的报告版本：v3')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '断言 claim-1' }));

  await waitFor(() => expect(screen.getByText('未找到断言来源。')).toBeInTheDocument());
  expect(screen.queryByText('hidden')).not.toBeInTheDocument();
});

test('shows persisted report integrity warning without repairing the payload', async () => {
  const invalid = report();
  invalid.sections[0].order = 5;
  getFinalReport.mockResolvedValue({ report: invalid });
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('报告完整性提醒'));
  expect(screen.getByText('Immutable paragraph text')).toBeInTheDocument();
});

test('shows persisted report integrity warning without repairing the payload', async () => {
  const invalid = report();
  invalid.sections[0].order = 5;
  getFinalReport.mockResolvedValue({ report: invalid });
  render(<MemoryRouter initialEntries={['/investigation/report?task_id=task-a']}><FinalReportViewer /></MemoryRouter>);

  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('报告完整性提醒'));
  expect(screen.getByText('Immutable paragraph text')).toBeInTheDocument();
});
