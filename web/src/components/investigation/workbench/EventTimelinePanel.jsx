// EventTimelinePanel.jsx
// Workbench 中栏 Timeline 视图：Investigation Events 的当前 narrative 列表。
// 点击 → 页面持有 selectedEventId；C9c 起顶部提供显式 New Investigation
// Event 表单（不做 Timeline Cluster 自动转换）。
import { CircleAlert, RefreshCw, Clock } from 'lucide-react';
import Badge from '../../common/Badge';
import Spinner from '../../common/Spinner';
import CreateEventForm from './CreateEventForm';
import { useTranslation } from '../../../hooks/useTranslation';

const formatTime = (iso) => {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
};

const EventTimelinePanel = ({
    events,
    selectedEventId,
    onSelectEvent,
    loading = false,
    error = null,
    onRetry,
    onCreateEvent,
}) => {
    const { t } = useTranslation();

    return (
        <div className="flex flex-col h-full" data-testid="event-timeline">
            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-white/10 dark:border-slate-700/40">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {t('investigation_workbench.timeline_title')}
                </h2>
                <button
                    type="button"
                    onClick={onRetry}
                    disabled={loading}
                    className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 disabled:opacity-50"
                    title={t('investigation_workbench.refresh')}
                >
                    <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            {onCreateEvent && <CreateEventForm onCreateEvent={onCreateEvent} />}

            <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
                {error ? (
                    <div className="flex flex-col items-center gap-2 py-8 text-center px-3">
                        <CircleAlert size={18} className="text-rose-500" />
                        <p className="text-xs text-rose-600 dark:text-rose-400">
                            {t('investigation_workbench.load_failed')}
                            {error?.status ? ` (HTTP ${error.status})` : ''}
                        </p>
                        <button type="button" onClick={onRetry}
                            className="px-2.5 py-1 text-xs rounded-lg bg-rose-500/10 text-rose-700 dark:text-rose-300 hover:bg-rose-500/20">
                            {t('investigation_workbench.retry')}
                        </button>
                    </div>
                ) : loading && (!events || events.length === 0) ? (
                    <div className="flex items-center justify-center py-10">
                        <Spinner size="md" />
                    </div>
                ) : !events || events.length === 0 ? (
                    <div className="flex flex-col items-center gap-1.5 py-10 text-slate-400 dark:text-slate-500">
                        <Clock size={18} />
                        <p className="text-xs">{t('investigation_workbench.no_events')}</p>
                    </div>
                ) : (
                    events.map((event) => {
                        const isSelected = event.event_id === selectedEventId;
                        return (
                            <button
                                key={event.event_id}
                                type="button"
                                data-testid={`event-item-${event.event_id}`}
                                onClick={() => onSelectEvent(event.event_id)}
                                className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors ${
                                    isSelected
                                        ? 'bg-yellow-500/15 ring-1 ring-yellow-500/40'
                                        : 'hover:bg-slate-100/60 dark:hover:bg-slate-800/60'
                                }`}
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-xs font-medium text-slate-800 dark:text-slate-100 break-all">
                                        {event.title || event.event_id}
                                    </span>
                                    <span className="flex items-center gap-1 shrink-0">
                                        <Badge variant="gray" size="sm">v{event.current_version}</Badge>
                                        {event.needs_refresh && (
                                            <Badge variant="yellow" size="sm">
                                                {t('investigation_workbench.needs_refresh')}
                                            </Badge>
                                        )}
                                    </span>
                                </div>
                                {event.summary && (
                                    <p className="mt-1 text-[11px] leading-snug text-slate-500 dark:text-slate-400 line-clamp-2">
                                        {event.summary}
                                    </p>
                                )}
                                <span className="block mt-1 text-[10px] text-slate-400 dark:text-slate-500">
                                    {formatTime(event.updated_at || event.created_at)}
                                </span>
                            </button>
                        );
                    })
                )}
            </div>
        </div>
    );
};

export default EventTimelinePanel;
