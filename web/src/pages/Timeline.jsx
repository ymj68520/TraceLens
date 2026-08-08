import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { setRefreshFlag } from '../store/intelligenceSlice';
import { Virtuoso } from 'react-virtuoso';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { useTranslation } from '../hooks/useTranslation';
import { getComprehensiveTimeline, getTimelineDistribution, getTimelineDetails, analyzeEventCluster, reanalyzeEventCluster } from '../services/forensicsService';
import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Calendar, Filter, X, ChevronLeft, ChevronRight, FileText, Clock, Layers, Folder, ArrowRight, Brain, RefreshCw, CheckCircle, History, Gauge } from 'lucide-react';

// Cluster investigation drawer (split for maintainability)
import ClusterInvestigationDrawer from '../components/timeline/ClusterInvestigationDrawer';

// --- Helper Functions ---
const formatTimestamp = (timestamp) => {
  if (!timestamp) return '-';
  return new Date(timestamp * 1000).toLocaleString();
};

const formatTimeOnly = (timestamp) => {
  if (!timestamp) return '-';
  return new Date(timestamp * 1000).toLocaleTimeString();
};

const formatFileSize = (bytes) => {
  const size = parseFloat(bytes);
  if (isNaN(size) || size <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let unitIndex = 0;
  let displaySize = size;
  while (displaySize >= 1024 && unitIndex < units.length - 1) {
    displaySize /= 1024;
    unitIndex++;
  }
  return `${displaySize.toFixed(1)} ${units[unitIndex]}`;
};

// Convert a unix-seconds timestamp (the format the API uses everywhere) into a
// value suitable for an <input type="datetime-local"> control, expressed in the
// user's local timezone (datetime-local always operates in local time).
const toDatetimeLocal = (unixSeconds) => {
  if (!unixSeconds) return '';
  const d = new Date(unixSeconds * 1000);
  if (isNaN(d.getTime())) return '';
  // Pad to YYYY-MM-DDTHH:MM (the format datetime-local expects, no seconds/zone)
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// Inverse of toDatetimeLocal: a datetime-local string -> unix seconds.
const fromDatetimeLocal = (value) => {
  if (!value) return null;
  const t = new Date(value).getTime();
  return isNaN(t) ? null : Math.floor(t / 1000);
};

// Map a total event span (in days) to a sensible clustering window (seconds).
// Used by the "auto" bucket option so very wide forensic images aggregate at a
// coarser grain, keeping the cluster list navigable.
const autoBucketForSpan = (spanDays) => {
  if (spanDays <= 1) return 60;       // 1 minute
  if (spanDays <= 7) return 300;      // 5 minutes
  if (spanDays <= 30) return 900;     // 15 minutes
  if (spanDays <= 90) return 1800;    // 30 minutes
  if (spanDays <= 365) return 3600;   // 1 hour
  return 21600;                       // 6 hours
};

const Timeline = () => {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);
  const { itemsPerPage } = useSelector((state) => state.settings);

  const currentPage = parseInt(searchParams.get('page')) || 1;
  const pageSize = itemsPerPage || 50;
  const eventType = searchParams.get('type') || '';
  const selectedDate = searchParams.get('date') || '';
  const customStart = searchParams.get('start') || '';
  const customEnd = searchParams.get('end') || '';
  const isClustered = searchParams.get('cluster') !== 'false';
  const viewMode = searchParams.get('view') || 'timeline';
  // Clustering window selector. 'auto' picks a window based on the overall
  // event span (see effectiveBucket below). Values are seconds. Default 60
  // preserves backward compatibility for URLs that carry no ?bucket= param.
  const bucketParam = searchParams.get('bucket') || '60';

  const [timelineData, setTimelineData] = useState(null);
  const [distributionData, setDistributionData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Investigation Drawer State
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [clusterDetails, setClusterDetails] = useState([]);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [drawerSearch, setDrawerSearch] = useState('');
  
  // AI Analysis State
  const [analyzingClusters, setAnalyzingClusters] = useState(new Set());

  const virtuosoRef = useRef();
  const dispatch = useDispatch();
  const currentTask = tasks.find((t) => t.id === taskId);

  const updateParams = useCallback((newParams) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(newParams).forEach(([key, value]) => {
      if (value === undefined || value === '' || value === null) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

  // Resolve the actual clustering window (seconds) to send to the backend.
  // 'auto' derives a window from the overall event span (distributionData spans
  // the full task timeline, independent of the current page/time filter), so
  // it stays stable as the user narrows filters. Fixed values pass through.
  const effectiveBucket = useMemo(() => {
    if (bucketParam !== 'auto') {
      const n = parseInt(bucketParam);
      return (n && n > 0) ? n : 60;
    }
    if (distributionData && distributionData.length > 0) {
      const first = new Date(distributionData[0].date).getTime();
      const last = new Date(distributionData[distributionData.length - 1].date).getTime();
      if (!isNaN(first) && !isNaN(last)) {
        const spanDays = Math.max(1, Math.ceil((last - first) / 86400000));
        return autoBucketForSpan(spanDays);
      }
    }
    return 60; // fallback before distribution data is available
  }, [bucketParam, distributionData]);

  const fetchTimeline = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);

    try {
      const offset = (currentPage - 1) * pageSize;
      const params = {
        limit: pageSize,
        offset: offset,
        event_type: eventType || undefined,
        cluster: isClustered,
        // Always send the resolved window so the backend groups identically.
        // (Effective only when cluster=true; backend ignores it otherwise.)
        bucket: effectiveBucket
      };

      console.log('Fetching timeline with params:', params);

      // Time-window filter. Three mutually exclusive sources, in priority order:
      // custom start/end > single-day pick (date). Setting one clears the other
      // (enforced in the UI handlers) so they never combine into an AND here.
      if (customStart || customEnd) {
        if (customStart) params.start_time = customStart;
        if (customEnd) params.end_time = customEnd;
      } else if (selectedDate) {
        const start = Math.floor(new Date(selectedDate).getTime() / 1000);
        params.start_time = start.toString();
        params.end_time = (start + 86400).toString();
      }

      console.log('Final params:', params);
      const data = await getComprehensiveTimeline(taskId, params);
      console.log('Received timeline data:', data);
      
      // Debug: Check if timeline exists and has data
      if (!data) {
        console.error('Timeline data is null or undefined');
        setError('Received empty timeline data');
        return;
      }
      
      if (!data.timeline || data.timeline.length === 0) {
        console.warn('Timeline is empty, no events found');
        setTimelineData(data);
        return;
      }
      
      console.log('Timeline has', data.timeline.length, 'events');
      console.log('Sample event:', data.timeline[0]);

      // Stamp each event with the bucket used to produce it, so cluster
      // detail/AI calls downstream use the same window boundary end-to-end.
      if (isClustered && Array.isArray(data.timeline)) {
        data.timeline = data.timeline.map((ev) => ({ ...ev, bucket_seconds: effectiveBucket }));
      }

      setTimelineData(data);
      if (virtuosoRef.current) virtuosoRef.current.scrollToIndex({ index: 0 });
    } catch (err) {
      console.error('Failed to fetch timeline:', err);
      setError(err.message || 'Failed to load timeline data');
    } finally {
      setLoading(false);
    }
  }, [taskId, currentPage, pageSize, eventType, selectedDate, customStart, customEnd, isClustered, effectiveBucket]);

  useEffect(() => {
    if (taskId) {
        getTimelineDistribution(taskId).then(timelineDist => {
            if (timelineDist && timelineDist.distribution) {
                const distMap = {};
                timelineDist.distribution.forEach(item => {
                  if (!distMap[item.event_date]) distMap[item.event_date] = { date: item.event_date, CREATED: 0, MODIFIED: 0, DELETED: 0, OTHER: 0 };
                  const type = ['CREATED', 'MODIFIED', 'DELETED'].includes(item.event_type) ? item.event_type : 'OTHER';
                  distMap[item.event_date][type] += item.count;
                });
                setDistributionData(Object.values(distMap).sort((a,b) => a.date.localeCompare(b.date)));
            }
        }).catch(err => console.error('Dist error', err));
    }
  }, [taskId]);

  // 自动分析重要的事件簇
  useEffect(() => {
    fetchTimeline();
  }, [fetchTimeline]);
  
  // 自动分析事件簇（AI 研判摘要）。
  //
  // 旧实现把 analyzingClusters / analyzedClusters / analysisInProgress 这些
  // 会自身变化的 state 放进了依赖数组，且每次分析完都无条件 fetchTimeline()，
  // 形成了"分析完成 -> 刷新 -> timelineData 变化 -> 重新分析"的无限刷新循环。
  //
  // 修复要点：用 ref 记录"已经为哪一批可见簇尝试过分析"的签名。effect 仍然
  // 依赖 timelineData（这样首次拿到数据时能启动分析），但只要签名没变就直接
  // return，不再重复分析。只有当用户翻页/改筛选导致可见簇集合真正变化时，
  // 签名才会变，才会对新一批簇再做一次分析。分析成功后的刷新会改变
  // timelineData 引用并重跑本 effect，但由于可见簇键集合不变 -> 签名不变 ->
  // 立即 return，循环就此终止。
  const autoAnalyzedSignatureRef = useRef('');

  useEffect(() => {
    if (!taskId || !timelineData?.timeline?.length) return;

    // 签名 = 查询参数 + 当前可见簇的键集合。后端分析成功会给同一批簇补上
    // llm_summary，但 timestamp/event_type/parent_directory 不变，所以刷新
    // 后签名一致，effect 早早 return。
    const visibleKeys = timelineData.timeline
      .map(ev => `${ev.timestamp}-${ev.event_type}-${ev.parent_directory}`)
      .sort()
      .join('|');
    const signature = `${taskId}|${currentPage}|${eventType}|${selectedDate}|${customStart}|${customEnd}|${isClustered}|${effectiveBucket}|${visibleKeys}`;

    if (autoAnalyzedSignatureRef.current === signature) return;
    autoAnalyzedSignatureRef.current = signature;

    const autoAnalyzeClusters = async () => {
      // 筛选还没有 AI 摘要的簇。当开启聚合视图时，每个分组项（哪怕只有 1 个
      // 事件）都是一个有意义的簇，都应纳入自动分析（不再用 cluster_count > 1
      // 门槛，否则单事件簇永远不被分析）。仍按 cluster_count 降序、每次最多
      // 5 个限流，避免请求量激增。
      const unanalyzedClusters = timelineData.timeline.filter(event => !event.llm_summary);
      if (unanalyzedClusters.length === 0) return;

      unanalyzedClusters.sort((a, b) => (b.cluster_count || 0) - (a.cluster_count || 0));
      const clustersToAnalyze = unanalyzedClusters.slice(0, 5);

      let analyzedAny = false;
      for (const cluster of clustersToAnalyze) {
        const clusterKey = `${cluster.timestamp}-${cluster.event_type}-${cluster.parent_directory}`;
        setAnalyzingClusters(prev => new Set(prev).add(clusterKey));
        try {
          await analyzeEventCluster(taskId, cluster);
          analyzedAny = true;
        } catch (error) {
          console.error('Auto-analyze failed for cluster:', clusterKey, error);
        } finally {
          setAnalyzingClusters(prev => {
            const next = new Set(prev);
            next.delete(clusterKey);
            return next;
          });
        }
        // 节流，避免请求过密
        await new Promise(resolve => setTimeout(resolve, 2000));
      }

      // 只有真的分析了新簇才刷新一次，把 AI 摘要显示出来。这次刷新会改变
      // timelineData 引用并重跑本 effect，但签名不变，所以会立即 return，
      // 不会再次触发分析。
      if (analyzedAny) {
        fetchTimeline();
        dispatch(setRefreshFlag({ type: 'clusters' }));
      }
    };

    // 延迟执行自动分析，确保数据已加载
    const timer = setTimeout(autoAnalyzeClusters, 1000);
    return () => clearTimeout(timer);
  }, [taskId, timelineData, currentPage, eventType, selectedDate, customStart, customEnd, isClustered, effectiveBucket, fetchTimeline, dispatch]);

  // Cluster Detail Fetching with Search Support
  const fetchClusterDetails = useCallback(async (cluster, search) => {
    if (!cluster) return;
    setLoadingDetails(true);
    try {
        // Use the same bucket that produced the cluster so the detail query
        // resolves exactly the same window boundary.
        const bucket = cluster.bucket_seconds || effectiveBucket;
        const window = Math.floor(cluster.timestamp / bucket);
        const data = await getTimelineDetails(taskId, {
            window,
            type: cluster.event_type,
            dir: cluster.parent_directory,
            search: search || undefined,
            bucket,
            limit: 5000
        });
        setClusterDetails(data.events || []);
    } catch (err) {
        console.error('Failed to fetch cluster details', err);
    } finally {
        setLoadingDetails(false);
    }
  }, [taskId, effectiveBucket]);

  // Handle Initial Open
  const handleOpenCluster = (event) => {
    setSelectedCluster(event);
    setDrawerSearch('');
    fetchClusterDetails(event, '');
  };

  // Debounced search for Drawer
  useEffect(() => {
    if (!selectedCluster) return;
    const timer = setTimeout(() => {
        fetchClusterDetails(selectedCluster, drawerSearch);
    }, 350);
    return () => clearTimeout(timer);
  }, [drawerSearch, selectedCluster, fetchClusterDetails]);
  
  // Handle AI Analysis for Event Clusters
  const handleAnalyzeCluster = async (cluster) => {
    // 验证 taskId
    if (!taskId) {
      console.error('[AI分析] taskId 为空，无法分析');
      alert('错误: 未选择任务。请先从任务页面选择一个任务。');
      return;
    }

    const clusterKey = `${cluster.timestamp}-${cluster.event_type}-${cluster.parent_directory}`;
    setAnalyzingClusters(prev => new Set(prev).add(clusterKey));

    try {
      console.log('[AI分析] 开始分析 cluster:', clusterKey);
      console.log('[AI分析] cluster 数据:', cluster);

      const result = await analyzeEventCluster(taskId, cluster);
      console.log('[AI分析] 分析成功:', result);

      // Refresh timeline data to show AI analysis results
      fetchTimeline();
      // Set refresh flag to notify CaseIntelligence to refresh
      dispatch(setRefreshFlag({ type: 'clusters' }));
    } catch (error) {
      console.error('[AI分析] 分析失败:', error);

      // 向用户显示详细错误
      let errorMsg = 'AI 分析失败';
      if (error.message) {
        errorMsg += `: ${error.message}`;
      }
      if (error.data) {
        errorMsg += `\n详细信息: ${JSON.stringify(error.data)}`;
      }
      if (error.status) {
        errorMsg += `\nHTTP 状态码: ${error.status}`;
      }

      alert(errorMsg);
    } finally {
      setAnalyzingClusters(prev => {
        const newSet = new Set(prev);
        newSet.delete(clusterKey);
        return newSet;
      });
    }
  };
  
  const handleReanalyzeCluster = async (cluster) => {
    // 验证 taskId
    if (!taskId) {
      console.error('[AI重新分析] taskId 为空，无法分析');
      alert('错误: 未选择任务。请先从任务页面选择一个任务。');
      return;
    }

    const clusterKey = `${cluster.timestamp}-${cluster.event_type}-${cluster.parent_directory}`;
    setAnalyzingClusters(prev => new Set(prev).add(clusterKey));

    try {
      console.log('[AI重新分析] 开始重新分析 cluster:', clusterKey);
      console.log('[AI重新分析] cluster 数据:', cluster);

      const result = await reanalyzeEventCluster(taskId, cluster);
      console.log('[AI重新分析] 分析成功:', result);

      // Refresh timeline data to show updated AI analysis results
      fetchTimeline();
      // Set refresh flag to notify CaseIntelligence to refresh
      dispatch(setRefreshFlag({ type: 'clusters' }));
    } catch (error) {
      console.error('[AI重新分析] 分析失败:', error);

      // 向用户显示详细错误
      let errorMsg = 'AI 重新分析失败';
      if (error.message) {
        errorMsg += `: ${error.message}`;
      }
      if (error.data) {
        errorMsg += `\n详细信息: ${JSON.stringify(error.data)}`;
      }
      if (error.status) {
        errorMsg += `\nHTTP 状态码: ${error.status}`;
      }

      alert(errorMsg);
    } finally {
      setAnalyzingClusters(prev => {
        const newSet = new Set(prev);
        newSet.delete(clusterKey);
        return newSet;
      });
    }
  };

  const handleBarClick = (data) => {
    if (data && data.activePayload && data.activePayload[0]) {
      const date = data.activePayload[0].payload.date;
      // Day pick is mutually exclusive with custom start/end time range.
      updateParams({ date: date === selectedDate ? '' : date, start: '', end: '', page: 1 });
    }
  };

  const resetFilters = () => {
    updateParams({ type: '', date: '', start: '', end: '', page: 1, cluster: 'true' });
  };

  // Apply a quick time preset, anchored to the LATEST event date in the task
  // (forensic images are captured at a point in the past, so "last 24h" is
  // relative to that, not the real wall clock). Clears the day pick since the
  // two filters are mutually exclusive.
  const applyTimePreset = (presetSeconds) => {
    if (!distributionData || distributionData.length === 0) return;
    const lastDate = distributionData[distributionData.length - 1].date;
    const endSec = Math.floor(new Date(lastDate).getTime() / 1000) + 86400; // end of that day
    const startSec = endSec - presetSeconds;
    updateParams({ start: String(startSec), end: String(endSec), date: '', page: 1 });
  };

  // Handler for the custom start/end datetime-local inputs.
  const handleCustomTimeChange = (field, value) => {
    const sec = fromDatetimeLocal(value);
    if (sec === null) {
      // empty input -> clear that bound, keep the other
      updateParams({ [field]: '', date: '', page: 1 });
    } else {
      updateParams({ [field]: String(sec), date: '', page: 1 });
    }
  };

  // 计算事件数据
  const events = useMemo(() => {
    console.log('Timeline data:', timelineData);
    return timelineData?.timeline || [];
  }, [timelineData]);
  
  // 计算元数据
  const metadata = useMemo(() => {
    return timelineData?.metadata || {};
  }, [timelineData]);
  
  // 计算总事件数和总页数
  const totalCount = useMemo(() => {
    return metadata.total_events || 0;
  }, [metadata]);
  
  const totalPages = useMemo(() => {
    return Math.ceil(totalCount / pageSize);
  }, [totalCount, pageSize]);

  if (!taskId) return <div className="p-8 text-center text-slate-500">Please select a task...</div>;

  return (
    <div className="h-[calc(100vh-140px)] flex flex-col space-y-4 overflow-hidden relative">
      {/* Investigation Drawer */}
      <ClusterInvestigationDrawer
        selectedCluster={selectedCluster}
        onClose={() => setSelectedCluster(null)}
        onAnalyze={handleAnalyzeCluster}
        onReanalyze={handleReanalyzeCluster}
        analyzingClusters={analyzingClusters}
        clusterDetails={clusterDetails}
        loadingDetails={loadingDetails}
        drawerSearch={drawerSearch}
        setDrawerSearch={setDrawerSearch}
      />


      {/* Header Block */}
      <div className="flex-shrink-0 flex flex-col md:flex-row md:items-center md:justify-between gap-4 px-1">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{t('timeline.title')}</h1>
          <p className="text-[10px] text-slate-500 font-mono mt-0.5">{currentTask?.image_path || taskId}</p>
        </div>
        <div className="flex items-center space-x-2 bg-slate-100 p-1 rounded-xl">
           <Button variant={viewMode === 'timeline' ? 'primary' : 'ghost'} size="sm" onClick={() => updateParams({ view: 'timeline' })} icon={Clock}>{t('timeline.view.list')}</Button>
           <Button variant={viewMode === 'table' ? 'primary' : 'ghost'} size="sm" onClick={() => updateParams({ view: 'table' })} icon={FileText}>{t('timeline.view.table')}</Button>
        </div>
      </div>

      <div className="flex-1 flex flex-col lg:flex-row gap-6 min-h-0 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-full lg:w-80 flex flex-col min-h-0 space-y-4 overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-slate-200">
          <div className="flex-shrink-0 bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden flex flex-col">
            <div className="p-3 border-b border-slate-50 flex justify-between items-center bg-slate-50/30">
                <span className="text-[11px] font-bold text-slate-600 flex items-center uppercase tracking-wider"><Calendar className="w-3.5 h-3.5 mr-1.5 text-primary-500"/> {t('timeline.stats.distribution')}</span>
                {selectedDate && <button onClick={() => updateParams({date: ''})} className="text-[10px] bg-primary-50 text-primary-600 px-2 py-0.5 rounded-full font-bold hover:bg-primary-100 transition-colors">{selectedDate} ×</button>}
            </div>
            <div className="p-2 overflow-x-auto scrollbar-hide">
              <div className="h-32" style={{ minWidth: (distributionData?.length * 20 || 300) + 'px' }}>
                {distributionData ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={distributionData} onClick={handleBarClick} margin={{top: 5, right: 5, left: -25, bottom: 0}}>
                      <XAxis dataKey="date" hide />
                      <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', fontSize: '10px', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                      <Bar dataKey="CREATED" stackId="a" fill="#10b981" radius={[2, 2, 0, 0]} />
                      <Bar dataKey="MODIFIED" stackId="a" fill="#3b82f6" />
                      <Bar dataKey="DELETED" stackId="a" fill="#ef4444" />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="h-full flex items-center justify-center text-[10px] text-slate-400">Syncing...</div>}
              </div>
            </div>
          </div>

          {/* Time Range Filter — quick presets + custom start/end.
              Mutually exclusive with the day pick (clicking a bar or setting a
              custom range clears the other) to avoid conflicting WHERE clauses. */}
          <Card title={t('timeline.filter.timespan')} icon={History} className="bg-white flex-shrink-0">
            <div className="space-y-3 p-1">
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  onClick={() => applyTimePreset(3600)}
                  disabled={!distributionData?.length}
                  className="text-[10px] font-bold text-slate-600 hover:text-white hover:bg-primary-500 bg-slate-100 px-2 py-1.5 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t('timeline.filter.preset.1h')}
                </button>
                <button
                  onClick={() => applyTimePreset(86400)}
                  disabled={!distributionData?.length}
                  className="text-[10px] font-bold text-slate-600 hover:text-white hover:bg-primary-500 bg-slate-100 px-2 py-1.5 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t('timeline.filter.preset.24h')}
                </button>
                <button
                  onClick={() => applyTimePreset(86400 * 7)}
                  disabled={!distributionData?.length}
                  className="text-[10px] font-bold text-slate-600 hover:text-white hover:bg-primary-500 bg-slate-100 px-2 py-1.5 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t('timeline.filter.preset.7d')}
                </button>
                <button
                  onClick={() => applyTimePreset(86400 * 30)}
                  disabled={!distributionData?.length}
                  className="text-[10px] font-bold text-slate-600 hover:text-white hover:bg-primary-500 bg-slate-100 px-2 py-1.5 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t('timeline.filter.preset.30d')}
                </button>
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-slate-400 uppercase block tracking-widest">{t('timeline.filter.custom_start')}</label>
                <input
                  type="datetime-local"
                  value={toDatetimeLocal(customStart ? parseInt(customStart) : null)}
                  onChange={(e) => handleCustomTimeChange('start', e.target.value)}
                  className="w-full rounded-lg border-slate-200 text-xs shadow-sm focus:ring-primary-500"
                />
                <label className="text-[10px] font-bold text-slate-400 uppercase block tracking-widest mt-1">{t('timeline.filter.custom_end')}</label>
                <input
                  type="datetime-local"
                  value={toDatetimeLocal(customEnd ? parseInt(customEnd) : null)}
                  onChange={(e) => handleCustomTimeChange('end', e.target.value)}
                  className="w-full rounded-lg border-slate-200 text-xs shadow-sm focus:ring-primary-500"
                />
              </div>

              {(customStart || customEnd) && (
                <button onClick={() => updateParams({ start: '', end: '', page: 1 })} className="text-[10px] text-rose-500 hover:text-rose-700 font-bold flex items-center gap-1">
                  <X size={11} /> {t('timeline.filter.clear_time')}
                </button>
              )}
            </div>
          </Card>

          <Card title={t('timeline.filter.type')} icon={Filter} className="bg-white flex-shrink-0">
            <div className="space-y-4 p-1">
              <div>
                <label className="text-[10px] font-bold text-slate-400 uppercase mb-1.5 block tracking-widest">{t('timeline.filter.type')}</label>
                <select 
                    value={eventType} 
                    onChange={(e) => updateParams({ type: e.target.value, page: 1 })}
                    className="w-full rounded-lg border-slate-200 text-xs shadow-sm focus:ring-primary-500"
                >
                    <option value="">{t('timeline.filter.all')}</option>
                    <option value="CREATED">{t('timeline.filter.created')}</option>
                    <option value="MODIFIED">{t('timeline.filter.modified')}</option>
                    <option value="DELETED">{t('timeline.filter.deleted')}</option>
                </select>
              </div>

              <div className="flex items-center space-x-3 p-2.5 bg-slate-50/50 rounded-xl border border-slate-100">
                <input
                  type="checkbox"
                  checked={isClustered}
                  onChange={(e) => updateParams({ cluster: e.target.checked ? 'true' : 'false', page: 1 })}
                  className="rounded text-primary-600 w-4 h-4 cursor-pointer"
                />
                <div className="text-xs">
                  <div className="font-bold text-slate-700 leading-none">{t('timeline.filter.cluster')}</div>
                  <div className="text-slate-400 mt-1 scale-90 origin-left">{t('timeline.filter.cluster_desc')}</div>
                </div>
              </div>

              {/* Aggregation window selector. Only meaningful when clustering is
                  on. 'auto' picks a window from the overall event span so very
                  wide images stay navigable; the fixed options give manual control. */}
              {isClustered && (
                <div className="p-2.5 bg-slate-50/50 rounded-xl border border-slate-100">
                  <label className="text-[10px] font-bold text-slate-400 uppercase mb-1.5 flex items-center tracking-widest"><Gauge className="w-3 h-3 mr-1.5 text-primary-400" />{t('timeline.filter.bucket')}</label>
                  <select
                    value={bucketParam}
                    onChange={(e) => updateParams({ bucket: e.target.value, page: 1 })}
                    className="w-full rounded-lg border-slate-200 text-xs shadow-sm focus:ring-primary-500"
                  >
                    <option value="auto">{t('timeline.filter.bucket.auto')}</option>
                    <option value="60">1 {t('timeline.filter.bucket.minute')}</option>
                    <option value="300">5 {t('timeline.filter.bucket.minutes')}</option>
                    <option value="900">15 {t('timeline.filter.bucket.minutes')}</option>
                    <option value="1800">30 {t('timeline.filter.bucket.minutes')}</option>
                    <option value="3600">1 {t('timeline.filter.bucket.hour')}</option>
                    <option value="21600">6 {t('timeline.filter.bucket.hours')}</option>
                  </select>
                  {bucketParam === 'auto' && (
                    <div className="text-[9px] text-primary-500 mt-1 font-mono">≈ {t('timeline.filter.bucket.resolved')}: {effectiveBucket}s</div>
                  )}
                </div>
              )}

              <div className="pt-2 px-1">
                <div className="flex justify-between text-[11px] text-slate-500">
                    <span>{t('timeline.stats.matches')}:</span>
                    <span className="font-bold text-slate-900">{totalCount.toLocaleString()}</span>
                </div>
                <div className="flex justify-between text-[11px] text-slate-500 mt-1.5">
                    <span>{t('timeline.stats.navigator')}:</span>
                    <span className="font-mono text-primary-600 font-bold">{currentPage} / {totalPages || 1}</span>
                </div>
              </div>

              {(eventType || selectedDate || customStart || customEnd) && (
                <Button variant="outline" size="sm" fullWidth onClick={resetFilters} icon={X} className="text-[11px] border-dashed">{t('timeline.filter.reset')}</Button>
              )}
            </div>
          </Card>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col min-h-0 bg-white rounded-2xl border border-slate-100 shadow-sm relative overflow-hidden">
          {loading && (
            <div className="absolute inset-0 bg-white/80 z-50 flex flex-col items-center justify-center backdrop-blur-sm">
                <Spinner size="lg" />
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mt-3">{t('timeline.status.loading')}</span>
            </div>
          )}
          
          <div className="flex-1 min-h-0 overflow-hidden">
            {events.length === 0 && !loading ? (
                <div className="h-full flex items-center justify-center text-slate-400 italic text-sm">{t('timeline.status.empty')}</div>
            ) : viewMode === 'timeline' ? (
                <Virtuoso
                  ref={virtuosoRef}
                  data={events}
                  style={{ height: '100%' }}
                  itemContent={(index, event) => {
                    // When clustering is enabled, every grouped item is a cluster
                    // (even single-event ones). The backend groups by
                    // (parent_directory, time_window, event_type); a group with
                    // cluster_count === 1 is still a meaningful cluster. Treating
                    // only count>1 as clusters left ~62% of groups rendered as
                    // flat events with no AI analysis / directory / click support.
                    const isCluster = isClustered;
                    const isMultiEventCluster = (event.cluster_count || 1) > 1;
                    return (
                      <div className="px-6 py-1.5">
                        <div className="relative ml-4 pl-8 border-l-2 border-slate-100 py-2 hover:border-primary-200 transition-colors">
                          <div className={`absolute -left-[9px] top-6 w-4 h-4 rounded-full border-2 border-white shadow-sm z-10 ${
                            event.event_type === 'CREATED' ? 'bg-emerald-500' :
                            event.event_type === 'MODIFIED' ? 'bg-blue-500' :
                            event.event_type === 'DELETED' ? 'bg-rose-500' : 'bg-slate-400'
                          }`} />
                          
                          <div 
                            className={`bg-white rounded-xl border ${isCluster ? 'border-primary-200 bg-primary-50/5 cursor-pointer' : 'border-slate-100'} p-4 shadow-sm hover:shadow-md transition-all group`}
                            onClick={() => isCluster && handleOpenCluster(event)}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                              <div className="flex items-center space-x-2">
                                <span className="text-[12px] font-bold text-slate-800 font-mono tracking-tight">
                                  {isMultiEventCluster
                                    ? `${formatTimeOnly(event.timestamp)} - ${formatTimeOnly(event.end_timestamp)}`
                                    : formatTimestamp(event.timestamp)}
                                </span>
                                <Badge variant={
                                  event.event_type === 'CREATED' ? 'green' :
                                  event.event_type === 'MODIFIED' ? 'blue' :
                                  event.event_type === 'DELETED' ? 'red' : 'gray'
                                } className="text-[9px] px-1.5 py-0 uppercase font-black">
                                  {event.event_type}
                                </Badge>
                                {isMultiEventCluster && (
                                  <Badge variant="blue" icon={Layers} className="text-[9px] px-1.5 py-0 font-bold">
                                    {event.cluster_count} {t('timeline.node.items')}
                                  </Badge>
                                )}
                                {isCluster && event.llm_summary && (
                                  <Badge variant="green" icon={CheckCircle} className="text-[9px] px-1.5 py-0 font-bold">
                                    AI Analyzed
                                  </Badge>
                                )}
                              </div>
                              {isCluster && (
                                <div className="flex items-center gap-2">
                                  {!event.llm_summary ? (
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleAnalyzeCluster(event);
                                      }}
                                      disabled={analyzingClusters.has(`${event.timestamp}-${event.event_type}-${event.parent_directory}`)}
                                      className="text-[10px] font-bold text-purple-600 hover:text-purple-700 px-2 py-1 bg-purple-50 hover:bg-purple-100 rounded-lg transition-colors flex items-center gap-1"
                                    >
                                      {analyzingClusters.has(`${event.timestamp}-${event.event_type}-${event.parent_directory}`) ? (
                                        <>
                                          <Spinner size="sm" />
                                          <span>分析中...</span>
                                        </>
                                      ) : (
                                        <>
                                          <Brain size={12} />
                                          <span>AI分析</span>
                                        </>
                                      )}
                                    </button>
                                  ) : (
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleReanalyzeCluster(event);
                                      }}
                                      disabled={analyzingClusters.has(`${event.timestamp}-${event.event_type}-${event.parent_directory}`)}
                                      className="text-[10px] font-bold text-amber-600 hover:text-amber-700 px-2 py-1 bg-amber-50 hover:bg-amber-100 rounded-lg transition-colors flex items-center gap-1"
                                    >
                                      {analyzingClusters.has(`${event.timestamp}-${event.event_type}-${event.parent_directory}`) ? (
                                        <>
                                          <Spinner size="sm" />
                                          <span>分析中...</span>
                                        </>
                                      ) : (
                                        <>
                                          <RefreshCw size={12} />
                                          <span>重新分析</span>
                                        </>
                                      )}
                                    </button>
                                  )}
                                  <ArrowRight size={14} className="text-primary-400 opacity-0 group-hover:opacity-100 transition-opacity" />
                                </div>
                              )}
                              {!isCluster && <span className="text-[10px] font-mono text-slate-400 opacity-60">ID:{event.inode}</span>}
                            </div>
                            
                            {isCluster ? (
                              <div className="space-y-1.5">
                                <div className="flex items-center text-[11px] font-bold text-slate-500">
                                  <Folder className="w-3 h-3 mr-1.5 text-primary-400" /> {event.parent_directory || '/'}
                                </div>
                                <p className="text-[11px] text-slate-600 truncate bg-slate-50 p-1.5 rounded-lg border border-slate-100 border-dashed font-mono">
                                  {t('timeline.node.sample')}: {event.file_path.split('/').pop()}
                                </p>
                                {event.llm_summary && (
                                  <div className="bg-green-50 border border-green-100 rounded-lg p-2">
                                    <p className="text-[11px] text-green-800 font-medium whitespace-pre-wrap break-words">{event.llm_summary}</p>
                                    {event.llm_keywords && (
                                      <div className="flex flex-wrap gap-1 mt-1">
                                        {event.llm_keywords.split(',').map((keyword, idx) => (
                                          <span key={idx} className="text-[9px] bg-white px-1.5 py-0.5 rounded-full border border-green-200 text-green-600">
                                            {keyword.trim()}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <p className="text-[13px] text-slate-700 font-medium break-all mb-1 leading-relaxed">
                                {event.file_path}
                              </p>
                            )}
                            
                            <div className="flex items-center space-x-4 text-[10px] text-slate-400 mt-2.5 pt-2 border-t border-slate-50">
                               <div className="flex items-center">
                                <FileText className="w-3 h-3 mr-1 opacity-70" />
                                {isMultiEventCluster && <span className="mr-1">[{event.cluster_count} {t('timeline.node.items')}]</span>}
                                {formatFileSize(event.file_size)} {isCluster ? `(${t('timeline.node.total')})` : ''}
                              </div>
                              {event.file_type && <span className="bg-slate-100 px-1.5 py-0.5 rounded text-[9px] font-black uppercase text-slate-500 tracking-tighter">{event.file_type}</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  }}
                />
            ) : (
                <div className="h-full overflow-auto scrollbar-thin scrollbar-thumb-slate-200">
                    <table className="min-w-full divide-y divide-slate-200">
                      <thead className="bg-slate-50 sticky top-0 z-10">
                        <tr>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">{t('timeline.stats.matches')}</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">{t('timeline.filter.type')}</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">Path</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">Size</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-slate-100">
                        {events.map((event, idx) => (
                          <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                            <td className="px-4 py-3 whitespace-nowrap text-[11px] font-mono text-slate-700">{formatTimestamp(event.timestamp)}</td>
                            <td className="px-4 py-3">
                                <Badge variant={event.event_type === 'CREATED' ? 'green' : event.event_type === 'MODIFIED' ? 'blue' : 'red'} className="text-[9px] font-black">{event.event_type}</Badge>
                            </td>
                            <td className="px-4 py-3 text-[11px] text-slate-600 truncate max-w-sm font-medium">{event.file_path}</td>
                            <td className="px-4 py-3 text-[11px] text-slate-500 font-mono">{formatFileSize(event.file_size)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                </div>
            )}
          </div>

          {/* Sticky Footer Pagination */}
          <footer className="flex-shrink-0 flex items-center justify-between border-t border-slate-100 p-3 bg-slate-50/80 backdrop-blur-sm">
                <Button variant="ghost" size="sm" disabled={currentPage === 1} onClick={() => updateParams({ page: currentPage - 1 })} icon={ChevronLeft} className="hover:bg-white shadow-sm">PREV</Button>
                <div className="text-[10px] text-slate-500 font-black bg-white px-4 py-1.5 rounded-full border border-slate-200 shadow-sm tracking-widest uppercase">
                    {t('timeline.stats.navigator')} {currentPage} / {totalPages || 1}
                </div>
                <Button variant="ghost" size="sm" disabled={currentPage === totalPages || totalPages === 0} onClick={() => updateParams({ page: currentPage + 1 })} icon={ChevronRight} iconPosition="right" className="hover:bg-white shadow-sm">NEXT</Button>
          </footer>
        </main>
      </div>
    </div>
  );
};

export default Timeline;
