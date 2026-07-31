import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportSearch } from './useReportSearch';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

test('supports next and previous hit navigation and uses the exact search limit', async () => {
  const source = {
    search: vi.fn().mockResolvedValue({
      total: 2,
      hits: [
        { record_id: 'r1', category_id: 'android.sms', page: 1 },
        { record_id: 'r2', category_id: 'linux.shell', page: 3 },
      ],
    }),
  };
  const { result } = renderHook(() => useReportSearch({ dataSource: source, reportId: 'report' }));

  await act(async () => result.current.submit('root'));
  await waitFor(() => expect(result.current.currentHit?.record_id).toBe('r1'));
  expect(source.search).toHaveBeenCalledWith('report', 'root', { offset: 0, limit: 200 });

  act(() => result.current.next());
  expect(result.current.currentHit?.record_id).toBe('r2');
  act(() => result.current.previous());
  expect(result.current.currentHit?.record_id).toBe('r1');
});

test('reactivates the same single hit for repeated submit and circular navigation', async () => {
  const hit = { record_id: 'only', category_id: 'android.sms', page: 1 };
  const source = { search: vi.fn().mockResolvedValue({ total: 1, hits: [hit] }) };
  const { result } = renderHook(() => useReportSearch({ dataSource: source, reportId: 'report' }));

  await act(async () => result.current.submit('root'));
  const firstActivation = result.current.activation;
  expect(result.current.currentHit).toEqual(hit);

  await act(async () => result.current.submit('root'));
  expect(result.current.activation).toBe(firstActivation + 1);
  expect(result.current.currentHit).toEqual(hit);

  act(() => result.current.next());
  expect(result.current.activation).toBe(firstActivation + 2);
  expect(result.current.currentHit).toEqual(hit);

  act(() => result.current.previous());
  expect(result.current.activation).toBe(firstActivation + 3);
  expect(result.current.currentHit).toEqual(hit);
});

test('treats a blank query as an empty local result without requesting search', async () => {
  const source = { search: vi.fn() };
  const { result } = renderHook(() => useReportSearch({ dataSource: source, reportId: 'report' }));

  await act(async () => result.current.submit('   '));

  expect(source.search).not.toHaveBeenCalled();
  expect(result.current.query).toBe('');
  expect(result.current.result).toEqual({ total: 0, hits: [] });
  expect(result.current.currentHit).toBeNull();
  expect(result.current.error).toBeNull();
});

test('clears old hits when search fails', async () => {
  const source = {
    search: vi.fn()
      .mockResolvedValueOnce({
        total: 1,
        hits: [{ record_id: 'old', category_id: 'android.sms', page: 1 }],
      })
      .mockRejectedValueOnce(new Error('index unavailable')),
  };
  const { result } = renderHook(() => useReportSearch({ dataSource: source, reportId: 'report' }));

  await act(async () => result.current.submit('first'));
  expect(result.current.currentHit?.record_id).toBe('old');
  await act(async () => result.current.submit('second'));

  expect(result.current.result).toEqual({ total: 0, hits: [] });
  expect(result.current.currentHit).toBeNull();
  expect(result.current.error).toMatchObject({ message: 'index unavailable' });
  expect(result.current.loading).toBe(false);
});

test('resets search activation when the report changes', async () => {
  const hit = { record_id: 'old', category_id: 'android.sms', page: 1 };
  const source = { search: vi.fn().mockResolvedValue({ total: 1, hits: [hit] }) };
  const { result, rerender } = renderHook(
    ({ reportId }) => useReportSearch({ dataSource: source, reportId }),
    { initialProps: { reportId: 'old-report' } },
  );

  await act(async () => result.current.submit('root'));
  expect(result.current.activation).toBe(1);

  rerender({ reportId: 'new-report' });
  expect(result.current.activation).toBe(0);
  expect(result.current.currentHit).toBeNull();
});

test('clears results when report changes and ignores the old report response', async () => {
  const oldSearch = deferred();
  const source = {
    search: vi.fn()
      .mockReturnValueOnce(oldSearch.promise)
      .mockResolvedValueOnce({
        total: 1,
        hits: [{ record_id: 'new', category_id: 'linux.shell', page: 2 }],
      }),
  };
  const { result, rerender } = renderHook(
    ({ reportId }) => useReportSearch({ dataSource: source, reportId }),
    { initialProps: { reportId: 'old-report' } },
  );

  let oldSubmission;
  act(() => { oldSubmission = result.current.submit('root'); });
  rerender({ reportId: 'new-report' });

  expect(result.current.result).toEqual({ total: 0, hits: [] });
  expect(result.current.currentHit).toBeNull();

  await act(async () => result.current.submit('bash'));
  expect(result.current.currentHit?.record_id).toBe('new');

  oldSearch.resolve({
    total: 1,
    hits: [{ record_id: 'stale', category_id: 'android.sms', page: 1 }],
  });
  await act(async () => { await oldSubmission; });

  expect(result.current.currentHit?.record_id).toBe('new');
  expect(result.current.query).toBe('bash');
});
