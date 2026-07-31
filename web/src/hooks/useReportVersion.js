import { useCallback, useEffect, useRef, useState } from 'react';

const GENERATING_STATUSES = new Set(['queued', 'generating']);

function latestReady(versions) {
  return versions
    .filter((version) => version.status === 'ready')
    .sort((left, right) => Number(right.version) - Number(left.version))[0] || null;
}

export function useReportVersion({ scopeType, scopeId, dataSource, pollInterval = 2000 }) {
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const selectedRef = useRef(null);
  const mountedRef = useRef(true);
  const scopeRef = useRef(`${scopeType}:${scopeId}`);
  const requestRef = useRef(0);
  const timerRef = useRef(null);

  const isCurrentScope = useCallback((scopeKey) => (
    mountedRef.current && scopeRef.current === scopeKey
  ), []);

  const loadManifest = useCallback(async (version, scopeKey = scopeRef.current) => {
    const request = ++requestRef.current;
    if (!version || version.status !== 'ready') {
      if (isCurrentScope(scopeKey)) setManifest(null);
      return null;
    }

    const nextManifest = await dataSource.getManifest(version.report_id);
    if (isCurrentScope(scopeKey) && request === requestRef.current) {
      setManifest(nextManifest);
    }
    return nextManifest;
  }, [dataSource, isCurrentScope]);

  const refresh = useCallback(async () => {
    const scopeKey = `${scopeType}:${scopeId}`;
    const request = ++requestRef.current;
    if (isCurrentScope(scopeKey)) setLoading(true);

    try {
      const list = await dataSource.listVersions(scopeType, scopeId);
      const generating = list.filter((version) => GENERATING_STATUSES.has(version.status));
      const statuses = await Promise.all(generating.map(async (version) => (
        await dataSource.getStatus(version.report_id)
      )));
      const resolvedList = list.map((version) => (
        statuses.find((status) => status?.report_id === version.report_id) || version
      ));
      if (!isCurrentScope(scopeKey) || request !== requestRef.current) return;

      setVersions(resolvedList);
      const selectedId = selectedRef.current?.report_id;
      const preserved = selectedId ? resolvedList.find((version) => version.report_id === selectedId) : null;
      const next = preserved || latestReady(resolvedList) || resolvedList[0] || null;
      selectedRef.current = next;
      setSelectedVersion(next);
      setError(null);
      await loadManifest(next, scopeKey);
    } catch (nextError) {
      if (isCurrentScope(scopeKey)) setError(nextError);
    } finally {
      if (isCurrentScope(scopeKey)) setLoading(false);
    }
  }, [dataSource, isCurrentScope, loadManifest, scopeId, scopeType]);

  useEffect(() => {
    const scopeKey = `${scopeType}:${scopeId}`;
    scopeRef.current = scopeKey;
    selectedRef.current = null;
    setVersions([]);
    setSelectedVersion(null);
    setManifest(null);
    void refresh();
  }, [refresh, scopeId, scopeType]);

  useEffect(() => {
    const scopeKey = `${scopeType}:${scopeId}`;
    const generating = versions.filter((version) => GENERATING_STATUSES.has(version.status));
    if (!generating.length) return undefined;

    const poll = async () => {
      try {
        const statuses = await Promise.all(generating.map((version) => dataSource.getStatus(version.report_id)));
        if (!isCurrentScope(scopeKey)) return;

        let selectedReady = null;
        setVersions((items) => items.map((version) => {
          const status = statuses.find((item) => item?.report_id === version.report_id) || version;
          if (status.report_id === selectedRef.current?.report_id && status.status === 'ready') {
            selectedReady = status;
          }
          return status;
        }));
        if (selectedReady) {
          selectedRef.current = selectedReady;
          setSelectedVersion(selectedReady);
          await loadManifest(selectedReady, scopeKey);
        }
        setError(null);
      } catch (nextError) {
        if (isCurrentScope(scopeKey)) setError(nextError);
      }
    };

    timerRef.current = setTimeout(() => { void poll(); }, pollInterval);
    return () => clearTimeout(timerRef.current);
  }, [dataSource, isCurrentScope, loadManifest, pollInterval, scopeId, scopeType, versions]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimeout(timerRef.current);
    };
  }, []);

  const selectVersion = useCallback(async (version) => {
    selectedRef.current = version;
    setSelectedVersion(version);
    setError(null);
    try {
      await loadManifest(version);
    } catch (nextError) {
      if (mountedRef.current) setError(nextError);
    }
  }, [loadManifest]);

  const createVersion = useCallback(async () => {
    const scopeKey = `${scopeType}:${scopeId}`;
    setLoading(true);
    setError(null);
    try {
      const created = await dataSource.createVersion(scopeType, scopeId);
      if (!isCurrentScope(scopeKey)) return created;
      setVersions((items) => [created, ...items.filter((item) => item.report_id !== created.report_id)]);
      selectedRef.current = created;
      setSelectedVersion(created);
      setManifest(null);
      return created;
    } catch (nextError) {
      if (isCurrentScope(scopeKey)) setError(nextError);
      throw nextError;
    } finally {
      if (isCurrentScope(scopeKey)) setLoading(false);
    }
  }, [dataSource, isCurrentScope, scopeId, scopeType]);

  return {
    versions,
    selectedVersion,
    manifest,
    loading,
    error,
    generating: versions.find((version) => GENERATING_STATUSES.has(version.status)) || null,
    selectVersion,
    createVersion,
    refresh,
  };
}
