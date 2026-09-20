import { useMemo, useState } from 'react';
import { CheckCircle2, CircleX, Clock3, FileText, RotateCw } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import ReportEvidenceJudgment from '../../../components/investigation/ReportEvidenceJudgment';
import AnalystNoteEditor from './AnalystNoteEditor';
import useEvidenceAnalysis from '../hooks/useEvidenceAnalysis';
import { useFeatures } from '../../../hooks/useFeatures';
import { ANALYSIS_STATUS, formatTimestamp, parseJson } from '../utils/investigationConstants';

const MACB_CHIPS = [
  { key: 'crtime', label: '创建' },
  { key: 'mtime', label: '修改' },
  { key: 'atime', label: '访问' },
  { key: 'ctime', label: '变更' },
];

/**
 * 右栏默认面板：以文件为核心的工作台。
 *
 * 判定（报告证据三态）复用全局唯一的 ReportEvidenceJudgment 组件（R1 真相源，
 * 与 /analysis-center 证据判定页同一写入路径）；证据分析与笔记沿 evidence_key
 * 维度；调查事件在此降级为佐证引用（点击进入事件面板）。
 */
export default function FileWorkbenchPanel({ taskId, file, events = [], onSelectEvent, onEvidenceChanged }) {
  const { workbench_llm_enabled: workbenchLlmEnabled } = useFeatures();
  const evidenceKey = file ? `file:${file.path}` : null;
  const { detail, versions, loading, error, refresh } = useEvidenceAnalysis(taskId, evidenceKey);
  const [acknowledge, setAcknowledge] = useState(false);
  const [actionError, setActionError] = useState(null);

  // 优先展示已接受的分析，其次待审版本——与证据分析面板同一优先序。
  const version = useMemo(() => (
    detail?.accepted_analysis
    || detail?.pending_analysis
    || detail?.latest_analysis
    || versions[0]
  ), [detail, versions]);
  const warnings = parseJson(version?.grounding_warnings, []);
  const status = version ? (ANALYSIS_STATUS[version.status] || ANALYSIS_STATUS.review_pending) : null;

  const fileEvents = useMemo(() => {
    if (!file) return [];
    const byId = new Map(events.map((event) => [event.id, event]));
    return (file.event_ids || []).map((id) => byId.get(id)).filter(Boolean);
  }, [file, events]);

  const accept = async () => {
    setActionError(null);
    try {
      await import('../../../services/investigationService').then(({ acceptAnalysis }) =>
        acceptAnalysis(taskId, version.id, acknowledge)
      );
      await refresh();
      onEvidenceChanged?.();
    } catch (err) { setActionError(err); }
  };
  const reject = async () => {
    setActionError(null);
    try {
      await import('../../../services/investigationService').then(({ rejectAnalysis }) =>
        rejectAnalysis(taskId, version.id)
      );
      await refresh();
      onEvidenceChanged?.();
    } catch (err) { setActionError(err); }
  };

  if (!file) {
    return <div className="p-8 text-center text-sm text-slate-500">在中间时间线选择一个文件节点进行证据判定。</div>;
  }

  return (
    <div className="h-full overflow-y-auto p-5 space-y-4" data-testid="file-workbench-panel">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-400">File Evidence · 文件工作台</div>
        <h2 className="mt-1 text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
          <FileText size={18} className="text-primary-500 shrink-0" />
          <span className="break-all">{file.name || file.path}</span>
        </h2>
        <p className="mt-1 text-xs text-slate-500 break-all">{file.path}</p>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
          {MACB_CHIPS.map(({ key, label }) => {
            const value = Number(file[key]);
            if (!Number.isFinite(value) || value <= 0) return null;
            return <span key={key}>{label} {formatTimestamp(value)}</span>;
          })}
        </div>
      </div>

      <section className="rounded-xl border border-purple-200 dark:border-purple-900/40 bg-purple-50/40 dark:bg-slate-900/40 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">报告证据判定</h3>
        {loading ? <Spinner size="sm" /> : (
          <ReportEvidenceJudgment
            taskId={taskId}
            evidenceKey={evidenceKey}
            status={detail?.report_evidence?.report_status || null}
            onChanged={async () => { await refresh(); onEvidenceChanged?.(); }}
          />
        )}
      </section>

      <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">初始分析（快照，只读）</h3>
        {loading ? <Spinner size="sm" /> : (
          <p className="text-sm leading-6 whitespace-pre-wrap text-slate-600 dark:text-slate-300">
            {detail?.snapshot?.initial_description || '初次流水线未生成描述。'}
          </p>
        )}
      </section>

      <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">二次分析评审</h3>
        {workbenchLlmEnabled ? null : <p className="text-xs text-slate-500">本验收版本未启用 LLM 二次分析。</p>}
        {loading ? <Spinner size="sm" /> : error ? (
          <p className="text-sm text-rose-600">加载证据详情失败：{error.message}</p>
        ) : version ? (
          <div className="rounded-xl bg-slate-50 dark:bg-slate-900/40 p-4">
            <div className="flex items-center gap-2">
              <strong>v{version.version}</strong>
              <Badge variant={status?.variant}>{status?.label}</Badge>
              {version.grounding_status && (
                <Badge variant={version.grounding_status === 'valid' ? 'green' : 'yellow'}>{version.grounding_status}</Badge>
              )}
            </div>
            <p className="mt-3 text-sm leading-6 whitespace-pre-wrap text-slate-600 dark:text-slate-300">
              {version.description || version.summary || '（无内容）'}
            </p>
            {!!warnings.length && (
              <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/20 p-3 text-xs text-amber-700">
                <div className="font-semibold">Grounding Warning</div>
                {warnings.map((w) => <div key={w}>• {w}</div>)}
                {version.grounding_status === 'partially_grounded' && (
                  <label className="mt-2 flex gap-2">
                    <input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />
                    我已人工复核并确认接受这些警告
                  </label>
                )}
              </div>
            )}
            {version.status === 'review_pending' && (
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="success" icon={CheckCircle2} disabled={version.grounding_status === 'partially_grounded' && !acknowledge} onClick={accept}>接受该分析</Button>
                <Button size="sm" variant="danger" icon={CircleX} onClick={reject}>拒绝</Button>
              </div>
            )}
            {actionError && <p className="mt-3 text-sm text-rose-600">操作失败：{actionError.message}</p>}
          </div>
        ) : (
          <p className="text-xs text-slate-500">该文件暂无二次分析版本。</p>
        )}
      </section>

      {evidenceKey && (
        <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">分析员笔记（调查上下文，不是证据）</h3>
          <AnalystNoteEditor taskId={taskId} evidenceKey={evidenceKey} initialValue={detail?.analyst_note?.content} onSaved={refresh} />
        </section>
      )}

      <section className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
          佐证事件 <span className="text-slate-400 font-normal">{fileEvents.length}</span>
          <span className="ml-2 text-[10px] font-normal text-slate-400">点击进入事件面板</span>
        </h3>
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
      </section>

      <Button size="sm" variant="ghost" icon={RotateCw} onClick={refresh}>刷新详情</Button>
    </div>
  );
}
