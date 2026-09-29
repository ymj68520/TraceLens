import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import LocalKnowledgeGraph from './LocalKnowledgeGraph';

vi.mock('react-force-graph-2d', async () => {
  const { forwardRef } = await import('react');
  return {
    default: forwardRef(({ graphData }, ref) => <div ref={ref} data-testid="force-graph-mock">{graphData.nodes.length} nodes</div>),
  };
});

test('shows task-scoped local entities and readable directed relations', () => {
  const graph = {
    base_available: true,
    nodes: [
      { id: 'path', name: '/case/UsrClass.dat', label: 'Entity', source: 'base_kg' },
      { id: 'name', name: 'UsrClass.dat', label: 'Entity', source: 'base_kg' },
    ],
    links: [{ id: 'relation', source: 'path', target: 'name', label: 'FILE_PATH_OF', kind: 'base_relation' }],
  };

  render(<LocalKnowledgeGraph graph={graph} />);

  expect(screen.getByTestId('force-graph-mock')).toHaveTextContent('2 nodes');
  expect(screen.getByTestId('local-graph-relations')).toHaveTextContent('UsrClass.dat（路径）— FILE_PATH_OF →UsrClass.dat');
  expect(graph.links[0].source).toBe('path');
});

test('does not invent a graph when no exact evidence relation exists', () => {
  render(<LocalKnowledgeGraph graph={{ base_available: true, nodes: [], links: [] }} />);
  expect(screen.getByText('暂无关联关系')).toHaveAttribute('title', '当前证据没有已记录的可核实关系。');
});
