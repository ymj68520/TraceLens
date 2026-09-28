import { useEffect, useState } from 'react';
import { listReportVersions } from '../../../services/reportService';

export function selectCitedNarrativeVersion(versions, requestedReportId = null) {
  const ready = (Array.isArray(versions) ? versions : versions?.versions || [])
    .filter((version) => version.report_kind === 'llm_generation' && version.status === 'ready');
  if (requestedReportId) return ready.find((version) => version.report_id === requestedReportId) || null;
  return ready.sort((left, right) => Number(right.version) - Number(left.version))[0] || null;
}

export default function useCitedReportVersion(taskId, requestedReportId = null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState({ reportId: null, loading: Boolean(taskId), error: null });

  useEffect(() => {
    if (!taskId) {
      setState({ reportId: null, loading: false, error: null });
      return undefined;
    }
    let active = true;
    setState({ reportId: null, loading: true, error: null });
    listReportVersions('task', taskId)
      .then((versions) => {
        if (!active) return;
        const selected = selectCitedNarrativeVersion(versions, requestedReportId);
        setState({
          reportId: selected?.report_id || null,
          loading: false,
          error: requestedReportId && !selected ? new Error('未找到该任务的指定最终报告版本') : null,
        });
      })
      .catch((error) => {
        if (active) setState({ reportId: null, loading: false, error });
      });
    return () => { active = false; };
  }, [taskId, requestedReportId, revision]);

  return { ...state, refresh: () => setRevision((value) => value + 1) };
}
