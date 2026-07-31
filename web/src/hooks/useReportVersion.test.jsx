import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportVersion } from './useReportVersion';

const ready = { report_id: 'r1', version: 1, status: 'ready' };
const running = { report_id: 'r2', version: 2, status: 'generating', stage: 'snapshot', progress: 20 };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

async function flush() {
  await act(async () => { await Promise.resolve(); });
}

test('selects latest ready version and loads its manifest', async () => {
  const source = {
    listVersions: vi.fn().mockResolvedValue([running, ready]),
    getStatus: vi.fn().mockResolvedValue(running),
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

test('preserves a newly created version when an older refresh and manifest resolve late', async () => {
  const list = deferred();
  const oldManifest = deferred();
  const created = { report_id: 'r2', version: 2, status: 'queued', stage: 'queued', progress: 0 };
  const source = {
    listVersions: vi.fn().mockReturnValue(list.promise),
    createVersion: vi.fn().mockResolvedValue(created),
    getStatus: vi.fn(),
    getManifest: vi.fn().mockReturnValue(oldManifest.promise),
  };
  const { result } = renderHook(() => useReportVersion({ scopeType: 'task', scopeId: 't1', dataSource: source }));

  await act(async () => { await result.current.createVersion(); });
  list.resolve([ready]);
  oldManifest.resolve({ report_id: 'r1' });
  await flush();

  expect(result.current.selectedVersion).toEqual(created);
  expect(result.current.versions).toEqual([created]);
  expect(result.current.manifest).toBeNull();
});

test('keeps the selected generating version synchronized through progress and failure', async () => {
  vi.useFakeTimers();
  const progressed = { ...running, stage: 'index', progress: 50 };
  const failed = { ...running, status: 'failed', stage: 'index', error: 'disk full' };
  const source = {
    listVersions: vi.fn().mockResolvedValue([running]),
    getStatus: vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(progressed).mockResolvedValueOnce(failed),
    getManifest: vi.fn(),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));

  await act(async () => vi.advanceTimersByTimeAsync(5));
  expect(result.current.selectedVersion).toEqual(progressed);
  await act(async () => vi.advanceTimersByTimeAsync(5));
  expect(result.current.selectedVersion).toEqual(failed);
  expect(result.current.manifest).toBeNull();
  vi.useRealTimers();
});

test('retries polling after a transient status failure', async () => {
  vi.useFakeTimers();
  const readyVersion = { ...running, status: 'ready', progress: 100 };
  const source = {
    listVersions: vi.fn().mockResolvedValue([running]),
    getStatus: vi.fn().mockRejectedValueOnce(new Error('temporary')).mockResolvedValueOnce(readyVersion),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r2' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));

  await act(async () => vi.advanceTimersByTimeAsync(20));
  expect(source.getStatus).toHaveBeenCalledTimes(2);
  expect(result.current.manifest?.report_id).toBe('r2');
  vi.useRealTimers();
});

test('clears the old manifest immediately when selecting ready B and ignores a late A manifest', async () => {
  const aManifest = deferred();
  const bManifest = deferred();
  const versionB = { report_id: 'r2', version: 2, status: 'ready' };
  const source = {
    listVersions: vi.fn().mockResolvedValue([ready, versionB]),
    getStatus: vi.fn(),
    getManifest: vi.fn()
      .mockReturnValueOnce(aManifest.promise)
      .mockReturnValueOnce(bManifest.promise),
  };
  const { result } = renderHook(() => useReportVersion({ scopeType: 'task', scopeId: 't1', dataSource: source }));
  await flush();

  await act(async () => { void result.current.selectVersion(versionB); });
  expect(result.current.selectedVersion).toEqual(versionB);
  expect(result.current.manifest).toBeNull();
  aManifest.resolve({ report_id: 'r1' });
  bManifest.reject(new Error('manifest unavailable'));
  await flush();

  expect(result.current.manifest).toBeNull();
  expect(result.current.error).toMatchObject({ message: 'manifest unavailable' });
});

test('derives ready polling state before writing versions and loads its manifest', async () => {
  vi.useFakeTimers();
  const readyVersion = { ...running, status: 'ready', progress: 100 };
  const source = {
    listVersions: vi.fn().mockResolvedValue([running]),
    getStatus: vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(readyVersion),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r2' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));

  await act(async () => vi.advanceTimersByTimeAsync(10));
  expect(result.current.versions).toEqual([readyVersion]);
  expect(result.current.selectedVersion).toEqual(readyVersion);
  expect(result.current.manifest).toEqual({ report_id: 'r2' });
  vi.useRealTimers();
});
