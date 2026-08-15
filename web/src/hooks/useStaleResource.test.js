import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { useStaleResource } from './useStaleResource';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe('useStaleResource', () => {
  test('loads data for the current key and resets on key change', async () => {
    const first = deferred();
    const second = deferred();
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ key }) => useStaleResource(fetcher, key),
      { initialProps: { key: 'task-a' } },
    );

    await act(async () => first.resolve({ value: 'a' }));
    await waitFor(() => expect(result.current.data).toEqual({ value: 'a' }));
    expect(result.current.error).toBeNull();

    await act(async () => rerender({ key: 'task-b' }));
    // old key's data cleared immediately, new load in flight
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);

    await act(async () => second.resolve({ value: 'b' }));
    await waitFor(() => expect(result.current.data).toEqual({ value: 'b' }));
  });

  test('ignores a stale success that resolves after the key changed', async () => {
    const first = deferred();
    const second = deferred();
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ key }) => useStaleResource(fetcher, key),
      { initialProps: { key: 'task-a' } },
    );

    await act(async () => {
      rerender({ key: 'task-b' });
      second.resolve({ value: 'b' });
    });
    await waitFor(() => expect(result.current.data).toEqual({ value: 'b' }));

    await act(async () => first.resolve({ value: 'stale-a' }));
    expect(result.current.data).toEqual({ value: 'b' });
    expect(result.current.loading).toBe(false);
  });

  test('ignores a stale rejection that happens after the key changed', async () => {
    const first = deferred();
    const second = deferred();
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ key }) => useStaleResource(fetcher, key),
      { initialProps: { key: 'task-a' } },
    );

    await act(async () => {
      rerender({ key: 'task-b' });
      second.resolve({ value: 'b' });
    });
    await waitFor(() => expect(result.current.data).toEqual({ value: 'b' }));

    await act(async () => first.reject(new Error('late failure')));
    expect(result.current.data).toEqual({ value: 'b' });
    expect(result.current.error).toBeNull();
  });

  test('records errors and supports retry through refresh', async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error('store unavailable'), { status: 503 }))
      .mockResolvedValueOnce({ value: 'ok' });
    const { result } = renderHook(() => useStaleResource(fetcher, 'task-a'));

    await waitFor(() => expect(result.current.error?.status).toBe(503));
    expect(result.current.data).toBeNull();

    await act(async () => result.current.refresh());
    await waitFor(() => expect(result.current.data).toEqual({ value: 'ok' }));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  test('never fetches while the key is falsy', async () => {
    const fetcher = vi.fn();
    const { result } = renderHook(() => useStaleResource(fetcher, null));

    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
  });
});
