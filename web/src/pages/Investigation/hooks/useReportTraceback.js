import { useCallback, useEffect, useRef, useState } from 'react';
import { getClaimProvenance } from '../../../services/investigationService';

function claimErrorMessage(error) {
  return error?.status === 404
    ? 'Claim provenance not found.'
    : error?.message || 'Claim provenance request failed.';
}

export default function useReportTraceback(taskId, reportId, report) {
  const [selectedTrace, setSelectedTrace] = useState(null);
  const [citationTrace, setCitationTrace] = useState(null);
  const [claimDetail, setClaimDetail] = useState(null);
  const [claimLoading, setClaimLoading] = useState(false);
  const [claimError, setClaimError] = useState(null);
  const requestRef = useRef(0);

  const clearTrace = useCallback(() => {
    requestRef.current += 1;
    setSelectedTrace(null);
    setCitationTrace(null);
    setClaimDetail(null);
    setClaimLoading(false);
    setClaimError(null);
  }, []);

  useEffect(() => {
    clearTrace();
  }, [clearTrace, taskId, reportId]);

  const openCitation = useCallback((citationId) => {
    const citation = Array.isArray(report?.citation_manifest)
      ? report.citation_manifest.find((entry) => entry?.citation_id === citationId)
      : null;
    requestRef.current += 1;
    setSelectedTrace({ type: 'citation', id: citationId });
    setCitationTrace(citation || null);
    setClaimDetail(null);
    setClaimLoading(false);
    setClaimError(null);
  }, [report]);

  const openClaim = useCallback(async (claimId) => {
    if (!taskId || !reportId || !claimId) return;
    const requestId = ++requestRef.current;
    const requestKey = `${taskId}:${reportId}:${claimId}`;
    setSelectedTrace({ type: 'claim', id: claimId });
    setCitationTrace(null);
    setClaimDetail(null);
    setClaimError(null);
    setClaimLoading(true);
    try {
      const response = await getClaimProvenance(taskId, claimId);
      if (
        requestRef.current !== requestId
        || `${taskId}:${reportId}:${claimId}` !== requestKey
      ) return;
      setClaimDetail(response?.claim || null);
    } catch (error) {
      if (requestRef.current === requestId) {
        setClaimError(claimErrorMessage(error));
      }
    } finally {
      if (requestRef.current === requestId) setClaimLoading(false);
    }
  }, [reportId, taskId]);

  return {
    selectedTrace,
    citationTrace,
    claimDetail,
    claimLoading,
    claimError,
    openCitation,
    openClaim,
    closeTrace: clearTrace,
  };
}
