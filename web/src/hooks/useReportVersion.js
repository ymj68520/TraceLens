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
  const createPromiseRef = useRef(new Map());
  const createdOverlayRef = useRef(new Map());

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

  const mergeCreated = useCallback((scopeKey, serverVersions) => {
    const pendingCreated = createdOverlayRef.current.get(scopeKey);
    if (!pendingCreated?.size) return serverVersions;

    const serverIds = new Set(serverVersions.map((version) => version.report_id));
    for (const reportId of serverIds) pendingCreated.delete(reportId);
    if (!pendingCreated.size) createdOverlayRef.current.delete(scopeKey);

    return [
      ...[...pendingCreated.values()].filter((version) => !serverIds.has(version.report_id)),
      ...serverVersions,
    ];
  }, []);

  const updateCreatedOverlay = useCallback((scopeKey, versions) => {
    const pendingCreated = createdOverlayRef.current.get(scopeKey);
    if (!pendingCreated) return;
    for (const version of versions) {
      if (pendingCreated.has(version.report_id)) pendingCreated.set(version.report_id, version);
    }
  }, []);

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

      let nextVersions = mergeCreated(scopeKey, list);
      const generating = nextVersions.filter(isGenerating);
      if (generating.length) {
        try {
          const statuses = await Promise.all(generating.map((version) => (
            dataSourceRef.current.getStatus(version.report_id)
          )));
          if (!isActive(scopeKey, intent)) return;
          nextVersions = nextVersions.map((version) => (
            statuses.find((status) => status?.report_id === version.report_id) || version
          ));
          updateCreatedOverlay(scopeKey, nextVersions);
        } catch (nextError) {
          if (isActive(scopeKey, intent)) setError(nextError);
        }
      }
      if (!isActive(scopeKey, intent)) return;

      updateCreatedOverlay(scopeKey, nextVersions);
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
  }, [beginIntent, commitSelection, commitVersions, isActive, loadManifest, mergeCreated, schedulePoll, scopeId, scopeType, updateCreatedOverlay]);

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

      updateCreatedOverlay(scopeKey, nextVersions);
      commitVersions(nextVersions);
      let manifestLoaded = true;
      if (nextSelected) {
        commitSelection(nextSelected);
        if (nextSelected.status === 'ready') {
          manifestLoaded = Boolean(await loadManifest(nextSelected, scopeKey, intent));
        } else if (nextSelected.status === 'failed' || isGenerating(nextSelected)) {
          setManifest(null);
        }
      }
      if (manifestLoaded && isActive(scopeKey, intent)) setError(null);
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

      let nextVersions = mergeCreated(scopeKey, list);
      const generating = nextVersions.filter(isGenerating);
      if (generating.length) {
        try {
          const statuses = await Promise.all(generating.map((version) => (
            dataSourceRef.current.getStatus(version.report_id)
          )));
          if (!isActive(scopeKey, intent)) return;
          nextVersions = nextVersions.map((version) => (
            statuses.find((status) => status?.report_id === version.report_id) || version
          ));
          updateCreatedOverlay(scopeKey, nextVersions);
        } catch (nextError) {
          if (isActive(scopeKey, intent)) setError(nextError);
        }
      }
      if (!isActive(scopeKey, intent)) return;

      updateCreatedOverlay(scopeKey, nextVersions);
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
  }, [beginIntent, clearTimer, commitSelection, commitVersions, isActive, loadManifest, mergeCreated, schedulePoll, scopeId, scopeType, updateCreatedOverlay]);

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

  const createVersion = useCallback(() => {
    const scopeKey = `${scopeType}:${scopeId}`;
    const pendingCreate = createPromiseRef.current.get(scopeKey);
    if (pendingCreate) return pendingCreate;

    const selectionIntent = beginIntent();
    if (mountedRef.current && scopeRef.current === scopeKey) {
      setLoading(true);
      setError(null);
    }

    const create = (async () => {
      try {
        const created = await dataSourceRef.current.createVersion(scopeType, scopeId);
        const overlay = createdOverlayRef.current.get(scopeKey) || new Map();
        overlay.set(created.report_id, created);
        createdOverlayRef.current.set(scopeKey, overlay);
        if (!mountedRef.current || scopeRef.current !== scopeKey) return created;

        const nextVersions = mergeCreated(scopeKey, versionsRef.current);
        commitVersions(nextVersions);
        if (intentRef.current === selectionIntent) {
          commitSelection(created);
          setManifest(null);
        }
        schedulePoll(scopeKey, intentRef.current);
        return created;
      } catch (nextError) {
        if (mountedRef.current && scopeRef.current === scopeKey) setError(nextError);
        throw nextError;
      } finally {
        if (createPromiseRef.current.get(scopeKey) === create) {
          createPromiseRef.current.delete(scopeKey);
        }
        if (mountedRef.current && scopeRef.current === scopeKey) {
          setLoading(false);
          schedulePoll(scopeKey, intentRef.current);
        }
      }
    })();

    createPromiseRef.current.set(scopeKey, create);
    return create;
  }, [beginIntent, commitSelection, commitVersions, mergeCreated, schedulePoll, scopeId, scopeType]);

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
