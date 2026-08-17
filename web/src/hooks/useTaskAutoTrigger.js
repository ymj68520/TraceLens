/**
 * useTaskAutoTrigger
 *
 * Handles two concerns previously mixed into Tasks.jsx's autoRefresh effect:
 *   1. Background silent polling of the task list (no loading spinner)
 *   2. No automatic report generation. Final reports are explicitly created
 *      from the R2 forensic report workflow.
 *
 * Why separate?  The old approach caused the whole Tasks page to re-render on
 * every poll cycle because fetchTasks set status='loading'. This hook uses
 * fetchTasksSilent instead.
 */
import { useEffect, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchTasksSilent } from '../store/taskSlice';

const POLL_INTERVAL_MS = 5000;

export function useTaskAutoTrigger({ enabled = true } = {}) {
  const dispatch = useDispatch();
  const { filters } = useSelector((state) => state.tasks);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);

  const interval = refreshInterval || POLL_INTERVAL_MS;

  const poll = useCallback(async () => {
    try {
      await dispatch(fetchTasksSilent(filters)).unwrap();
    } catch (err) {
      // Network errors during background poll are non-fatal
      console.warn('[useTaskAutoTrigger] Poll error:', err);
    }
  }, [dispatch, filters]);

  useEffect(() => {
    if (!enabled || !autoRefresh) return;

    // Run once immediately, then on interval
    poll();
    const id = setInterval(poll, interval);
    return () => clearInterval(id);
  }, [enabled, autoRefresh, interval, poll]);
}
