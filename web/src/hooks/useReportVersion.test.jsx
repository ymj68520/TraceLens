import { useLayoutEffect } from 'react';
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

test('merges a completed create after a newer selection without replacing that selection', async () => {
  vi.useFakeTimers();
  const create = deferred();
  const created = { report_id: 'r3', version: 3, status: 'generating', stage: 'snapshot', progress: 0 };
  const source = {
    listVersions: vi.fn().mockResolvedValue([ready]),
    createVersion: vi.fn().mockReturnValue(create.promise),
    getStatus: vi.fn().mockResolvedValue(created),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r1' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));
  await flush();
  expect(result.current.selectedVersion).toEqual(ready);

  let creating;
  await act(async () => { creating = result.current.createVersion(); });
  await act(async () => { await result.current.selectVersion(ready); });
  create.resolve(created);
  await act(async () => { await creating; });

  expect(result.current.selectedVersion).toEqual(ready);
  expect(result.current.versions).toEqual([created, ready]);
  expect(result.current.loading).toBe(false);
  await act(async () => vi.advanceTimersByTimeAsync(5));
  expect(source.getStatus).toHaveBeenCalledWith('r3');
});

test('does not create a second version while the first version is generating', async () => {
  const created = { report_id: 'r3', version: 3, status: 'queued', stage: 'queued', progress: 0 };
  const source = {
    listVersions: vi.fn().mockResolvedValue([]),
    createVersion: vi.fn().mockResolvedValue(created),
    getStatus: vi.fn().mockResolvedValue(created),
    getManifest: vi.fn(),
  };
  const { result } = renderHook(() => useReportVersion({ scopeType: 'task', scopeId: 't1', dataSource: source }));
  await flush();

  await act(async () => { await result.current.createVersion(); });
  await act(async () => { await result.current.createVersion(); });

  expect(source.createVersion).toHaveBeenCalledTimes(1);
  expect(result.current.selectedVersion).toEqual(created);
});

test('shares concurrent create calls to avoid duplicate report mutations', async () => {
  const create = deferred();
  const created = { report_id: 'r3', version: 3, status: 'queued', stage: 'queued', progress: 0 };
  const source = {
    listVersions: vi.fn().mockResolvedValue([]),
    createVersion: vi.fn().mockReturnValue(create.promise),
    getStatus: vi.fn().mockResolvedValue(created),
    getManifest: vi.fn(),
  };
  const { result } = renderHook(() => useReportVersion({ scopeType: 'task', scopeId: 't1', dataSource: source }));
  await flush();

  let first;
  let second;
  await act(async () => {
    first = result.current.createVersion();
    second = result.current.createVersion();
  });
  expect(source.createVersion).toHaveBeenCalledTimes(1);
  create.resolve(created);
  await act(async () => { await first; });

  expect(result.current.versions).toEqual([created]);
  expect(result.current.loading).toBe(false);
});


test('preserves a manifest-load error after polling reaches ready until refresh succeeds', async () => {
  vi.useFakeTimers();
  const readyVersion = { ...running, status: 'ready', progress: 100 };
  const source = {
    listVersions: vi.fn()
      .mockResolvedValueOnce([running])
      .mockResolvedValueOnce([readyVersion]),
    getStatus: vi.fn().mockResolvedValue(readyVersion),
    getManifest: vi.fn()
      .mockRejectedValueOnce(new Error('manifest unavailable'))
      .mockResolvedValueOnce({ report_id: 'r2' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));

  await act(async () => vi.advanceTimersByTimeAsync(10));
  expect(result.current.selectedVersion).toEqual(readyVersion);
  expect(result.current.manifest).toBeNull();
  expect(result.current.error).toMatchObject({ message: 'manifest unavailable' });

  await act(async () => { await result.current.refresh(); });
  expect(result.current.manifest).toEqual({ report_id: 'r2' });
  expect(result.current.error).toBeNull();
  vi.useRealTimers();
});

test('reconciles a created report into a late refresh list and keeps polling it', async () => {
  vi.useFakeTimers();
  const initialList = deferred();
  const refreshList = deferred();
  const create = deferred();
  const created = { report_id: 'r3', version: 3, status: 'generating', stage: 'snapshot', progress: 0 };
  const source = {
    listVersions: vi.fn()
      .mockReturnValueOnce(initialList.promise)
      .mockReturnValueOnce(refreshList.promise),
    createVersion: vi.fn().mockReturnValue(create.promise),
    getStatus: vi.fn().mockResolvedValue(created),
    getManifest: vi.fn(),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));
  initialList.resolve([]);
  await flush();

  let creating;
  await act(async () => { creating = result.current.createVersion(); });
  let refreshing;
  await act(async () => { refreshing = result.current.refresh(); });
  create.resolve(created);
  await act(async () => { await creating; });
  refreshList.resolve([]);
  await act(async () => { await refreshing; });

  expect(result.current.versions).toEqual([created]);
  await act(async () => vi.advanceTimersByTimeAsync(5));
  expect(source.getStatus).toHaveBeenCalledWith('r3');
  vi.useRealTimers();
});

test('keeps a create that completes while refresh is waiting for stale statuses', async () => {
  vi.useFakeTimers();
  const create = deferred();
  const staleStatus = deferred();
  const created = { report_id: 'r3', version: 3, status: 'generating', stage: 'snapshot', progress: 10 };
  const source = {
    listVersions: vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([running]),
    createVersion: vi.fn().mockReturnValue(create.promise),
    getStatus: vi.fn()
      .mockReturnValueOnce(staleStatus.promise)
      .mockImplementation((reportId) => Promise.resolve(reportId === created.report_id ? created : running)),
    getManifest: vi.fn(),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));
  await flush();

  let creating;
  await act(async () => { creating = result.current.createVersion(); });
  let refreshing;
  await act(async () => { refreshing = result.current.refresh(); });
  await flush();
  expect(source.getStatus).toHaveBeenCalledWith(running.report_id);

  create.resolve(created);
  await act(async () => { await creating; });
  staleStatus.resolve(running);
  await act(async () => { await refreshing; });

  expect(result.current.versions.map((version) => version.report_id)).toEqual(['r3', 'r2']);
  await act(async () => vi.advanceTimersByTimeAsync(5));
  expect(source.getStatus).toHaveBeenCalledWith(created.report_id);
  vi.useRealTimers();
});

test('keeps same-report progress and terminal status monotonic across refresh and polling', async () => {
  vi.useFakeTimers();
  const localProgress = { report_id: 'r3', version: 3, status: 'generating', stage: 'index', progress: 70 };
  const staleList = { ...localProgress, status: 'queued', stage: 'queued', progress: 0 };
  const staleStatus = { ...localProgress, stage: 'snapshot', progress: 20 };
  const readyVersion = { ...localProgress, status: 'ready', stage: 'complete', progress: 100 };
  const conflictingTerminal = { ...localProgress, status: 'failed', stage: 'complete', error: 'late failure' };
  const source = {
    listVersions: vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([staleList])
      .mockResolvedValueOnce([conflictingTerminal]),
    createVersion: vi.fn().mockResolvedValue(localProgress),
    getStatus: vi.fn()
      .mockResolvedValueOnce(staleStatus)
      .mockResolvedValueOnce(readyVersion),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r3' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));
  await flush();

  await act(async () => { await result.current.createVersion(); });
  await act(async () => { await result.current.refresh(); });
  expect(result.current.versions).toEqual([localProgress]);

  await act(async () => vi.advanceTimersByTimeAsync(5));
  expect(result.current.versions).toEqual([readyVersion]);
  await act(async () => { await result.current.refresh(); });
  expect(result.current.versions).toEqual([readyVersion]);
  expect(result.current.selectedVersion).toEqual(readyVersion);
  vi.useRealTimers();
});

test.each(['create', 'refresh'])(
  'keeps loading true until concurrent create and refresh both finish when %s finishes first',
  async (firstCompletion) => {
    const create = deferred();
    const refreshList = deferred();
    const created = { report_id: 'r3', version: 3, status: 'queued', stage: 'queued', progress: 0 };
    const source = {
      listVersions: vi.fn()
        .mockResolvedValueOnce([])
        .mockReturnValueOnce(refreshList.promise),
      createVersion: vi.fn().mockReturnValue(create.promise),
      getStatus: vi.fn().mockResolvedValue(created),
      getManifest: vi.fn(),
    };
    const { result } = renderHook(() => useReportVersion({ scopeType: 'task', scopeId: 't1', dataSource: source }));
    await flush();

    let creating;
    let refreshing;
    await act(async () => {
      creating = result.current.createVersion();
      refreshing = result.current.refresh();
    });
    expect(result.current.loading).toBe(true);

    if (firstCompletion === 'create') {
      create.resolve(created);
      await act(async () => { await creating; });
      expect(result.current.loading).toBe(true);
      refreshList.resolve([]);
      await act(async () => { await refreshing; });
    } else {
      refreshList.resolve([]);
      await act(async () => { await refreshing; });
      expect(result.current.loading).toBe(true);
      create.resolve(created);
      await act(async () => { await creating; });
    }

    expect(result.current.loading).toBe(false);
  },
);

test.each(['task', 'case'])(
  'synchronously hides the previous %s scope state on a same-type route transition',
  async (scopeType) => {
    const source = {
      listVersions: vi.fn((_, scopeId) => (
        scopeId === 'A' ? Promise.resolve([ready]) : new Promise(() => {})
      )),
      getStatus: vi.fn(),
      getManifest: vi.fn().mockResolvedValue({ report_id: 'r1', title: 'Scope A' }),
    };
    let stateSeenBeforePassiveEffects;
    const { result, rerender } = renderHook(
      ({ scopeId }) => {
        const state = useReportVersion({ scopeType, scopeId, dataSource: source });
        useLayoutEffect(() => {
          if (scopeId === 'B' && stateSeenBeforePassiveEffects === undefined) {
            stateSeenBeforePassiveEffects = state;
          }
        }, [scopeId, state]);
        return state;
      },
      { initialProps: { scopeId: 'A' } },
    );
    await waitFor(() => expect(result.current.manifest?.report_id).toBe('r1'));

    rerender({ scopeId: 'B' });

    expect(stateSeenBeforePassiveEffects.versions).toEqual([]);
    expect(stateSeenBeforePassiveEffects.selectedVersion).toBeNull();
    expect(stateSeenBeforePassiveEffects.manifest).toBeNull();
    expect(stateSeenBeforePassiveEffects.error).toBeNull();
    expect(stateSeenBeforePassiveEffects.generating).toBeNull();
    expect(stateSeenBeforePassiveEffects.loading).toBe(true);
  },
);
test('keeps create guards and results isolated by scope', async () => {
  const createA = deferred();
  const createB = deferred();
  const createdA = { report_id: 'a-created', version: 2, status: 'queued', stage: 'queued', progress: 0 };
  const createdB = { report_id: 'b-created', version: 1, status: 'queued', stage: 'queued', progress: 0 };
  const source = {
    listVersions: vi.fn().mockResolvedValue([]),
    createVersion: vi.fn((scopeType, scopeId) => (scopeId === 'A' ? createA.promise : createB.promise)),
    getStatus: vi.fn(),
    getManifest: vi.fn(),
  };
  const { result, rerender } = renderHook(
    ({ scopeId }) => useReportVersion({ scopeType: 'task', scopeId, dataSource: source }),
    { initialProps: { scopeId: 'A' } },
  );
  await flush();

  let pendingA;
  await act(async () => { pendingA = result.current.createVersion(); });
  rerender({ scopeId: 'B' });
  await flush();
  let pendingB;
  await act(async () => { pendingB = result.current.createVersion(); });
  expect(source.createVersion).toHaveBeenNthCalledWith(1, 'task', 'A');
  expect(source.createVersion).toHaveBeenNthCalledWith(2, 'task', 'B');

  createA.resolve(createdA);
  await act(async () => { await pendingA; });
  expect(result.current.versions).toEqual([]);
  expect(result.current.loading).toBe(true);

  createB.resolve(createdB);
  await act(async () => { await pendingB; });
  expect(result.current.versions).toEqual([createdB]);
  expect(result.current.selectedVersion).toEqual(createdB);
  expect(result.current.loading).toBe(false);
});
