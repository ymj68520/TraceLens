import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getFinalReportPublication,
  publishFinalReport,
} from '../../../services/investigationService';

function readErrorMessage(error) {
  return error?.message || 'Publication read failed.';
}

function publishErrorMessage(error) {
  return error?.message || 'Publication failed.';
}

export default function useFinalReportPublication(taskId, reportId, enabled = false) {
  const [publication, setPublication] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);
  const [publishLoading, setPublishLoading] = useState(false);
  const [publishError, setPublishError] = useState(null);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const readRequestRef = useRef(0);
  const publishGenerationRef = useRef(0);
  const identityRef = useRef(null);
  const identity = taskId && reportId ? `${taskId}:${reportId}` : null;
  identityRef.current = identity;

  const refresh = useCallback(async () => {
    if (!enabled || !taskId || !reportId) return null;
    const requestId = ++readRequestRef.current;
    const requestIdentity = `${taskId}:${reportId}`;
    setLoading(true);
    setError(null);
    try {
      const response = await getFinalReportPublication(taskId, reportId);
      if (readRequestRef.current !== requestId || identityRef.current !== requestIdentity) return null;
      const nextPublication = response?.publication ?? null;
      setPublication(nextPublication);
      setReady(true);
      return nextPublication;
    } catch (requestError) {
      if (readRequestRef.current === requestId && identityRef.current === requestIdentity) {
        setPublication(null);
        setReady(true);
        setError(readErrorMessage(requestError));
      }
      return null;
    } finally {
      if (readRequestRef.current === requestId && identityRef.current === requestIdentity) {
        setLoading(false);
      }
    }
  }, [enabled, reportId, taskId]);

  useEffect(() => {
    readRequestRef.current += 1;
    publishGenerationRef.current += 1;
    setPublication(null);
    setLoading(Boolean(enabled && taskId && reportId));
    setReady(false);
    setError(null);
    setPublishLoading(false);
    setPublishError(null);
    setPublishSuccess(false);
    if (enabled && taskId && reportId) void refresh();
  }, [enabled, reportId, refresh, taskId]);

  const publish = useCallback(async () => {
    if (!taskId || !reportId || publishLoading) return;
    const generation = ++publishGenerationRef.current;
    const submittedIdentity = `${taskId}:${reportId}:${generation}`;
    setPublishLoading(true);
    setPublishError(null);
    setPublishSuccess(false);
    try {
      await publishFinalReport(taskId, reportId);
      if (identityRef.current !== `${taskId}:${reportId}` || publishGenerationRef.current !== generation) return;
      setPublishSuccess(true);
      await refresh();
    } catch (requestError) {
      if (
        identityRef.current === `${taskId}:${reportId}`
        && publishGenerationRef.current === generation
        && submittedIdentity === `${taskId}:${reportId}:${generation}`
      ) setPublishError(publishErrorMessage(requestError));
    } finally {
      if (identityRef.current === `${taskId}:${reportId}` && publishGenerationRef.current === generation) {
        setPublishLoading(false);
      }
    }
  }, [publishLoading, refresh, reportId, taskId]);

  return {
    publication,
    loading,
    ready,
    error,
    publishLoading,
    publishError,
    publishSuccess,
    refresh,
    publish,
  };
}
