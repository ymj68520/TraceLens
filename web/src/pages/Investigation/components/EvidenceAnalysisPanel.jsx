import { useMemo, useState } from 'react';
import { BrainCircuit, CheckCircle2, CircleX, Clock3, FileText, RotateCw } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import {
  acceptAnalysis,
  bindReportEvidenceAnalysis,
  pollAnalysisJob,
  rejectAnalysis,
  startEvidenceAnalysis,
} from '../../../services/investigationService';
import useEvidenceAnalysis from '../hooks/useEvidenceAnalysis';
import useInitialAnalysisTranslation, { initialAnalysisText } from '../hooks/useInitialAnalysisTranslation';
import { useFeatures } from '../../../hooks/useFeatures';
import { ANALYSIS_STATUS, formatTimestamp, parseJson } from '../utils/investigationConstants';
import AnalystNoteEditor from './AnalystNoteEditor';
import AnalysisVersionList from './AnalysisVersionList';
import ClaimList from './ClaimList';
import LocalKnowledgeGraph from './LocalKnowledgeGraph';
import ReportEvidenceJudgment from '../../../components/investigation/ReportEvidenceJudgment';
import { getFrozenAndroidArtifact } from '../../../services/evidenceIntakeService';

function Section({ title, hint, children }) {
  return <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4"><h3 title={hint} className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>{children}</section>;
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
export default function EvidenceAnalysisPanel({ taskId, eventId, evidenceKey, onEvidenceChanged, fileContext, readOnly = false }) {
  const file = fileContext?.file || null;
  const { detail, versions, graph, loading, error, refresh } = useEvidenceAnalysis(taskId, evidenceKey);
  // MVP (mvp-phase1-acceptance §4.4): the secondary-analysis action is trimmed;
  // metadata/notes/report-evidence/history stay.
  const { secondary_analysis_enabled: secondaryAnalysisEnabled } = useFeatures();
  const [selectedVersionId, setSelectedVersionId] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [job, setJob] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const [frozenRow, setFrozenRow] = useState(null);
  const [frozenError, setFrozenError] = useState('');
  const [bindingId, setBindingId] = useState('');
  const initialAnalysis = detail?.snapshot?.payload || detail?.snapshot || {};
  const androidEvidence = detail?.evidence_type === 'android_artifact';
  const initialSourceText = initialAnalysisText(initialAnalysis);
  const translatedAnalysis = useInitialAnalysisTranslation(taskId, evidenceKey, initialSourceText);

  const version = useMemo(() => (
    versions.find((v) => v.id === selectedVersionId)
    || detail?.accepted_analysis
    || detail?.pending_analysis
    || detail?.latest_analysis
    || versions[0]
  ), [detail, versions, selectedVersionId]);
  const acceptedVersions = versions.filter((item) => item.status === 'accepted');
  const selectedBinding = bindingId || detail?.report_evidence?.analysis_id || acceptedVersions[0]?.id || '';
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
        <div className="text-xs uppercase tracking-wide text-slate-400">{androidEvidence ? 'AndroidAnalyzer 派生记录' : detail.evidence_type === 'event_cluster' ? 'Event Cluster Evidence' : 'File Evidence'}</div>
        <h2 className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{detail.title}</h2>
        <p className="mt-1 text-xs text-slate-500 break-all">{androidEvidence || detail.evidence_type === 'event_cluster' ? detail.evidence_key : detail.file_path}</p>
      </div>

      <Section title="1. 证据信息">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          {androidEvidence ? <>
            <dt className="text-slate-500">结果版本</dt><dd className="break-all">{initialAnalysis.result_set_id}</dd>
            <dt className="text-slate-500">工件/记录 ID</dt><dd>{initialAnalysis.artifact_kind} / {initialAnalysis.record_id}</dd>
            <dt className="text-slate-500">记录 SHA-256</dt><dd className="break-all">{initialAnalysis.record_hash}</dd>
            <dt className="text-slate-500">时间单位/时区</dt><dd>{initialAnalysis.timestamp_unit || '未知'} / {initialAnalysis.timestamp_timezone || '未知'}</dd>
          </> : detail.evidence_type === 'event_cluster' ? <>
            <dt className="text-slate-500">事件类型</dt><dd>{detail.metadata?.event_type || '—'}</dd>
            <dt className="text-slate-500">事件数</dt><dd>{detail.metadata?.event_count ?? '—'}</dd>
            <dt className="text-slate-500">采样数</dt><dd>{detail.metadata?.sampled_event_count ?? '—'}</dd>
            <dt className="text-slate-500">时间窗口</dt><dd>{detail.metadata?.time_window ?? '—'}</dd>
            <dt className="text-slate-500">簇快照摘要 (SHA-256)</dt><dd className="break-all">{detail.snapshot?.source_hash || '—'}</dd>
          </> : <>
            <dt className="text-slate-500">MD5</dt><dd className="break-all">{detail.md5 || '—'}</dd>
            <dt className="text-slate-500">文件大小</dt><dd>{detail.size != null ? `${detail.size} 字节` : '—'}</dd>
          </>}
          <dt className="text-slate-500">证据时间</dt><dd>{formatTimestamp(detail.timestamp)}</dd>
          <dt className="text-slate-500">快照时间</dt><dd>{formatTimestamp(detail.snapshot?.captured_at)}</dd>
        </dl>
      </Section>

      {androidEvidence && <Section title="冻结记录与来源核对">
        <p className="text-xs text-amber-800">这是 AndroidAnalyzer 的单条派生解析结果；候选文件不证明原始数据库行或 WAL 位置。来源与覆盖限制以冻结快照为准。</p>
        <pre className="mt-2 whitespace-pre-wrap break-all rounded-lg bg-slate-50 p-2 text-xs">{JSON.stringify({record: initialAnalysis.record_fields, provenance: initialAnalysis.provenance, coverage: initialAnalysis.coverage, warnings: initialAnalysis.warnings}, null, 2)}</pre>
        <Button size="sm" onClick={async () => {
          setFrozenError('');
          try { setFrozenRow(await getFrozenAndroidArtifact(taskId, initialAnalysis.result_set_id, initialAnalysis.artifact_kind, initialAnalysis.record_id)); }
          catch (err) { setFrozenError(err?.data?.detail || err?.message || '冻结结果不可用'); }
        }}>查看同一冻结结果版本的原记录</Button>
        {frozenError && <p role="alert" className="text-xs text-rose-700">{frozenError}</p>}
        {frozenRow && <pre className="mt-2 whitespace-pre-wrap break-all text-xs">{JSON.stringify({record: frozenRow.record, source: frozenRow.source, record_hash: frozenRow.record_hash}, null, 2)}</pre>}
      </Section>}

      <Section title="2. 初次分析" hint="来自已保存的只读分析快照，中文译文仅辅助阅读。">
        {!initialSourceText ? <p className="text-sm text-slate-500">暂无分析描述</p> : <>
          {translatedAnalysis.loading ? <p role="status" className="text-sm text-slate-500">正在本地生成中文译文，请稍候……</p> : <>
            {translatedAnalysis.error && <div className="mb-2"><Badge variant="gray" size="sm" title="中文阅读服务未返回译文，当前保留分析原文，未改写证据快照。">分析原文</Badge></div>}
            <p className="text-sm leading-6 whitespace-pre-wrap" lang={translatedAnalysis.translated ? 'zh-CN' : undefined} data-testid="initial-analysis-description">{translatedAnalysis.text || initialSourceText}</p>
          </>}
          {(translatedAnalysis.translated || translatedAnalysis.loading) && <>
            {translatedAnalysis.translated && <div className="mt-3"><Badge variant="blue" size="sm" title="本地机器译文仅辅助阅读，不替代分析快照或原始证据。">中文阅读</Badge></div>}
            <details className="mt-3 text-xs text-slate-500">
              <summary className="cursor-pointer">查看分析原文</summary>
              <p className="mt-2 whitespace-pre-wrap break-words" lang="en">{initialSourceText}</p>
            </details>
          </>}
        </>}
      </Section>

      <Section title="3. 调查备注" hint="调查上下文与个人分析思路，不作为证据事实。">
        <AnalystNoteEditor taskId={taskId} evidenceKey={evidenceKey} initialValue={detail.analyst_note?.content} onSaved={refresh} readOnly={readOnly} />
      </Section>

      <Section title="4. 二次分析">
        {secondaryAnalysisEnabled && <Button icon={BrainCircuit} loading={analyzing} disabled={readOnly || analyzing} onClick={analyze}>执行二次分析</Button>}
        {secondaryAnalysisEnabled && job && <span className="ml-3 text-xs text-slate-500">{job.status} · {job.progress || 0}%</span>}
        {!version && <p className="text-xs text-slate-500">暂无分析记录</p>}
        {!secondaryAnalysisEnabled && version && <Badge variant="gray" size="sm" title="已保存的二次分析版本">历史分析</Badge>}
        {actionError && <p className="mt-3 text-sm text-rose-600">操作失败：{actionError?.data?.detail || actionError.message}</p>}
        {version && <div className="mt-4 rounded-xl bg-slate-50 dark:bg-slate-900/40 p-4">
          <div className="flex items-center gap-2"><strong>v{version.version}</strong><Badge variant={status.variant}>{status.label}</Badge>{version.grounding_status && <Badge variant={version.grounding_status === 'valid' ? 'green' : 'yellow'} title="Grounded 仅表示 Evidence ID 真实存在，不代表事实已被充分证明。">{version.grounding_status}</Badge>}</div>
          <p className="mt-3 text-sm leading-6 whitespace-pre-wrap">{version.description || version.summary}</p>
          {!!warnings.length && <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/20 p-3 text-xs text-amber-700"><div className="font-semibold">落地警告</div>{warnings.map((w) => <div key={w}>• {w}</div>)}{version.grounding_status === 'partially_grounded' && <label className="mt-2 flex gap-2"><input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />我已人工复核并确认接受这些警告</label>}</div>}
          {version.status === 'review_pending' && <div className="mt-3 flex gap-2"><Button size="sm" variant="success" icon={CheckCircle2} disabled={readOnly || (version.grounding_status === 'partially_grounded' && !acknowledge)} onClick={accept}>接受该分析</Button><Button size="sm" variant="danger" icon={CircleX} disabled={readOnly} onClick={reject}>拒绝</Button></div>}
        </div>}
      </Section>

      <Section title="5. 结论引用"><ClaimList claims={version?.claims || []} /></Section>
      <Section title="6. 关联图谱">{androidEvidence ? <p className="text-xs text-slate-500">暂无已核实的关联关系</p> : <LocalKnowledgeGraph graph={graph} />}</Section>
      <Section title="7. 报告证据"><ReportEvidenceJudgment taskId={taskId} evidenceKey={evidenceKey} status={detail.report_evidence?.report_status || null} readOnly={readOnly} onChanged={async () => { await refresh(); onEvidenceChanged?.(); }} /></Section>
      {androidEvidence && acceptedVersions.length > 0 && <Section title="报告引用的分析版本（显式绑定）">
        <p className="mb-2 text-xs text-slate-600">只有已接受的同一证据分析可绑定；新分析被接受不会自动替换本报告的旧绑定。</p>
        <p className="mb-2 text-xs">当前绑定：{detail.report_evidence?.analysis_id || '无（仅引用冻结工件，不代表 AI 结论已采纳）'}</p>
        <div className="flex flex-wrap items-center gap-2">
          <select className="rounded-lg border border-slate-300 p-2 text-xs" value={selectedBinding}
            onChange={(event) => setBindingId(event.target.value)} aria-label="选择已接受分析版本">
            {acceptedVersions.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.id}</option>)}
          </select>
          <Button size="sm" disabled={readOnly || !detail.report_evidence || !selectedBinding || selectedBinding === detail.report_evidence.analysis_id}
            onClick={async () => {
              setActionError(null);
              try { await bindReportEvidenceAnalysis(taskId, evidenceKey, selectedBinding); await refresh(); onEvidenceChanged?.(); }
              catch (err) { setActionError(err); }
            }}>绑定该分析版本</Button>
        </div>
        {!detail.report_evidence && <p className="mt-2 text-xs text-amber-700">请先把这条工件判定为正文或附件证据，再显式绑定分析。</p>}
      </Section>}
      <Section title="8. 分析历史"><AnalysisVersionList versions={versions} selectedId={version?.id} onSelect={setSelectedVersionId} /></Section>
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
