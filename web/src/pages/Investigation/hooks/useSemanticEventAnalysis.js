import { useCallback, useEffect, useRef, useState } from 'react';
import { acceptEventSemanticVersion, getEventSemanticVersions, rejectEventSemanticVersion, refreshInvestigationEvent, pollAnalysisJob } from '../../../services/investigationService';

export default function useSemanticEventAnalysis(taskId, event, onRefresh) {
  const [versions, setVersions] = useState([]);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const requestIdRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!taskId || !event?.id) return;
    const requestId = ++requestIdRef.current;
    try {
      const response = await getEventSemanticVersions(taskId, event.id);
      if (requestId === requestIdRef.current) setVersions(response.versions || []);
    } catch (err) {
      if (requestId === requestIdRef.current) { setVersions([]); setError(err); }
      throw err;
    }
  }, [taskId, event?.id]);

  useEffect(() => {
    setVersions([]); setJob(null); setError(null);
    refresh().catch(() => {});
  }, [refresh]);

  const start = async (options = {}) => {
    setLoading(true); setError(null);
    try {
      const result = await refreshInvestigationEvent(taskId, event.id, options);
      const completed = await pollAnalysisJob(taskId, result.job_id, setJob);
      await refresh();
      onRefresh?.();
      return completed;
    } catch (err) { setError(err); throw err; } finally { setLoading(false); }
  };

  const accept = async (versionId) => { setError(null); try { await acceptEventSemanticVersion(taskId, event.id, versionId); await refresh(); onRefresh?.(); } catch (err) { setError(err); throw err; } };
  const reject = async (versionId) => { setError(null); try { await rejectEventSemanticVersion(taskId, event.id, versionId); await refresh(); onRefresh?.(); } catch (err) { setError(err); throw err; } };
  return { versions, job, loading, error, refresh, start, accept, reject };
}
