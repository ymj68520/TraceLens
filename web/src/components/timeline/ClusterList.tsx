import { Virtuoso } from 'react-virtuoso';
import {
  Brain,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Folder,
  Clock,
  Layers,
  FileSearch,
  RotateCcw,
} from 'lucide-react';
import type { EventCluster } from '../../types/api';
import EmptyState from '../ui/EmptyState';
import { SkeletonTable } from '../ui/PageScaffold';
import { useTranslation } from '../../hooks/useTranslation';
import { basename, cx, formatBytes, formatDateTime, formatRelativeTime } from '../../lib/utils';
import {
  EVENT_TYPE_LABEL,
  EVENT_TYPE_TEXT,
  clusterIdentity,
  normalizeEventType,
  toUnixMs,
  type ClusterDetailEvent,
} from './eventTypes';

/** Cap rendered rows per expanded cluster; the note below shows the real total. */
const MAX_VISIBLE_EVENTS = 200;

interface ClusterListProps {
  clusters: EventCluster[];
  total: number;
  currentPage: number;
  pageSize: number;
  loading: boolean;
  analyzingClusters: Set<string>;
  /** True when type/date filters are set — switches the empty-state copy. */
  hasActiveFilters: boolean;
  expandedKeys: Set<string>;
  eventsByCluster: Record<string, ClusterDetailEvent[]>;
  loadingClusterKeys: Set<string>;
  onPageChange: (page: number) => void;
  onToggleCluster: (cluster: EventCluster) => void;
  onOpenEvent: (event: ClusterDetailEvent) => void;
  onAnalyzeCluster: (cluster: EventCluster) => void;
  onResetFilters: () => void;
}

/** Relative time with the absolute timestamp as native tooltip. */
function EventTime({ ts, className }: { ts?: number | string | null; className?: string }) {
  const ms = toUnixMs(ts);
  if (!ms) return <span className={className}>—</span>;
  return (
    <span className={className} title={formatDateTime(ms)}>
      {formatRelativeTime(ms)}
    </span>
  );
}

export default function ClusterList({
  clusters,
  total,
  currentPage,
  pageSize,
  loading,
  analyzingClusters,
  hasActiveFilters,
  expandedKeys,
  eventsByCluster,
  loadingClusterKeys,
  onPageChange,
  onToggleCluster,
  onOpenEvent,
  onAnalyzeCluster,
  onResetFilters,
}: ClusterListProps) {
  const { t } = useTranslation();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (!loading && clusters.length === 0) {
    return (
      <div className="card">
        <EmptyState
          icon={<FileSearch size={36} />}
          title={hasActiveFilters ? t('timeline.cluster.empty_filtered.title') : t('timeline.cluster.empty.title')}
          description={
            hasActiveFilters
              ? t('timeline.cluster.empty_filtered.desc')
              : t('timeline.cluster.empty.desc')
          }
          action={
            hasActiveFilters ? (
              <button type="button" className="btn-secondary btn-sm" onClick={onResetFilters}>
                <RotateCcw size={13} />
                {t('common.clear_filters')}
              </button>
            ) : undefined
          }
        />
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="px-5 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
        <h3 className="card-title flex items-center gap-1.5">
          <Layers size={14} className="text-ink-400" />
          {t('timeline.cluster.title')}
          <span className="text-2xs font-normal text-ink-400">
            {t('timeline.cluster.matches').replace('{n}', String(total))}
          </span>
        </h3>
        <div className="flex items-center gap-1 text-xs">
          <button
            type="button"
            className="btn-ghost btn-sm"
            disabled={currentPage <= 1}
            onClick={() => onPageChange(currentPage - 1)}
            aria-label={t('timeline.cluster.prev_page')}
          >
            <ChevronLeft size={14} />
          </button>
          <span className="text-ink-500 dark:text-ink-400 tabular-nums px-1">
            {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            className="btn-ghost btn-sm"
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(currentPage + 1)}
            aria-label={t('timeline.cluster.next_page')}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {loading ? (
        <SkeletonTable rows={8} cols={4} />
      ) : (
        <Virtuoso
          style={{ height: 560 }}
          data={clusters}
          itemContent={(_, cluster) => {
            const key = clusterIdentity(cluster);
            const analyzing = analyzingClusters.has(key);
            const expanded = expandedKeys.has(key);
            const eventsLoading = loadingClusterKeys.has(key);
            const events = eventsByCluster[key];
            const count = cluster.cluster_count ?? cluster.event_count ?? 1;
            const eventType = normalizeEventType(cluster.group_descriptor?.event_type);
            const visibleEvents = events?.slice(0, MAX_VISIBLE_EVENTS) ?? [];

            return (
              <div className="border-b border-ink-100 dark:border-ink-800/60">
                {/* Cluster header — click to expand/collapse the member events */}
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={expanded}
                  className="px-5 py-3 hover:bg-ink-50 dark:hover:bg-ink-900/40 transition-colors cursor-pointer"
                  onClick={() => onToggleCluster(cluster)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onToggleCluster(cluster);
                    }
                  }}
                >
                  <div className="flex items-start gap-3">
                    <ChevronDown
                      size={15}
                      className={cx(
                        'mt-0.5 shrink-0 text-ink-400 transition-transform duration-150',
                        !expanded && '-rotate-90',
                      )}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={cx('text-xs font-semibold', EVENT_TYPE_TEXT[eventType])}>
                          {eventType === 'OTHER'
                            ? cluster.group_descriptor?.event_type || t(EVENT_TYPE_LABEL.OTHER)
                            : t(EVENT_TYPE_LABEL[eventType])}
                        </span>
                        <span className="chip bg-ink-100 dark:bg-ink-800 text-ink-600 dark:text-ink-300">
                          {count} {t('timeline.node.items')}
                        </span>
                        <span className="text-2xs text-ink-400 flex items-center gap-1">
                          <Clock size={11} />
                          <EventTime ts={cluster.first_seen} />
                          —
                          <EventTime ts={cluster.last_seen} />
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-ink-600 dark:text-ink-300 flex items-center gap-1 truncate">
                        <Folder size={12} className="shrink-0 text-ink-400" />
                        <span className="truncate font-mono">
                          {cluster.group_descriptor?.parent_directory || '/'}
                        </span>
                      </p>
                      {cluster.llm_summary && (
                        <p className="mt-1.5 text-xs text-ink-500 dark:text-ink-400 line-clamp-2 leading-relaxed">
                          {cluster.llm_summary}
                        </p>
                      )}
                      {cluster.sample_files && cluster.sample_files.length > 0 && (
                        <p className="mt-1 text-2xs text-ink-400 truncate">
                          {t('timeline.cluster.sample_file').replace('{name}', basename(String(cluster.sample_files[0])))}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {!cluster.llm_summary && (
                        <button
                          type="button"
                          disabled={analyzing}
                          onClick={(e) => {
                            e.stopPropagation();
                            void onAnalyzeCluster(cluster);
                          }}
                          className="btn-ghost btn-sm text-accent-600 dark:text-accent-400"
                          title={t('timeline.cluster.analyze_title')}
                        >
                          <Brain size={14} className={analyzing ? 'animate-pulse' : ''} />
                          {analyzing ? t('timeline.cluster.analyzing') : t('timeline.cluster.analyze')}
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Expanded member events */}
                {expanded && (
                  <div className="bg-ink-50/60 dark:bg-ink-900/40 px-5 py-2">
                    {eventsLoading ? (
                      <div className="py-3 space-y-2" aria-label={t('common.loading')}>
                        {[0, 1, 2].map((i) => (
                          <div
                            key={i}
                            className="h-4 rounded bg-ink-100 dark:bg-ink-800/70 animate-pulse"
                            style={{ width: `${88 - i * 14}%` }}
                          />
                        ))}
                      </div>
                    ) : events && events.length === 0 ? (
                      <p className="py-3 text-2xs text-ink-400 text-center">{t('timeline.cluster.no_events')}</p>
                    ) : (
                      <div className="max-h-72 overflow-y-auto -mx-1 py-0.5">
                        {visibleEvents.map((ev, idx) => {
                          const path = ev.file_path ? String(ev.file_path) : '';
                          const size = ev.file_size;
                          return (
                            <button
                              key={idx}
                              type="button"
                              className="w-full flex items-center gap-3 px-2 py-1.5 rounded-md text-left hover:bg-white dark:hover:bg-ink-800/70 transition-colors group"
                              onClick={() => onOpenEvent(ev)}
                            >
                              <EventTime
                                ts={ev.timestamp}
                                className="w-16 shrink-0 text-2xs text-ink-500 dark:text-ink-400 truncate"
                              />
                              <span className="flex-1 min-w-0">
                                <span className="block text-xs text-ink-700 dark:text-ink-200 font-mono truncate">
                                  {basename(path) || path || '—'}
                                </span>
                                {path && basename(path) !== path && (
                                  <span className="block text-2xs text-ink-400 dark:text-ink-500 font-mono truncate">
                                    {path}
                                  </span>
                                )}
                              </span>
                              <span className="shrink-0 text-2xs text-ink-400 tabular-nums whitespace-nowrap">
                                {size === undefined || size === null || size === ''
                                  ? '—'
                                  : formatBytes(Number(size))}
                              </span>
                              <ChevronRight
                                size={12}
                                className="shrink-0 text-ink-300 dark:text-ink-600 group-hover:text-accent-500 transition-colors"
                              />
                            </button>
                          );
                        })}
                      </div>
                    )}
                    {events && events.length > 0 && (
                      <p className="mt-1 px-2 text-2xs text-ink-400">
                        {t(
                          events.length > MAX_VISIBLE_EVENTS
                            ? 'timeline.cluster.events_truncated'
                            : 'timeline.cluster.events_count',
                        )
                          .replace('{n}', String(events.length))
                          .replace('{max}', String(MAX_VISIBLE_EVENTS))}
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          }}
        />
      )}
    </div>
  );
}
