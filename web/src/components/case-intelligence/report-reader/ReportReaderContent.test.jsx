import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import ReportReaderContent from './ReportReaderContent';
import * as associationService from '../../../services/associationService';

vi.mock('../../../services/associationService', async (importOriginal) => ({
  ...(await importOriginal()),
  getFileEvents: vi.fn(),
}));

function renderContent(props = {}) {
  const node = {
    id: 'chapter-1',
    kind: 'chapter',
    title: '证据清单',
  };
  const pageData = {
    records: [
      {
        markdown:
          '本案关键证据文件：\n- 证据 [[file:/case/a.txt]] 为核心文件。',
      },
    ],
    page: 1,
    page_size: 20,
  };
  return render(
    <MemoryRouter>
      <ReportReaderContent
        node={node}
        report={{ metadata: { task_id: 't1' } }}
        pageData={pageData}
        loading={false}
        taskId="t1"
        {...props}
      />
    </MemoryRouter>,
  );
}

test('clicking a file badge opens the file + related-events drawer', async () => {
  associationService.getFileEvents.mockResolvedValue({
    success: true,
    matched_by: 'exact_path',
    events: [{ id: 1, timestamp: 1_700_000_000, event_type: 'CREATED', description: 'd' }],
    total_count: 1,
  });

  renderContent();

  const badge = await screen.findByRole('button', { name: /a\.txt/ });
  fireEvent.click(badge);

  await waitFor(() => expect(screen.getByTestId('file-events-drawer')).toBeInTheDocument());
  expect(associationService.getFileEvents).toHaveBeenCalledWith('t1', '/case/a.txt', 200);
  expect(screen.getAllByTestId('file-event-row')).toHaveLength(1);
});

test('the drawer is not open before any badge click', () => {
  renderContent();
  expect(screen.queryByTestId('file-events-drawer')).not.toBeInTheDocument();
});
