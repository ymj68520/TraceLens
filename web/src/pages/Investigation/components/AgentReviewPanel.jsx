import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleX,
  Clock3,
  FileText,
  History,
  Info,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  User,
} from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import { useToast } from '../../../components/common/useToast';
import {
  getAgentReviewCandidate,
  getAgentReviewHistory,
  listAgentReviewCandidates,
  submitAgentReviewDecision,
} from '../../../services/investigationService';

const EPISTEMIC_VARIANTS = {
  FACT: 'green',
  INFERENCE: 'yellow',
  HYPOTHESIS: 'purple',
};

const STATUS_VARIANTS = {
  review_pending: 'yellow',
  accepted: 'green',
  rejected: 'red',
};

const GROUNDING_VARIANTS = {
  grounded: 'blue',
  ungrounded: 'red',
};

const FALLBACK_TOAST = {
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
};

export default function AgentReviewPanel({
  taskId,
  evidenceKey = null,
  eventId = null,
  onTraceEvidence,
  className = '',
}) {
  // Safe toast access with fallback
  let rawToast;
  try {
    rawToast = useToast();
  } catch {
    rawToast = FALLBACK_TOAST;
  }
  const toastRef = useRef(rawToast);
  toastRef.current = rawToast;

  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [selectedCandidateId, setSelectedCandidateId] = useState(null);
  const [selectedCandidateDetail, setSelectedCandidateDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [filterByContext, setFilterByContext] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Review confirmation modal / action state
  const [confirmAction, setConfirmAction] = useState(null); // 'accepted' | 'rejected' | null
  const [reviewNote, setReviewNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [requestId, setRequestId] = useState('');

  // Protect against stale async response across task switches (T04, T23)
  const currentTaskRef = useRef(taskId);
  currentTaskRef.current = taskId;

  // Reviewer identity limitation disclosure (T30)
  const declaredReviewer = useMemo(() => {
    if (typeof window !== 'undefined' && window.localStorage) {
      return localStorage.getItem('auth_user') || 'analyst';
    }
    return 'analyst';
  }, []);

  // Fetch candidates for current task
  const fetchCandidates = useCallback(async (targetTaskId) => {
    if (!targetTaskId) {
      setCandidates([]);
      return;
    }
    if (typeof listAgentReviewCandidates !== 'function') {
      setCandidates([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await listAgentReviewCandidates(targetTaskId);
      // Verify response belongs to the active task (T23)
      if (currentTaskRef.current === targetTaskId) {
        const list = Array.isArray(response)
          ? response
          : Array.isArray(response?.candidates)
            ? response.candidates
            : [];
        setCandidates(list);
      }
    } catch (err) {
      if (currentTaskRef.current === targetTaskId) {
        setError(err);
        toastRef.current.error(err.data?.detail || err.message || '加载审核候选失败');
      }
    } finally {
      if (currentTaskRef.current === targetTaskId) {
        setLoading(false);
      }
    }
  }, []);

  // Task switch handler (T04, T23)
  useEffect(() => {
    setCandidates([]);
    setSelectedCandidateId(null);
    setSelectedCandidateDetail(null);
    setHistory([]);
    setConfirmAction(null);
    setReviewNote('');
    setRequestId('');
    if (taskId) {
      fetchCandidates(taskId);
    }
  }, [taskId, fetchCandidates]);

  // Load selected candidate detail & history
  useEffect(() => {
    let active = true;
    if (!taskId || !selectedCandidateId) {
      setSelectedCandidateDetail(null);
      setHistory([]);
      return () => {
        active = false;
      };
    }

    setDetailLoading(true);
    setHistoryLoading(true);

    if (typeof getAgentReviewCandidate === 'function') {
      getAgentReviewCandidate(taskId, selectedCandidateId)
        .then((detail) => {
          if (active && currentTaskRef.current === taskId) {
            setSelectedCandidateDetail(detail);
          }
        })
        .catch((err) => {
          if (active && currentTaskRef.current === taskId) {
            toastRef.current.error(err.data?.detail || err.message || '加载候选详情失败');
          }
        })
        .finally(() => {
          if (active && currentTaskRef.current === taskId) {
            setDetailLoading(false);
          }
        });
    } else {
      setDetailLoading(false);
    }

    if (typeof getAgentReviewHistory === 'function') {
      getAgentReviewHistory(taskId, selectedCandidateId)
        .then((hist) => {
          if (active && currentTaskRef.current === taskId) {
            const list = Array.isArray(hist) ? hist : [];
            setHistory(list);
          }
        })
        .catch((err) => {
          if (active && currentTaskRef.current === taskId) {
            toastRef.current.error(err.data?.detail || err.message || '加载审核历史失败');
          }
        })
        .finally(() => {
          if (active && currentTaskRef.current === taskId) {
            setHistoryLoading(false);
          }
        });
    } else {
      setHistoryLoading(false);
    }

    return () => {
      active = false;
    };
  }, [taskId, selectedCandidateId]);

  // Context-matching candidates
  const matchingCandidates = useMemo(() => {
    if (!evidenceKey) return [];
    return candidates.filter((c) =>
      Array.isArray(c.evidence_refs) && c.evidence_refs.includes(evidenceKey),
    );
  }, [candidates, evidenceKey]);

  // Filtered list based on toggle
  const visibleCandidates = useMemo(() => {
    if (filterByContext && evidenceKey) {
      return matchingCandidates;
    }
    return candidates;
  }, [candidates, filterByContext, evidenceKey, matchingCandidates]);

  // Count summaries
  const pendingCount = useMemo(
    () => candidates.filter((c) => c.review_status === 'review_pending').length,
    [candidates],
  );

  const activeCandidate = selectedCandidateDetail || candidates.find((c) => c.candidate_id === selectedCandidateId);

  // Open explicit confirmation modal (T11, T12)
  const openConfirmation = (action) => {
    if (!activeCandidate || activeCandidate.review_status !== 'review_pending') return;
    setConfirmAction(action);
    setReviewNote('');
    // Generate fresh idempotent request ID (T21)
    const newReqId = `req_rev_${activeCandidate.candidate_id}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    setRequestId(newReqId);
  };

  const cancelConfirmation = () => {
    if (submitting) return;
    setConfirmAction(null);
    setReviewNote('');
    setRequestId('');
  };

  // Submit explicit review decision (T11, T12, T13, T14, T15, T17, T18, T19, T20, T21, T22, T24)
  const handleSubmitReview = async () => {
    if (submitting || !activeCandidate || !confirmAction) return;

    // Boundary check: ensure current task matches (T24)
    if (activeCandidate.task_id && activeCandidate.task_id !== taskId) {
      toastRef.current.error('Cross-task review submission prevented');
      return;
    }

    setSubmitting(true);

    const payload = {
      task_id: taskId,
      investigation_id: activeCandidate.investigation_id || undefined,
      review_target_id: activeCandidate.candidate_id,
      expected_source_revision: activeCandidate.source_revision,
      expected_candidate_hash: activeCandidate.candidate_hash,
      decision: confirmAction,
      reviewer: declaredReviewer,
      request_id: requestId,
      ...(reviewNote.trim() ? { note: reviewNote.trim() } : {}),
      ...(confirmAction === 'accepted' ? { requested_assertion_class: activeCandidate.claim_type } : {}),
    };

    try {
      const outcome = await submitAgentReviewDecision(payload);

      // Server authoritative confirmation received (T13)
      toastRef.current.success(`审核已提交：${confirmAction === 'accepted' ? '已接受' : '已拒绝'}`);

      // Update candidate status in local list (T14, T15)
      setCandidates((prev) =>
        prev.map((c) =>
          c.candidate_id === activeCandidate.candidate_id
            ? {
                ...c,
                review_status: outcome.decision || confirmAction,
                reviewed_at: outcome.reviewed_at,
                reviewer: outcome.reviewer,
                review_note: outcome.note,
              }
            : c,
        ),
      );

      // Update selected candidate detail
      setSelectedCandidateDetail((prev) =>
        prev && prev.candidate_id === activeCandidate.candidate_id
          ? {
              ...prev,
              review_status: outcome.decision || confirmAction,
              reviewed_at: outcome.reviewed_at,
              reviewer: outcome.reviewer,
              review_note: outcome.note,
            }
          : prev,
      );

      // Refresh history from authoritative backend (T29)
      if (taskId && activeCandidate.candidate_id) {
        getAgentReviewHistory(taskId, activeCandidate.candidate_id)
          .then((hist) => setHistory(Array.isArray(hist) ? hist : []))
          .catch(() => {});
      }

      setConfirmAction(null);
      setReviewNote('');
      setRequestId('');
    } catch (err) {
      // Staleness / Concurrency 409 (T17)
      if (err.status === 409) {
        toastRef.current.error('The review candidate has changed or has already been reviewed.');
        // Refresh authoritative candidate data, do NOT auto retry
        if (taskId && activeCandidate.candidate_id) {
          getAgentReviewCandidate(taskId, activeCandidate.candidate_id)
            .then((fresh) => {
              setSelectedCandidateDetail(fresh);
              setCandidates((prev) =>
                prev.map((c) => (c.candidate_id === fresh.candidate_id ? fresh : c)),
              );
            })
            .catch(() => {});
        }
        setConfirmAction(null);
      } else if (err.status === 422) {
        // Validation / Unsupported FACT promotion / Provenance failure 422 (T18)
        toastRef.current.error(`审核验证失败：${err.data?.detail || err.message}`);
      } else {
        // Other errors (404, 503, network) (T19)
        toastRef.current.error(`审核提交失败：${err.data?.detail || err.message}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className={`flex flex-col border-t border-slate-200/60 dark:border-slate-700/60 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm ${className}`}
      data-testid="agent-review-panel"
    >
      {/* Header Bar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200/40 dark:border-slate-800/40 shrink-0">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-primary-500" />
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-slate-200">
            Agent Analyst Review
          </h2>
          <Badge variant={pendingCount > 0 ? 'yellow' : 'gray'} size="sm">
            {pendingCount} 待审核
          </Badge>
          <span className="text-[11px] text-slate-400">总计 {candidates.length}</span>
        </div>

        <div className="flex items-center gap-2">
          {evidenceKey && (
            <button
              type="button"
              onClick={() => setFilterByContext((prev) => !prev)}
              className={`px-2 py-0.5 text-xs rounded-md transition-colors ${
                filterByContext
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300 font-semibold'
                  : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
              }`}
              title="按当前证据/事件过滤候选"
            >
              当前证据关联 ({matchingCandidates.length})
            </button>
          )}

          <Button
            size="sm"
            variant="ghost"
            icon={RefreshCw}
            className="h-7 w-7 p-0"
            onClick={() => fetchCandidates(taskId)}
            loading={loading}
            title="刷新候选队列"
          />

          <button
            type="button"
            onClick={() => setIsCollapsed((prev) => !prev)}
            className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded"
            aria-label={isCollapsed ? '展开审核面板' : '折叠审核面板'}
          >
            {isCollapsed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {/* Main Panel Content (collapsible) */}
      {!isCollapsed && (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row overflow-hidden">
          {/* Left Column: Candidates List / Queue */}
          <div className="w-full md:w-5/12 border-b md:border-b-0 md:border-r border-slate-200/40 dark:border-slate-800/40 flex flex-col min-h-0">
            <div className="p-2 bg-slate-50/60 dark:bg-slate-950/30 text-[11px] text-slate-500 flex justify-between items-center shrink-0">
              <span>{filterByContext ? '上下文相关候选' : '全部任务候选'}</span>
              <span>{visibleCandidates.length} 项</span>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800/40">
              {loading && !candidates.length && (
                <div className="p-4 text-center">
                  <Spinner size="sm" />
                </div>
              )}

              {error && (
                <div className="p-3 text-xs text-rose-600">
                  <AlertTriangle size={14} className="inline mr-1" />
                  加载错误：{error.message}
                </div>
              )}

              {!loading && visibleCandidates.length === 0 && (
                <div className="p-6 text-center text-xs text-slate-400">
                  {filterByContext
                    ? '当前证据上下文无匹配的审核候选'
                    : '当前任务暂无 Agent 调查候选'}
                </div>
              )}

              {visibleCandidates.map((c) => {
                const isSelected = c.candidate_id === selectedCandidateId;
                const epistemicVariant = EPISTEMIC_VARIANTS[c.claim_type] || 'gray';
                const statusVariant = STATUS_VARIANTS[c.review_status] || 'gray';

                return (
                  <button
                    key={c.candidate_id}
                    type="button"
                    onClick={() => setSelectedCandidateId(c.candidate_id)}
                    data-testid={`candidate-item-${c.candidate_id}`}
                    className={`w-full text-left p-3 transition-colors flex flex-col gap-1.5 ${
                      isSelected
                        ? 'bg-primary-50/70 dark:bg-primary-950/30 border-l-2 border-primary-500'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Badge size="sm" variant={epistemicVariant}>
                          {c.claim_type}
                        </Badge>
                        <Badge size="sm" variant={statusVariant}>
                          {c.review_status}
                        </Badge>
                        <Badge
                          size="sm"
                          variant={GROUNDING_VARIANTS[c.grounding_status] || 'gray'}
                        >
                          {c.grounding_status}
                        </Badge>
                      </div>
                      <span className="text-[10px] font-mono text-slate-400">
                        r{c.source_revision}
                      </span>
                    </div>

                    <p className="text-xs text-slate-700 dark:text-slate-200 line-clamp-2 leading-relaxed">
                      {c.content}
                    </p>

                    <div className="flex items-center justify-between text-[10px] text-slate-400 mt-0.5">
                      <span className="font-mono truncate max-w-[150px]">{c.candidate_id}</span>
                      <span>{c.created_at ? c.created_at.slice(11, 19) : ''}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Right Column: Selected Candidate Details & Actions */}
          <div className="w-full md:w-7/12 flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
            {detailLoading && (
              <div className="p-8 text-center">
                <Spinner size="md" />
              </div>
            )}

            {!detailLoading && !activeCandidate && (
              <div className="m-auto text-center p-8 text-xs text-slate-400">
                从左侧选择一个调查候选进行详细研判与审核。
              </div>
            )}

            {!detailLoading && activeCandidate && (
              <>
                {/* Epistemic Alert for HYPOTHESIS (T06, T16) */}
                {activeCandidate.claim_type === 'HYPOTHESIS' && (
                  <div
                    className="rounded-xl border border-purple-300 bg-purple-50 dark:border-purple-800/50 dark:bg-purple-950/20 p-3 text-xs text-purple-800 dark:text-purple-300 flex items-start gap-2"
                    data-testid="hypothesis-epistemic-warning"
                  >
                    <Info size={16} className="shrink-0 mt-0.5" />
                    <div>
                      <span className="font-semibold">推测性假说（HYPOTHESIS）：</span>
                      This is a hypothesis, not a verified fact.
                      接受此假说仅确认其作为调查线索的合理性，系统绝不会将其自动晋升为确凿事实（FACT）。
                    </div>
                  </div>
                )}

                {/* Candidate Overview Card */}
                <div className="rounded-xl border border-slate-200/60 dark:border-slate-800/60 p-3.5 bg-slate-50/50 dark:bg-slate-900/30 flex flex-col gap-2">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <Badge
                        size="md"
                        variant={EPISTEMIC_VARIANTS[activeCandidate.claim_type] || 'gray'}
                      >
                        {activeCandidate.claim_type}
                      </Badge>
                      <Badge
                        size="md"
                        variant={STATUS_VARIANTS[activeCandidate.review_status] || 'gray'}
                      >
                        {activeCandidate.review_status}
                      </Badge>
                      <Badge
                        size="md"
                        variant={GROUNDING_VARIANTS[activeCandidate.grounding_status] || 'gray'}
                      >
                        {activeCandidate.grounding_status}
                      </Badge>
                    </div>

                    <span className="font-mono text-xs text-slate-400">
                      Rev {activeCandidate.source_revision}
                    </span>
                  </div>

                  <div className="text-[11px] font-mono text-slate-500 break-all">
                    ID: {activeCandidate.candidate_id}
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 break-all">
                    Hash: {activeCandidate.candidate_hash}
                  </div>
                </div>

                {/* Safe Claim / Content Rendering (T34) */}
                <section>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                    Claim Content
                  </h3>
                  <div
                    className="p-3 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/50 dark:border-slate-800/50 text-sm leading-relaxed text-slate-800 dark:text-slate-200 whitespace-pre-wrap select-text"
                    data-testid="candidate-full-content"
                  >
                    {activeCandidate.content}
                  </div>
                </section>

                {/* Evidence References (T08, T09) */}
                <section>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                    Evidence Provenance References
                  </h3>
                  {activeCandidate.evidence_refs && activeCandidate.evidence_refs.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {activeCandidate.evidence_refs.map((ref) => (
                        <button
                          key={ref}
                          type="button"
                          onClick={() => onTraceEvidence?.(ref)}
                          data-testid={`evidence-ref-${ref}`}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-primary-200 dark:border-primary-800/60 bg-primary-50/50 dark:bg-primary-950/20 text-xs font-mono text-primary-700 dark:text-primary-300 hover:bg-primary-100 dark:hover:bg-primary-900/40 transition-colors"
                          title="在工作台查看该证据详情"
                        >
                          <FileText size={12} />
                          {ref}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div
                      className="p-2.5 rounded-lg border border-amber-200 bg-amber-50/40 text-xs text-amber-700 dark:border-amber-900/30 dark:bg-amber-950/10 dark:text-amber-300 italic"
                      data-testid="evidence-unavailable-notice"
                    >
                      EVIDENCE_UNAVAILABLE (无关联证据引用)
                    </div>
                  )}
                </section>

                {/* Reviewer Authority Boundary Disclosure (T30) */}
                <div
                  className="rounded-lg border border-slate-200 dark:border-slate-800 p-2.5 bg-slate-50 dark:bg-slate-900/40 text-[11px] text-slate-500 flex items-center justify-between"
                  data-testid="reviewer-authority-notice"
                >
                  <div className="flex items-center gap-1.5">
                    <User size={13} className="text-slate-400" />
                    <span>
                      Reviewer:{' '}
                      <strong className="text-slate-700 dark:text-slate-300">
                        {declaredReviewer}
                      </strong>
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-400">
                    [REVIEWER_AUTHENTICATION_LIMITATION: caller-declared identity in local mode]
                  </span>
                </div>

                {/* Explicit Review Actions (T10, T11, T12) */}
                {activeCandidate.review_status === 'review_pending' && !confirmAction && (
                  <div className="mt-auto pt-2 flex items-center gap-3">
                    <Button
                      size="sm"
                      variant="success"
                      icon={CheckCircle2}
                      onClick={() => openConfirmation('accepted')}
                      data-testid="btn-accept-candidate"
                    >
                      接受 (Accept)
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      icon={CircleX}
                      onClick={() => openConfirmation('rejected')}
                      data-testid="btn-reject-candidate"
                    >
                      拒绝 (Reject)
                    </Button>
                  </div>
                )}

                {/* Explicit Confirmation Dialog / Section (T11, T12, T13, T20, T21, T22) */}
                {confirmAction && (
                  <div
                    className={`rounded-xl border p-4 flex flex-col gap-3 ${
                      confirmAction === 'accepted'
                        ? 'border-emerald-300 bg-emerald-50/40 dark:border-emerald-800 dark:bg-emerald-950/20'
                        : 'border-rose-300 bg-rose-50/40 dark:border-rose-800 dark:bg-rose-950/20'
                    }`}
                    data-testid="review-confirmation-dialog"
                  >
                    <div className="flex items-center gap-2">
                      <ShieldAlert
                        size={18}
                        className={
                          confirmAction === 'accepted' ? 'text-emerald-600' : 'text-rose-600'
                        }
                      />
                      <h4 className="text-sm font-bold text-slate-900 dark:text-white">
                        确认显式审核决策：{confirmAction === 'accepted' ? '接受候选' : '拒绝候选'}
                      </h4>
                    </div>

                    <div className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
                      <div>
                        候选类型：<strong>{activeCandidate.claim_type}</strong> (
                        {activeCandidate.target_type})
                      </div>
                      <div>
                        候选标识：<span className="font-mono">{activeCandidate.candidate_id}</span>
                      </div>
                      <div>
                        版本哈希：
                        <span className="font-mono text-[10px]">
                          {activeCandidate.candidate_hash}
                        </span>
                      </div>
                      {activeCandidate.claim_type === 'HYPOTHESIS' && (
                        <div className="font-semibold text-purple-700 dark:text-purple-300 mt-1">
                          注意：接受推测（HYPOTHESIS）不会将其晋升为 FACT。
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        审核批注（可选，将持久化至不可变审核日志）：
                      </label>
                      <textarea
                        rows={2}
                        value={reviewNote}
                        onChange={(e) => setReviewNote(e.target.value)}
                        placeholder="请输入分析员审核意见或判定依据..."
                        className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        data-testid="review-note-input"
                      />
                    </div>

                    <div className="text-[10px] font-mono text-slate-400">
                      Request ID: {requestId}
                    </div>

                    <div className="flex items-center gap-2 pt-1">
                      <Button
                        size="sm"
                        variant={confirmAction === 'accepted' ? 'success' : 'danger'}
                        loading={submitting}
                        disabled={submitting}
                        onClick={handleSubmitReview}
                        data-testid="btn-confirm-review-decision"
                      >
                        {confirmAction === 'accepted' ? '确认接受 (Confirm Accept)' : '确认拒绝 (Confirm Reject)'}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={submitting}
                        onClick={cancelConfirmation}
                      >
                        取消
                      </Button>
                    </div>
                  </div>
                )}

                {/* Review History / Provenance (T29) */}
                <section className="pt-2 border-t border-slate-200/50 dark:border-slate-800/50">
                  <div className="flex items-center gap-1.5 mb-2">
                    <History size={14} className="text-slate-400" />
                    <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Authoritative Review History ({history.length})
                    </h3>
                  </div>

                  {historyLoading && (
                    <div className="p-2 text-center">
                      <Spinner size="xs" />
                    </div>
                  )}

                  {!historyLoading && history.length === 0 && (
                    <div className="text-xs text-slate-400 italic">暂无历史审核记录。</div>
                  )}

                  {!historyLoading && history.length > 0 && (
                    <div className="space-y-2">
                      {history.map((h) => (
                        <div
                          key={h.review_id}
                          className="rounded-lg border border-slate-200/40 dark:border-slate-800/40 p-2.5 text-xs bg-slate-50/40 dark:bg-slate-900/20"
                          data-testid={`history-item-${h.review_id}`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <Badge
                              size="sm"
                              variant={h.decision === 'accepted' ? 'green' : 'red'}
                            >
                              {h.decision}
                            </Badge>
                            <span className="text-[10px] text-slate-400">
                              <Clock3 size={10} className="inline mr-0.5 -mt-0.5" />
                              {h.created_at}
                            </span>
                          </div>
                          <div className="mt-1 text-[11px] text-slate-600 dark:text-slate-300">
                            审核人：<span className="font-mono">{h.reviewer}</span>
                          </div>
                          {h.note && (
                            <p className="mt-1 text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-950 p-1.5 rounded border border-slate-200/30 text-[11px]">
                              {h.note}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
