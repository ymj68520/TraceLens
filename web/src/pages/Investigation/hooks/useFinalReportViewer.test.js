import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import useFinalReportViewer from './useFinalReportViewer';
import { getFinalReport, getFinalReports } from '../../../services/investigationService';

vi.mock('../../../services/investigationService', () => ({
  getFinalReports: vi.fn(),
  getFinalReport: vi.fn(),
}));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

const reports = [
  { report_id: 'r3', report_version: 3, status: 'assembled' },
  { report_id: 'r2', report_version: 2, status: 'assembled' },
  { report_id: 'r1', report_version: 1, status: 'assembled' },
];

beforeEach(() => {
  vi.clearAllMocks();
});

test('selects the first backend version and loads its explicit detail', async () => {
  getFinalReports.mockResolvedValue({ reports });
  getFinalReport.mockResolvedValue({ report: { ...reports[0], sections: [] } });

  const { result } = renderHook(() => useFinalReportViewer('task-a'));

  await waitFor(() => expect(result.current.selectedReportId).toBe('r3'));
  await waitFor(() => expect(result.current.selectedReport?.report_id).toBe('r3'));
  expect(getFinalReports).toHaveBeenCalledWith('task-a');
  expect(getFinalReport).toHaveBeenCalledWith('task-a', 'r3');
  expect(result.current.reports).toEqual(reports);
});

test('clears old state and ignores late responses after task switch', async () => {
  const taskAList = deferred();
  const taskBList = deferred();
  const taskADetail = deferred();
  const taskBDetail = deferred();
  getFinalReports.mockImplementation((taskId) => taskId === 'task-a' ? taskAList.promise : taskBList.promise);
  getFinalReport.mockImplementation((taskId) => taskId === 'task-a' ? taskADetail.promise : taskBDetail.promise);

  const { result, rerender } = renderHook(
    ({ taskId }) => useFinalReportViewer(taskId),
    { initialProps: { taskId: 'task-a' } },
  );

  await act(async () => {
    taskAList.resolve({ reports: [{ report_id: 'a1', report_version: 1 }] });
  });
  await waitFor(() => expect(getFinalReport).toHaveBeenCalledWith('task-a', 'a1'));

  rerender({ taskId: 'task-b' });
  expect(result.current.reports).toEqual([]);
  expect(result.current.selectedReportId).toBeNull();
  expect(result.current.selectedReport).toBeNull();

  await act(async () => {
    taskBList.resolve({ reports: [{ report_id: 'b1', report_version: 1 }] });
  });
  await waitFor(() => expect(getFinalReport).toHaveBeenCalledWith('task-b', 'b1'));

  await act(async () => {
    taskADetail.resolve({ report: { report_id: 'a1', sections: [{ section_id: 'SEC-001' }] } });
    taskBDetail.resolve({ report: { report_id: 'b1', sections: [{ section_id: 'SEC-002' }] } });
  });

  await waitFor(() => expect(result.current.selectedReport?.report_id).toBe('b1'));
  expect(result.current.selectedReport.sections[0].section_id).toBe('SEC-002');
});

test('detail error preserves the version list and retry uses selected report id', async () => {
  getFinalReports.mockResolvedValue({ reports: [reports[0]] });
  getFinalReport.mockRejectedValueOnce({ status: 404, message: 'not found' }).mockResolvedValueOnce({ report: reports[0] });

  const { result } = renderHook(() => useFinalReportViewer('task-a'));

  await waitFor(() => expect(result.current.detailError).toBe('Report version not found.'));
  expect(result.current.reports).toEqual([reports[0]]);

  await act(async () => {
    await result.current.retryDetail();
  });
  await waitFor(() => expect(result.current.selectedReport?.report_id).toBe('r3'));
  expect(getFinalReport).toHaveBeenLastCalledWith('task-a', 'r3');
});
