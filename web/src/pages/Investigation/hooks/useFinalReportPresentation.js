import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getFinalReportHtml,
  getFinalReportMarkdown,
  getFinalReportPrint,
} from '../../../services/investigationService';

function errorMessage(error) {
  return error?.message || 'Report presentation request failed.';
}

function reportFilename(reportId, reportVersion, extension) {
  const safeId = String(reportId || 'report').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[.-]+|[.-]+$/g, '') || 'report';
  return `tracelens-report-v${reportVersion || 'unknown'}-${safeId}.${extension}`;
}

function writePopup(targetWindow, content, shouldPrint = false) {
  if (!targetWindow || targetWindow.closed) throw new Error('Could not open report presentation window.');
  const document = targetWindow.document;
  document.open();
  document.write(content);
  document.close();
  if (shouldPrint) {
    setTimeout(() => {
      if (!targetWindow.closed) targetWindow.print();
    }, 0);
  }
}

export default function useFinalReportPresentation(taskId, reportId, reportVersion, enabled) {
  const [loading, setLoading] = useState(null);
  const [error, setError] = useState(null);
  const identityRef = useRef(`${taskId || ''}:${reportId || ''}`);
  const generationRef = useRef(0);

  useEffect(() => {
    identityRef.current = `${taskId || ''}:${reportId || ''}`;
    generationRef.current += 1;
    setLoading(null);
    setError(null);
  }, [taskId, reportId]);

  const run = useCallback(async (kind, request, targetWindow = null) => {
    const identity = `${taskId || ''}:${reportId || ''}`;
    const generation = ++generationRef.current;
    setLoading(kind);
    setError(null);
    try {
      const content = await request(taskId, reportId);
      if (kind === 'markdown') {
        const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = reportFilename(reportId, reportVersion, 'md');
        anchor.click();
        URL.revokeObjectURL(url);
      } else {
        writePopup(targetWindow, content, kind === 'print');
      }
      if (identityRef.current === identity && generationRef.current === generation) {
        setLoading(null);
      }
    } catch (requestError) {
      if (targetWindow && !targetWindow.closed) targetWindow.close();
      if (identityRef.current === identity && generationRef.current === generation) {
        setLoading(null);
        setError(errorMessage(requestError));
      }
    }
  }, [reportId, reportVersion, taskId]);

  const downloadMarkdown = useCallback(() => {
    if (!enabled || !taskId || !reportId) return;
    void run('markdown', getFinalReportMarkdown);
  }, [enabled, reportId, run, taskId]);

  const openHtml = useCallback(() => {
    if (!enabled || !taskId || !reportId) return;
    const targetWindow = window.open('', '_blank');
    if (!targetWindow) {
      setError('Could not open report presentation window.');
      return;
    }
    void run('html', getFinalReportHtml, targetWindow);
  }, [enabled, reportId, run, taskId]);

  const printReport = useCallback(() => {
    if (!enabled || !taskId || !reportId) return;
    const targetWindow = window.open('', '_blank');
    if (!targetWindow) {
      setError('Could not open report presentation window.');
      return;
    }
    void run('print', getFinalReportPrint, targetWindow);
  }, [enabled, reportId, run, taskId]);

  return {
    loading,
    error,
    downloadMarkdown,
    openHtml,
    printReport,
    canPresent: Boolean(enabled && taskId && reportId),
  };
}

export { reportFilename, writePopup };
