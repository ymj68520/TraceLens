import { useCallback, useEffect, useRef, useState } from 'react';

const GENERATING_STATUSES = new Set(['queued', 'generating']);
const STATUS_PHASE = {
  queued: 0,
  generating: 1,
  ready: 2,
  failed: 2,
};

function isGenerating(version) {
  return version && GENERATING_STATUSES.has(version.status);
}

function latestReady(versions) {
  return versions
    .filter((version) => version.status === 'ready')
    .sort((left, right) => Number(right.version) - Number(left.version))[0] || null;
}

function statusPhase(version) {
  return STATUS_PHASE[version?.status] ?? -1;
}

export function mergeReportVersion(serverVersion, observedVersion) {
  if (!serverVersion) return observedVersion;
  if (!observedVersion) return serverVersion;

  const serverPhase = statusPhase(serverVersion);
  const observedPhase = statusPhase(observedVersion);
  if (serverPhase > observedPhase) return serverVersion;
  if (serverPhase < observedPhase) return observedVersion;

  if (serverVersion.status === 'generating' && observedVersion.status === 'generating') {
    return Number(serverVersion.progress || 0) > Number(observedVersion.progress || 0)
      ? serverVersion
      : observedVersion;
  }

  if (serverPhase === STATUS_PHASE.ready) {
    if (serverVersion.status !== observedVersion.status) return observedVersion;
    return { ...observedVersion, ...serverVersion };
  }

  return observedVersion;
}

export function mergeReportVersions(serverVersions, observedVersions) {
  const serverIds = new Set(serverVersions.map((version) => version.report_id));
  const observedById = new Map(observedVersions.map((version) => [version.report_id, version]));
  return [
    ...observedVersions.filter((version) => !serverIds.has(version.report_id)),
    ...serverVersions.map((serverVersion) => (
      mergeReportVersion(serverVersion, observedById.get(serverVersion.report_id))
    )),
  ];
}

function serverConfirmsObserved(serverVersion, observedVersion) {
  const serverPhase = statusPhase(serverVersion);
  const observedPhase = statusPhase(observedVersion);
  if (serverPhase !== observedPhase) return serverPhase > observedPhase;
  if (serverPhase === STATUS_PHASE.generating) {
    return Number(serverVersion.progress || 0) >= Number(observedVersion.progress || 0);
  }
  if (serverPhase === STATUS_PHASE.ready) return serverVersion.status === observedVersion.status;
  return serverVersion.status === observedVersion.status;
}

function serverSnapshotWithStatuses(list, statuses) {
  const statusById = new Map(statuses.map((status) => [status.report_id, status]));
  const listIds = new Set(list.map((version) => version.report_id));
  return [
    ...statuses.filter((status) => !listIds.has(status.report_id)),
    ...list.map((version) => statusById.get(version.report_id) || version),
  ];
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
  const operationsRef = useRef(new Map());
  const operationIdRef = useRef(0);

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

  const beginOperation = useCallback((scopeKey) => {
    const token = ++operationIdRef.current;
    const operations = operationsRef.current.get(scopeKey) || new Set();
    operations.add(token);
    operationsRef.current.set(scopeKey, operations);
    if (mountedRef.current && scopeRef.current === scopeKey) setLoading(true);
    return token;
  }, []);

  const endOperation = useCallback((scopeKey, token) => {
    const operations = operationsRef.current.get(scopeKey);
    if (!operations?.delete(token)) return;
    if (!operations.size) operationsRef.current.delete(scopeKey);
    if (mountedRef.current && scopeRef.current === scopeKey) setLoading(operations.size > 0);
  }, []);

  const currentOverlay = useCallback((scopeKey) => (
    [...(createdOverlayRef.current.get(scopeKey)?.values() || [])]
  ), []);

  const reconcileCreatedOverlay = useCallback((scopeKey, serverVersions) => {
    const overlay = createdOverlayRef.current.get(scopeKey);
    if (!overlay) return;

    for (const serverVersion of serverVersions) {
      const observedVersion = overlay.get(serverVersion.report_id);
      if (!observedVersion) continue;
      if (serverConfirmsObserved(serverVersion, observedVersion)) {
        overlay.delete(serverVersion.report_id);
      } else {
        overlay.set(
          serverVersion.report_id,
          mergeReportVersion(serverVersion, observedVersion),
        );
      }
    }
    if (!overlay.size) createdOverlayRef.current.delete(scopeKey);
  }, []);

  const reconcileServerSnapshot = useCallback((scopeKey, serverVersions) => {
    reconcileCreatedOverlay(scopeKey, serverVersions);
    const withCurrent = mergeReportVersions(serverVersions, versionsRef.current);
    return mergeReportVersions(withCurrent, currentOverlay(scopeKey));
  }, [currentOverlay, reconcileCreatedOverlay]);

  const updateCreatedOverlay = useCallback((scopeKey, nextVersions) => {
    const overlay = createdOverlayRef.current.get(scopeKey);
    if (!overlay) return;
    for (const version of nextVersions) {
      const observedVersion = overlay.get(version.report_id);
      if (observedVersion) {
        overlay.set(version.report_id, mergeReportVersion(version, observedVersion));
      }
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

  const readVersions = useCallback(async (scopeKey, intent, preserveSelection) => {
    const list = await dataSourceRef.current.listVersions(scopeType, scopeId);
    if (!isActive(scopeKey, intent)) return;

    const candidateVersions = reconcileServerSnapshot(scopeKey, list);
    const generating = candidateVersions.filter(isGenerating);
    let serverSnapshot = list;
    if (generating.length) {
      try {
        const statuses = await Promise.all(generating.map((version) => (
          dataSourceRef.current.getStatus(version.report_id)
        )));
        if (!isActive(scopeKey, intent)) return;
        serverSnapshot = serverSnapshotWithStatuses(list, statuses.filter(Boolean));
      } catch (nextError) {
        if (isActive(scopeKey, intent)) setError(nextError);
      }
    }
    if (!isActive(scopeKey, intent)) return;

    // Re-read both current state and the mutation overlay only after all status
    // requests settle; neither the list-stage snapshot nor a stale status owns commit.
    const nextVersions = reconcileServerSnapshot(scopeKey, serverSnapshot);
    updateCreatedOverlay(scopeKey, nextVersions);
    commitVersions(nextVersions);
    const previousId = preserveSelection ? selectedRef.current?.report_id : null;
    const preserved = previousId
      ? nextVersions.find((version) => version.report_id === previousId)
      : null;
    const nextSelected = preserved || latestReady(nextVersions) || nextVersions[0] || null;
    commitSelection(nextSelected);
    if (nextSelected?.status === 'ready') {
      await loadManifest(nextSelected, scopeKey, intent);
    } else if (isActive(scopeKey, intent)) {
      setManifest(null);
    }
  }, [commitSelection, commitVersions, isActive, loadManifest, reconcileServerSnapshot, scopeId, scopeType, updateCreatedOverlay]);

  const refresh = useCallback(async () => {
    const scopeKey = `${scopeType}:${scopeId}`;
    const intent = beginIntent();
    const operation = beginOperation(scopeKey);
    if (isActive(scopeKey, intent)) setError(null);

    try {
      await readVersions(scopeKey, intent, true);
    } catch (nextError) {
      if (isActive(scopeKey, intent)) setError(nextError);
    } finally {
      if (isActive(scopeKey, intent)) schedulePoll(scopeKey, intent);
      endOperation(scopeKey, operation);
    }
  }, [beginIntent, beginOperation, endOperation, isActive, readVersions, schedulePoll, scopeId, scopeType]);

  pollRef.current = async (scopeKey, intent) => {
    if (!isActive(scopeKey, intent)) return;
    const generating = versionsRef.current.filter(isGenerating);
    if (!generating.length) return;

    try {
      const statuses = (await Promise.all(generating.map((version) => (
        dataSourceRef.current.getStatus(version.report_id)
      )))).filter(Boolean);
      if (!isActive(scopeKey, intent)) return;

      reconcileCreatedOverlay(scopeKey, statuses);
      const statusById = new Map(statuses.map((status) => [status.report_id, status]));
      const nextVersions = versionsRef.current.map((version) => (
        mergeReportVersion(statusById.get(version.report_id), version)
      ));
      const withOverlay = mergeReportVersions(nextVersions, currentOverlay(scopeKey));
      const currentId = selectedRef.current?.report_id;
      const nextSelected = currentId
        ? withOverlay.find((version) => version.report_id === currentId) || selectedRef.current
        : null;

      updateCreatedOverlay(scopeKey, withOverlay);
      commitVersions(withOverlay);
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
    const operation = beginOperation(scopeKey);
    versionsRef.current = [];
    selectedRef.current = null;
    setVersions([]);
    setSelectedVersion(null);
    setManifest(null);
    setError(null);

    void readVersions(scopeKey, intent, false)
      .catch((nextError) => {
        if (isActive(scopeKey, intent)) setError(nextError);
      })
      .finally(() => {
        if (isActive(scopeKey, intent)) schedulePoll(scopeKey, intent);
        endOperation(scopeKey, operation);
      });

    return clearTimer;
  }, [beginIntent, beginOperation, clearTimer, endOperation, isActive, readVersions, schedulePoll, scopeId, scopeType]);

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
    const operation = beginOperation(scopeKey);
    if (mountedRef.current && scopeRef.current === scopeKey) setError(null);

    const create = (async () => {
      try {
        const created = await dataSourceRef.current.createVersion(scopeType, scopeId);
        const overlay = createdOverlayRef.current.get(scopeKey) || new Map();
        overlay.set(created.report_id, created);
        createdOverlayRef.current.set(scopeKey, overlay);
        if (!mountedRef.current || scopeRef.current !== scopeKey) return created;

        const nextVersions = mergeReportVersions(versionsRef.current, [created]);
        updateCreatedOverlay(scopeKey, nextVersions);
        commitVersions(nextVersions);
        if (intentRef.current === selectionIntent) {
          const nextCreated = nextVersions.find((version) => version.report_id === created.report_id) || created;
          commitSelection(nextCreated);
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
          schedulePoll(scopeKey, intentRef.current);
        }
        endOperation(scopeKey, operation);
      }
    })();

    createPromiseRef.current.set(scopeKey, create);
    return create;
  }, [beginIntent, beginOperation, commitSelection, commitVersions, endOperation, schedulePoll, scopeId, scopeType, updateCreatedOverlay]);

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
