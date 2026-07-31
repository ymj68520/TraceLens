import { useCallback, useEffect, useRef, useState } from 'react';

const GENERATING_STATUSES = new Set(['queued', 'generating']);

function isGenerating(version) {
  return version && GENERATING_STATUSES.has(version.status);
}

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
  const mountedRef = useRef(true);
  const scopeRef = useRef(`${scopeType}:${scopeId}`);
  const intentRef = useRef(0);
  const versionsRef = useRef([]);
  const selectedRef = useRef(null);
  const timerRef = useRef(null);
  const dataSourceRef = useRef(dataSource);
  const pollIntervalRef = useRef(pollInterval);
  const pollRef = useRef(null);

  dataSourceRef.current = dataSource;
  pollIntervalRef.current = pollInterval;

  const clearTimer = useCallback(() => {
    clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const isActive = useCallback((scopeKey, intent) => (
    mountedRef.current && scopeRef.current === scopeKey && intentRef.current === intent
  ), []);

  const beginIntent = useCallback(() => {
    clearTimer();
    intentRef.current += 1;
    return intentRef.current;
  }, [clearTimer]);

  const commitVersions = useCallback((nextVersions) => {
    versionsRef.current = nextVersions;
    setVersions(nextVersions);
  }, []);

  const commitSelection = useCallback((nextVersion) => {
    selectedRef.current = nextVersion;
    setSelectedVersion(nextVersion);
  }, []);

  const loadManifest = useCallback(async (version, scopeKey, intent) => {
    if (!version || version.status !== 'ready') {
      if (isActive(scopeKey, intent)) setManifest(null);
      return null;
    }

    try {
      const nextManifest = await dataSourceRef.current.getManifest(version.report_id);
      if (isActive(scopeKey, intent)) {
        setManifest(nextManifest);
        setError(null);
      }
      return nextManifest;
    } catch (nextError) {
      if (isActive(scopeKey, intent)) {
        setManifest(null);
        setError(nextError);
      }
      return null;
    }
  }, [isActive]);

  const schedulePoll = useCallback((scopeKey, intent) => {
    clearTimer();
    if (!isActive(scopeKey, intent) || !versionsRef.current.some(isGenerating)) return;
    timerRef.current = setTimeout(() => { void pollRef.current(scopeKey, intent); }, pollIntervalRef.current);
  }, [clearTimer, isActive]);

  const refresh = useCallback(async () => {
    const scopeKey = `${scopeType}:${scopeId}`;
    const intent = beginIntent();
    if (isActive(scopeKey, intent)) {
      setLoading(true);
      setError(null);
    }

    try {
      const list = await dataSourceRef.current.listVersions(scopeType, scopeId);
      if (!isActive(scopeKey, intent)) return;

      let nextVersions = list;
      const generating = list.filter(isGenerating);
      if (generating.length) {
        try {
          const statuses = await Promise.all(generating.map((version) => (
            dataSourceRef.current.getStatus(version.report_id)
          )));
          if (!isActive(scopeKey, intent)) return;
          nextVersions = list.map((version) => (
            statuses.find((status) => status?.report_id === version.report_id) || version
          ));
        } catch (nextError) {
          if (isActive(scopeKey, intent)) setError(nextError);
        }
      }
      if (!isActive(scopeKey, intent)) return;

      commitVersions(nextVersions);
      const previousId = selectedRef.current?.report_id;
      const preserved = previousId ? nextVersions.find((version) => version.report_id === previousId) : null;
      const nextSelected = preserved || latestReady(nextVersions) || nextVersions[0] || null;
      commitSelection(nextSelected);
      if (nextSelected?.status === 'ready') {
        await loadManifest(nextSelected, scopeKey, intent);
      } else {
        setManifest(null);
      }
    } catch (nextError) {
      if (isActive(scopeKey, intent)) setError(nextError);
    } finally {
      if (isActive(scopeKey, intent)) {
        setLoading(false);
        schedulePoll(scopeKey, intent);
      }
    }
  }, [beginIntent, commitSelection, commitVersions, isActive, loadManifest, schedulePoll, scopeId, scopeType]);

  pollRef.current = async (scopeKey, intent) => {
    if (!isActive(scopeKey, intent)) return;
    const beforePoll = versionsRef.current;
    const generating = beforePoll.filter(isGenerating);
    if (!generating.length) return;

    try {
      const statuses = await Promise.all(generating.map((version) => (
        dataSourceRef.current.getStatus(version.report_id)
      )));
      if (!isActive(scopeKey, intent)) return;

      const nextVersions = beforePoll.map((version) => (
        statuses.find((status) => status?.report_id === version.report_id) || version
      ));
      const currentId = selectedRef.current?.report_id;
      const nextSelected = currentId
        ? nextVersions.find((version) => version.report_id === currentId) || selectedRef.current
        : null;

      commitVersions(nextVersions);
      if (nextSelected) {
        commitSelection(nextSelected);
        if (nextSelected.status === 'ready') {
          await loadManifest(nextSelected, scopeKey, intent);
        } else if (nextSelected.status === 'failed' || isGenerating(nextSelected)) {
          setManifest(null);
        }
      }
      if (isActive(scopeKey, intent)) setError(null);
    } catch (nextError) {
      if (isActive(scopeKey, intent)) setError(nextError);
    } finally {
      if (isActive(scopeKey, intent)) schedulePoll(scopeKey, intent);
    }
  };

  useEffect(() => {
    const scopeKey = `${scopeType}:${scopeId}`;
    scopeRef.current = scopeKey;
    const intent = beginIntent();
    versionsRef.current = [];
    selectedRef.current = null;
    setVersions([]);
    setSelectedVersion(null);
    setManifest(null);
    setError(null);
    setLoading(true);
    void (async () => {
      // refresh owns its token, so create one operation for each scope reset.
      const list = await dataSourceRef.current.listVersions(scopeType, scopeId);
      if (!isActive(scopeKey, intent)) return;

      let nextVersions = list;
      const generating = list.filter(isGenerating);
      if (generating.length) {
        try {
          const statuses = await Promise.all(generating.map((version) => (
            dataSourceRef.current.getStatus(version.report_id)
          )));
          if (!isActive(scopeKey, intent)) return;
          nextVersions = list.map((version) => (
            statuses.find((status) => status?.report_id === version.report_id) || version
          ));
        } catch (nextError) {
          if (isActive(scopeKey, intent)) setError(nextError);
        }
      }
      if (!isActive(scopeKey, intent)) return;

      commitVersions(nextVersions);
      const nextSelected = latestReady(nextVersions) || nextVersions[0] || null;
      commitSelection(nextSelected);
      if (nextSelected?.status === 'ready') {
        await loadManifest(nextSelected, scopeKey, intent);
      } else {
        setManifest(null);
      }
      if (isActive(scopeKey, intent)) setLoading(false);
      schedulePoll(scopeKey, intent);
    })().catch((nextError) => {
      if (isActive(scopeKey, intent)) {
        setError(nextError);
        setLoading(false);
      }
    });

    return clearTimer;
  }, [beginIntent, clearTimer, commitSelection, commitVersions, isActive, loadManifest, schedulePoll, scopeId, scopeType]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer();
    };
  }, [clearTimer]);

  const selectVersion = useCallback(async (version) => {
    const scopeKey = scopeRef.current;
    const intent = beginIntent();
    commitSelection(version);
    setManifest(null);
    setError(null);
    await loadManifest(version, scopeKey, intent);
    if (isActive(scopeKey, intent)) schedulePoll(scopeKey, intent);
  }, [beginIntent, commitSelection, isActive, loadManifest, schedulePoll]);

  const createVersion = useCallback(async () => {
    const scopeKey = `${scopeType}:${scopeId}`;
    const intent = beginIntent();
    if (isActive(scopeKey, intent)) {
      setLoading(true);
      setError(null);
    }

    try {
      const created = await dataSourceRef.current.createVersion(scopeType, scopeId);
      if (!isActive(scopeKey, intent)) return created;

      const nextVersions = [created, ...versionsRef.current.filter((item) => item.report_id !== created.report_id)];
      commitVersions(nextVersions);
      commitSelection(created);
      setManifest(null);
      schedulePoll(scopeKey, intent);
      return created;
    } catch (nextError) {
      if (isActive(scopeKey, intent)) setError(nextError);
      throw nextError;
    } finally {
      if (isActive(scopeKey, intent)) {
        setLoading(false);
        schedulePoll(scopeKey, intent);
      }
    }
  }, [beginIntent, commitSelection, commitVersions, isActive, schedulePoll, scopeId, scopeType]);

  return {
    versions,
    selectedVersion,
    manifest,
    loading,
    error,
    generating: versions.find(isGenerating) || null,
    selectVersion,
    createVersion,
    refresh,
  };
}
