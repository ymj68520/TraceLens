import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getAnalysisVersions,
  getEvidenceDetail,
  getLocalGraph,
} from '../../../services/investigationService';

export default function useEvidenceAnalysis(taskId, evidenceKey) {
  const [detail, setDetail] = useState(null);
  const [versions, setVersions] = useState([]);
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const requestIdRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!taskId || !evidenceKey) {
      requestIdRef.current += 1;
      setDetail(null);
      setVersions([]);
      setGraph(null);
      setLoading(false);
      setError(null);
      return;
    }
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const [detailResult, versionsResult, graphResult] = await Promise.all([
        getEvidenceDetail(taskId, evidenceKey),
        getAnalysisVersions(taskId, evidenceKey),
        getLocalGraph(taskId, { evidence_key: evidenceKey, max_nodes: 50 }),
      ]);
      if (requestId !== requestIdRef.current) return;
      setDetail(detailResult.evidence);
      setVersions(versionsResult.versions || []);
      setGraph(graphResult);
    } catch (err) {
      if (requestId === requestIdRef.current) setError(err);
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [taskId, evidenceKey]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { detail, versions, graph, loading, error, refresh };
}
