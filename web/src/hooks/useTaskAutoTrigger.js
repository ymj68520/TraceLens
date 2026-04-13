/**
 * useTaskAutoTrigger
 *
 * Handles two concerns previously mixed into Tasks.jsx's autoRefresh effect:
 *   1. Background silent polling of the task list (no loading spinner)
 *   2. Auto-triggering AI case analysis when a task transitions to COMPLETED
 *
 * Why separate?  The old approach caused the whole Tasks page to re-render on
 * every poll cycle because fetchTasks set status='loading'.  This hook uses
 * fetchTasksSilent instead, and encapsulates the "already triggered" state so
 * it doesn't leak into the page component.
 */
import { useEffect, useRef, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchTasksSilent } from '../store/taskSlice';
import { startCaseAnalysis, getCaseReport } from '../services/caseAnalysisService';

const POLL_INTERVAL_MS = 5000;

export function useTaskAutoTrigger({ enabled = true, onAiStarted } = {}) {
  const dispatch = useDispatch();
  const { filters } = useSelector((state) => state.tasks);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);

  /** Set of task IDs whose AI analysis has already been triggered this session. */
  const triggeredRef = useRef(new Set());
  /** On first poll, we catalogue existing completed tasks so we don't re-trigger them. */
  const initializedRef = useRef(false);

  const interval = refreshInterval || POLL_INTERVAL_MS;

  const poll = useCallback(async () => {
    try {
      const result = await dispatch(fetchTasksSilent(filters)).unwrap();
      const tasks = result.tasks || [];

      // — First run: mark all currently completed tasks as "seen" —
      if (!initializedRef.current) {
        tasks.forEach((t) => {
          if (t.status?.toLowerCase() === 'completed') {
            triggeredRef.current.add(t.id);
          }
        });
        initializedRef.current = true;
        return;
      }

      // — Subsequent runs: trigger AI only for newly completed tasks —
      for (const task of tasks) {
        const isCompleted = task.status?.toLowerCase() === 'completed';
        const alreadyTriggered = triggeredRef.current.has(task.id);

        if (!isCompleted || alreadyTriggered) continue;

        // Mark immediately to prevent duplicate triggers across polls
        triggeredRef.current.add(task.id);

        // Check whether a report already exists (task may have been resumed)
        try {
          const report = await getCaseReport(task.id);
          if (report?.report) continue; // Report already exists, skip
        } catch (_) {
          // 404 means no report yet — proceed to trigger analysis
        }

        try {
          await startCaseAnalysis({
            taskId: task.id,
            filesDbPath: task.output_files_db,
            caseDescription: task.case_description || '自动分析',
            maxFilterFiles: 200,
          });
          if (onAiStarted) onAiStarted(task);
        } catch (err) {
          console.error('[useTaskAutoTrigger] Failed to auto-trigger AI:', err);
        }
      }
    } catch (err) {
      // Network errors during background poll are non-fatal
      console.warn('[useTaskAutoTrigger] Poll error:', err);
    }
  }, [dispatch, filters, onAiStarted]);

  useEffect(() => {
    if (!enabled || !autoRefresh) return;

    // Run once immediately, then on interval
    poll();
    const id = setInterval(poll, interval);
    return () => clearInterval(id);
  }, [enabled, autoRefresh, interval, poll]);
}
