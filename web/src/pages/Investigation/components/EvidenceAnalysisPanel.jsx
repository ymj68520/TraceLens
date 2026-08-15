import { useMemo, useState } from 'react';
import { BrainCircuit, CheckCircle2, CircleX, RotateCw } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import {
  acceptAnalysis,
  pollAnalysisJob,
  rejectAnalysis,
  startEvidenceAnalysis,
} from '../../../services/investigationService';
import useEvidenceAnalysis from '../hooks/useEvidenceAnalysis';
import { ANALYSIS_STATUS, formatTimestamp, parseJson } from '../utils/investigationConstants';
import AnalystNoteEditor from './AnalystNoteEditor';
import AnalysisVersionList from './AnalysisVersionList';
import ClaimList from './ClaimList';
import LocalKnowledgeGraph from './LocalKnowledgeGraph';
import ReportEvidenceSelector from './ReportEvidenceSelector';

function Section({ title, children }) {
  return <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4"><h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>{children}</section>;
}

export default function EvidenceAnalysisPanel({ taskId, eventId, evidenceKey, onEvidenceChanged }) {
  const { detail, versions, graph, loading, error, refresh } = useEvidenceAnalysis(taskId, evidenceKey);
  const [selectedVersionId, setSelectedVersionId] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [job, setJob] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [acknowledge, setAcknowledge] = useState(false);

  const version = useMemo(() => (
    versions.find((v) => v.id === selectedVersionId)
    || detail?.accepted_analysis
    || detail?.pending_analysis
    || detail?.latest_analysis
    || versions[0]
  ), [detail, versions, selectedVersionId]);
  const warnings = parseJson(version?.grounding_warnings, []);
  const status = version ? (ANALYSIS_STATUS[version.status] || ANALYSIS_STATUS.review_pending) : null;

  const analyze = async () => {
    setAnalyzing(true); setJob(null); setActionError(null);
    try {
      const result = await startEvidenceAnalysis(taskId, {
        evidence_key: evidenceKey,
        analyst_note: detail?.analyst_note?.content || '',
        event_id: eventId,
        include_case_context: true,
        include_related_evidence: true,
      });
      await pollAnalysisJob(taskId, result.job_id, setJob);
      await refresh();
      onEvidenceChanged?.();
    } catch (err) {
      setActionError(err);
    } finally {
      setAnalyzing(false);
    }
  };

  const accept = async () => {
    setActionError(null);
    try {
      await acceptAnalysis(taskId, version.id, acknowledge);
      await refresh(); onEvidenceChanged?.();
    } catch (err) { setActionError(err); }
  };
  const reject = async () => {
    setActionError(null);
    try {
      await rejectAnalysis(taskId, version.id);
      await refresh(); onEvidenceChanged?.();
    } catch (err) { setActionError(err); }
  };

  if (loading) return <div className="h-full flex items-center justify-center"><Spinner size="lg" /></div>;
  if (error) return <div className="p-6 text-rose-600">加载证据详情失败：{error.message}</div>;
  if (!detail) return null;

  return (
    <div className="h-full overflow-y-auto p-5 space-y-4" data-testid="evidence-analysis-panel">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-400">{detail.evidence_type === 'event_cluster' ? 'Event Cluster Evidence' : 'File Evidence'}</div>
        <h2 className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{detail.title}</h2>
        <p className="mt-1 text-xs text-slate-500 break-all">{detail.evidence_type === 'event_cluster' ? detail.evidence_key : detail.file_path}</p>
      </div>

      <Section title="1. Evidence Metadata">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          {detail.evidence_type === 'event_cluster' ? <>
            <dt className="text-slate-500">Event Type</dt><dd>{detail.metadata?.event_type || '—'}</dd>
            <dt className="text-slate-500">Event Count</dt><dd>{detail.metadata?.event_count ?? '—'}</dd>
            <dt className="text-slate-500">Sampled</dt><dd>{detail.metadata?.sampled_event_count ?? '—'}</dd>
            <dt className="text-slate-500">Time Window</dt><dd>{detail.metadata?.time_window ?? '—'}</dd>
            <dt className="text-slate-500">Cluster Snapshot Digest (SHA-256)</dt><dd className="break-all">{detail.snapshot?.source_hash || '—'}</dd>
          </> : <>
            <dt className="text-slate-500">MD5</dt><dd className="break-all">{detail.md5 || '—'}</dd>
            <dt className="text-slate-500">Size</dt><dd>{detail.size ?? '—'} bytes</dd>
          </>}
          <dt className="text-slate-500">Timestamp</dt><dd>{formatTimestamp(detail.timestamp)}</dd>
          <dt className="text-slate-500">Snapshot captured</dt><dd>{formatTimestamp(detail.snapshot?.captured_at)}</dd>
        </dl>
      </Section>

      <Section title="2. Initial Analysis（快照，只读）">
        <p className="text-sm leading-6 whitespace-pre-wrap">{detail.snapshot?.initial_description || '初次流水线未生成描述。'}</p>
        {detail.snapshot?.initial_summary && <p className="mt-2 text-xs text-slate-500">摘要：{detail.snapshot.initial_summary}</p>}
      </Section>

      <Section title="3. Analyst Note（调查上下文，不是证据）">
        <AnalystNoteEditor taskId={taskId} evidenceKey={evidenceKey} initialValue={detail.analyst_note?.content} onSaved={refresh} />
      </Section>

      <Section title="4. Secondary Analysis">
        <Button icon={BrainCircuit} loading={analyzing} disabled={analyzing} onClick={analyze}>执行二次分析</Button>
        {job && <span className="ml-3 text-xs text-slate-500">{job.status} · {job.progress || 0}%</span>}
        {actionError && <p className="mt-3 text-sm text-rose-600">操作失败：{actionError.message}</p>}
        {version && <div className="mt-4 rounded-xl bg-slate-50 dark:bg-slate-900/40 p-4">
          <div className="flex items-center gap-2"><strong>v{version.version}</strong><Badge variant={status.variant}>{status.label}</Badge>{version.grounding_status && <Badge variant={version.grounding_status === 'valid' ? 'green' : 'yellow'} title="Grounded 仅表示 Evidence ID 真实存在，不代表事实已被充分证明。">{version.grounding_status}</Badge>}</div>
          <p className="mt-3 text-sm leading-6 whitespace-pre-wrap">{version.description || version.summary}</p>
          {!!warnings.length && <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/20 p-3 text-xs text-amber-700"><div className="font-semibold">Grounding Warning</div>{warnings.map((w) => <div key={w}>• {w}</div>)}{version.grounding_status === 'partially_grounded' && <label className="mt-2 flex gap-2"><input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />我已人工复核并确认接受这些警告</label>}</div>}
          {version.status === 'review_pending' && <div className="mt-3 flex gap-2"><Button size="sm" variant="success" icon={CheckCircle2} disabled={version.grounding_status === 'partially_grounded' && !acknowledge} onClick={accept}>接受该分析</Button><Button size="sm" variant="danger" icon={CircleX} onClick={reject}>拒绝</Button></div>}
        </div>}
      </Section>

      <Section title="5. Claims"><ClaimList claims={version?.claims || []} /></Section>
      <Section title="6. Local Investigation Graph"><LocalKnowledgeGraph graph={graph} /></Section>
      <Section title="7. Report Evidence"><ReportEvidenceSelector taskId={taskId} evidenceKey={evidenceKey} value={detail.report_evidence} onChange={async () => { await refresh(); onEvidenceChanged?.(); }} /></Section>
      <Section title="8. Analysis History"><AnalysisVersionList versions={versions} selectedId={version?.id} onSelect={setSelectedVersionId} /></Section>
      <Button size="sm" variant="ghost" icon={RotateCw} onClick={refresh}>刷新详情</Button>
    </div>
  );
}
