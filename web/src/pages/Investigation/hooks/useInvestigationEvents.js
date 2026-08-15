import { useCallback, useEffect, useState } from 'react';
import {
  bootstrapInvestigation,
  getInvestigationEvents,
  getOverview,
} from '../../../services/investigationService';

export default function useInvestigationEvents(taskId) {
  const [overview, setOverview] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      let nextOverview = await getOverview(taskId);
      if (!nextOverview.initialized) {
        nextOverview = await bootstrapInvestigation(taskId);
      }
      const response = await getInvestigationEvents(taskId);
      setOverview(nextOverview);
      setEvents(response.events || []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { overview, events, loading, error, refresh, setEvents };
}
