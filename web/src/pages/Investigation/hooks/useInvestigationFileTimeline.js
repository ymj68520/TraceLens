import { useCallback, useEffect, useRef, useState } from 'react';
import { getInvestigationFileTimeline } from '../../../services/investigationService';

/**
 * 文件中心时间线数据：/file-timeline 返回已分析文件（MACB 最新时间排序）
 * 与每个文件关联的事件 id 列表。事件对象本身仍来自 /events。
 * @param {string} taskId
 * @param {string|null} ensurePath 报告引用深链目标：即使超出显示截断也保证在投影里。
 */
export default function useInvestigationFileTimeline(taskId, ensurePath = null, reportId = null) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(Boolean(taskId && reportId));
  const [error, setError] = useState(null);
  const requestRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++requestRef.current;
    if (!taskId || !reportId) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const nextData = await getInvestigationFileTimeline(
        taskId,
        { report_id: reportId, ...(ensurePath ? { ensure_path: ensurePath } : {}) },
      );
      if (requestRef.current === requestId) setData(nextData);
    } catch (err) {
      if (requestRef.current === requestId) setError(err);
    } finally {
      if (requestRef.current === requestId) setLoading(false);
    }
  }, [taskId, ensurePath, reportId]);

  useEffect(() => {
    refresh();
    return () => { requestRef.current += 1; };
  }, [refresh]);

  return { fileTimeline: data, loading, error, refresh };
}
