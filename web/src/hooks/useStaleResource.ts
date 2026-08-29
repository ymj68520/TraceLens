import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Generic read-only resource loader with stale-response protection.
 *
 * `key` is the resource's full identity (e.g. `taskId` or `taskId:eventId`).
 * A falsy key means "nothing selected" — no request fires. When the key
 * changes, in-flight requests for the old key are invalidated and old data
 * is dropped.
 *
 * Invariant: a late response from an old key (success or failure) never
 * overwrites the current key's data / error / loading.
 */
export function useStaleResource<T>(fetcher: () => Promise<T>, key: string | null | undefined | false) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
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

  const load = useCallback(async (): Promise<T | undefined> => {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, loading, error, reload: load };
}

export default useStaleResource;
