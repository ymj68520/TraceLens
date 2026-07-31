import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportCategory } from './useReportCategory';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

test('loads only the selected category page', async () => {
  const source = {
    getCategoryPage: vi.fn().mockResolvedValue({
      category_id: 'windows.event_logs', page: 2, page_size: 100, total: 250, records: ['row'],
    }),
  };
  const { result } = renderHook(() => useReportCategory({
    dataSource: source, reportId: 'r1', categoryId: 'windows.event_logs', page: 2,
  }));

  await waitFor(() => expect(result.current.data?.records).toEqual(['row']));
  expect(source.getCategoryPage).toHaveBeenCalledTimes(1);
  expect(source.getCategoryPage).toHaveBeenCalledWith('r1', 'windows.event_logs', 2);
});

test('ignores a stale category response after the selection changes', async () => {
  const oldPage = deferred();
  const source = {
    getCategoryPage: vi.fn()
      .mockReturnValueOnce(oldPage.promise)
      .mockResolvedValueOnce({
        category_id: 'linux.shell', page: 1, page_size: 100, total: 1, records: ['new'],
      }),
  };
  const { result, rerender } = renderHook(
    ({ categoryId }) => useReportCategory({
      dataSource: source, reportId: 'report', categoryId, page: 1,
    }),
    { initialProps: { categoryId: 'android.sms' } },
  );

  rerender({ categoryId: 'linux.shell' });
  await waitFor(() => expect(result.current.data?.records).toEqual(['new']));

  oldPage.resolve({
    category_id: 'android.sms', page: 1, page_size: 100, total: 1, records: ['old'],
  });
  await act(async () => { await Promise.resolve(); });

  expect(result.current.data?.records).toEqual(['new']);
});

test('clears page data and exposes an error when loading fails', async () => {
  const source = { getCategoryPage: vi.fn().mockRejectedValue(new Error('page unavailable')) };
  const { result } = renderHook(() => useReportCategory({
    dataSource: source, reportId: 'r1', categoryId: 'android.sms', page: 1,
  }));

  await waitFor(() => expect(result.current.error).toMatchObject({ message: 'page unavailable' }));
  expect(result.current.data).toBeNull();
  expect(result.current.loading).toBe(false);
});
