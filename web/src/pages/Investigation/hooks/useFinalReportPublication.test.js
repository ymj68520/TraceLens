import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import useFinalReportPublication from './useFinalReportPublication';
import { getFinalReportPublication, publishFinalReport } from '../../../services/investigationService';

vi.mock('../../../services/investigationService', () => ({
  getFinalReportPublication: vi.fn(),
  publishFinalReport: vi.fn(),
}));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => { resolve = nextResolve; reject = nextReject; });
  return { promise, resolve, reject };
}

beforeEach(() => vi.clearAllMocks());

test('reads explicit report publication and preserves null as a successful fact', async () => {
  getFinalReportPublication.mockResolvedValue({ publication: null });
  const { result } = renderHook(() => useFinalReportPublication('task-a', 'r1', true));

  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.publication).toBeNull();
  expect(result.current.error).toBeNull();
  expect(getFinalReportPublication).toHaveBeenCalledWith('task-a', 'r1');
});

test('discards stale publication read after report switch', async () => {
  const r1 = deferred();
  const r2 = deferred();
  getFinalReportPublication.mockImplementation((taskId, reportId) => reportId === 'r1' ? r1.promise : r2.promise);
  const { result, rerender } = renderHook(
    ({ reportId }) => useFinalReportPublication('task-a', reportId, true),
    { initialProps: { reportId: 'r1' } },
  );

  rerender({ reportId: 'r2' });
  await waitFor(() => expect(getFinalReportPublication).toHaveBeenCalledWith('task-a', 'r2'));
  await act(async () => {
    r1.resolve({ publication: { report_id: 'r1', status: 'published' } });
    r2.resolve({ publication: null });
  });

  await waitFor(() => expect(result.current.publication).toBeNull());
  expect(result.current.error).toBeNull();
});

test('publishes selected report and refreshes the same report publication', async () => {
  getFinalReportPublication.mockResolvedValueOnce({ publication: null }).mockResolvedValueOnce({ publication: { report_id: 'r1', status: 'published' } });
  publishFinalReport.mockResolvedValue({ publication: { report_id: 'r1', status: 'published' } });
  const { result } = renderHook(() => useFinalReportPublication('task-a', 'r1', true));

  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => { await result.current.publish(); });

  expect(publishFinalReport).toHaveBeenCalledWith('task-a', 'r1');
  expect(getFinalReportPublication).toHaveBeenLastCalledWith('task-a', 'r1');
  expect(result.current.publication.status).toBe('published');
});

test('discards stale publish UI result after switching reports', async () => {
  const publish = deferred();
  getFinalReportPublication.mockResolvedValue({ publication: null });
  publishFinalReport.mockReturnValue(publish.promise);
  const { result, rerender } = renderHook(
    ({ reportId }) => useFinalReportPublication('task-a', reportId, true),
    { initialProps: { reportId: 'r1' } },
  );

  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => { void result.current.publish(); });
  rerender({ reportId: 'r2' });
  await waitFor(() => expect(getFinalReportPublication).toHaveBeenCalledWith('task-a', 'r2'));
  const readCountAfterSwitch = getFinalReportPublication.mock.calls.length;
  await act(async () => { publish.resolve({ publication: { report_id: 'r1', status: 'published' } }); });

  await waitFor(() => expect(result.current.publishSuccess).toBe(false));
  expect(getFinalReportPublication.mock.calls.length).toBe(readCountAfterSwitch);
});
