import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { useEventRefreshPolling } from './useEventRefreshPolling';

const SUBMISSION_A = { taskId: 't1', eventId: 'ie_1', refreshId: 'er_1' };
const SUBMISSION_B = { taskId: 't2', eventId: 'ie_2', refreshId: 'er_2' };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

const history = (rows) => rows;
const refresh = (status, refreshId = 'er_1', extra = {}) => ({
  refresh_id: refreshId,
  task_id: 't1',
  event_id: 'ie_1',
  status,
  ...extra,
});

describe('useEventRefreshPolling', () => {
  test('polls the exact refresh_id while queued/running and stops at completed', async () => {
    // deferred 控序：intervalMs=0 时轮询会立刻推进，中间状态必须逐步放行。
    const steps = [deferred(), deferred(), deferred()];
    const fetchRefreshes = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(steps[1].promise)
      .mockReturnValueOnce(steps[2].promise);
    const { result } = renderHook(
      () => useEventRefreshPolling(SUBMISSION_A, { intervalMs: 0, fetchRefreshes }),
    );

    await act(async () => steps[0].resolve(history([refresh('queued')])));
    await waitFor(() => expect(result.current.refresh?.status).toBe('queued'));
    expect(result.current.active).toBe(true);

    await act(async () => steps[1].resolve(history([refresh('running')])));
    await waitFor(() => expect(result.current.refresh?.status).toBe('running'));
    expect(result.current.active).toBe(true);

    await act(async () => steps[2].resolve(history([
      refresh('completed', 'er_1', { produced_version: 4 }),
    ])));
    await waitFor(() => expect(result.current.refresh?.status).toBe('completed'));
    expect(result.current.refresh?.produced_version).toBe(4);
    expect(result.current.active).toBe(false);
    expect(result.current.error).toBeNull();

    // stopped: terminal 之后不再有新请求
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(fetchRefreshes).toHaveBeenCalledTimes(3);
    expect(fetchRefreshes).toHaveBeenNthCalledWith(1, 't1', 'ie_1');
  });

  test('stops polling at failed and keeps the error row', async () => {
    const fetchRefreshes = vi.fn()
      .mockResolvedValueOnce(history([refresh('queued')]))
      .mockResolvedValueOnce(history([
        refresh('failed', 'er_1', { error_code: 'llm_timeout', error_message: 'sanitized' }),
      ]));
    const { result } = renderHook(
      () => useEventRefreshPolling(SUBMISSION_A, { intervalMs: 0, fetchRefreshes }),
    );

    await waitFor(() => expect(result.current.refresh?.status).toBe('failed'));
    expect(result.current.refresh?.error_code).toBe('llm_timeout');
    const callsAtStop = fetchRefreshes.mock.calls.length;
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(fetchRefreshes.mock.calls.length).toBe(callsAtStop);
    expect(result.current.active).toBe(false);
  });

  test('filters the exact refresh_id out of history — a decoy row never wins', async () => {
    const decoy = refresh('completed', 'er_9', { produced_version: 99 });
    const fetchRefreshes = vi.fn()
      .mockResolvedValueOnce(history([decoy, refresh('running')]))
      .mockResolvedValueOnce(history([refresh('completed'), decoy]));
    const { result } = renderHook(
      () => useEventRefreshPolling(SUBMISSION_A, { intervalMs: 0, fetchRefreshes }),
    );

    await waitFor(() => expect(result.current.refresh?.status).toBe('completed'));
    expect(result.current.refresh?.refresh_id).toBe('er_1');
    expect(result.current.refresh?.produced_version).toBeUndefined();
  });

  test('a history without the exact refresh_id stops scheduling (fail-closed)', async () => {
    const fetchRefreshes = vi.fn()
      .mockResolvedValueOnce(history([refresh('running', 'er_other')]));
    const { result } = renderHook(
      () => useEventRefreshPolling(SUBMISSION_A, { intervalMs: 0, fetchRefreshes }),
    );

    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(result.current.refresh).toBeNull();
    expect(fetchRefreshes).toHaveBeenCalledTimes(1);
  });

  test('task/event switch mid-poll ignores the late response of the old identity', async () => {
    const first = deferred();
    const second = deferred();
    const fetchRefreshes = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ submission }) => useEventRefreshPolling(submission, { intervalMs: 0, fetchRefreshes }),
      { initialProps: { submission: SUBMISSION_A } },
    );

    // user switches to task B (identity changes) before A's poll resolves
    await act(async () => rerender({ submission: SUBMISSION_B }));
    expect(result.current.refresh).toBeNull();

    await act(async () => {
      first.resolve(history([refresh('completed')])); // late terminal for A
      second.resolve(history([refresh('running', 'er_2', { task_id: 't2', event_id: 'ie_2' })]));
    });
    await waitFor(() => expect(result.current.refresh?.refresh_id).toBe('er_2'));
    expect(result.current.refresh?.status).toBe('running');
    expect(result.current.active).toBe(true);
  });

  test('switching to null submission drops the old state entirely', async () => {
    const first = deferred();
    const fetchRefreshes = vi.fn().mockReturnValueOnce(first.promise);
    const { result, rerender } = renderHook(
      ({ submission }) => useEventRefreshPolling(submission, { intervalMs: 0, fetchRefreshes }),
      { initialProps: { submission: SUBMISSION_A } },
    );

    await act(async () => rerender({ submission: null }));
    await act(async () => first.resolve(history([refresh('completed')])));
    expect(result.current.refresh).toBeNull();
    expect(result.current.active).toBe(false);
    expect(fetchRefreshes).toHaveBeenCalledTimes(1);
  });

  test('keeps polling through a transient GET error and clears it on success', async () => {
    const steps = [deferred(), deferred(), deferred()];
    const fetchRefreshes = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(steps[1].promise)
      .mockReturnValueOnce(steps[2].promise);
    const { result } = renderHook(
      () => useEventRefreshPolling(SUBMISSION_A, { intervalMs: 0, fetchRefreshes }),
    );

    await act(async () => steps[0].resolve(history([refresh('queued')])));
    await waitFor(() => expect(result.current.refresh?.status).toBe('queued'));

    await act(async () => steps[1].reject(Object.assign(new Error('down'), { status: 503 })));
    await waitFor(() => expect(result.current.error?.status).toBe(503));
    // 瞬时错误不清掉最后一个已知状态，也不终止轮询
    expect(result.current.refresh?.status).toBe('queued');
    expect(result.current.active).toBe(true);

    await act(async () => steps[2].resolve(history([refresh('completed')])));
    await waitFor(() => expect(result.current.refresh?.status).toBe('completed'));
    expect(result.current.error).toBeNull();
    expect(fetchRefreshes).toHaveBeenCalledTimes(3);
  });

  test('never fetches without a submission', () => {
    const fetchRefreshes = vi.fn();
    const { result } = renderHook(
      () => useEventRefreshPolling(null, { intervalMs: 0, fetchRefreshes }),
    );
    expect(fetchRefreshes).not.toHaveBeenCalled();
    expect(result.current.refresh).toBeNull();
    expect(result.current.active).toBe(false);
  });
});
