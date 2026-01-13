import { useEffect, useRef } from 'react';
import { useDispatch } from 'react-redux';
import { fetchTaskProgress } from '../store/taskSlice';

/**
 * Custom hook for polling task progress
 * @param {string} taskId - Task ID to poll
 * @param {Object} options - Polling options
 * @param {number} options.interval - Polling interval in ms (default: 2000)
 * @param {boolean} options.enabled - Enable/disable polling
 * @param {Function} options.onComplete - Callback when task completes
 * @param {Function} options.onError - Callback when error occurs
 */
export const useTaskPolling = (taskId, options = {}) => {
  const {
    interval = 2000,
    enabled = true,
    onComplete = null,
    onError = null,
  } = options;

  const dispatch = useDispatch();
  const intervalRef = useRef(null);

  useEffect(() => {
    if (!enabled || !taskId) return;

    const poll = async () => {
      try {
        const result = await dispatch(fetchTaskProgress(taskId)).unwrap();

        // Stop polling if task is complete or failed
        if (result.status === 'completed' || result.status === 'failed') {
          stopPolling();
          if (onComplete) onComplete(result);
        }
      } catch (error) {
        console.error('Polling error:', error);
        if (onError) onError(error);
      }
    };

    // Initial poll
    poll();

    // Set up interval
    intervalRef.current = setInterval(poll, interval);

    // Cleanup
    return () => {
      stopPolling();
    };
  }, [taskId, enabled, interval, dispatch, onComplete, onError]);

  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  return { stopPolling };
};
