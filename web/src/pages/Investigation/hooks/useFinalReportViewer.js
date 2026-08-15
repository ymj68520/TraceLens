import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getFinalReport,
  getFinalReports,
} from '../../../services/investigationService';

const emptyState = {
  reports: [],
  selectedReportId: null,
  selectedReport: null,
  listLoading: false,
  listError: null,
  detailLoading: false,
  detailError: null,
};

function errorMessage(error) {
  return error?.status === 404 ? 'Report version not found.' : error?.message || 'Report viewer request failed.';
}

export default function useFinalReportViewer(taskId) {
  const [reports, setReports] = useState(emptyState.reports);
  const [selectedReportId, setSelectedReportId] = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const listRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const taskRef = useRef(taskId);
  const selectedReportRef = useRef(null);

  const loadDetail = useCallback(async (reportId) => {
    if (!taskId || !reportId) return;
    const requestId = ++detailRequestRef.current;
    const requestTask = taskId;
    const requestReport = reportId;
    selectedReportRef.current = requestReport;
    setSelectedReportId(requestReport);
    setSelectedReport(null);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const response = await getFinalReport(requestTask, requestReport);
      if (
        detailRequestRef.current !== requestId
        || taskRef.current !== requestTask
        || selectedReportRef.current !== requestReport
      ) return;
      setSelectedReport(response?.report || null);
    } catch (error) {
      if (
        detailRequestRef.current === requestId
        && taskRef.current === requestTask
        && selectedReportRef.current === requestReport
      ) {
        setSelectedReport(null);
        setDetailError(errorMessage(error));
      }
    } finally {
      if (
        detailRequestRef.current === requestId
        && taskRef.current === requestTask
        && selectedReportRef.current === requestReport
      ) setDetailLoading(false);
    }
  }, [taskId]);

  const loadList = useCallback(async () => {
    const requestId = ++listRequestRef.current;
    const requestTask = taskId;
    taskRef.current = requestTask;
    detailRequestRef.current += 1;
    selectedReportRef.current = null;
    setReports([]);
    setSelectedReportId(null);
    setSelectedReport(null);
    setDetailLoading(false);
    setDetailError(null);
    setListError(null);
    if (!requestTask) {
      setListLoading(false);
      return [];
    }
    setListLoading(true);
    try {
      const response = await getFinalReports(requestTask);
      const nextReports = Array.isArray(response?.reports) ? response.reports : [];
      if (listRequestRef.current !== requestId || taskRef.current !== requestTask) return nextReports;
      setReports(nextReports);
      if (nextReports.length > 0) {
        const firstId = nextReports[0].report_id;
        setSelectedReportId(firstId);
        selectedReportRef.current = firstId;
        void loadDetail(firstId);
      }
      return nextReports;
    } catch (error) {
      if (listRequestRef.current === requestId && taskRef.current === requestTask) {
        setReports([]);
        setListError(errorMessage(error));
      }
      return [];
    } finally {
      if (listRequestRef.current === requestId && taskRef.current === requestTask) setListLoading(false);
    }
  }, [loadDetail, taskId]);

  useEffect(() => {
    taskRef.current = taskId;
    loadList();
  }, [loadList, taskId]);

  const selectReport = useCallback((reportId) => {
    if (!reportId || reportId === selectedReportRef.current) return;
    void loadDetail(reportId);
  }, [loadDetail]);

  const retryList = useCallback(() => loadList(), [loadList]);
  const retryDetail = useCallback(() => {
    if (selectedReportRef.current) void loadDetail(selectedReportRef.current);
  }, [loadDetail]);

  return {
    reports,
    selectedReportId,
    selectedReport,
    listLoading,
    listError,
    detailLoading,
    detailError,
    selectReport,
    retryList,
    retryDetail,
  };
}
