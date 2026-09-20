import { useEffect, useState } from 'react';
import { ArrowLeft, CheckCircle2, CircleX, Clock3, RefreshCw } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import { acceptEventClaim, getEffectiveEventClaims, rejectEventClaim, reviewInvestigationEvent } from '../../../services/investigationService';
import ClaimList from './ClaimList';
import useSemanticEventAnalysis from '../hooks/useSemanticEventAnalysis';
import { useFeatures } from '../../../hooks/useFeatures';
import { REVIEW_STATUS, formatTimestamp } from '../utils/investigationConstants';

// 事件向判定（事件评审 / 语义版本评审 / Claim 评审）在后端 workbench 契约中
// 是 409 桩（"not part of the canonical local contract"）。按钮保留、先隐藏，
// 待后端契约解禁后把此开关置 true 即可整体恢复。
const EVENT_REVIEW_ENABLED = false;

export default function EventAnalysisPanel({ taskId, event, onRefresh, onTraceClaim, onTraceEvidence, onBackToFile }) {
  const [includePending, setIncludePending] = useState(false);
  // MVP (mvp-phase1-acceptance §4.4): LLM re-summary actions are trimmed.
  const { workbench_llm_enabled: workbenchLlmEnabled } = useFeatures();
  const [claims, setClaims] = useState([]);
  const [claimError, setClaimError] = useState(null);
  const { versions, job, loading: refreshing, error, start, accept, reject } = useSemanticEventAnalysis(taskId, event, onRefresh);
  useEffect(() => {
    let active = true;
    setClaims([]); setClaimError(null);
    const versionId = event?.semantic_version_id;
    if (!taskId || !event?.id || !versionId) return undefined;
    getEffectiveEventClaims(taskId, event.id)
      .then((response) => { if (active) setClaims(response.claims || []); })
      .catch((err) => { if (active) setClaimError(err); });
    return () => { active = false; };
  }, [taskId, event?.id, event?.semantic_version_id]);

  if (!event) return <div className="p-8 text-center text-sm text-slate-500">选择中间时间线中的 Investigation Event 查看详情。</div>;
  const status = REVIEW_STATUS[event.review_status] || REVIEW_STATUS.draft;
  const pendingVersion = versions.find((version) => version.status === 'review_pending');
  const pendingStale = event.pending_semantic_stale || (pendingVersion && Number(pendingVersion.source_revision) !== Number(event.semantic_revision));
  const review = async (next) => { await reviewInvestigationEvent(taskId, event.id, next); onRefresh?.(); };
  return (
    <div className="p-5 space-y-5 overflow-y-auto h-full">
      <div>
        {onBackToFile && (
          <button type="button" onClick={onBackToFile} data-testid="back-to-file-workbench" className="mb-2 inline-flex items-center gap-1 text-xs font-semibold text-primary-600 hover:text-primary-500 dark:text-primary-300">
            <ArrowLeft size={12} /> 返回文件工作台
          </button>
        )}
        <div className="flex items-center gap-2"><Badge variant={status.variant}>{status.label}</Badge><span className="text-xs text-slate-400">{event.source}</span>{event.semantic_source === 'accepted' && <Badge variant="green">已接受语义</Badge>}</div>
        <h2 className="mt-2 text-xl font-bold text-slate-900 dark:text-white">{event.effective_title || event.title}</h2>
        <div className="mt-1 text-xs text-slate-500 inline-flex items-center gap-1"><Clock3 size={13} />{formatTimestamp(event.start_time)} – {formatTimestamp(event.end_time)}</div>
      </div>
      <section><h3 className="text-sm font-semibold mb-2">事件总结</h3><p className="text-sm leading-6 text-slate-600 dark:text-slate-300 whitespace-pre-wrap">{event.effective_summary || event.summary || '暂无总结'}</p></section>
      <section><h3 className="text-sm font-semibold mb-2">证据构成</h3><div className="grid grid-cols-4 gap-2 text-center text-xs">{['primary','supporting','context','contradicting'].map((key) => <div key={key} className="rounded-xl bg-slate-100 dark:bg-slate-800 p-2"><div className="text-lg font-semibold">{event.evidence_counts?.[key] || 0}</div>{key}</div>)}</div></section>
      {workbenchLlmEnabled && Boolean(event.needs_refresh) && <div className="rounded-xl border border-amber-300 bg-amber-50 dark:bg-amber-950/20 p-3 text-sm text-amber-700"><RefreshCw size={14} className="inline mr-1" />关联证据已有新的二次分析，该调查事件可能需要重新总结。<div className="mt-3 flex items-center gap-3"><Button size="sm" icon={RefreshCw} loading={refreshing} onClick={() => start({ include_related_evidence: true, include_review_pending_analyses: includePending }).catch(() => {})}>重新总结事件</Button><label className="text-xs"><input type="checkbox" className="mr-1" checked={includePending} onChange={(e) => setIncludePending(e.target.checked)} />包含未确认分析</label></div>{job && <div className="mt-2 text-xs">{job.status} · {job.progress || 0}%</div>}</div>}
      {error && <div className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">操作失败：{error.message}</div>}
      {pendingVersion && <section className={`rounded-xl border p-4 ${pendingStale ? 'border-amber-300 bg-amber-50/50 dark:bg-amber-950/20' : 'border-violet-200 bg-violet-50/50 dark:bg-violet-950/20'}`}><div className="flex items-center gap-2"><Badge variant="yellow">{pendingStale ? '已过期待审核' : '待审核'}</Badge><strong>语义版本 v{pendingVersion.version}</strong></div><h3 className="mt-3 font-semibold">{pendingVersion.title}</h3><p className="mt-2 text-sm whitespace-pre-wrap">{pendingVersion.summary}</p><p className="mt-2 text-xs text-slate-500">输入证据 {JSON.parse(pendingVersion.input_evidence_refs || '[]').length} 项</p>{EVENT_REVIEW_ENABLED && !pendingStale && <div className="mt-3 flex gap-2"><Button size="sm" variant="success" onClick={() => accept(pendingVersion.id).catch(() => {})}>接受语义版本</Button><Button size="sm" variant="danger" onClick={() => reject(pendingVersion.id).catch(() => {})}>拒绝</Button></div>}</section>}
      {event.semantic_version_id && event.effective_semantic_valid && <section><h3 className="text-sm font-semibold mb-2">Event Claims</h3>{claimError && <p className="text-xs text-rose-600">Claims 加载失败：{claimError.message}</p>}<ClaimList claims={claims} onTraceClaim={onTraceClaim} onTraceEvidence={onTraceEvidence} canReview={EVENT_REVIEW_ENABLED && event.semantic_source === 'accepted' && !event.pending_semantic_stale} onAccept={async (claimId) => { await acceptEventClaim(taskId, event.id, event.semantic_version_id, claimId); onRefresh?.(); }} onReject={async (claimId) => { await rejectEventClaim(taskId, event.id, event.semantic_version_id, claimId); onRefresh?.(); }} /></section>}
      {EVENT_REVIEW_ENABLED && <div className="flex flex-wrap gap-2"><Button size="sm" variant="success" icon={CheckCircle2} onClick={() => review('confirmed').catch(() => {})}>确认事件</Button><Button size="sm" variant="secondary" icon={RefreshCw} onClick={() => review('review_pending').catch(() => {})}>标记待复核</Button><Button size="sm" variant="danger" icon={CircleX} onClick={() => review('rejected').catch(() => {})}>排除事件</Button></div>}
    </div>
  );
}
