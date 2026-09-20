import { useMemo, useState } from 'react';
import { BrainCircuit, CheckCircle2, CircleX, Clock3, FileText, RotateCw } from 'lucide-react';
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
import { useFeatures } from '../../../hooks/useFeatures';
import { ANALYSIS_STATUS, formatTimestamp, parseJson } from '../utils/investigationConstants';
import AnalystNoteEditor from './AnalystNoteEditor';
import AnalysisVersionList from './AnalysisVersionList';
import ClaimList from './ClaimList';
import LocalKnowledgeGraph from './LocalKnowledgeGraph';
import ReportEvidenceJudgment from '../../../components/investigation/ReportEvidenceJudgment';

function Section({ title, children }) {
  return <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4"><h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>{children}</section>;
}

// 文件上下文头（点击时间线文件节点时展示）：MACB 四时间与身份信息，
// 与证据详情数据无关，loading 期间也可见。
function FileContextHeader({ file }) {
  const MACB_CHIPS = [
    { key: 'crtime', label: '创建' },
    { key: 'mtime', label: '修改' },
    { key: 'atime', label: '访问' },
    { key: 'ctime', label: '变更' },
  ];
  return (
    <div className="rounded-xl border border-primary-200/60 dark:border-primary-900/40 bg-primary-50/40 dark:bg-slate-900/40 p-4" data-testid="file-context-header">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
        <FileText size={14} className="shrink-0 text-primary-500" />
        <span className="truncate">{file.name || file.path}</span>
      </div>
      <div className="mt-0.5 break-all font-mono text-[10px] text-slate-400">{file.path}</div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
        {MACB_CHIPS.map(({ key, label }) => {
          const value = Number(file[key]);
          if (!Number.isFinite(value) || value <= 0) return null;
          return <span key={key}><Clock3 size={10} className="mr-0.5 -mt-0.5 inline" />{label} {formatTimestamp(value)}</span>;
        })}
      </div>
    </div>
  );
}

// 佐证事件 section（文件上下文）：文件关联的调查事件，点击进入事件面板。
function CorroboratingEventsSection({ file, events = [], onSelectEvent }) {
  const fileEvents = useMemo(() => {
    if (!file) return [];
    const byId = new Map(events.map((event) => [event.id, event]));
    const resolved = (file.event_ids || []).map((id) => byId.get(id)).filter(Boolean);
    return resolved.sort((a, b) => (a.start_time ?? Infinity) - (b.start_time ?? Infinity));
  }, [file, events]);
  return (
    <Section title={`佐证事件 · ${fileEvents.length}`}>
      <p className="mb-2 text-[10px] text-slate-400">点击进入事件面板查看语义总结与 Claim。</p>
      {fileEvents.length ? (
        <div className="space-y-1">
          {fileEvents.map((event) => (
            <button
              key={event.id}
              type="button"
              onClick={() => onSelectEvent?.(event.id)}
              data-testid={`workbench-event-${event.id}`}
              className="flex w-full items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left text-xs transition-colors hover:border-slate-200 hover:bg-slate-100/70 dark:hover:border-slate-700 dark:hover:bg-slate-800/60"
            >
              <Clock3 size={11} className="shrink-0 text-slate-400" />
              <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">{event.effective_title || event.title}</span>
              <span className="shrink-0 text-[10px] text-slate-400">{formatTimestamp(event.start_time)}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-400">该文件暂无关联事件。</p>
      )}
    </Section>
  );
}

/**
 * 证据分析工作台：任务内任意已捕获证据（file: / cluster:）的完整详情与操作。
 *
 * 传 `fileContext`（点击时间线文件节点的入口）时，顶部追加文件身份头、
 * 末尾追加佐证事件 section——功能与关联证据入口完全一致，只是多了文件
 * 上下文。判定（第 7 节）复用全局唯一的 ReportEvidenceJudgment。
 */
export default function EvidenceAnalysisPanel({ taskId, eventId, evidenceKey, onEvidenceChanged, fileContext }) {
  const file = fileContext?.file || null;
  const { detail, versions, graph, loading, error, refresh } = useEvidenceAnalysis(taskId, evidenceKey);
  // MVP (mvp-phase1-acceptance §4.4): the secondary-analysis action is trimmed;
  // metadata/notes/report-evidence/history stay.
  const { workbench_llm_enabled: workbenchLlmEnabled } = useFeatures();
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
      {file && <FileContextHeader file={file} />}
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
        {workbenchLlmEnabled && <Button icon={BrainCircuit} loading={analyzing} disabled={analyzing} onClick={analyze}>执行二次分析</Button>}
        {workbenchLlmEnabled && job && <span className="ml-3 text-xs text-slate-500">{job.status} · {job.progress || 0}%</span>}
        {!workbenchLlmEnabled && <p className="text-xs text-slate-500">本验收版本未启用 LLM 二次分析。</p>}
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
      <Section title="7. Report Evidence"><ReportEvidenceJudgment taskId={taskId} evidenceKey={evidenceKey} status={detail.report_evidence?.report_status || null} onChanged={async () => { await refresh(); onEvidenceChanged?.(); }} /></Section>
      <Section title="8. Analysis History"><AnalysisVersionList versions={versions} selectedId={version?.id} onSelect={setSelectedVersionId} /></Section>
      {file && (
        <CorroboratingEventsSection
          file={file}
          events={fileContext.events}
          onSelectEvent={fileContext.onSelectEvent}
        />
      )}
      <Button size="sm" variant="ghost" icon={RotateCw} onClick={refresh}>刷新详情</Button>
    </div>
  );
}
