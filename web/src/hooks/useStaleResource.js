import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * 通用只读资源加载 hook，复用 useReportSearch / useInvestigationGraph 的
 * requestId 防陈旧模式。
 *
 * `key` 是资源的完整身份（如 `taskId`、`taskId:eventId`）。key 为 falsy 时
 * 不发请求（无任务/无选中）。key 变化时使未完成请求失效并清空旧数据。
 *
 * 不变量：旧 key 的响应（无论成功或失败）晚于新 key 返回时，绝不覆盖
 * 当前 key 的 data / error / loading。
 */
export function useStaleResource(fetcher, key) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const keyRef = useRef(key);
  const requestRef = useRef(0);

  useEffect(() => {
    keyRef.current = key;
    requestRef.current += 1;
    setData(null);
    setError(null);
    setLoading(false);
  }, [key]);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(async () => {
    const requestKey = key;
    if (!requestKey) return undefined;

    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);

    try {
      const result = await fetcherRef.current();
      if (requestRef.current !== requestId || keyRef.current !== requestKey) {
        return result;
      }
      setData(result);
      return result;
    } catch (nextError) {
      if (requestRef.current === requestId && keyRef.current === requestKey) {
        setData(null);
        setError(nextError);
      }
      return undefined;
    } finally {
      if (requestRef.current === requestId && keyRef.current === requestKey) {
        setLoading(false);
      }
    }
  }, [key]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, loading, error, refresh: load };
}
