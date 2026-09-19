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

  // 任务切换的渲染期同步清空（React derive-state-from-props 模式）：旧任务的
  // events 若残留到下一个 commit，自动选中效果会把上一任务的事件选回，
  // 其 eventId 随新 taskId 发出的 evidence/versions 请求必然 404。
  const [prevTaskId, setPrevTaskId] = useState(taskId);
  if (prevTaskId !== taskId) {
    setPrevTaskId(taskId);
    setEvents([]);
    setOverview(null);
  }

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
