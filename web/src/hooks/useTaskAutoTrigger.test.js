import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { useDispatch, useSelector } from 'react-redux';
import { fetchTasksSilent } from '../store/taskSlice';
import { useTaskAutoTrigger } from './useTaskAutoTrigger';

vi.mock('react-redux', () => ({
  useDispatch: vi.fn(),
  useSelector: vi.fn(),
}));

vi.mock('../store/taskSlice', () => ({
  fetchTasksSilent: vi.fn((filters) => ({ type: 'tasks/fetchTasksSilent', payload: filters })),
}));

describe('useTaskAutoTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('refreshes tasks without creating a legacy report when a task is completed', async () => {
    const dispatch = vi.fn(() => ({
      unwrap: vi.fn().mockResolvedValue({
        tasks: [{ id: 'task-1', status: 'completed', output_files_db: '/tmp/files.db' }],
      }),
    }));
    useDispatch.mockReturnValue(dispatch);
    useSelector.mockImplementation((selector) => selector({
      tasks: { filters: { status: 'all' } },
      settings: { autoRefresh: true, refreshInterval: 60_000 },
    }));

    const { unmount } = renderHook(() => useTaskAutoTrigger());

    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(1));
    expect(fetchTasksSilent).toHaveBeenCalledWith({ status: 'all' });
    unmount();
  });
});
