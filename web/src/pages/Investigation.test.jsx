import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('react-force-graph-2d', () => ({
  default: vi.fn(() => <div data-testid="force-graph-mock" />),
}));

vi.mock('../services/investigationService', () => ({
  getInvestigationGraph: vi.fn(),
  listInvestigationEvidence: vi.fn(),
  getInvestigationSnapshot: vi.fn(),
  listInvestigationAnalyses: vi.fn(),
  getInvestigationAnalysis: vi.fn(),
  listInvestigationAnalysisClaims: vi.fn(),
  listInvestigationEvents: vi.fn(),
  getInvestigationEvent: vi.fn(),
  listInvestigationEventVersions: vi.fn(),
  listInvestigationEventEvidence: vi.fn(),
  listInvestigationEventRefreshes: vi.fn(),
}));

vi.mock('../hooks/useTranslation', () => ({
  useTranslation: () => ({ t: (key) => key, language: 'en' }),
}));

import ForceGraph2D from 'react-force-graph-2d';
import * as service from '../services/investigationService';
import Investigation from './Investigation';

const KEY_A = 'file:/case/a.txt';
const KEY_B = 'file:/case/b.txt';
const EVENT_ID = 'ie_111';
const ANALYSIS_ID = 'sa_222';
const CLAIM_ID = 'cl_333';

// React may append a zero-arg spy invocation; only calls carrying props count.
const lastCanvasProps = () => {
  const call = ForceGraph2D.mock.calls.filter((args) => args[0] && args[0].graphData).at(-1);
  return call ? call[0] : undefined;
};

function graphResponse() {
  return {
    task_id: 't1',
    base_graph_available: true,
    base_max_nodes: 200,
    nodes: [
      { id: `event:${EVENT_ID}`, name: 'Event', label: 'InvestigationEvent', source: 'investigation', provenance: { event_id: EVENT_ID, version: 1 } },
      { id: `evidence:${KEY_A}`, name: KEY_A, label: 'Evidence', source: 'investigation', provenance: { evidence_key: KEY_A } },
      { id: `analysis:${ANALYSIS_ID}`, name: 'Analysis v1', label: 'Analysis', source: 'investigation', confirmed: true, provenance: { analysis_id: ANALYSIS_ID, review_state: 'accepted' } },
      { id: `claim:${CLAIM_ID}`, name: 'claim text', label: 'Claim', source: 'investigation', confirmed: false, provenance: { claim_id: CLAIM_ID, analysis_id: ANALYSIS_ID, claim_type: 'FACT', grounding_status: 'grounded' } },
    ],
    links: [],
    warnings: [],
  };
}

function evidenceRows() {
  return [
    { task_id: 't1', evidence_key: KEY_A, evidence_type: 'file', captured_at: 1, selected_analysis: { evidence_key: KEY_A, analysis_id: ANALYSIS_ID, version: 2, review_state: 'accepted', summary: 'accepted summary' } },
    { task_id: 't1', evidence_key: KEY_B, evidence_type: 'file', captured_at: 2, selected_analysis: null },
  ];
}

function snapshotResponse() {
  return {
    task_id: 't1',
    evidence_key: KEY_A,
    evidence_type: 'file',
    captured_at: 1700000000,
    payload: {
      normalized_path: '/case/a.txt',
      initial_summary: 'frozen summary',
      initial_description: 'frozen initial analysis',
      initial_model: 'model-x',
    },
  };
}

function analysisRow(id = ANALYSIS_ID, version = 2, status = 'accepted') {
  return {
    analysis_id: id, task_id: 't1', evidence_key: KEY_A, version, status,
    input_hash: 'h', input_envelope_json: '{}', prompt_version: 'p',
    description: 'analysis description', summary: 'analysis summary', model: 'm',
    created_at: '2026-08-15T00:00:00+00:00', decided_by: 'analyst-1',
    decided_at: '2026-08-15T01:00:00+00:00', grounding_status: 'grounded',
  };
}

function claimsResponse() {
  return {
    task_id: 't1',
    analysis_id: ANALYSIS_ID,
    claims: [
      {
        claim_id: CLAIM_ID, analysis_id: ANALYSIS_ID, claim_index: 0,
        claim_type: 'FACT', claim_text: 'exact persisted claim',
        grounding_status: 'grounded', warnings: null,
        evidence_refs: [KEY_A, KEY_B], created_at: '2026-08-15T00:00:00+00:00',
      },
    ],
  };
}

function eventRows() {
  return [
    { event_id: EVENT_ID, task_id: 't1', needs_refresh: true, current_version: 3, title: 'USB event', summary: 'narrative v3', created_at: '2026-08-14T00:00:00+00:00', updated_at: '2026-08-15T00:00:00+00:00' },
  ];
}

function eventBundleResponses() {
  return {
    event: eventRows()[0],
    versions: [
      { task_id: 't1', event_id: EVENT_ID, version: 3, title: 'USB event', summary: 'narrative v3', created_at: '2026-08-15T00:00:00+00:00', created_by: 'refresh' },
      { task_id: 't1', event_id: EVENT_ID, version: 1, title: 'USB event', summary: 'narrative v1', created_at: '2026-08-14T00:00:00+00:00', created_by: 'analyst' },
    ],
    links: [
      { task_id: 't1', event_id: EVENT_ID, evidence_key: KEY_A, linked_at: '2026-08-14T12:00:00+00:00', linked_by: 'analyst-1' },
    ],
    refreshes: [
      { refresh_id: 'er_1', task_id: 't1', event_id: EVENT_ID, base_version: 2, status: 'completed', produced_version: 3, created_at: '2026-08-15T00:00:00+00:00' },
    ],
  };
}

function stubService(overrides = {}) {
  const versions = eventBundleResponses();
  const defaults = {
    listInvestigationEvidence: evidenceRows(),
    listInvestigationEvents: eventRows(),
    getInvestigationSnapshot: snapshotResponse(),
    listInvestigationAnalyses: [analysisRow()],
    getInvestigationAnalysis: analysisRow(),
    listInvestigationAnalysisClaims: claimsResponse(),
    getInvestigationEvent: versions.event,
    listInvestigationEventVersions: versions.versions,
    listInvestigationEventEvidence: versions.links,
    listInvestigationEventRefreshes: versions.refreshes,
    getInvestigationGraph: graphResponse(),
    ...overrides,
  };
  for (const [name, value] of Object.entries(defaults)) {
    service[name].mockReset();
    if (value instanceof Error || (value && typeof value.then === 'function')) {
      service[name].mockRejectedValue(value);
    } else if (Array.isArray(value) && value[0] instanceof Error) {
      service[name].mockRejectedValue(value[0]);
    } else {
      service[name].mockResolvedValue(value);
    }
  }
}

function renderPage({ route = '/investigation?task_id=t1' } = {}) {
  let navigate;
  function Harness() {
    navigate = useNavigate();
    return <Investigation />;
  }
  const view = render(
    <MemoryRouter initialEntries={[route]}>
      <Harness />
    </MemoryRouter>,
  );
  return { ...view, navigateTo: (next) => act(async () => navigate(next)) };
}

describe('Investigation Workbench (C9a)', () => {
  beforeEach(() => {
    ForceGraph2D.mockClear();
    stubService();
  });

  test('renders the three workspaces with task-level lists', async () => {
    renderPage();
    expect(await screen.findByTestId(`evidence-item-${KEY_A}`)).toBeInTheDocument();
    expect(screen.getByTestId(`evidence-item-${KEY_B}`)).toBeInTheDocument();
    expect(await screen.findByTestId(`event-item-${EVENT_ID}`)).toBeInTheDocument();
    // selection state from the backend surfaces as badges, not client recomputation
    expect(screen.getByText('accepted')).toBeInTheDocument();
    expect(screen.getByTestId('evidence-count').textContent).toContain('2');
    expect(screen.getByTestId('event-count').textContent).toContain('1');
    expect(screen.getByTestId('needs-refresh-count')).toBeInTheDocument();
    // right column shows the selection hint until something is selected
    expect(screen.getByTestId('detail-empty')).toBeInTheDocument();
    expect(service.listInvestigationEvidence).toHaveBeenCalledWith('t1');
    expect(service.listInvestigationEvents).toHaveBeenCalledWith('t1');
  });

  test('evidence click shows the Snapshot Initial Analysis and analysis versions', async () => {
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());

    const detail = await screen.findByTestId('evidence-detail');
    expect(within(detail).getByText('frozen initial analysis')).toBeInTheDocument();
    expect(within(detail).getByText('frozen summary')).toBeInTheDocument();
    expect(within(detail).getByText('model-x')).toBeInTheDocument();
    // Initial Analysis comes from the snapshot endpoint only
    expect(service.getInvestigationSnapshot).toHaveBeenCalledWith('t1', KEY_A);
    expect(await within(detail).findByTestId(`analysis-item-${ANALYSIS_ID}`)).toBeInTheDocument();
    expect(service.listInvestigationAnalyses).toHaveBeenCalledWith('t1', KEY_A);
  });

  test('analysis click loads the exact analysis and its exact persisted claims', async () => {
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());

    const detail = await screen.findByTestId('analysis-detail');
    expect(within(detail).getByText(ANALYSIS_ID)).toBeInTheDocument();
    expect(within(detail).getByText('analysis description')).toBeInTheDocument();
    expect(within(detail).getByText('analyst-1')).toBeInTheDocument();
    expect(service.getInvestigationAnalysis).toHaveBeenCalledWith('t1', ANALYSIS_ID);
    expect(service.listInvestigationAnalysisClaims).toHaveBeenCalledWith('t1', ANALYSIS_ID);

    // claim click → exact persisted claim provenance
    act(() => within(detail).getByTestId(`claim-item-${CLAIM_ID}`).click());
    const claimDetail = await screen.findByTestId('claim-detail');
    expect(within(claimDetail).getByText(CLAIM_ID)).toBeInTheDocument();
    expect(within(claimDetail).getByText('exact persisted claim')).toBeInTheDocument();
    expect(within(claimDetail).getByTestId(`claim-ref-${KEY_A}`)).toBeInTheDocument();
    expect(within(claimDetail).getByTestId(`claim-ref-${KEY_B}`)).toBeInTheDocument();
    expect(within(claimDetail).getByText(ANALYSIS_ID)).toBeInTheDocument();
  });

  test('claim evidence ref click routes back to the evidence workspace', async () => {
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    const detail = await screen.findByTestId('analysis-detail');
    act(() => within(detail).getByTestId(`claim-item-${CLAIM_ID}`).click());
    const claimDetail = await screen.findByTestId('claim-detail');
    act(() => within(claimDetail).getByTestId(`claim-ref-${KEY_B}`).click());

    const backToEvidence = await screen.findByTestId('evidence-detail');
    expect(within(backToEvidence).getByText(KEY_B)).toBeInTheDocument();
    expect(service.getInvestigationSnapshot).toHaveBeenCalledWith('t1', KEY_B);
  });

  test('event click drives the left authoritative evidence list and the right narrative panel', async () => {
    renderPage();
    await screen.findByTestId(`event-item-${EVENT_ID}`);
    act(() => screen.getByTestId(`event-item-${EVENT_ID}`).click());

    // right: current narrative + versions + refresh status
    const detail = await screen.findByTestId('event-detail');
    expect(within(detail).getByText('USB event')).toBeInTheDocument();
    expect(within(detail).getByText('narrative v3')).toBeInTheDocument();
    expect(within(detail).getAllByText(/v3|v1/).length).toBeGreaterThan(0);
    expect(within(detail).getByText('er_1')).toBeInTheDocument();
    expect(within(detail).getByText('completed')).toBeInTheDocument();
    expect(within(detail).getByText('investigation_workbench.needs_refresh')).toBeInTheDocument();
    expect(service.getInvestigationEvent).toHaveBeenCalledWith('t1', EVENT_ID);
    expect(service.listInvestigationEventVersions).toHaveBeenCalledWith('t1', EVENT_ID);
    expect(service.listInvestigationEventRefreshes).toHaveBeenCalledWith('t1', EVENT_ID);

    // left: authoritative event evidence replaces the full task list
    expect(await screen.findByTestId(`event-evidence-${KEY_A}`)).toBeInTheDocument();
    const leftPanel = screen.getByTestId('evidence-workspace');
    expect(within(leftPanel).getByText(/analyst-1/)).toBeInTheDocument();
    expect(screen.queryByTestId(`evidence-item-${KEY_B}`)).not.toBeInTheDocument();
    expect(service.listInvestigationEventEvidence).toHaveBeenCalledWith('t1', EVENT_ID);
  });

  test('graph tab reuses the C8c canvas and maps overlay node clicks to selection', async () => {
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    await userEvent.click(screen.getByTestId('tab-graph'));

    // canvas mounted and consumed the graph endpoint (single implementation)
    await waitFor(() => expect(lastCanvasProps()).toBeDefined());
    expect(service.getInvestigationGraph).toHaveBeenCalledWith('t1', { maxBaseNodes: 200 });

    // claim node click → exact claim selection with analysis context
    act(() => lastCanvasProps().onNodeClick({
      id: `claim:${CLAIM_ID}`, label: 'Claim', source: 'investigation',
      provenance: { claim_id: CLAIM_ID, analysis_id: ANALYSIS_ID },
    }));
    const claimDetail = await screen.findByTestId('claim-detail');
    expect(within(claimDetail).getByText('exact persisted claim')).toBeInTheDocument();
    expect(service.getInvestigationAnalysis).toHaveBeenCalledWith('t1', ANALYSIS_ID);
    expect(service.listInvestigationAnalysisClaims).toHaveBeenCalledWith('t1', ANALYSIS_ID);

    // evidence node click → evidence selection
    act(() => lastCanvasProps().onNodeClick({
      id: `evidence:${KEY_B}`, label: 'Evidence', source: 'investigation',
      provenance: { evidence_key: KEY_B },
    }));
    await screen.findByTestId('evidence-detail');
    expect(service.getInvestigationSnapshot).toHaveBeenCalledWith('t1', KEY_B);

    // base KG nodes never drive a workbench selection
    act(() => lastCanvasProps().onNodeClick({ id: 'uuid-1', label: 'Entity', source: 'base_kg' }));
    await waitFor(() => expect(screen.getByTestId('evidence-detail')).toBeInTheDocument());
  });

  test('switching the task clears the selection and reloads the lists', async () => {
    const { navigateTo } = renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    await screen.findByTestId('evidence-detail');

    await navigateTo('/investigation?task_id=t2');
    expect(await screen.findByTestId('detail-empty')).toBeInTheDocument();
    expect(service.listInvestigationEvidence).toHaveBeenCalledWith('t2');
  });

  test('shows a distinct error state when the store is unavailable (503)', async () => {
    stubService({ listInvestigationEvidence: [Object.assign(new Error('down'), { status: 503 })] });
    renderPage();
    const workspace = await screen.findByTestId('evidence-workspace');
    expect(await within(workspace).findByText(/HTTP 503/)).toBeInTheDocument();
    expect(within(workspace).getByText('investigation_workbench.retry')).toBeInTheDocument();
    // events column is independent and still loads
    expect(await screen.findByTestId(`event-item-${EVENT_ID}`)).toBeInTheDocument();
  });

  test('asks for a task when none is selected', () => {
    renderPage({ route: '/investigation' });
    expect(screen.getByTestId('no-task')).toBeInTheDocument();
    expect(service.listInvestigationEvidence).not.toHaveBeenCalled();
  });

  test('graph tab keeps the overlay when the Base KG degrades', async () => {
    stubService({
      getInvestigationGraph: { ...graphResponse(), base_graph_available: false, warnings: ['base_graph_unavailable'] },
    });
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    await userEvent.click(screen.getByTestId('tab-graph'));
    await waitFor(() => expect(lastCanvasProps()).toBeDefined());
    expect(screen.getByTestId('workbench-base-unavailable')).toBeInTheDocument();
    expect(lastCanvasProps().graphData.nodes).toHaveLength(4);
  });
});
