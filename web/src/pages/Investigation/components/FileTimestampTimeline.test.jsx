import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi, beforeEach } from 'vitest';
import FileTimestampTimeline, { formatFileTime } from './FileTimestampTimeline';
import { pythonApi } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  pythonApi: { get: vi.fn() },
}));

const T0 = 1_700_000_000;

const payload = {
  success: true,
  task_id: 't1',
  scope_size: 3,
  total_count: 2,
  axis: { start: T0, end: T0 + 600 },
  files: [
    { path: '/case/a.txt', name: 'a.txt', size: 10, crtime: T0, mtime: T0 + 600, atime: null, ctime: null },
    { path: '/case/b.bin', name: 'b.bin', size: 20, crtime: T0 + 300, mtime: T0 + 300, atime: T0 + 300, ctime: T0 + 300 },
  ],
};

beforeEach(() => {
  pythonApi.get.mockReset();
  pythonApi.get.mockResolvedValue(payload);
});

test('renders the file timeline rows, markers, and axis range', async () => {
  render(<FileTimestampTimeline taskId="t1" />);

  await waitFor(() => expect(screen.getAllByTestId('file-timeline-row')).toHaveLength(2));
  expect(pythonApi.get).toHaveBeenCalledWith('/api/associations/file-timeline', { params: { task_id: 't1' } });
  // axis label shows start → end formatted times
  expect(screen.getByTestId('file-timeline-axis').textContent).toContain('→');
  // a.txt has exactly two timestamps; b.bin has four markers
  const rows = screen.getAllByTestId('file-timeline-row');
  expect(rows[0].querySelectorAll('[data-testid="file-timeline-marker-crtime"]')).toHaveLength(1);
  expect(rows[0].querySelectorAll('[data-testid^="file-timeline-marker-"]')).toHaveLength(2);
  expect(rows[1].querySelectorAll('[data-testid^="file-timeline-marker-"]')).toHaveLength(4);
});

test('paginates long lists behind a load-more control', async () => {
  const many = Array.from({ length: 450 }, (_, i) => ({
    path: `/case/f${i}.txt`, name: `f${i}.txt`, size: 1,
    crtime: T0 + i, mtime: null, atime: null, ctime: null,
  }));
  pythonApi.get.mockResolvedValue({ ...payload, files: many, total_count: 450 });
  render(<FileTimestampTimeline taskId="t1" />);

  await waitFor(() => expect(screen.getAllByTestId('file-timeline-row')).toHaveLength(200));
  fireEvent.click(screen.getByRole('button', { name: /加载更多/ }));
  await waitFor(() => expect(screen.getAllByTestId('file-timeline-row')).toHaveLength(400));
});

test('shows the empty and error states', async () => {
  pythonApi.get.mockResolvedValue({ ...payload, files: [], axis: { start: null, end: null } });
  const { container } = render(<FileTimestampTimeline taskId="t1" />);
  await waitFor(() => expect(screen.getByText(/暂无带时间戳的文件/)).toBeInTheDocument());
  expect(container.querySelectorAll('[data-testid="file-timeline-row"]')).toHaveLength(0);

  pythonApi.get.mockRejectedValue({ message: 'boom' });
  render(<FileTimestampTimeline taskId="t2" />);
  await waitFor(() => expect(screen.getByTestId('file-timeline-error')).toHaveTextContent('boom'));
});

test('formatFileTime formats unix seconds and rejects junk', () => {
  expect(formatFileTime(T0)).toBe(new Date(T0 * 1000).toLocaleString());
  expect(formatFileTime(null)).toBeNull();
  expect(formatFileTime('abc')).toBeNull();
});
