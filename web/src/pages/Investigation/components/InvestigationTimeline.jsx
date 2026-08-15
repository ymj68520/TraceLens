import { Clock3, Database, FileCheck2 } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Spinner from '../../../components/common/Spinner';
import { REVIEW_STATUS, formatTimestamp } from '../utils/investigationConstants';

const count = (event, key) => event.evidence_counts?.[key] || 0;

export default function InvestigationTimeline({ events, selectedEventId, onSelect, loading }) {
  if (loading) return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  if (!events.length) {
    return <div className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">暂无调查事件。请确认初次流水线已完成并产生已分析 Event Cluster。</div>;
  }

  return (
    <div className="h-full overflow-y-auto p-3 space-y-3" data-testid="investigation-timeline">
      {events.map((event) => {
        const status = REVIEW_STATUS[event.review_status] || REVIEW_STATUS.draft;
        const selected = selectedEventId === event.id;
        return (
          <button
            type="button"
            key={event.id}
            onClick={() => onSelect(event.id)}
            className={`w-full text-left rounded-xl border p-4 transition-all ${selected
              ? 'border-primary-500 bg-primary-50/70 dark:bg-primary-950/30 shadow-md'
              : 'border-slate-200/70 dark:border-slate-700/60 bg-white/50 dark:bg-slate-900/35 hover:border-primary-300'}`}
            data-testid={`event-${event.id}`}
          >
            <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1"><Clock3 size={13} />{formatTimestamp(event.start_time)}</span>
              <Badge variant={status.variant} size="sm">{status.label}</Badge>
            </div>
            <h3 className="mt-2 font-semibold text-slate-900 dark:text-slate-100">{event.title}</h3>
            {event.summary && <p className="mt-1 text-xs text-slate-600 dark:text-slate-400 line-clamp-3">{event.summary}</p>}
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
              <span className="inline-flex items-center gap-1"><Database size={12} />Primary {count(event, 'primary')}</span>
              <span>Supporting {count(event, 'supporting')}</span>
              <span>Contradicting {count(event, 'contradicting')}</span>
              <span className="inline-flex items-center gap-1"><FileCheck2 size={12} />Report {event.report_evidence_count || 0}</span>
            </div>
            <div className="mt-2 text-[11px] uppercase tracking-wide text-slate-400">{event.source === 'cluster_seed' ? 'Cluster Seed' : event.source}</div>
          </button>
        );
      })}
    </div>
  );
}
