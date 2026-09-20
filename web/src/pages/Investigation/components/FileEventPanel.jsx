import { Clock3, FileText } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import EventEvidencePanel from './EventEvidencePanel';
import { REVIEW_STATUS, formatTimestamp } from '../utils/investigationConstants';

const STATUS_DOT = {
  draft: 'bg-slate-400 dark:bg-slate-500',
  review_pending: 'bg-amber-400',
  confirmed: 'bg-emerald-500',
  rejected: 'bg-rose-500',
};

const toUnix = (value) => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
};

const statusKey = (event) => (REVIEW_STATUS[event.review_status] ? event.review_status : 'draft');

const MACB_CHIPS = [
  { key: 'crtime', label: '创建' },
  { key: 'mtime', label: '修改' },
  { key: 'atime', label: '访问' },
  { key: 'ctime', label: '变更' },
];

/**
 * 左栏：以文件为核心。上半部分展示当前时间线文件关联的全部
 * Investigation Events（点击选中，驱动右栏分析工作台）；下半部分保留
 * 原有关联证据面板（当前选中事件的证据、Claim 引用追踪）。
 */
export default function FileEventPanel({ file, events, selectedEventId, onSelectEvent, evidencePanel }) {
  const ordered = [...(events || [])].sort(
    (a, b) => (toUnix(a.start_time) ?? Infinity) - (toUnix(b.start_time) ?? Infinity)
  );

  return (
    <div className="h-full flex flex-col min-h-0" data-testid="file-event-panel">
      <div className="shrink-0 border-b border-slate-200/60 p-3 dark:border-slate-700/50">
        <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">文件关联事件 <span className="text-slate-400 font-normal">{ordered.length}</span></div>
        {file ? (
          <>
            <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs font-medium text-slate-700 dark:text-slate-200">
              <FileText size={12} className="shrink-0 text-primary-500" />
              <span className="truncate" data-testid="file-event-panel-name">{file.name || file.path}</span>
            </div>
            <div className="mt-0.5 break-all font-mono text-[10px] text-slate-400">{file.path}</div>
            <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-slate-400">
              {MACB_CHIPS.map(({ key, label }) => {
                const value = toUnix(file[key]);
                if (value === null) return null;
                return <span key={key}>{label} {formatTimestamp(value)}</span>;
              })}
            </div>
          </>
        ) : (
          <p className="mt-1 text-xs text-slate-400">在中间时间线选择一个文件节点</p>
        )}
      </div>
      <div className="max-h-[38%] shrink-0 overflow-y-auto p-3" data-testid="file-event-list">
        {ordered.length ? (
          <div className="space-y-1">
            {ordered.map((event) => {
              const status = REVIEW_STATUS[event.review_status] || REVIEW_STATUS.draft;
              const selected = event.id === selectedEventId;
              return (
                <button
                  key={event.id}
                  type="button"
                  onClick={() => onSelectEvent?.(event.id)}
                  data-testid={`file-event-${event.id}`}
                  className={`flex w-full items-center gap-2 rounded-xl border px-2 py-1.5 text-left text-xs transition-colors ${selected
                    ? 'border-primary-300 bg-primary-50/60 dark:border-primary-700 dark:bg-primary-950/30'
                    : 'border-transparent hover:border-slate-200 hover:bg-slate-100/70 dark:hover:border-slate-700 dark:hover:bg-slate-800/60'}`}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[statusKey(event)]}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-slate-700 dark:text-slate-200">{event.title || '(未命名事件)'}</span>
                    <span className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-400">
                      <Clock3 size={10} /> {formatTimestamp(toUnix(event.start_time))}
                    </span>
                  </span>
                  <Badge variant={status.variant} size="sm">{status.label}</Badge>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="py-6 text-center text-xs text-slate-500">
            {file ? '该文件暂无关联事件' : '暂无文件'}
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1">{evidencePanel}</div>
    </div>
  );
}
