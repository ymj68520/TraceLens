import { useEffect, useRef } from 'react';
import { useAppDispatch } from '../store';
import { fetchTaskProgress } from '../store/taskSlice';
import type { ForensicTask } from '../types/api';

interface TaskPollingOptions {
  interval?: number;
  enabled?: boolean;
  onComplete?: (result: Partial<ForensicTask>) => void;
  onError?: (error: unknown) => void;
}

/** Poll a task's progress until it reaches a terminal status. */
export const useTaskPolling = (taskId: string | null, options: TaskPollingOptions = {}) => {
  const { interval = 2000, enabled = true, onComplete, onError } = options;

  const dispatch = useAppDispatch();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled || !taskId) return;

    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    const poll = async () => {
      try {
        const result = (await dispatch(fetchTaskProgress(taskId)).unwrap()) as Partial<ForensicTask>;
        if (result.status === 'completed' || result.status === 'failed') {
          stopPolling();
          onComplete?.(result);
        }
      } catch (error) {
        console.error('Polling error:', error);
        onError?.(error);
      }
    };

    void poll();
    intervalRef.current = setInterval(poll, interval);

    return stopPolling;
  }, [taskId, enabled, interval, dispatch, onComplete, onError]);
};

export default useTaskPolling;
