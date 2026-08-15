import { useCallback, useEffect, useRef, useState } from 'react';
import { getEventEvidence } from '../../../services/investigationService';

export default function useEventEvidence(taskId, eventId) {
  const [evidence, setEvidence] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const requestIdRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!taskId || !eventId) {
      requestIdRef.current += 1;
      setEvidence([]);
      setLoading(false);
      setError(null);
      return;
    }
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const response = await getEventEvidence(taskId, eventId);
      if (requestId === requestIdRef.current) setEvidence(response.evidence || []);
    } catch (err) {
      if (requestId === requestIdRef.current) setError(err);
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [taskId, eventId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { evidence, loading, error, refresh };
}
