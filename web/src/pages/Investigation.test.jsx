import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  createSecondaryAnalysis: vi.fn(),
  reviewSecondaryAnalysis: vi.fn(),
  listInvestigationAnalysisClaims: vi.fn(),
  listInvestigationEvents: vi.fn(),
  getInvestigationEvent: vi.fn(),
  listInvestigationEventVersions: vi.fn(),
  listInvestigationEventEvidence: vi.fn(),
  listInvestigationEventRefreshes: vi.fn(),
  createInvestigationEvent: vi.fn(),
  linkInvestigationEventEvidence: vi.fn(),
  startInvestigationEventRefresh: vi.fn(),
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
    createSecondaryAnalysis: { analysis_id: 'sa_new', status: 'queued' },
    reviewSecondaryAnalysis: analysisRow(),
    listInvestigationAnalysisClaims: claimsResponse(),
    getInvestigationEvent: versions.event,
    listInvestigationEventVersions: versions.versions,
    listInvestigationEventEvidence: versions.links,
    listInvestigationEventRefreshes: versions.refreshes,
    createInvestigationEvent: {
      event_id: 'ie_new', task_id: 't1', needs_refresh: false, current_version: 1,
      title: 'New event', summary: 'fresh v1 narrative',
      created_at: '2026-08-16T00:00:00+00:00', updated_at: '2026-08-16T00:00:00+00:00',
    },
    linkInvestigationEventEvidence: {
      task_id: 't1', event_id: EVENT_ID, evidence_key: KEY_B,
      linked_at: '2026-08-16T00:00:00+00:00', linked_by: 'analyst-1',
    },
    startInvestigationEventRefresh: {
      refresh_id: 'er_new', task_id: 't1', event_id: EVENT_ID,
      base_version: 3, status: 'queued', requested_by: 'analyst-1',
      created_at: '2026-08-16T00:00:00+00:00',
    },
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

describe('Investigation Workbench analysis actions (C9b)', () => {
  const NEW_ANALYSIS_ID = 'sa_new';

  beforeEach(() => {
    ForceGraph2D.mockClear();
    stubService();
  });

  async function openEvidenceAndForm() {
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const detail = await screen.findByTestId('evidence-detail');
    act(() => within(detail).getByTestId('run-analysis-toggle').click());
    return detail;
  }

  // 让 polling 与 analysisBundle 共用同一个 exact GET：按 analysis_id 分发。
  function stubExactAnalysis(analysisById) {
    service.getInvestigationAnalysis.mockImplementation(
      async (taskId, analysisId) => analysisById[analysisId] ?? analysisRow(),
    );
    service.listInvestigationAnalysisClaims.mockImplementation(
      async (taskId, analysisId) => ({
        ...claimsResponse(),
        analysis_id: analysisId,
        claims: claimsResponse().claims.map((claim) => ({ ...claim, analysis_id: analysisId })),
      }),
    );
  }

  test('submit sends exactly the backend contract fields and auto-selects the new analysis at review_pending', async () => {
    stubExactAnalysis({
      [ANALYSIS_ID]: analysisRow(),
      [NEW_ANALYSIS_ID]: { ...analysisRow(NEW_ANALYSIS_ID, 3, 'review_pending'), evidence_key: KEY_A },
    });
    const detail = await openEvidenceAndForm();

    await userEvent.type(within(detail).getByTestId('analyst-note-input'), 'note from analyst');
    await userEvent.type(within(detail).getByTestId('case-context-input'), 'case background');
    await userEvent.click(within(detail).getByTestId(`related-option-${KEY_B}`));
    await userEvent.click(within(detail).getByTestId('submit-analysis-button'));

    // 请求只携带后端 CreateAnalysisRequest 支持的字段（extra=forbid）。
    await waitFor(() => expect(service.createSecondaryAnalysis).toHaveBeenCalledTimes(1));
    expect(service.createSecondaryAnalysis).toHaveBeenCalledWith('t1', KEY_A, {
      analystNote: 'note from analyst',
      caseContext: 'case background',
      relatedEvidence: [KEY_B],
    });

    // admission 的 exact analysis_id 成为轮询身份；完成后自动选中该 analysis。
    await waitFor(() => expect(service.getInvestigationAnalysis).toHaveBeenCalledWith('t1', NEW_ANALYSIS_ID));
    const analysisDetail = await screen.findByTestId('analysis-detail');
    expect(within(analysisDetail).getByText(NEW_ANALYSIS_ID)).toBeInTheDocument();
    expect(within(analysisDetail).getByText('investigation_workbench.awaiting_review')).toBeInTheDocument();
    expect(within(analysisDetail).getByTestId('review-decision-form')).toBeInTheDocument();
  });

  test('related evidence picker only offers other captured evidence of the task', async () => {
    const detail = await openEvidenceAndForm();
    const options = within(detail).getByTestId('related-evidence-options');
    expect(within(options).getByTestId(`related-option-${KEY_B}`)).toBeInTheDocument();
    // primary evidence 自动排除；没有自由输入框
    expect(within(options).queryByTestId(`related-option-${KEY_A}`)).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('related-evidence-free-input')).not.toBeInTheDocument();
  });

  test('rapid double click submits exactly one POST', async () => {
    stubExactAnalysis({
      [NEW_ANALYSIS_ID]: { ...analysisRow(NEW_ANALYSIS_ID, 3, 'review_pending'), evidence_key: KEY_A },
    });
    const detail = await openEvidenceAndForm();
    fireEvent.click(within(detail).getByTestId('submit-analysis-button'));
    fireEvent.click(within(detail).getByTestId('submit-analysis-button'));
    await waitFor(() => expect(service.createSecondaryAnalysis).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(service.createSecondaryAnalysis).toHaveBeenCalledTimes(1);
  });

  test('a late completion never yanks the workspace after the analyst switched evidence', async () => {
    const gate = {};
    gate.promise = new Promise((resolve) => { gate.resolve = resolve; });
    // 该 submission 的轮询响应被扣住，直到用户已切到 KEY_B 之后才放行
    service.getInvestigationAnalysis.mockImplementation(async (taskId, analysisId) => {
      if (analysisId === NEW_ANALYSIS_ID) return gate.promise;
      return analysisRow();
    });
    service.listInvestigationAnalysisClaims.mockImplementation(
      async (taskId, analysisId) => ({ ...claimsResponse(), analysis_id: analysisId }),
    );
    const detail = await openEvidenceAndForm();
    await userEvent.click(within(detail).getByTestId('submit-analysis-button'));
    await waitFor(() => expect(service.createSecondaryAnalysis).toHaveBeenCalledTimes(1));

    // 切到另一条 Evidence：右栏必须停留在 KEY_B
    act(() => screen.getByTestId(`evidence-item-${KEY_B}`).click());
    await screen.findByText(KEY_B);
    expect(screen.queryByTestId('analysis-detail')).not.toBeInTheDocument();

    // E1 的 A1 轮询此刻才完成——只刷新 read-side，不把右栏切回 E1
    await act(async () => gate.resolve({ ...analysisRow(NEW_ANALYSIS_ID, 3, 'review_pending'), evidence_key: KEY_A }));
    await waitFor(() => expect(service.listInvestigationEvidence).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('evidence-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('analysis-detail')).not.toBeInTheDocument();
  });

  test('review_pending exposes the review form and an explicit decision reloads all read-sides', async () => {
    stubService({ getInvestigationAnalysis: analysisRow(ANALYSIS_ID, 2, 'review_pending') });
    stubExactAnalysis({ [ANALYSIS_ID]: analysisRow(ANALYSIS_ID, 2, 'review_pending') });
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    const detail = await screen.findByTestId('analysis-detail');

    // grounding=valid + review_pending：显示待复核，绝不显示 accepted
    expect(within(detail).getByText('investigation_workbench.awaiting_review')).toBeInTheDocument();
    expect(within(detail).queryByText('accepted')).not.toBeInTheDocument();

    const form = within(detail).getByTestId('review-decision-form');
    expect(within(form).getByText('investigation_workbench.review_terminal_warning')).toBeInTheDocument();

    await userEvent.click(within(form).getByTestId('review-decision-rejected'));
    await userEvent.type(within(form).getByTestId('reviewer-input'), 'analyst-9');
    await userEvent.type(within(form).getByTestId('review-reason-input'), 'not supported');
    await userEvent.click(within(form).getByTestId('submit-review-button'));

    // 请求体只有 ReviewAnalysisRequest 的四个字段语义
    await waitFor(() => expect(service.reviewSecondaryAnalysis).toHaveBeenCalledTimes(1));
    expect(service.reviewSecondaryAnalysis).toHaveBeenCalledWith('t1', ANALYSIS_ID, {
      decision: 'rejected',
      reviewer: 'analyst-9',
      reason: 'not supported',
    });

    // §9：统一失效重读——exact analysis / evidence 选择徽章 / events；
    // 版本列表按 selection key 在回到 evidence 视图时重读（见下）
    await waitFor(() => expect(service.getInvestigationAnalysis.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(service.listInvestigationEvidence.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(service.listInvestigationEvents.mock.calls.length).toBeGreaterThanOrEqual(2));

    // 回到 evidence 视图：版本列表重新读取（不做本地状态 patch）
    await userEvent.click(within(detail).getByText('investigation_workbench.goto_evidence'));
    await screen.findByTestId('evidence-detail');
    await waitFor(() => expect(service.listInvestigationAnalyses.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  test('review decision reloads the graph when the graph tab is mounted', async () => {
    stubExactAnalysis({ [ANALYSIS_ID]: analysisRow(ANALYSIS_ID, 2, 'review_pending') });
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    await userEvent.click(screen.getByTestId('tab-graph'));
    await waitFor(() => expect(service.getInvestigationGraph).toHaveBeenCalledTimes(1));

    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    await screen.findByTestId('analysis-detail');

    const form = screen.getByTestId('review-decision-form');
    await userEvent.type(within(form).getByTestId('reviewer-input'), 'analyst-9');
    await userEvent.click(within(form).getByTestId('submit-review-button'));

    // review 成功后只调用 graph refresh，前端不改节点/confirmed
    await waitFor(() => expect(service.getInvestigationGraph.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(service.getInvestigationGraph).toHaveBeenCalledWith('t1', { maxBaseNodes: 200 });
  });

  test('review controls stay hidden for non-review_pending statuses', async () => {
    stubService({ getInvestigationAnalysis: analysisRow(ANALYSIS_ID, 2, 'accepted') });
    stubExactAnalysis({ [ANALYSIS_ID]: analysisRow(ANALYSIS_ID, 2, 'accepted') });
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    const detail = await screen.findByTestId('analysis-detail');

    expect(screen.queryByTestId('review-decision-form')).not.toBeInTheDocument();
    // 已决策的分析显示决策信息分区
    expect(within(detail).getByText('analyst-1')).toBeInTheDocument();
  });

  test('failed analysis surfaces error_code/error_message without any automatic resubmission', async () => {
    const failedRow = {
      ...analysisRow(ANALYSIS_ID, 2, 'failed'),
      error_code: 'LLM_TIMEOUT',
      error_message: 'sanitized failure detail',
    };
    stubService({ getInvestigationAnalysis: failedRow });
    stubExactAnalysis({ [ANALYSIS_ID]: failedRow });
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    const detail = await screen.findByTestId('analysis-detail');

    expect(within(detail).getByText('LLM_TIMEOUT')).toBeInTheDocument();
    expect(within(detail).getByText('sanitized failure detail')).toBeInTheDocument();
    expect(within(detail).getByText('investigation_workbench.failure_no_retry')).toBeInTheDocument();
    expect(screen.queryByTestId('review-decision-form')).not.toBeInTheDocument();
    expect(service.createSecondaryAnalysis).not.toHaveBeenCalled();
  });

  test('submitted analyst context renders the frozen envelope, not the live form', async () => {
    const row = {
      ...analysisRow(),
      input_envelope_json: JSON.stringify({
        schema_version: 2,
        analyst_note: 'frozen note',
        case_context: 'frozen context',
        related_evidence: [{ evidence_key: KEY_B, snapshot: { evidence_key: KEY_B } }],
      }),
    };
    stubService({ getInvestigationAnalysis: row });
    stubExactAnalysis({ [ANALYSIS_ID]: row });
    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    const detail = await screen.findByTestId('analysis-detail');

    expect(within(detail).getByText('frozen note')).toBeInTheDocument();
    expect(within(detail).getByText('frozen context')).toBeInTheDocument();
    expect(within(detail).getByText(KEY_B)).toBeInTheDocument();
  });
});

describe('Investigation Workbench event actions (C9c)', () => {
  const NEW_EVENT_ID = 'ie_new';
  const NEW_REFRESH_ID = 'er_new';
  const EVENT_2_ID = 'ie_222';
  const TS = '2026-08-16T00:00:00+00:00';

  beforeEach(() => {
    ForceGraph2D.mockClear();
    stubService();
  });

  async function openEvent(eventId = EVENT_ID) {
    renderPage();
    await screen.findByTestId(`event-item-${eventId}`);
    act(() => screen.getByTestId(`event-item-${eventId}`).click());
    return screen.findByTestId('event-detail');
  }

  // 轮询 history 与 eventBundle 共用同一个 GET：mutable 行对象随步骤推进。
  function stubEventState(initial) {
    const state = { ...initial };
    service.listInvestigationEvents.mockImplementation(async () => [{ ...state }]);
    service.getInvestigationEvent.mockImplementation(async () => ({ ...state }));
    return state;
  }

  test('creates an event with exactly the backend contract fields and selects it from a reload', async () => {
    // 新事件从 exact GET 读取（不插入本地临时 row）
    service.getInvestigationEvent.mockImplementation(
      async (taskId, eventId) => (eventId === NEW_EVENT_ID
        ? { event_id: NEW_EVENT_ID, task_id: 't1', needs_refresh: false, current_version: 1, title: 'USB exfil', summary: 'suspected exfiltration', created_at: TS, updated_at: TS }
        : eventBundleResponses().event),
    );
    renderPage();
    act(() => screen.getByTestId('new-event-toggle').click());

    await userEvent.type(screen.getByTestId('event-title-input'), 'USB exfil');
    await userEvent.type(screen.getByTestId('event-summary-input'), 'suspected exfiltration');
    await userEvent.type(screen.getByTestId('event-created-by-input'), 'analyst-1');
    await userEvent.click(screen.getByTestId('create-event-button'));

    await waitFor(() => expect(service.createInvestigationEvent).toHaveBeenCalledTimes(1));
    expect(service.createInvestigationEvent).toHaveBeenCalledWith('t1', {
      title: 'USB exfil',
      summary: 'suspected exfiltration',
      createdBy: 'analyst-1',
    });
    // Event list 重新读取；selection 切到 exact new event_id
    await waitFor(() => expect(service.listInvestigationEvents.mock.calls.length).toBeGreaterThanOrEqual(2));
    const detail = await screen.findByTestId('event-detail');
    expect(within(detail).getByText('USB exfil')).toBeInTheDocument();
    expect(service.getInvestigationEvent).toHaveBeenCalledWith('t1', NEW_EVENT_ID);
  });

  test('rapid double click on create posts exactly once', async () => {
    renderPage();
    act(() => screen.getByTestId('new-event-toggle').click());
    await userEvent.type(screen.getByTestId('event-title-input'), 'dup');
    await userEvent.type(screen.getByTestId('event-created-by-input'), 'analyst-1');
    fireEvent.click(screen.getByTestId('create-event-button'));
    fireEvent.click(screen.getByTestId('create-event-button'));
    await waitFor(() => expect(service.createInvestigationEvent).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(service.createInvestigationEvent).toHaveBeenCalledTimes(1);
  });

  test('create form keeps the analyst-event disclaimer, not a timeline-cluster conversion', async () => {
    renderPage();
    act(() => screen.getByTestId('new-event-toggle').click());
    expect(screen.getByText('investigation_workbench.event_form_disclaimer')).toBeInTheDocument();
  });

  test('link picker only offers captured evidence that is not already linked', async () => {
    const detail = await openEvent();
    // KEY_A 已在 fixture links 中：候选只有 KEY_B；没有自由输入
    act(() => within(detail).getByTestId('add-evidence-toggle').click());
    const options = within(detail).getByTestId('link-evidence-options');
    expect(within(options).getByTestId(`link-option-${KEY_B}`)).toBeInTheDocument();
    expect(within(options).queryByTestId(`link-option-${KEY_A}`)).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('link-evidence-free-input')).not.toBeInTheDocument();
  });

  test('linking posts the exact contract fields and reloads links/list/graph', async () => {
    renderPage();
    // 先在 Timeline 选中事件（切到 Graph 后 Timeline 卸载）
    await screen.findByTestId(`event-item-${EVENT_ID}`);
    act(() => screen.getByTestId(`event-item-${EVENT_ID}`).click());
    const detail = await screen.findByTestId('event-detail');
    await userEvent.click(screen.getByTestId('tab-graph'));
    await waitFor(() => expect(service.getInvestigationGraph).toHaveBeenCalledTimes(1));

    act(() => within(detail).getByTestId('add-evidence-toggle').click());
    await userEvent.click(within(detail).getByTestId(`link-option-${KEY_B}`));
    await userEvent.type(within(detail).getByTestId('linked-by-input'), 'analyst-7');
    await userEvent.click(within(detail).getByTestId('link-evidence-button'));

    await waitFor(() => expect(service.linkInvestigationEventEvidence).toHaveBeenCalledTimes(1));
    expect(service.linkInvestigationEventEvidence).toHaveBeenCalledWith('t1', EVENT_ID, KEY_B, {
      linkedBy: 'analyst-7',
    });
    // §6：link 成功 → event links/detail、Event list、Graph 全部重读
    await waitFor(() => expect(service.listInvestigationEventEvidence.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(service.listInvestigationEvents.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(service.getInvestigationGraph.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  test('a 409 duplicate link shows a stable conflict message', async () => {
    service.linkInvestigationEventEvidence.mockRejectedValue(
      Object.assign(new Error('duplicate'), { status: 409 }),
    );
    const detail = await openEvent();
    act(() => within(detail).getByTestId('add-evidence-toggle').click());
    await userEvent.click(within(detail).getByTestId(`link-option-${KEY_B}`));
    await userEvent.type(within(detail).getByTestId('linked-by-input'), 'analyst-7');
    await userEvent.click(within(detail).getByTestId('link-evidence-button'));

    const error = await within(detail).findByTestId('link-evidence-error');
    expect(error.textContent).toContain('investigation_workbench.link_conflict');
  });

  test('a late link success after switching events never yanks the selection back', async () => {
    const gate = {};
    gate.promise = new Promise((resolve) => { gate.resolve = resolve; });
    service.linkInvestigationEventEvidence.mockImplementation(async () => gate.promise);
    // 两个事件：E1 fixture + E2
    service.listInvestigationEvents.mockImplementation(async () => [
      ...eventRows(),
      { event_id: EVENT_2_ID, task_id: 't1', needs_refresh: false, current_version: 1, title: 'Event two', summary: null, created_at: TS, updated_at: TS },
    ]);
    service.getInvestigationEvent.mockImplementation(
      async (taskId, eventId) => (eventId === EVENT_2_ID
        ? { event_id: EVENT_2_ID, task_id: 't1', needs_refresh: false, current_version: 1, title: 'Event two', summary: null, created_at: TS, updated_at: TS }
        : eventBundleResponses().event),
    );
    const detail = await openEvent();
    act(() => within(detail).getByTestId('add-evidence-toggle').click());
    await userEvent.click(within(detail).getByTestId(`link-option-${KEY_B}`));
    await userEvent.type(within(detail).getByTestId('linked-by-input'), 'analyst-7');
    await userEvent.click(within(detail).getByTestId('link-evidence-button'));

    // E1 POST 未返回时用户切到 E2
    act(() => screen.getByTestId(`event-item-${EVENT_2_ID}`).click());
    const detailTwo = await screen.findByTestId('event-detail');
    expect(within(detailTwo).getByText('Event two')).toBeInTheDocument();

    // E1 link 此刻才成功：只失效全局数据，selection 停留在 E2
    await act(async () => gate.resolve({ task_id: 't1', event_id: EVENT_ID, evidence_key: KEY_B, linked_at: TS, linked_by: 'analyst-7' }));
    await waitFor(() => expect(service.listInvestigationEvents.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(within(screen.getByTestId('event-detail')).getByText('Event two')).toBeInTheDocument();
  });

  test('refresh stays available on a dirty event with the staleness hint', async () => {
    const dirtyDetail = await openEvent(); // fixture: needs_refresh=true
    expect(within(dirtyDetail).getByText('investigation_workbench.refresh_hint_dirty')).toBeInTheDocument();
    await userEvent.type(within(dirtyDetail).getByTestId('requested-by-input'), 'analyst-9');
    // needs_refresh=true 绝不禁用 refresh（只换提示文案）
    expect(within(dirtyDetail).getByTestId('refresh-narrative-button')).not.toBeDisabled();
    expect(within(dirtyDetail).queryByTestId('refresh-in-progress')).not.toBeInTheDocument();
  });

  test('refresh stays available on a clean event (R8: only the hint changes)', async () => {
    stubEventState({ ...eventRows()[0], needs_refresh: false });
    const cleanDetail = await openEvent();
    expect(within(cleanDetail).getByText('investigation_workbench.refresh_hint_clean')).toBeInTheDocument();
    await userEvent.type(within(cleanDetail).getByTestId('requested-by-input'), 'analyst-9');
    // needs_refresh=0 同样允许显式 refresh（C7c R8）
    expect(within(cleanDetail).getByTestId('refresh-narrative-button')).not.toBeDisabled();
    expect(within(cleanDetail).queryByText('investigation_workbench.needs_refresh')).not.toBeInTheDocument();
  });

  test('refresh admission posts only task_id/requested_by and polls the exact refresh_id', async () => {
    const state = stubEventState({ ...eventRows()[0] });
    const erRow = {
      refresh_id: NEW_REFRESH_ID, task_id: 't1', event_id: EVENT_ID,
      base_version: 3, status: 'queued', requested_by: 'analyst-9', created_at: TS,
    };
    // gate 只扣住 admission 之后的第一次轮询，不劫持 bundle 的初始加载。
    let admitted = false;
    let firstPollGated = false;
    const gate = {};
    gate.promise = new Promise((resolve) => { gate.resolve = resolve; });
    service.startInvestigationEventRefresh.mockImplementation(async () => {
      admitted = true;
      return { ...erRow };
    });
    service.listInvestigationEventRefreshes.mockImplementation(async () => {
      if (admitted && !firstPollGated) {
        firstPollGated = true;
        return gate.promise;
      }
      return [...eventBundleResponses().refreshes, { ...erRow }];
    });

    const detail = await openEvent();
    await userEvent.type(within(detail).getByTestId('requested-by-input'), 'analyst-9');
    await userEvent.click(within(detail).getByTestId('refresh-narrative-button'));

    await waitFor(() => expect(service.startInvestigationEventRefresh).toHaveBeenCalledTimes(1));
    expect(service.startInvestigationEventRefresh).toHaveBeenCalledWith('t1', EVENT_ID, {
      requestedBy: 'analyst-9',
    });

    // admission 不等待 LLM：首个轮询在途时按钮已进入 busy
    await waitFor(() => expect(screen.getByTestId('refresh-in-progress')).toBeInTheDocument());
    expect(screen.getByTestId('refresh-narrative-button')).toBeDisabled();

    // 轮询看到 exact refresh_id 已 completed → terminal 处理 + 全量重读
    Object.assign(erRow, { status: 'completed', produced_version: 4 });
    Object.assign(state, { needs_refresh: false, current_version: 4, summary: 'narrative v4', updated_at: TS });
    await act(async () => gate.resolve([{ ...erRow }]));
    await waitFor(() => expect(service.getInvestigationEvent.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(service.listInvestigationEventVersions.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(service.listInvestigationEvents.mock.calls.length).toBeGreaterThanOrEqual(2));

    const updated = await screen.findByTestId('event-detail');
    await waitFor(() => expect(within(updated).getByText('narrative v4')).toBeInTheDocument());
    expect(within(updated).getByText(NEW_REFRESH_ID)).toBeInTheDocument();
    // §14：primary selection 仍是 Event（右栏还是 event-detail，不是 refresh 对象）
    expect(within(updated).queryByText('investigation_workbench.needs_refresh')).not.toBeInTheDocument();
  });

  test('a failed refresh stops polling, surfaces the error, and never retries automatically', async () => {
    stubEventState({ ...eventRows()[0] });
    const erRow = {
      refresh_id: NEW_REFRESH_ID, task_id: 't1', event_id: EVENT_ID,
      base_version: 3, status: 'queued', requested_by: 'analyst-9', created_at: TS,
    };
    // 第一次轮询即看到 failed（queued→failed 中间态由 hook 测试覆盖）
    service.startInvestigationEventRefresh.mockImplementation(async () => ({ ...erRow }));
    service.listInvestigationEventRefreshes.mockImplementation(async () => [{
      ...erRow,
      status: 'failed', failed_at: TS,
      error_code: 'llm_timeout', error_message: 'sanitized timeout detail',
    }]);

    const detail = await openEvent();
    await userEvent.type(within(detail).getByTestId('requested-by-input'), 'analyst-9');
    await userEvent.click(within(detail).getByTestId('refresh-narrative-button'));
    await waitFor(() => expect(service.startInvestigationEventRefresh).toHaveBeenCalledTimes(1));

    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    await waitFor(() => expect(service.getInvestigationEvent.mock.calls.length).toBeGreaterThanOrEqual(2));

    const updated = await screen.findByTestId('event-detail');
    const historyRow = within(updated).getByTestId(`refresh-item-${NEW_REFRESH_ID}`);
    expect(within(historyRow).getByText('llm_timeout')).toBeInTheDocument();
    expect(within(historyRow).getByText('sanitized timeout detail')).toBeInTheDocument();
    expect(within(historyRow).getByText('investigation_workbench.failure_no_retry')).toBeInTheDocument();
    // 不自动重试；terminal 后按钮恢复（Refresh Again = 显式新 refresh_id）
    expect(service.startInvestigationEventRefresh).toHaveBeenCalledTimes(1);
    expect(within(updated).getByTestId('refresh-narrative-button')).not.toBeDisabled();
  });

  test('base_version_changed renders the neutral concurrency explanation', async () => {
    const versions = eventBundleResponses();
    stubService({
      listInvestigationEventRefreshes: [
        {
          refresh_id: 'er_bvc', task_id: 't1', event_id: EVENT_ID, base_version: 2,
          status: 'failed', requested_by: 'analyst-1', created_at: TS, failed_at: TS,
          error_code: 'base_version_changed', error_message: 'base moved to v3',
        },
        ...versions.refreshes,
      ],
    });
    const detail = await openEvent();
    const row = within(detail).getByTestId('refresh-item-er_bvc');
    expect(within(row).getByText('base_version_changed')).toBeInTheDocument();
    expect(within(row).getByText('investigation_workbench.base_version_changed_note')).toBeInTheDocument();
  });

  // §26：Evidence Analysis accepted → Event dirty → 显式 refresh → 新版本 + clean
  test('integration chain: accepted analysis marks the event dirty, refresh produces a clean new version', async () => {
    const state = stubEventState({
      ...eventRows()[0], needs_refresh: false, current_version: 1, summary: 'narrative v1',
    });
    // C9b review：accepted 后服务器把 Event 标 dirty（C7b propagation）
    service.reviewSecondaryAnalysis.mockImplementation(async () => {
      state.needs_refresh = true;
      return analysisRow(ANALYSIS_ID, 2, 'accepted');
    });
    const pending = analysisRow(ANALYSIS_ID, 2, 'review_pending');
    service.getInvestigationAnalysis.mockImplementation(
      async (taskId, analysisId) => (analysisId === ANALYSIS_ID ? pending : analysisRow()),
    );
    service.listInvestigationAnalysisClaims.mockImplementation(
      async (taskId, analysisId) => ({ ...claimsResponse(), analysis_id: analysisId }),
    );

    renderPage();
    await screen.findByTestId(`evidence-item-${KEY_A}`);
    act(() => screen.getByTestId(`evidence-item-${KEY_A}`).click());
    const evidenceDetail = await screen.findByTestId('evidence-detail');
    act(() => within(evidenceDetail).getByTestId(`analysis-item-${ANALYSIS_ID}`).click());
    await screen.findByTestId('analysis-detail');
    const form = screen.getByTestId('review-decision-form');
    await userEvent.click(within(form).getByTestId('review-decision-accepted'));
    await userEvent.type(within(form).getByTestId('reviewer-input'), 'analyst-9');
    await userEvent.click(within(form).getByTestId('submit-review-button'));
    await waitFor(() => expect(service.reviewSecondaryAnalysis).toHaveBeenCalledTimes(1));

    // Event reload 返回 needs_refresh=true → dirty badge 出现（§25 critical）
    act(() => screen.getByTestId(`event-item-${EVENT_ID}`).click());
    const dirtyDetail = await screen.findByTestId('event-detail');
    expect(within(dirtyDetail).getByText('investigation_workbench.needs_refresh')).toBeInTheDocument();

    // 显式 refresh → exact refresh_id 轮询 → completed → 服务器返回 clean v2
    const erRow = {
      refresh_id: NEW_REFRESH_ID, task_id: 't1', event_id: EVENT_ID,
      base_version: 1, status: 'queued', requested_by: 'analyst-9', created_at: TS,
    };
    // admission 返回 queued；此后服务器完成写入（新版本 + clean），
    // 第一次轮询即看到 completed。
    service.startInvestigationEventRefresh.mockImplementation(async () => {
      Object.assign(erRow, { status: 'completed', produced_version: 2 });
      Object.assign(state, {
        needs_refresh: false, current_version: 2, summary: 'narrative v2', updated_at: TS,
      });
      return { ...erRow, status: 'queued' };
    });
    service.listInvestigationEventRefreshes.mockImplementation(async () => [{ ...erRow }]);

    await userEvent.type(within(dirtyDetail).getByTestId('requested-by-input'), 'analyst-9');
    await userEvent.click(within(dirtyDetail).getByTestId('refresh-narrative-button'));
    await waitFor(() => expect(service.startInvestigationEventRefresh).toHaveBeenCalledTimes(1));

    const cleanDetail = await screen.findByTestId('event-detail');
    await waitFor(() => expect(within(cleanDetail).getByText('narrative v2')).toBeInTheDocument());
    expect(within(cleanDetail).queryByText('investigation_workbench.needs_refresh')).not.toBeInTheDocument();
    expect(within(cleanDetail).getAllByText(/v2/).length).toBeGreaterThan(0);
  });

  // §26 并发版本：completed 后 Event reload 仍 needs_refresh=true → dirty badge 保留
  test('integration chain: completed refresh with a concurrent accepted analysis keeps the event dirty', async () => {
    const state = stubEventState({
      ...eventRows()[0], needs_refresh: true, current_version: 2, summary: 'narrative v2',
    });
    const erRow = {
      refresh_id: NEW_REFRESH_ID, task_id: 't1', event_id: EVENT_ID,
      base_version: 2, status: 'queued', requested_by: 'analyst-9', created_at: TS,
    };
    // admission 返回 queued；执行期间 A2 accepted → completed 写入 v3 但仍 dirty
    // （C7c-2 completion-time staleness），第一次轮询即看到 completed。
    service.startInvestigationEventRefresh.mockImplementation(async () => {
      Object.assign(erRow, { status: 'completed', produced_version: 3 });
      Object.assign(state, { current_version: 3, summary: 'narrative v3' });
      // needs_refresh 保持 true——绝不能被前端本地清除
      return { ...erRow, status: 'queued' };
    });
    service.listInvestigationEventRefreshes.mockImplementation(async () => [{ ...erRow }]);

    const detail = await openEvent();
    await userEvent.type(within(detail).getByTestId('requested-by-input'), 'analyst-9');
    await userEvent.click(within(detail).getByTestId('refresh-narrative-button'));
    await waitFor(() => expect(service.startInvestigationEventRefresh).toHaveBeenCalledTimes(1));

    const updated = await screen.findByTestId('event-detail');
    await waitFor(() => expect(within(updated).getByText('narrative v3')).toBeInTheDocument());
    // completed ≠ clean：dirty badge 由服务器 reload 决定，仍然显示
    expect(within(updated).getByText('investigation_workbench.needs_refresh')).toBeInTheDocument();
  });
});
