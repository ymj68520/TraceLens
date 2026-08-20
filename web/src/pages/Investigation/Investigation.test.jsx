import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';
import Investigation from './Investigation';
import * as service from '../../services/investigationService';

vi.mock('./components/LocalKnowledgeGraph', () => ({
  default: ({ graph }) => <div>{graph?.nodes?.map((node) => node.label).join(',')}</div>,
}));

vi.mock('../../services/investigationService', () => ({
  getOverview: vi.fn(),
  bootstrapInvestigation: vi.fn(),
  getInvestigationEvents: vi.fn(),
  getEventEvidence: vi.fn(),
  getEvidenceDetail: vi.fn(),
  getAnalysisVersions: vi.fn(),
  getLocalGraph: vi.fn(),
  reviewInvestigationEvent: vi.fn(),
  saveAnalystNote: vi.fn(),
  startEvidenceAnalysis: vi.fn(),
  pollAnalysisJob: vi.fn(),
  acceptAnalysis: vi.fn(),
  rejectAnalysis: vi.fn(),
  getEventSemanticVersions: vi.fn().mockResolvedValue({ versions: [] }),
  getEventClaims: vi.fn().mockResolvedValue({ claims: [] }),
  getEffectiveEventClaims: vi.fn().mockResolvedValue({ claims: [] }),
  acceptEventClaim: vi.fn(),
  rejectEventClaim: vi.fn(),
  refreshInvestigationEvent: vi.fn(),
  acceptEventSemanticVersion: vi.fn(),
  rejectEventSemanticVersion: vi.fn(),
  setReportEvidence: vi.fn(),
  removeReportEvidence: vi.fn(),
}));

const events = [
  { id: 'e1', title: '事件一', summary: 'summary 1', source: 'cluster_seed', review_status: 'draft', start_time: 100, evidence_counts: { total: 1, primary: 1, supporting: 0, context: 0, contradicting: 0 } },
  { id: 'e2', title: '事件二', summary: 'summary 2', source: 'cluster_seed', review_status: 'draft', start_time: 200, evidence_counts: { total: 1, primary: 0, supporting: 1, context: 0, contradicting: 0 } },
];
const evidenceByEvent = {
  e1: [{ evidence_key: 'file:/a.txt', title: 'a.txt', role: 'primary', evidence_type: 'file', initial_summary: 'A' }],
  e2: [{ evidence_key: 'file:/b.txt', title: 'b.txt', role: 'supporting', evidence_type: 'file', initial_summary: 'B' }],
};

function renderPage(route = '/investigation?task_id=t1') {
  return render(<MemoryRouter initialEntries={[route]}><Investigation /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  service.getOverview.mockResolvedValue({ initialized: true, event_count: 2, analysis_count: 0, report_evidence_count: 0 });
  service.getInvestigationEvents.mockResolvedValue({ events });
  service.getEventEvidence.mockImplementation((taskId, eventId) => Promise.resolve({ evidence: evidenceByEvent[eventId] || [] }));
  service.getEvidenceDetail.mockResolvedValue({ evidence: { evidence_key: 'file:/b.txt', title: 'b.txt', file_path: '/b.txt', snapshot: { initial_description: 'Initial B' }, metadata: {}, related_event_ids: [] } });
  service.getAnalysisVersions.mockResolvedValue({ versions: [] });
  service.getLocalGraph.mockResolvedValue({ nodes: [], links: [], base_available: false });
});

test('shows a task-selection placeholder without task context', () => {
  renderPage('/investigation');
  expect(screen.getByText('请先从顶部任务选择器选择一个已完成初次自动分析的任务。')).toBeInTheDocument();
  expect(service.getOverview).not.toHaveBeenCalled();
});

test('uses overview-gated bootstrap', async () => {
  service.getOverview.mockResolvedValueOnce({ initialized: false });
  service.bootstrapInvestigation.mockResolvedValueOnce({ initialized: true, event_count: 2 });
  renderPage();
  await waitFor(() => expect(service.bootstrapInvestigation).toHaveBeenCalledWith('t1'));
  expect(service.getInvestigationEvents).toHaveBeenCalledWith('t1');
});

test('does not bootstrap an initialized investigation', async () => {
  renderPage();
  await screen.findByText('事件一');
  expect(service.bootstrapInvestigation).not.toHaveBeenCalled();
});

test('selecting an event refreshes its evidence panel', async () => {
  renderPage();
  await screen.findByText('a.txt');
  fireEvent.click(screen.getByTestId('event-e2'));
  await screen.findByText('b.txt');
  expect(service.getEventEvidence).toHaveBeenCalledWith('t1', 'e2');
});

test('selecting evidence opens the evidence analysis workspace', async () => {
  renderPage();
  await screen.findByText('a.txt');
  fireEvent.click(screen.getByTestId('event-e2'));
  await screen.findByText('b.txt');
  fireEvent.click(screen.getByTestId('evidence-file:/b.txt'));
  await screen.findByTestId('evidence-analysis-panel');
  expect(screen.getByText('Initial B')).toBeInTheDocument();
  expect(service.getEvidenceDetail).toHaveBeenCalledWith('t1', 'file:/b.txt');
});

test('displays accepted evidence analysis ahead of newer pending history', async () => {
  service.getEvidenceDetail.mockResolvedValue({ evidence: {
    evidence_key: 'file:/a.txt', title: 'a.txt', file_path: '/a.txt', snapshot: { initial_description: 'Initial A' }, metadata: {}, related_event_ids: [],
    accepted_analysis: { id: 'accepted', version: 1, status: 'accepted', description: 'Accepted analysis' },
    pending_analysis: { id: 'pending', version: 2, status: 'review_pending', description: 'Pending analysis' },
    latest_analysis: { id: 'pending', version: 2, status: 'review_pending', description: 'Pending analysis' },
  } });
  service.getAnalysisVersions.mockResolvedValue({ versions: [
    { id: 'pending', version: 2, status: 'review_pending', description: 'Pending analysis' },
    { id: 'accepted', version: 1, status: 'accepted', description: 'Accepted analysis' },
  ] });
  renderPage();
  await screen.findByText('a.txt');
  fireEvent.click(screen.getByTestId('evidence-file:/a.txt'));
  await screen.findByTestId('evidence-analysis-panel');
  expect(screen.getByText('Accepted analysis')).toBeInTheDocument();
});

test('marks stale pending semantic content without replacing the timeline title', async () => {
  service.getInvestigationEvents.mockResolvedValue({ events: [{
    ...events[0], title: 'Seed title', effective_title: 'Seed title', effective_summary: 'Seed summary', semantic_revision: 2,
    pending_semantic_stale: true,
  }] });
  service.getEventSemanticVersions.mockResolvedValue({ versions: [{
    id: 'stale', version: 1, status: 'review_pending', source_revision: 1, title: 'Stale candidate', summary: 'stale', input_evidence_refs: '[]',
  }] });
  renderPage();
  expect(await screen.findByTestId('event-e1')).toHaveTextContent('Seed title');
  await screen.findByText('已过期待审核');
  expect(screen.getByText('Stale candidate')).toBeInTheDocument();
});

test('renders historical claim citation and preserves provenance scope', async () => {
  service.getInvestigationEvents.mockResolvedValue({ events: [{ ...events[0], semantic_source: 'accepted', semantic_version_id: 'ev1', effective_semantic_valid: true }] });
  service.getEventSemanticVersions.mockResolvedValue({ versions: [] });
  service.getEffectiveEventClaims.mockResolvedValue({ claims: [{ id: 'c1', claim_text: 'Claim A', type: 'fact', status: 'review_pending', grounding_status: 'grounded', evidence_refs: [{ evidence_key: 'file:/a.txt' }, { evidence_key: 'file:/historical.txt' }] }] });
  service.getEventEvidence.mockResolvedValue({ evidence: [{ ...evidenceByEvent.e1[0], evidence_key: 'file:/a.txt' }] });
  service.getEvidenceDetail.mockImplementation((_, key) => Promise.resolve({ evidence: { evidence_key: key, title: key.includes('historical') ? 'Historical evidence' : 'a.txt', file_path: key, snapshot: { initial_description: 'detail' }, metadata: {}, related_event_ids: [] } }));
  renderPage();
  await screen.findByText('Claim A');
  fireEvent.click(screen.getByText('Claim A'));
  await screen.findByText('Claim 历史引用 / 已不属于当前 Event');
  expect(screen.getAllByText('file:/historical.txt').length).toBeGreaterThan(0);
});

test('shows unavailable historical citation instead of silently dropping it', async () => {
  service.getInvestigationEvents.mockResolvedValue({ events: [{ ...events[0], semantic_source: 'accepted', semantic_version_id: 'ev1', effective_semantic_valid: true }] });
  service.getEffectiveEventClaims.mockResolvedValue({ claims: [{ id: 'c1', claim_text: 'Claim unavailable', type: 'fact', status: 'review_pending', grounding_status: 'grounded', evidence_refs: [{ evidence_key: 'file:/missing.txt' }] }] });
  service.getEventEvidence.mockResolvedValue({ evidence: [] });
  service.getEvidenceDetail.mockRejectedValue(new Error('not found'));
  renderPage();
  await screen.findByText('Claim unavailable');
  fireEvent.click(screen.getByText('Claim unavailable'));
  await screen.findByText('Claim 历史引用 / 已不属于当前 Event');
  expect(screen.getAllByText('file:/missing.txt').length).toBeGreaterThan(0);
  expect(screen.getByText('Evidence unavailable / unresolved')).toBeInTheDocument();
});

test('ignores every late response from a previously selected evidence item', async () => {
  const deferred = () => {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
  };
  const a = { detail: deferred(), versions: deferred(), graph: deferred() };
  service.getEvidenceDetail.mockImplementation((_, key) => key === 'file:/a.txt' ? a.detail.promise : Promise.resolve({ evidence: { evidence_key: 'file:/b.txt', title: 'b.txt', file_path: '/b.txt', snapshot: { initial_description: 'Initial B' }, metadata: {}, related_event_ids: [] } }));
  service.getAnalysisVersions.mockImplementation((_, key) => key === 'file:/a.txt' ? a.versions.promise : Promise.resolve({ versions: [{ id: 'b', version: 1, status: 'accepted', description: 'B analysis' }] }));
  service.getLocalGraph.mockImplementation((_, payload) => payload.evidence_key === 'file:/a.txt' ? a.graph.promise : Promise.resolve({ nodes: [{ id: 'b-node', label: 'B graph' }], links: [], base_available: false }));
  renderPage();
  await screen.findByText('a.txt');
  fireEvent.click(screen.getByTestId('evidence-file:/a.txt'));
  fireEvent.click(screen.getByTestId('event-e2'));
  await screen.findByText('b.txt');
  fireEvent.click(screen.getByTestId('evidence-file:/b.txt'));
  await screen.findByText('B analysis');
  await act(async () => {
    a.detail.resolve({ evidence: { evidence_key: 'file:/a.txt', title: 'a.txt', file_path: '/a.txt', snapshot: { initial_description: 'Late A' }, metadata: {}, related_event_ids: [] } });
    a.versions.resolve({ versions: [{ id: 'a', version: 1, status: 'accepted', description: 'A analysis' }] });
    a.graph.resolve({ nodes: [{ id: 'a-node', label: 'A graph' }], links: [], base_available: false });
  });
  expect(screen.getByText('B analysis')).toBeInTheDocument();
  expect(screen.queryByText('A analysis')).not.toBeInTheDocument();
  expect(screen.queryByText('Late A')).not.toBeInTheDocument();
});
