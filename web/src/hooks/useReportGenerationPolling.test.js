import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { useReportGenerationPolling } from './useReportGenerationPolling';

const SUBMISSION_A = { taskId: 't1', generationId: 'rg_1' };
const SUBMISSION_B = { taskId: 't2', generationId: 'rg_2' };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

const generation = (status, generationId = 'rg_1', extra = {}) => ({
  generation_id: generationId,
  task_id: 't1',
  status,
  ...extra,
});

describe('useReportGenerationPolling', () => {
  test('polls the exact generation_id while admitted/running and stops at completed', async () => {
    const steps = [deferred(), deferred(), deferred()];
    const fetchGeneration = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(steps[1].promise)
      .mockReturnValueOnce(steps[2].promise);
    const { result } = renderHook(
      () => useReportGenerationPolling(SUBMISSION_A, { intervalMs: 0, fetchGeneration }),
    );

    await act(async () => steps[0].resolve(generation('admitted')));
    await waitFor(() => expect(result.current.generation?.status).toBe('admitted'));
    expect(result.current.active).toBe(true);

    await act(async () => steps[1].resolve(generation('running')));
    await waitFor(() => expect(result.current.generation?.status).toBe('running'));
    expect(result.current.active).toBe(true);

    await act(async () => steps[2].resolve(generation('completed', 'rg_1', {
      report_id: 'rep-9', produced_version: 4,
    })));
    await waitFor(() => expect(result.current.generation?.status).toBe('completed'));
    expect(result.current.generation.report_id).toBe('rep-9');
    expect(result.current.generation.produced_version).toBe(4);
    expect(result.current.active).toBe(false);
    expect(result.current.error).toBeNull();

    // terminal 之后不再发起新请求
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(fetchGeneration).toHaveBeenCalledTimes(3);
    expect(fetchGeneration).toHaveBeenNthCalledWith(1, 't1', 'rg_1');
  });

  test('failed is terminal: stops polling and exposes the durable failure', async () => {
    const steps = [deferred(), deferred()];
    const fetchGeneration = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(steps[1].promise);
    const { result } = renderHook(
      () => useReportGenerationPolling(SUBMISSION_A, { intervalMs: 0, fetchGeneration }),
    );

    await act(async () => steps[0].resolve(generation('running')));
    await waitFor(() => expect(result.current.active).toBe(true));

    await act(async () => steps[1].resolve(generation('failed', 'rg_1', {
      error_code: 'llm_timeout', error_message: 'LLM request timed out',
    })));
    await waitFor(() => expect(result.current.generation?.status).toBe('failed'));
    expect(result.current.active).toBe(false);
    expect(result.current.generation.error_code).toBe('llm_timeout');

    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(fetchGeneration).toHaveBeenCalledTimes(2);
  });

  test('task switch drops the late response of the old generation (§23)', async () => {
    const late = deferred();
    const next = deferred();
    const fetchGeneration = vi.fn()
      .mockReturnValueOnce(late.promise)
      .mockReturnValueOnce(next.promise);
    const { result, rerender } = renderHook(
      ({ submission }) => useReportGenerationPolling(submission, { intervalMs: 0, fetchGeneration }),
      { initialProps: { submission: SUBMISSION_A } },
    );

    await act(async () => rerender({ submission: SUBMISSION_B }));
    await act(async () => late.resolve(generation('completed', 'rg_1')));
    await act(async () => next.resolve(generation('admitted', 'rg_2', { task_id: 't2' })));

    await waitFor(() => expect(result.current.generation?.generation_id).toBe('rg_2'));
    // Task A 的晚返回 completed 绝不写入 B 的状态，也绝不携带 A 的 report。
    expect(result.current.generation.status).toBe('admitted');
    expect(result.current.generation.report_id).toBeUndefined();
  });

  test('transient poll error keeps polling and is cleared by the next success', async () => {
    const steps = [deferred(), deferred(), deferred()];
    // reject 会先于下一次 poll 挂载 handler —— 先挂一个 suppressor，
    // 避免 Node 在窗口期把它记成 unhandled rejection（hook 端仍会 catch）。
    const rejected = Promise.reject({ status: 503, message: 'unavailable' });
    rejected.catch(() => {});
    const fetchGeneration = vi.fn()
      .mockReturnValueOnce(steps[0].promise)
      .mockReturnValueOnce(rejected)
      .mockReturnValueOnce(steps[1].promise)
      .mockReturnValueOnce(steps[2].promise);
    const { result } = renderHook(
      () => useReportGenerationPolling(SUBMISSION_A, { intervalMs: 0, fetchGeneration }),
    );

    await act(async () => steps[0].resolve(generation('admitted')));
    await waitFor(() => expect(result.current.error?.status).toBe(503));
    expect(result.current.active).toBe(true);

    await act(async () => steps[1].resolve(generation('running')));
    await act(async () => steps[2].resolve(generation('failed', 'rg_1', {
      error_code: 'service_restart',
    })));
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.generation.error_code).toBe('service_restart');
  });

  test('null submission never polls', async () => {
    const fetchGeneration = vi.fn();
    const { result } = renderHook(
      () => useReportGenerationPolling(null, { intervalMs: 0, fetchGeneration }),
    );
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(fetchGeneration).not.toHaveBeenCalled();
    expect(result.current.active).toBe(false);
  });
});
