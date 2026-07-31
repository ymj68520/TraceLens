import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const EMPTY_RESULT = { total: 0, hits: [] };

export function useReportSearch({ dataSource, reportId }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(EMPTY_RESULT);
  const [cursor, setCursor] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const reportRef = useRef(reportId);
  const requestRef = useRef(0);

  useEffect(() => {
    reportRef.current = reportId;
    requestRef.current += 1;
    setQuery('');
    setResult(EMPTY_RESULT);
    setCursor(0);
    setLoading(false);
    setError(null);
  }, [reportId]);

  const submit = useCallback(async (nextQuery) => {
    const normalizedQuery = String(nextQuery ?? '').trim();
    const requestReport = reportId;
    const requestId = ++requestRef.current;

    if (!normalizedQuery || !requestReport) {
      setQuery('');
      setResult(EMPTY_RESULT);
      setCursor(0);
      setLoading(false);
      setError(null);
      return EMPTY_RESULT;
    }

    setQuery(normalizedQuery);
    setResult(EMPTY_RESULT);
    setCursor(0);
    setLoading(true);
    setError(null);

    try {
      const response = await dataSource.search(
        requestReport,
        normalizedQuery,
        { offset: 0, limit: 200 },
      );
      if (requestRef.current !== requestId || reportRef.current !== requestReport) return response;
      const nextResult = {
        total: Number(response?.total) || 0,
        hits: Array.isArray(response?.hits) ? response.hits : [],
      };
      setResult(nextResult);
      setCursor(0);
      return nextResult;
    } catch (nextError) {
      if (requestRef.current === requestId && reportRef.current === requestReport) {
        setResult(EMPTY_RESULT);
        setCursor(0);
        setError(nextError);
      }
      return EMPTY_RESULT;
    } finally {
      if (requestRef.current === requestId && reportRef.current === requestReport) {
        setLoading(false);
      }
    }
  }, [dataSource, reportId]);

  const hits = result.hits;
  const next = useCallback(() => {
    setCursor((value) => (hits.length ? (value + 1) % hits.length : 0));
  }, [hits.length]);
  const previous = useCallback(() => {
    setCursor((value) => (hits.length ? (value - 1 + hits.length) % hits.length : 0));
  }, [hits.length]);
  const currentHit = useMemo(() => hits[cursor] || null, [cursor, hits]);

  return {
    query,
    result,
    currentHit,
    cursor,
    loading,
    error,
    submit,
    next,
    previous,
  };
}
