import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import RelationshipTracePanel from './RelationshipTracePanel';

const trace = { relationship: {
  id: 'edge-1', label: 'USES_FILE', fact: 'Chrome uses the file.',
  source: { id: 's', name: 'Google Chrome' },
  target: { id: 't', name: 'ssl_error_assistant.pb' },
  episode_count: 1,
  episodes: [{
    id: 'episode-1', source_kind: 'llm_analysis',
    file_path: '/Chrome/ssl_error_assistant.pb',
    evidence_key: 'file:/Chrome/ssl_error_assistant.pb',
    content: 'file_path: /Chrome/ssl_error_assistant.pb\nanalysis: model text',
    original_preview: { available: true, kind: 'binary', file_size: 8,
      hex: '08 07 12 35', printable_strings: ['sha256/abc'],
      integrity_note: '提取副本，未与原镜像比对' },
  }],
} };

test('separates machine fact, episode text, and real extracted bytes', () => {
  render(<MemoryRouter><RelationshipTracePanel taskId="task-a" trace={trace} onClose={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText('机器提取 · 待人工核验')).toBeInTheDocument();
  expect(screen.getByText('Chrome uses the file.')).toBeInTheDocument();
  expect(screen.getByTestId('graph-source-episode-content')).toHaveTextContent('analysis: model text');
  expect(screen.getByTestId('graph-original-preview')).toHaveTextContent('08 07 12 35');
  expect(screen.getByText('sha256/abc')).toBeInTheDocument();
  expect(screen.getByText('打开任务文件证据与提取副本 →')).toHaveAttribute(
    'href', '/graph-source-file?task_id=task-a&evidence_key=file%3A%2FChrome%2Fssl_error_assistant.pb&relationship_id=edge-1&episode_id=episode-1',
  );
});
