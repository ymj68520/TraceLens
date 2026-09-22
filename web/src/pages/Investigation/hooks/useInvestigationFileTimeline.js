import { useCallback, useEffect, useState } from 'react';
import { getInvestigationFileTimeline } from '../../../services/investigationService';

/**
 * 文件中心时间线数据：/file-timeline 返回已分析文件（MACB 最新时间排序）
 * 与每个文件关联的事件 id 列表。事件对象本身仍来自 /events。
 * @param {string} taskId
 * @param {string|null} ensurePath 报告引用深链目标：即使超出显示截断也保证在投影里。
 */
export default function useInvestigationFileTimeline(taskId, ensurePath = null) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getInvestigationFileTimeline(
        taskId,
        ensurePath ? { ensure_path: ensurePath } : {},
      ));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [taskId, ensurePath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { fileTimeline: data, loading, error, refresh };
}
