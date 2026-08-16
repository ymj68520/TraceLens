import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { useSecondaryAnalysisPolling } from './useSecondaryAnalysisPolling';

const SUBMISSION_A = { taskId: 't1', evidenceKey: 'file:/case/a.txt', analysisId: 'sa_1' };
const SUBMISSION_B = { taskId: 't2', evidenceKey: 'file:/case/b.txt', analysisId: 'sa_2' };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

const analysis = (status, analysisId = 'sa_1') => ({ analysis_id: analysisId, status });

describe('useSecondaryAnalysisPolling', () => {
  test('polls while queued/running and stops at review_pending', async () => {
    // deferred 控序：intervalMs=0 时轮询会立刻推进，中间状态必须逐步放行。
    const steps = [deferred(), deferred(), deferred()];
    const fetchAnalysis = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(steps[1].promise)
      .mockReturnValueOnce(steps[2].promise);
    const { result } = renderHook(
      () => useSecondaryAnalysisPolling(SUBMISSION_A, { intervalMs: 0, fetchAnalysis }),
    );

    await act(async () => steps[0].resolve(analysis('queued')));
    await waitFor(() => expect(result.current.analysis?.status).toBe('queued'));
    expect(result.current.active).toBe(true);

    await act(async () => steps[1].resolve(analysis('running')));
    await waitFor(() => expect(result.current.analysis?.status).toBe('running'));
    expect(result.current.active).toBe(true);

    await act(async () => steps[2].resolve(analysis('review_pending')));
    await waitFor(() => expect(result.current.analysis?.status).toBe('review_pending'));
    expect(result.current.active).toBe(false);
    expect(result.current.error).toBeNull();

    // stopped: terminal 之后不再有新请求
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(fetchAnalysis).toHaveBeenCalledTimes(3);
  });

  test.each(['accepted', 'rejected', 'invalid', 'failed'])(
    'stops polling at terminal status %s',
    async (status) => {
      const fetchAnalysis = vi.fn()
        .mockResolvedValueOnce(analysis('queued'))
        .mockResolvedValueOnce(analysis(status));
      const { result } = renderHook(
        () => useSecondaryAnalysisPolling(SUBMISSION_A, { intervalMs: 0, fetchAnalysis }),
      );

      await waitFor(() => expect(result.current.analysis?.status).toBe(status));
      const callsAtStop = fetchAnalysis.mock.calls.length;
      await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
      expect(fetchAnalysis.mock.calls.length).toBe(callsAtStop);
      expect(result.current.active).toBe(false);
    },
  );

  test('task/evidence switch mid-poll ignores the late response of the old identity', async () => {
    const first = deferred();
    const second = deferred();
    const fetchAnalysis = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ submission }) => useSecondaryAnalysisPolling(submission, { intervalMs: 0, fetchAnalysis }),
      { initialProps: { submission: SUBMISSION_A } },
    );

    // user switches to task B (identity changes) before A's poll resolves
    await act(async () => rerender({ submission: SUBMISSION_B }));
    expect(result.current.analysis).toBeNull();

    await act(async () => {
      first.resolve(analysis('review_pending')); // late terminal for A
      second.resolve(analysis('running', 'sa_2')); // B's fresh response
    });
    await waitFor(() => expect(result.current.analysis?.analysis_id).toBe('sa_2'));
    expect(result.current.analysis?.status).toBe('running');
    expect(result.current.active).toBe(true);
  });

  test('switching to null submission drops the old state entirely', async () => {
    const first = deferred();
    const fetchAnalysis = vi.fn().mockReturnValueOnce(first.promise);
    const { result, rerender } = renderHook(
      ({ submission }) => useSecondaryAnalysisPolling(submission, { intervalMs: 0, fetchAnalysis }),
      { initialProps: { submission: SUBMISSION_A } },
    );

    await act(async () => rerender({ submission: null }));
    await act(async () => first.resolve(analysis('review_pending')));
    expect(result.current.analysis).toBeNull();
    expect(result.current.active).toBe(false);
    expect(fetchAnalysis).toHaveBeenCalledTimes(1);
  });

  test('keeps polling through a transient GET error and clears it on success', async () => {
    const steps = [deferred(), deferred(), deferred()];
    const fetchAnalysis = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(steps[1].promise)
      .mockReturnValueOnce(steps[2].promise);
    const { result } = renderHook(
      () => useSecondaryAnalysisPolling(SUBMISSION_A, { intervalMs: 0, fetchAnalysis }),
    );

    await act(async () => steps[0].resolve(analysis('queued')));
    await waitFor(() => expect(result.current.analysis?.status).toBe('queued'));

    await act(async () => steps[1].reject(Object.assign(new Error('down'), { status: 503 })));
    await waitFor(() => expect(result.current.error?.status).toBe(503));
    // 瞬时错误不清掉最后一个已知状态，也不终止轮询
    expect(result.current.analysis?.status).toBe('queued');
    expect(result.current.active).toBe(true);

    await act(async () => steps[2].resolve(analysis('review_pending')));
    await waitFor(() => expect(result.current.analysis?.status).toBe('review_pending'));
    expect(result.current.error).toBeNull();
    expect(fetchAnalysis).toHaveBeenCalledTimes(3);
  });

  test('never fetches without a submission', () => {
    const fetchAnalysis = vi.fn();
    const { result } = renderHook(
      () => useSecondaryAnalysisPolling(null, { intervalMs: 0, fetchAnalysis }),
    );
    expect(fetchAnalysis).not.toHaveBeenCalled();
    expect(result.current.analysis).toBeNull();
    expect(result.current.active).toBe(false);
  });
});
