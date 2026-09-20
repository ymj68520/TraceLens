import { useCallback, useEffect, useState } from 'react';
import { getInvestigationFileTimeline } from '../../../services/investigationService';

/**
 * 文件中心时间线数据：/file-timeline 返回已分析文件（MACB 最新时间排序）
 * 与每个文件关联的事件 id 列表。事件对象本身仍来自 /events。
 */
export default function useInvestigationFileTimeline(taskId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getInvestigationFileTimeline(taskId));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { fileTimeline: data, loading, error, refresh };
}
