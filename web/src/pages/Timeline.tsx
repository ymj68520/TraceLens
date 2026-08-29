import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../store';
import { setRefreshFlag } from '../store/intelligenceSlice';
import {
  getComprehensiveTimeline,
  getTimelineDistribution,
  getTimelineDetails,
  analyzeEventCluster,
} from '../services/forensicsService';
import type { EventCluster } from '../types/api';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import TimelineFilterBar from '../components/timeline/TimelineFilterBar';
import DistributionChart from '../components/timeline/DistributionChart';
import ClusterList from '../components/timeline/ClusterList';
import ClusterDetailDrawer, { type ClusterDetailEvent } from '../components/timeline/ClusterDetailDrawer';
import { Clock } from 'lucide-react';

export interface DistributionRow {
  date: string;
  CREATED: number;
  MODIFIED: number;
  DELETED: number;
  OTHER: number;
}

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

const clusterIdentity = (cluster: EventCluster) =>
  JSON.stringify(cluster?.group_descriptor || null);

export default function Timeline() {
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const itemsPerPage = useAppSelector((state) => state.settings.itemsPerPage);
  const dispatch = useAppDispatch();
  const toast = useToast();

  const currentPage = parseInt(searchParams.get('page') || '1', 10) || 1;
  const pageSize = itemsPerPage || 50;
  const eventType = searchParams.get('type') || '';
  const selectedDate = searchParams.get('date') || '';
  const customStart = searchParams.get('start') || '';
  const customEnd = searchParams.get('end') || '';
  const isClustered = searchParams.get('cluster') !== 'false';
  const bucketParam = searchParams.get('bucket') || '60';

  const [timelineData, setTimelineData] = useState<TimelineResponse | null>(null);
  const [distributionData, setDistributionData] = useState<DistributionRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedCluster, setSelectedCluster] = useState<EventCluster | null>(null);
  const [clusterDetails, setClusterDetails] = useState<ClusterDetailEvent[]>([]);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [drawerSearch, setDrawerSearch] = useState('');
  const [analyzingClusters, setAnalyzingClusters] = useState<Set<string>>(new Set());

  const autoAnalyzedSignatureRef = useRef('');

  const updateParams = useCallback(
    (newParams: Record<string, string | undefined>) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(newParams).forEach(([key, value]) => {
        if (value === undefined || value === '' || value === null) next.delete(key);
        else next.set(key, value);
      });
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
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
      setError((err as Error).message || '时间线加载失败');
    } finally {
      setLoading(false);
    }
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

  const fetchClusterDetails = useCallback(
    async (cluster: EventCluster, search: string) => {
      setLoadingDetails(true);
      try {
        const descriptor = cluster.group_descriptor;
        if (!descriptor) throw new Error('Timeline group descriptor missing');
        const data = (await getTimelineDetails(taskId!, {
          bucket_index: descriptor.bucket_index,
          type: descriptor.event_type,
          dir: descriptor.parent_directory,
          search: search || undefined,
          bucket: descriptor.bucket_seconds,
          limit: 5000,
        })) as { events?: ClusterDetailEvent[] };
        setClusterDetails(data.events || []);
      } catch (err) {
        console.error('Failed to fetch cluster details', err);
      } finally {
        setLoadingDetails(false);
      }
    },
    [taskId],
  );

  const handleOpenCluster = (cluster: EventCluster) => {
    setSelectedCluster(cluster);
    setDrawerSearch('');
    void fetchClusterDetails(cluster, '');
  };

  useEffect(() => {
    if (!selectedCluster) return;
    const timer = setTimeout(() => {
      void fetchClusterDetails(selectedCluster, drawerSearch);
    }, 350);
    return () => clearTimeout(timer);
  }, [drawerSearch, selectedCluster, fetchClusterDetails]);

  const handleAnalyzeCluster = async (cluster: EventCluster) => {
    if (!taskId) {
      toast.error('未选择任务');
      return;
    }
    const key = clusterIdentity(cluster);
    setAnalyzingClusters((prev) => new Set(prev).add(key));
    try {
      await analyzeEventCluster(taskId, cluster);
      void fetchTimeline();
      dispatch(setRefreshFlag({ type: 'clusters' }));
    } catch (e) {
      toast.error(`分析失败：${(e as Error).message}`);
    } finally {
      setAnalyzingClusters((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<Clock size={36} />}
          title="未选择任务"
          description="请从页面顶部的任务选择器中选择一个已完成的分析任务。"
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-7xl">
      <TimelineFilterBar
        eventType={eventType}
        selectedDate={selectedDate}
        customStart={customStart}
        customEnd={customEnd}
        isClustered={isClustered}
        bucketParam={bucketParam}
        effectiveBucket={effectiveBucket}
        onChange={updateParams}
      />

      {distributionData && distributionData.length > 0 && (
        <DistributionChart data={distributionData} />
      )}

      {loading && !timelineData ? (
        <div className="card">
          <LoadingBlock text="正在获取取证证据…" />
        </div>
      ) : error ? (
        <div className="card">
          <EmptyState title="加载失败" description={error} />
        </div>
      ) : (
        <ClusterList
          clusters={timelineData?.timeline ?? []}
          total={timelineData?.total ?? 0}
          currentPage={currentPage}
          pageSize={pageSize}
          loading={loading}
          analyzingClusters={analyzingClusters}
          onPageChange={(page) => updateParams({ page: String(page) })}
          onOpenCluster={handleOpenCluster}
          onAnalyzeCluster={handleAnalyzeCluster}
        />
      )}

      <ClusterDetailDrawer
        cluster={selectedCluster}
        events={clusterDetails}
        loading={loadingDetails}
        search={drawerSearch}
        onSearchChange={setDrawerSearch}
        onClose={() => setSelectedCluster(null)}
      />
    </div>
  );
}
