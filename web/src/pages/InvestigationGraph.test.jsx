import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('react-force-graph-2d', () => ({
  default: vi.fn(() => <div data-testid="force-graph-mock" />),
}));

vi.mock('../hooks/useInvestigationGraph', () => ({
  useInvestigationGraph: vi.fn(),
}));

vi.mock('../hooks/useTranslation', () => ({
  useTranslation: () => ({ t: (key) => key, language: 'en' }),
}));

import ForceGraph2D from 'react-force-graph-2d';
import { useInvestigationGraph } from '../hooks/useInvestigationGraph';
import InvestigationGraph from './InvestigationGraph';

const EVIDENCE_ID = 'evidence:file:/case/a';

function mixedGraph(overrides = {}) {
  return {
    task_id: 't1',
    base_graph_available: true,
    base_max_nodes: 200,
    nodes: [
      { id: 'u-1', name: 'Bob', label: 'User', source: 'base_kg', confirmed: null, provenance: null },
      { id: 'u-2', name: 'Cleanup Tool', label: 'Process', source: 'base_kg', confirmed: null, provenance: null },
      { id: 'event:e1', name: 'USB insertion', label: 'InvestigationEvent', source: 'investigation', confirmed: null, provenance: { event_id: 'e1', version: 3 } },
      { id: EVIDENCE_ID, name: 'file:/case/a', label: 'Evidence', source: 'investigation', confirmed: null, provenance: { evidence_key: 'file:/case/a', evidence_type: 'file' } },
      { id: 'analysis:a1', name: 'Analysis v2 - file:/case/a', label: 'Analysis', source: 'investigation', confirmed: true, summary: 'Accepted analysis', provenance: { analysis_id: 'a1', evidence_key: 'file:/case/a', version: 2, review_state: 'accepted' } },
      { id: 'claim:c1', name: 'Device was attached', label: 'Claim', source: 'investigation', confirmed: false, provenance: { claim_id: 'c1', analysis_id: 'a1', claim_type: 'FACT', grounding_status: 'grounded' } },
    ],
    links: [
      { id: 'base:u-1:USES:u-2', source: 'u-1', target: 'u-2', label: 'USES', kind: 'base_relation' },
      { id: 'event_evidence:e1:file:/case/a', source: 'event:e1', target: EVIDENCE_ID, label: 'LINKS_EVIDENCE', kind: 'event_evidence' },
      { id: 'analysis_evidence:a1:file:/case/a', source: 'analysis:a1', target: EVIDENCE_ID, label: 'ANALYZES_EVIDENCE', kind: 'analysis_evidence' },
      { id: 'analysis_claim:a1:c1', source: 'analysis:a1', target: 'claim:c1', label: 'CONTAINS_CLAIM', kind: 'analysis_claim' },
      { id: 'claim_evidence:c1:file:/case/a', source: 'claim:c1', target: EVIDENCE_ID, label: 'REFERENCES_EVIDENCE', kind: 'claim_evidence' },
    ],
    warnings: [],
    ...overrides,
  };
}

// React may append a zero-arg spy invocation; only calls carrying props count.
const lastCanvasProps = () => {
  const call = ForceGraph2D.mock.calls.filter((args) => args[0] && args[0].graphData).at(-1);
  return call ? call[0] : undefined;
};

const refresh = vi.fn();

function renderPage({ route = '/investigation-graph?task_id=t1' } = {}) {
  let navigate;
  function Harness() {
    navigate = useNavigate();
    return <InvestigationGraph />;
  }
  const view = render(
    <MemoryRouter initialEntries={[route]}>
      <Harness />
    </MemoryRouter>,
  );
  return {
    ...view,
    navigateTo: (next) => act(async () => navigate(next)),
    clickNode: (node) => act(() => lastCanvasProps().onNodeClick(node)),
  };
}

const setGraphState = ({ graph, loading = false, error = null }) => {
  useInvestigationGraph.mockReturnValue({ graph, loading, error, refresh });
};

describe('InvestigationGraph page', () => {
  beforeEach(() => {
    ForceGraph2D.mockClear();
    refresh.mockClear();
    useInvestigationGraph.mockReset();
    setGraphState({ graph: mixedGraph() });
  });

  test('renders base and overlay nodes side by side with namespace counts', () => {
    renderPage();
    expect(screen.getByText('investigation_graph.base_nodes: 2')).toBeInTheDocument();
    expect(screen.getByText('investigation_graph.overlay_nodes: 4')).toBeInTheDocument();
    expect(lastCanvasProps().graphData.nodes).toHaveLength(6);
    expect(lastCanvasProps().graphData.links).toHaveLength(5);
    // namespace legend shows the four investigation entries plus Base KG
    expect(screen.getByText('InvestigationEvent')).toBeInTheDocument();
    expect(screen.getByText('Base KG')).toBeInTheDocument();
  });

  test('base degradation keeps the overlay rendered and only warns', () => {
    setGraphState({
      graph: mixedGraph({ base_graph_available: false, warnings: ['base_graph_unavailable'] }),
    });
    renderPage();
    expect(screen.getByTestId('base-unavailable-warning')).toHaveTextContent(
      'investigation_graph.base_unavailable_warning',
    );
    // overlay nodes are still handed to the renderer
    expect(lastCanvasProps().graphData.nodes).toHaveLength(6);
    expect(screen.queryByTestId('graph-error')).not.toBeInTheDocument();
  });

  test('a 503 investigation store failure is an explicit error state, not an empty graph', () => {
    setGraphState({
      graph: { nodes: [], links: [], warnings: [] },
      error: { message: 'unavailable', status: 503, data: { detail: 'investigation store is unavailable' } },
    });
    renderPage();
    expect(screen.getByTestId('graph-error')).toHaveTextContent('HTTP 503');
    expect(screen.getByText('investigation store is unavailable')).toBeInTheDocument();
    expect(ForceGraph2D.mock.calls.length).toBe(0);
    expect(screen.queryByTestId('graph-empty')).not.toBeInTheDocument();

    act(() => screen.getByRole('button', { name: 'investigation_graph.retry' }).click());
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  test('a fully empty graph shows the dedicated empty state', () => {
    setGraphState({ graph: mixedGraph({ nodes: [], links: [] }) });
    renderPage();
    expect(screen.getByTestId('graph-empty')).toHaveTextContent('investigation_graph.empty');
    expect(screen.queryByTestId('base-unavailable-warning')).not.toBeInTheDocument();
  });

  test('asks for a task when none is selected and disables refresh', () => {
    renderPage({ route: '/investigation-graph' });
    expect(screen.getByText('investigation_graph.no_task')).toBeInTheDocument();
    expect(screen.getByTestId('refresh-graph')).toBeDisabled();
  });

  test('evidence node click selects the exact deterministic evidence id', async () => {
    renderPage();
    await clickEvidenceNode();
    const panel = screen.getByTestId('node-detail-panel');
    expect(within(panel).getByText(EVIDENCE_ID)).toBeInTheDocument();
    expect(within(panel).getByText('evidence')).toBeInTheDocument();
    expect(within(panel).getAllByText('file:/case/a').length).toBeGreaterThan(0);
    // evidence never shows an unconfirmed badge even when confirmed is falsy
    expect(within(panel).queryByText('investigation_graph.unconfirmed')).not.toBeInTheDocument();
  });

  test('event and analysis node clicks surface their frozen provenance fields', async () => {
    renderPage();
    const nodes = lastCanvasProps().graphData.nodes;
    act(() => lastCanvasProps().onNodeClick(nodes.find((n) => n.id === 'event:e1')));
    const eventPanel = screen.getByTestId('node-detail-panel');
    expect(await within(eventPanel).findByText('event:e1')).toBeInTheDocument();
    expect(within(eventPanel).getByText('current version')).toBeInTheDocument();

    act(() => lastCanvasProps().onNodeClick(nodes.find((n) => n.id === 'analysis:a1')));
    const analysisPanel = screen.getByTestId('node-detail-panel');
    expect(await within(analysisPanel).findByText('review_state')).toBeInTheDocument();
    expect(within(analysisPanel).getByText('accepted')).toBeInTheDocument();
    expect(within(analysisPanel).getByText('investigation_graph.confirmed')).toBeInTheDocument();
    expect(within(analysisPanel).getByText('version')).toBeInTheDocument();
  });

  test('an unconfirmed claim is flagged while base nodes are not', async () => {
    renderPage();
    const nodes = lastCanvasProps().graphData.nodes;
    act(() => lastCanvasProps().onNodeClick(nodes.find((n) => n.id === 'claim:c1')));
    const claimPanel = screen.getByTestId('node-detail-panel');
    expect(await within(claimPanel).findByText('claim:c1')).toBeInTheDocument();
    expect(within(claimPanel).getByText('FACT')).toBeInTheDocument();
    expect(within(claimPanel).getByText('grounded')).toBeInTheDocument();
    expect(within(claimPanel).getAllByText('investigation_graph.unconfirmed').length).toBe(1);

    act(() => lastCanvasProps().onNodeClick(nodes.find((n) => n.id === 'u-1')));
    const basePanel = screen.getByTestId('node-detail-panel');
    expect(await within(basePanel).findByText('u-1')).toBeInTheDocument();
    expect(within(basePanel).queryByText('investigation_graph.unconfirmed')).not.toBeInTheDocument();
  });

  test('switching the task clears the selected graph node', async () => {
    const { navigateTo } = renderPage();
    await clickEvidenceNode();
    expect(screen.getByText(EVIDENCE_ID)).toBeInTheDocument();

    await navigateTo('/investigation-graph?task_id=t2');
    expect(screen.getByText('investigation_graph.select_hint')).toBeInTheDocument();
    expect(screen.queryByText(EVIDENCE_ID)).not.toBeInTheDocument();
  });

  test('the base node limit selector reloads with the new bound', async () => {
    renderPage();
    expect(useInvestigationGraph).toHaveBeenLastCalledWith({ taskId: 't1', maxBaseNodes: 200 });
    await userEvent.selectOptions(screen.getByTestId('max-base-nodes'), '500');
    expect(useInvestigationGraph).toHaveBeenLastCalledWith({ taskId: 't1', maxBaseNodes: 500 });
  });
});

async function clickEvidenceNode() {
  const nodes = lastCanvasProps().graphData.nodes;
  act(() => lastCanvasProps().onNodeClick(nodes.find((n) => n.id === EVIDENCE_ID)));
}
