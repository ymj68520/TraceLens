import { useCallback, useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasksSilent } from '../store/taskSlice';

const POLL_INTERVAL_MS = 5000;

/**
 * Background silent polling of the task list — no loading spinner, no full
 * page re-render. Reports are created explicitly from the R2 workflow; this
 * hook intentionally does NOT auto-generate anything.
 */
export function useTaskAutoTrigger({ enabled = true } = {}) {
  const dispatch = useAppDispatch();
  const filters = useAppSelector((state) => state.tasks.filters);
  const autoRefresh = useAppSelector((state) => state.settings.autoRefresh);
  const refreshInterval = useAppSelector((state) => state.settings.refreshInterval);

  const interval = refreshInterval || POLL_INTERVAL_MS;

  const poll = useCallback(async () => {
    try {
      await dispatch(fetchTasksSilent(filters)).unwrap();
    } catch (err) {
      // Background poll failures are non-fatal.
      console.warn('[useTaskAutoTrigger] poll error:', err);
    }
  }, [dispatch, filters]);

  useEffect(() => {
    if (!enabled || !autoRefresh) return;
    void poll();
    const id = setInterval(poll, interval);
    return () => clearInterval(id);
  }, [enabled, autoRefresh, interval, poll]);
}

export default useTaskAutoTrigger;
