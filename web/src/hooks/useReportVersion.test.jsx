import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportVersion } from './useReportVersion';

const ready = { report_id: 'r1', version: 1, status: 'ready' };
const running = { report_id: 'r2', version: 2, status: 'generating', progress: 20 };

test('selects latest ready version and loads its manifest', async () => {
  const source = {
    listVersions: vi.fn().mockResolvedValue([running, ready]),
    getStatus: vi.fn(),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r1', title: 'Report' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));

  await waitFor(() => expect(result.current.manifest?.report_id).toBe('r1'));
  expect(result.current.selectedVersion.report_id).toBe('r1');
});

test('polls an existing generating version after refresh until it is ready', async () => {
  vi.useFakeTimers();
  const source = {
    listVersions: vi.fn().mockResolvedValue([running]),
    getStatus: vi.fn().mockResolvedValue({ ...running, status: 'ready', progress: 100 }),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r2' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));

  await act(async () => vi.advanceTimersByTimeAsync(10));
  expect(result.current.manifest?.report_id).toBe('r2');
  vi.useRealTimers();
});
