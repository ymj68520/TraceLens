import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Clock, Download, RotateCcw } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { setRefreshFlag } from '../store/intelligenceSlice';
import {
  getComprehensiveTimeline,
  getTimelineDistribution,
  getTimelineDetails,
  analyzeEventCluster,
} from '../services/forensicsService';
import type { EventCluster } from '../types/api';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import { PageHeader, StatStrip, type StatItem } from '../components/ui/PageScaffold';
import { downloadCSV } from '../lib/exportUtils';
import { emitAppEvent } from '../lib/appEvents';
import { formatDateTime } from '../lib/utils';
import { useUrlState } from '../hooks/useUrlState';
import { useTranslation } from '../hooks/useTranslation';
import TimelineFilterBar from '../components/timeline/TimelineFilterBar';
import DistributionChart, { type DistributionRow } from '../components/timeline/DistributionChart';
import ClusterList from '../components/timeline/ClusterList';
import EventDetailDrawer from '../components/timeline/EventDetailDrawer';
import {
  EVENT_TYPE_DOT,
  clusterIdentity,
  toUnixMs,
  typeLabel,
  type ClusterDetailEvent,
  type TimelineEventType,
} from '../components/timeline/eventTypes';

export interface TimelineResponse {
  timeline: EventCluster[];
  total?: number;
  [key: string]: unknown;
}

/** Pick a clustering window (seconds) from the total event span. */
export const autoBucketForSpan = (spanDays: number): number => {
  if (spanDays <= 1) return 60;
  if (spanDays <= 7) return 300;
  if (spanDays <= 30) return 900;
  if (spanDays <= 90) return 1800;
  if (spanDays <= 365) return 3600;
  return 21600;
};

export const toDatetimeLocal = (unixSeconds?: number | null): string => {
  if (!unixSeconds) return '';
  const d = new Date(unixSeconds * 1000);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const fromDatetimeLocal = (value: string): number | null => {
  if (!value) return null;
  const t = new Date(value).getTime();
  return Number.isNaN(t) ? null : Math.floor(t / 1000);
};

export default function Timeline() {
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const itemsPerPage = useAppSelector((state) => state.settings.itemsPerPage);
  const dispatch = useAppDispatch();
  const toast = useToast();
  const { t } = useTranslation();

  const currentPage = parseInt(searchParams.get('page') || '1', 10) || 1;
  const pageSize = itemsPerPage || 50;
  const customStart = searchParams.get('start') || '';
  const customEnd = searchParams.get('end') || '';
  const isClustered = searchParams.get('cluster') !== 'false';

  // Type filter, single-day pick and bucket granularity persist in the URL.
  const [eventType, setEventType] = useUrlState('type', '');
  const [selectedDate, setSelectedDate] = useUrlState('date', '');
  const [bucketParam, setBucketParam] = useUrlState('bucket', '60');

  const [timelineData, setTimelineData] = useState<TimelineResponse | null>(null);
  const [distributionData, setDistributionData] = useState<DistributionRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedEvent, setSelectedEvent] = useState<ClusterDetailEvent | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [eventsByCluster, setEventsByCluster] = useState<Record<string, ClusterDetailEvent[]>>({});
  const [loadingClusterKeys, setLoadingClusterKeys] = useState<Set<string>>(new Set());
  const [analyzingClusters, setAnalyzingClusters] = useState<Set<string>>(new Set());

  const autoAnalyzedSignatureRef = useRef('');

  const updateParams = useCallback(
    (newParams: Record<string, string | undefined>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        Object.entries(newParams).forEach(([key, value]) => {
          if (value === undefined || value === '') next.delete(key);
          else next.set(key, value);
        });
        return next;
      });
    },
    [setSearchParams],
  );

  const effectiveBucket = useMemo(() => {
    if (bucketParam !== 'auto') {
      const n = parseInt(bucketParam, 10);
      return n && n > 0 ? n : 60;
    }
    if (distributionData && distributionData.length > 0) {
      const first = new Date(distributionData[0].date).getTime();
      const last = new Date(distributionData[distributionData.length - 1].date).getTime();
      if (!Number.isNaN(first) && !Number.isNaN(last)) {
        const spanDays = Math.max(1, Math.ceil((last - first) / 86400000));
        return autoBucketForSpan(spanDays);
      }
    }
    return 60;
  }, [bucketParam, distributionData]);

  const fetchTimeline = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const offset = (currentPage - 1) * pageSize;
      const params: Record<string, unknown> = {
        limit: pageSize,
        offset,
        event_type: eventType || undefined,
        cluster: isClustered,
        bucket: effectiveBucket,
      };
      // Custom start/end wins over single-day pick; the UI never sets both.
      if (customStart || customEnd) {
        if (customStart) params.start_time = customStart;
        if (customEnd) params.end_time = customEnd;
      } else if (selectedDate) {
        const start = Math.floor(new Date(selectedDate).getTime() / 1000);
        params.start_time = start.toString();
        params.end_time = (start + 86400).toString();
      }

      const data = (await getComprehensiveTimeline(taskId, params)) as TimelineResponse;
      setTimelineData(data);
    } catch (err) {
      console.error('Failed to fetch timeline:', err);
      const message = (err as Error).message || t('timeline.error.fallback');
      setError(message);
      toast.error(t('timeline.error.load_failed').replace('{error}', message));
    } finally {
      setLoading(false);
    }
    // toast (a context value) is intentionally omitted: its unstable identity
    // would recreate this callback and refetch on unrelated re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, currentPage, pageSize, eventType, selectedDate, customStart, customEnd, isClustered, effectiveBucket]);

  useEffect(() => {
    if (!taskId) return;
    getTimelineDistribution(taskId)
      .then((dist: unknown) => {
        const d = dist as { distribution?: { event_date: string; event_type: string; count: number }[] };
        if (d?.distribution) {
          const distMap: Record<string, DistributionRow> = {};
          d.distribution.forEach((item) => {
            if (!distMap[item.event_date]) {
              distMap[item.event_date] = { date: item.event_date, CREATED: 0, MODIFIED: 0, DELETED: 0, OTHER: 0 };
            }
            const type = ['CREATED', 'MODIFIED', 'DELETED'].includes(item.event_type)
              ? (item.event_type as 'CREATED' | 'MODIFIED' | 'DELETED')
              : 'OTHER';
            distMap[item.event_date][type] += item.count;
          });
          setDistributionData(Object.values(distMap).sort((a, b) => a.date.localeCompare(b.date)));
        }
      })
      .catch((err) => console.error('Distribution error', err));
  }, [taskId]);

  useEffect(() => {
    void fetchTimeline();
  }, [fetchTimeline]);

  // Collapse expanded clusters and drop cached member events whenever the
  // query context changes (task, filters, granularity, page).
  useEffect(() => {
    setExpandedKeys(new Set());
    setEventsByCluster({});
    setLoadingClusterKeys(new Set());
  }, [taskId, eventType, selectedDate, customStart, customEnd, isClustered, effectiveBucket, currentPage]);

  // Auto-analyze visible clusters once per unique query+cluster-set signature.
  // The signature survives post-analysis refreshes (llm_summary doesn't change
  // bucket keys), which is what terminates the refresh loop.
  useEffect(() => {
    if (!taskId || !timelineData?.timeline?.length || !isClustered) return;

    const visibleKeys = timelineData.timeline.map((ev) => clusterIdentity(ev)).sort().join('|');
    const signature = `${taskId}|${currentPage}|${eventType}|${selectedDate}|${customStart}|${customEnd}|${isClustered}|${effectiveBucket}|${visibleKeys}`;
    if (autoAnalyzedSignatureRef.current === signature) return;
    autoAnalyzedSignatureRef.current = signature;

    const autoAnalyze = async () => {
      const unanalyzed = timelineData.timeline.filter((ev) => !ev.llm_summary);
      if (unanalyzed.length === 0) return;

      unanalyzed.sort(
        (a, b) => Number(b.cluster_count ?? 0) - Number(a.cluster_count ?? 0),
      );
      const toAnalyze = unanalyzed.slice(0, 5);

      let analyzedAny = false;
      for (const cluster of toAnalyze) {
        const key = clusterIdentity(cluster);
        setAnalyzingClusters((prev) => new Set(prev).add(key));
        try {
          await analyzeEventCluster(taskId, cluster);
          analyzedAny = true;
        } catch (e) {
          console.error('Auto-analyze failed for cluster:', key, e);
        } finally {
          setAnalyzingClusters((prev) => {
            const next = new Set(prev);
            next.delete(key);
            return next;
          });
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }

      if (analyzedAny) {
        void fetchTimeline();
        dispatch(setRefreshFlag({ type: 'clusters' }));
      }
    };

    const timer = setTimeout(() => void autoAnalyze(), 1000);
    return () => clearTimeout(timer);
  }, [taskId, timelineData, currentPage, eventType, selectedDate, customStart, customEnd, isClustered, effectiveBucket, fetchTimeline, dispatch]);

  const loadClusterEvents = async (cluster: EventCluster) => {
    if (!taskId) return;
    const descriptor = cluster.group_descriptor;
    if (!descriptor) return;
    const key = clusterIdentity(cluster);
    setLoadingClusterKeys((prev) => new Set(prev).add(key));
    try {
      const data = (await getTimelineDetails(taskId, {
        bucket_index: descriptor.bucket_index,
        type: descriptor.event_type,
        dir: descriptor.parent_directory,
        bucket: descriptor.bucket_seconds,
        limit: 5000,
      })) as { events?: ClusterDetailEvent[] };
      const events = data.events ?? [];
      setEventsByCluster((prev) => ({ ...prev, [key]: events }));
      if (events.length === 0) {
        toast.info(t('timeline.cluster.empty_toast'));
      }
    } catch (err) {
      console.error('Failed to fetch cluster details', err);
      toast.error(t('timeline.cluster.load_failed'));
      // Collapse so the next click retries instead of showing a stale spinner.
      setExpandedKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    } finally {
      setLoadingClusterKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const handleToggleCluster = (cluster: EventCluster) => {
    const key = clusterIdentity(cluster);
    const willExpand = !expandedKeys.has(key);
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    if (willExpand && !eventsByCluster[key]) void loadClusterEvents(cluster);
  };

  const handleAnalyzeCluster = async (cluster: EventCluster) => {
    if (!taskId) {
      toast.error(t('timeline.error.no_task'));
      return;
    }
    const key = clusterIdentity(cluster);
    setAnalyzingClusters((prev) => new Set(prev).add(key));
    try {
      await analyzeEventCluster(taskId, cluster);
      void fetchTimeline();
      dispatch(setRefreshFlag({ type: 'clusters' }));
    } catch (e) {
      toast.error(t('timeline.error.analyze_failed').replace('{error}', (e as Error).message));
    } finally {
      setAnalyzingClusters((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  // ── Type facet counts (task-wide, from the distribution endpoint) ──────────
  const typeCounts = useMemo(() => {
    const counts: Record<TimelineEventType, number> = { CREATED: 0, MODIFIED: 0, DELETED: 0, OTHER: 0 };
    (distributionData ?? []).forEach((row) => {
      counts.CREATED += row.CREATED;
      counts.MODIFIED += row.MODIFIED;
      counts.DELETED += row.DELETED;
      counts.OTHER += row.OTHER;
    });
    return counts;
  }, [distributionData]);
  const totalCount = typeCounts.CREATED + typeCounts.MODIFIED + typeCounts.DELETED + typeCounts.OTHER;

  const toggleTypeFilter = (type: string) => {
    setEventType(eventType === type ? '' : type);
    updateParams({ page: '1' });
  };

  const typeStats: StatItem[] = [
    {
      label: t('common.all'),
      value: totalCount,
      active: !eventType,
      onClick: () => toggleTypeFilter(''),
    },
    {
      label: t('timeline.filter.created'),
      value: typeCounts.CREATED,
      dotClass: EVENT_TYPE_DOT.CREATED,
      active: eventType === 'CREATED',
      onClick: () => toggleTypeFilter('CREATED'),
    },
    {
      label: t('timeline.filter.modified'),
      value: typeCounts.MODIFIED,
      dotClass: EVENT_TYPE_DOT.MODIFIED,
      active: eventType === 'MODIFIED',
      onClick: () => toggleTypeFilter('MODIFIED'),
    },
    {
      label: t('timeline.filter.deleted'),
      value: typeCounts.DELETED,
      dotClass: EVENT_TYPE_DOT.DELETED,
      active: eventType === 'DELETED',
      onClick: () => toggleTypeFilter('DELETED'),
    },
    {
      label: t('timeline.chip.other'),
      value: typeCounts.OTHER,
      dotClass: EVENT_TYPE_DOT.OTHER,
      active: eventType === 'OTHER',
      onClick: () => toggleTypeFilter('OTHER'),
    },
  ];

  // ── CSV export of the current filtered clusters ────────────────────────────
  const clusters = timelineData?.timeline ?? [];
  const handleExportCsv = () => {
    if (clusters.length === 0) {
      toast.info(t('timeline.export.empty'));
      return;
    }
    const rows = clusters.map((c) => ({
      event_type: typeLabel(c.group_descriptor?.event_type),
      count: c.cluster_count ?? c.event_count ?? 1,
      first_seen: formatDateTime(toUnixMs(c.first_seen)),
      last_seen: formatDateTime(toUnixMs(c.last_seen)),
      directory: c.group_descriptor?.parent_directory ?? '',
      sample_file: c.sample_files?.[0] ? String(c.sample_files[0]) : '',
      summary: c.llm_summary ?? '',
    }));
    downloadCSV(rows, `timeline-${(taskId ?? '').slice(0, 8)}.csv`, [
      { key: 'event_type', label: t('timeline.csv.event_type') },
      { key: 'count', label: t('timeline.csv.count') },
      { key: 'first_seen', label: t('timeline.csv.first_seen') },
      { key: 'last_seen', label: t('timeline.csv.last_seen') },
      { key: 'directory', label: t('timeline.csv.directory') },
      { key: 'sample_file', label: t('timeline.csv.sample_file') },
      { key: 'summary', label: t('timeline.csv.summary') },
    ]);
    toast.success(t('timeline.export.success').replace('{n}', String(rows.length)));
    emitAppEvent({
      kind: 'info',
      title: t('timeline.export.event_title'),
      detail: t('timeline.export.event_detail').replace('{n}', String(rows.length)),
    });
  };

  const resetAllFilters = () => {
    setEventType('');
    setSelectedDate('');
    setBucketParam('60');
    updateParams({ start: '', end: '', cluster: undefined, page: '' });
  };

  if (!taskId) {
    return (
      <div className="space-y-4 max-w-7xl">
        <PageHeader icon={Clock} tone="sky" title={t('nav.timeline')} subtitle={t('timeline.subtitle')} />
        <div className="card">
          <EmptyState
            icon={<Clock size={36} />}
            title={t('timeline.empty.no_task.title')}
            description={t('timeline.empty.no_task.desc')}
          />
        </div>
      </div>
    );
  }

  const hasActiveFilters = Boolean(eventType || selectedDate || customStart || customEnd);

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader
        icon={Clock}
        tone="sky"
        title={t('nav.timeline')}
        subtitle={t('timeline.subtitle')}
        actions={
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={handleExportCsv}
            disabled={loading || clusters.length === 0}
          >
            <Download size={14} />
            {t('timeline.export_csv')}
          </button>
        }
      />

      {distributionData !== null && (
        <StatStrip stats={typeStats} />
      )}

      <TimelineFilterBar
        eventType={eventType}
        selectedDate={selectedDate}
        customStart={customStart}
        customEnd={customEnd}
        isClustered={isClustered}
        bucketParam={bucketParam}
        effectiveBucket={effectiveBucket}
        onEventTypeChange={(v) => {
          setEventType(v);
          updateParams({ page: '1' });
        }}
        onDateChange={(v) => {
          setSelectedDate(v);
          updateParams({ start: '', end: '', page: '1' });
        }}
        onStartChange={(v) => {
          updateParams({ start: fromDatetimeLocal(v)?.toString(), date: '', page: '1' });
        }}
        onEndChange={(v) => {
          updateParams({ end: fromDatetimeLocal(v)?.toString(), date: '', page: '1' });
        }}
        onClusteredChange={(v) => updateParams({ cluster: v ? undefined : 'false', page: '1' })}
        onBucketChange={(v) => {
          setBucketParam(v);
          updateParams({ page: '1' });
        }}
        onReset={resetAllFilters}
      />

      {distributionData && distributionData.length > 0 && (
        <DistributionChart data={distributionData} />
      )}

      {error ? (
        <div className="card">
          <EmptyState
            title={t('timeline.error.load_title')}
            description={error}
            action={
              <button type="button" className="btn-secondary btn-sm" onClick={() => void fetchTimeline()}>
                <RotateCcw size={13} />
                {t('common.retry')}
              </button>
            }
          />
        </div>
      ) : (
        <ClusterList
          clusters={clusters}
          total={timelineData?.total ?? 0}
          currentPage={currentPage}
          pageSize={pageSize}
          loading={loading}
          analyzingClusters={analyzingClusters}
          hasActiveFilters={hasActiveFilters}
          expandedKeys={expandedKeys}
          eventsByCluster={eventsByCluster}
          loadingClusterKeys={loadingClusterKeys}
          onPageChange={(page) => updateParams({ page: String(page) })}
          onToggleCluster={handleToggleCluster}
          onOpenEvent={setSelectedEvent}
          onAnalyzeCluster={handleAnalyzeCluster}
          onResetFilters={resetAllFilters}
        />
      )}

      <EventDetailDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </div>
  );
}
