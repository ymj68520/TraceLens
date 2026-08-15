import { render } from '@testing-library/react';
import { describe, expect, test, vi, beforeEach } from 'vitest';

vi.mock('react-force-graph-2d', () => ({
  default: vi.fn(() => <div data-testid="force-graph-mock" />),
}));

import ForceGraph2D from 'react-force-graph-2d';
import InvestigationGraphCanvas from './InvestigationGraphCanvas';

// React may append a zero-arg spy invocation; only calls carrying props count.
const canvasProps = () => {
  const call = ForceGraph2D.mock.calls.filter((args) => args[0] && args[0].graphData).at(-1);
  return call ? call[0] : undefined;
};

const data = {
  nodes: [
    { id: 'event:e1', name: 'Event One', label: 'InvestigationEvent', source: 'investigation' },
    { id: 'u-1', name: 'Base user', label: 'User', source: 'base_kg' },
  ],
  links: [
    { id: 'event_evidence:e1:k', source: 'event:e1', target: 'evidence:k', label: 'LINKS_EVIDENCE', kind: 'event_evidence' },
  ],
};

describe('InvestigationGraphCanvas', () => {
  beforeEach(() => {
    ForceGraph2D.mockClear();
  });

  test('passes backend nodes and links straight through without recomputing graph semantics', () => {
    render(<InvestigationGraphCanvas data={data} />);
    const props = canvasProps();
    expect(props.graphData.nodes).toEqual(data.nodes);
    expect(props.graphData.links).toEqual(data.links);
  });

  test('forwards node clicks with the exact backend node object', () => {
    const onNodeClick = vi.fn();
    render(<InvestigationGraphCanvas data={data} onNodeClick={onNodeClick} />);
    const node = { id: 'claim:c-9', label: 'Claim', source: 'investigation' };
    canvasProps().onNodeClick(node);
    expect(onNodeClick).toHaveBeenCalledWith(node);
  });

  test('empty or missing data still renders an empty graph', () => {
    render(<InvestigationGraphCanvas data={null} />);
    expect(canvasProps().graphData).toEqual({ nodes: [], links: [] });
  });

  test('tooltips route through the escaped builders and link colors through the kind map', () => {
    render(<InvestigationGraphCanvas data={data} />);
    const props = canvasProps();
    expect(props.nodeLabel({ id: 'x', name: '<b>raw</b>', label: 'Claim', source: 'investigation', provenance: {} }))
      .not.toContain('<b>raw</b>');
    expect(props.linkLabel({ label: 'CONTAINS_CLAIM' })).toBe('CONTAINS_CLAIM');
    expect(props.linkColor({ kind: 'claim_evidence' })).not.toBe(props.linkColor({ kind: 'base_relation' }));
  });

  test('pointer area paint tolerates being invoked (smoke)', () => {
    render(<InvestigationGraphCanvas data={data} />);
    const ctx = {
      beginPath: vi.fn(),
      arc: vi.fn(),
      set fillStyle(v) { this._fill = v; },
      get fillStyle() { return this._fill; },
      fill: vi.fn(),
    };
    expect(() => canvasProps().nodePointerAreaPaint({ x: 1, y: 2 }, '#fff', ctx)).not.toThrow();
    expect(ctx.arc).toHaveBeenCalledWith(1, 2, 9, 0, 2 * Math.PI);
  });
});
