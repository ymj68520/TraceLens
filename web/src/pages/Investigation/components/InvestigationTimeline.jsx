import { useEffect, useRef } from 'react';
import { Clock3, Database, FileCheck2 } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Spinner from '../../../components/common/Spinner';
import { REVIEW_STATUS, formatTimestamp } from '../utils/investigationConstants';

const DOT_CLASS = {
  gray: 'bg-slate-400',
  yellow: 'bg-amber-400',
  green: 'bg-emerald-500',
  red: 'bg-rose-500',
};

// 轴体两端的刻度用短格式（日期 + 时:分），卡片内仍用完整的 formatTimestamp。
const formatAxisTime = (value) => {
  if (!value) return '时间未知';
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
};

function AxisPill({ testid, time }) {
  return (
    <div className="relative z-10 flex h-7 items-center justify-center">
      <span
        data-testid={testid}
        className="whitespace-nowrap rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-[10px] font-medium text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
      >
        {formatAxisTime(time)}
      </span>
    </div>
  );
}

export default function InvestigationTimeline({ events, selectedEventId, onSelect, loading }) {
  const selectedRowRef = useRef(null);
  useEffect(() => {
    // jsdom（单测环境）未实现 scrollIntoView，做存在性守卫。
    if (selectedEventId && typeof selectedRowRef.current?.scrollIntoView === 'function') {
      selectedRowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedEventId]);

  if (loading) return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  if (!events.length) {
    return <div className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">暂无调查事件。请确认初次流水线已完成并产生已分析 Event Cluster。</div>;
  }

  const sorted = [...events].sort((a, b) => (a.start_time || 0) - (b.start_time || 0));
  const starts = sorted.map((event) => Number(event.start_time)).filter((t) => Number.isFinite(t) && t > 0);
  const earliest = starts.length ? Math.min(...starts) : null;
  const latest = starts.length ? Math.max(...starts) : null;

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden" data-testid="investigation-timeline">
      <div className="relative min-h-full px-3 py-3">
        {/* 竖向轴体：贯穿全部事件节点，两端为时间刻度 */}
        <div className="absolute bottom-[1.625rem] left-1/2 top-[1.625rem] w-px -translate-x-1/2 bg-slate-300 dark:bg-slate-600" aria-hidden="true" />
        <div className="relative">
          <AxisPill testid="timeline-axis-start" time={earliest} />
          {sorted.map((event, index) => {
            const status = REVIEW_STATUS[event.review_status] || REVIEW_STATUS.draft;
            const selected = selectedEventId === event.id;
            const onRight = index % 2 === 0;
            const label = (
              <span className={`pointer-events-none absolute top-1/2 max-w-[10rem] -translate-y-1/2 whitespace-nowrap truncate rounded px-1 text-xs ${onRight ? 'left-4' : 'right-4'} ${selected
                ? 'font-semibold text-primary-600 opacity-100 dark:text-primary-300'
                : 'bg-white/90 text-slate-500 opacity-0 shadow-sm group-hover:opacity-100 dark:bg-slate-900/90 dark:text-slate-400'}`}
              >
                {formatAxisTime(event.start_time)} · {event.effective_title || event.title}
              </span>
            );
            return (
              <div
                key={event.id}
                data-testid={`event-${event.id}`}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(event.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(event.id); }}
                ref={selected ? selectedRowRef : null}
                className="group relative z-10 cursor-pointer outline-none"
              >
                <div className="grid grid-cols-[1fr_3rem_1fr]">
                  {/* 三列必须始终渲染（空侧占位），否则网格自动前移、圆点脱离轴线 */}
                  {!onRight ? (
                    <div className="relative h-7">
                      <span className={`absolute right-0 top-1/2 h-px w-3 -translate-y-1/2 ${selected ? 'bg-primary-400' : 'bg-slate-300 dark:bg-slate-600'}`} />
                      {label}
                    </div>
                  ) : (
                    <div className="relative h-7" />
                  )}
                  <div className="flex h-7 items-center justify-center">
                    <span className={`h-3.5 w-3.5 rounded-full transition-transform group-hover:scale-125 ${selected
                      ? 'bg-primary-500 ring-4 ring-primary-200 dark:ring-primary-800'
                      : `${DOT_CLASS[status.variant] || DOT_CLASS.gray} ring-4 ring-white dark:ring-slate-900`}`}
                    />
                  </div>
                  {onRight ? (
                    <div className="relative h-7">
                      <span className={`absolute left-0 top-1/2 h-px w-3 -translate-y-1/2 ${selected ? 'bg-primary-400' : 'bg-slate-300 dark:bg-slate-600'}`} />
                      {label}
                    </div>
                  ) : (
                    <div className="relative h-7" />
                  )}
                </div>
                {/* 点击节点才展开：卡片占满整行宽度，盖住轴体 */}
                {selected && (
                  <div className="mb-2 mt-1 rounded-xl border border-primary-300 bg-white p-3 text-left shadow-md dark:border-primary-500/60 dark:bg-slate-900">
                    <div className="flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
                      <span className="inline-flex items-center gap-1">
                        <Clock3 size={12} />
                        {formatTimestamp(event.start_time)}{event.end_time ? ` – ${formatTimestamp(event.end_time)}` : ''}
                      </span>
                      <Badge variant={status.variant} size="sm">{status.label}</Badge>
                    </div>
                    <h3 className="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">{event.effective_title || event.title}</h3>
                    {(event.effective_summary || event.summary) && (
                      <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-400">{event.effective_summary || event.summary}</p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
                      <span className="inline-flex items-center gap-1"><Database size={12} />Evidence {event.evidence_count || event.evidence_counts?.total || 0}</span>
                      <span className="inline-flex items-center gap-1"><FileCheck2 size={12} />Report {event.report_evidence_count || 0}</span>
                      <span className="uppercase tracking-wide text-slate-400">{event.source === 'cluster_seed' ? 'Cluster Seed' : event.source}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          <AxisPill testid="timeline-axis-end" time={latest} />
        </div>
      </div>
    </div>
  );
}
