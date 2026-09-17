import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi, beforeEach } from 'vitest';
import FileEventsDrawer from './FileEventsDrawer';
import * as associationService from '../../services/associationService';

vi.mock('../../services/associationService', async (importOriginal) => ({
  ...(await importOriginal()),
  getFileEvents: vi.fn(),
}));

// The drawer contains a react-router <Link> (index-file jump).
const renderDrawer = (props) =>
  render(
    <MemoryRouter>
      <FileEventsDrawer {...props} />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
});

test('renders nothing without a selected file', () => {
  renderDrawer({ taskId: "t1", filePath: null, onClose: () => {} });
  expect(screen.queryByTestId('file-events-drawer')).not.toBeInTheDocument();
  expect(associationService.getFileEvents).not.toHaveBeenCalled();
});

test('shows the file path, related events, and the index-file link', async () => {
  associationService.getFileEvents.mockResolvedValue({
    success: true,
    matched_by: 'exact_path',
    events: [
      { id: 1, timestamp: 1_700_000_000, event_type: 'CREATED', description: 'created d1' },
      { id: 2, timestamp: 1_700_000_100, event_type: 'MODIFIED', description: null },
    ],
    total_count: 2,
  });

  renderDrawer({ taskId: "t1", filePath: "/case/a.txt", onClose: () => {} });

  await waitFor(() => expect(screen.getAllByTestId('file-event-row')).toHaveLength(2));
  expect(associationService.getFileEvents).toHaveBeenCalledWith('t1', '/case/a.txt', 200);
  expect(screen.getByTestId('file-events-drawer').textContent).toContain('/case/a.txt');
  expect(screen.getByTestId('file-events-matched-by').textContent).toContain('2 条事件');
  expect(screen.getByText('created d1')).toBeInTheDocument();
  // file indexing: jump to the Files page with the task context kept
  expect(screen.getByTestId('file-events-index-link')).toHaveAttribute(
    'href',
    '/files?task_id=t1',
  );
});

test('shows the empty state when no events reference the file', async () => {
  associationService.getFileEvents.mockResolvedValue({
    success: true, matched_by: 'exact_path', events: [], total_count: 0,
  });
  renderDrawer({ taskId: "t1", filePath: "/case/none.txt", onClose: () => {} });
  await waitFor(() => expect(screen.getByText(/没有引用该文件的事件/)).toBeInTheDocument());
});

test('close button invokes onClose', async () => {
  associationService.getFileEvents.mockResolvedValue({ success: true, events: [], total_count: 0 });
  const onClose = vi.fn();
  renderDrawer({ taskId: "t1", filePath: "/case/a.txt", onClose });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Close file events drawer' })).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Close file events drawer' }));
  expect(onClose).toHaveBeenCalledTimes(1);
});
