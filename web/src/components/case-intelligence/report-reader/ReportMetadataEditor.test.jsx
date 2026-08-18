/**
 * Tests for ReportMetadataEditor: loads metadata on open and persists on submit.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithRouter } from '../../../test/renderWithRouter';
import ReportMetadataEditor from './ReportMetadataEditor';

vi.mock('../../../services/intelligenceReportService', () => ({
  getReportMetadata: vi.fn(),
  saveReportMetadata: vi.fn(),
}));

import { getReportMetadata, saveReportMetadata } from '../../../services/intelligenceReportService';

// Stub the ToastContext via the Button/toast — wrap provider in test helper is enough;
// useToast is consumed; provide a minimal stand-in by mocking the context.
vi.mock('../../common/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  getReportMetadata.mockResolvedValue({
    metadata: { case_name: '原案件名', holder: '张三', collector_name: '' },
  });
  saveReportMetadata.mockResolvedValue({
    metadata: { case_name: '新案件名', holder: '张三' },
  });
});

test('loads metadata on open and submits the edited payload', async () => {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  renderWithRouter(
    <ReportMetadataEditor taskId="task-1" isOpen onClose={onClose} onSaved={onSaved} />,
  );

  // waits for GET to populate the form
  await waitFor(() => expect(getReportMetadata).toHaveBeenCalledWith('task-1'));
  await waitFor(() => expect(screen.getByDisplayValue('原案件名')).toBeInTheDocument());

  // edit the case name
  fireEvent.change(screen.getByDisplayValue('原案件名'), { target: { value: '新案件名' } });

  // submit
  fireEvent.click(screen.getByText('保存'));

  await waitFor(() => expect(saveReportMetadata).toHaveBeenCalledWith('task-1',
    expect.objectContaining({ case_name: '新案件名' })));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  await waitFor(() => expect(onClose).toHaveBeenCalled());
});

test('does not load when closed', () => {
  renderWithRouter(
    <ReportMetadataEditor taskId="task-1" isOpen={false} onClose={() => {}} />,
  );
  expect(getReportMetadata).not.toHaveBeenCalled();
});
