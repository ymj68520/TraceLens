import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  FileDown,
  FileJson,
  FileText,
  Info,
  Layers,
  ListChecks,
  ListPlus,
  RefreshCw,
  Scale,
  ScanSearch,
  Search,
  Star,
  StarOff,
} from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks } from '../store/taskSlice';
import { clearRefreshFlag, setRefreshFlag } from '../store/intelligenceSlice';
import { getTaskResults } from '../services/taskService';
import { getAnalyzedEventClusters } from '../services/forensicsService';
import { analyzeContent, toggleFileRelevance } from '../services/llmService';
import { saveCaseDescription } from '../services/caseAnalysisService';
import { pythonApi } from '../services/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import { PageHeader, Segmented, SkeletonTable, StatStrip } from '../components/ui/PageScaffold';
import { basename, cx, errorMessage } from '../lib/utils';
import { useDebouncedValue, useUrlState } from '../hooks/useUrlState';
import QueuePanel from './analysis/QueuePanel';
import HistoryPanel from './analysis/HistoryPanel';
import CompareView from './analysis/CompareView';
import ResultDetailDrawer from './analysis/ResultDetailDrawer';
import { useAnalysisQueue, type QueueSettledSummary } from './analysis/useAnalysisQueue';
import { useAnalysisHistory } from './analysis/history';
import { exportResultCSV, exportResultJSON, relevantFileCount, shortTaskId } from './analysis/exporters';
import type {
  AnalysisHistoryEntry,
  ClusterRow,
  DrawerTarget,
  FileAnalysisResult,
  LlmDescriptionRow,
  QueueEntry,
  QueueItem,
  QueueRunResult,
  TaskQueueItem,
  TaskResultSnapshot,
} from './analysis/types';

type ViewMode = 'all' | 'files' | 'clusters';

const entryLabel = (item: QueueItem): string =>
  item.kind === 'task' ? item.label : basename(item.filePath);

export default function AnalysisCenter() {
  const [searchParams] = useSearchParams();
  const urlTaskId = searchParams.get('task_id') || searchParams.get('taskId');
  const caseId = searchParams.get('case_id');
  const activeContextId = caseId || urlTaskId;

  const dispatch = useAppDispatch();
  const toast = useToast();
  const { tasks } = useAppSelector((state) => state.tasks);
  const { refreshFlags } = useAppSelector((state) => state.intelligence);

  const [caseDescription, setCaseDescription] = useState('');
  const [llmResults, setLlmResults] = useState<{ descriptions: LlmDescriptionRow[] } | null>(null);
  const [eventClusters, setEventClusters] = useState<ClusterRow[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('all');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 视图模式持久化到 URL（?mode=queue|compare）。
  const [mode, setMode] = useUrlState('mode', 'queue');

  // 队列 runner 回调里的 toast 通过 ref 取最新实例，避免回调身份抖动。
  const toastRef = useRef(toast);
  useEffect(() => {
    toastRef.current = toast;
  }, [toast]);

  const currentTask = tasks.find((t) => t.id === activeContextId);
  const filesDbPath = useMemo(
    () => ((currentTask as { output_files_db?: string } | undefined)?.output_files_db ?? null),
    [currentTask],
  );

  /* ------------------------------ 历史记录 ------------------------------ */

  const history = useAnalysisHistory();

  /* ------------------------------ 数据加载 ------------------------------ */

  useEffect(() => {
    void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
  }, [dispatch]);

  const fetchData = useCallback(async (): Promise<boolean> => {
    if (!activeContextId) return false;
    setLoading(true);
    let resultsOk = true;
    try {
      try {
        const results = (await getTaskResults(activeContextId)) as {
          llm_results?: { descriptions?: LlmDescriptionRow[] };
        };
        setLlmResults(results.llm_results ? { descriptions: results.llm_results.descriptions ?? [] } : { descriptions: [] });
        setLoadError(null);
      } catch (err) {
        resultsOk = false;
        setLlmResults({ descriptions: [] });
        setLoadError(errorMessage(err));
      }

      try {
        const clusterData = (await getAnalyzedEventClusters(activeContextId)) as { clusters?: ClusterRow[] };
        setEventClusters(clusterData?.clusters ?? []);
      } catch {
        setEventClusters([]);
      }
    } finally {
      setLoading(false);
    }
    return resultsOk;
  }, [activeContextId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (refreshFlags.files || refreshFlags.clusters) {
      void fetchData();
      if (refreshFlags.files) dispatch(clearRefreshFlag({ type: 'files' }));
      if (refreshFlags.clusters) dispatch(clearRefreshFlag({ type: 'clusters' }));
    }
  }, [refreshFlags, fetchData, dispatch]);

  const handleRetryFetch = async () => {
    const ok = await fetchData();
    if (ok) toast.success('研判数据已重新加载');
    else toast.error('重试仍失败，请检查后端服务是否可用');
  };

  /* ------------------------------ 案情描述 ------------------------------ */

  const saveDescription = async () => {
    if (!activeContextId || !caseDescription.trim()) return;
    try {
      await saveCaseDescription(activeContextId, caseDescription.trim());
      toast.success('案情描述已保存');
    } catch (err) {
      toast.error(`保存失败：${errorMessage(err)}`);
    }
  };

  /* --------------------------- 检索与过滤 ------------------------------ */

  const debouncedSearch = useDebouncedValue(searchQuery, 250);

  const filteredDescriptions = useMemo(() => {
    const items = llmResults?.descriptions || [];
    if (!debouncedSearch) return items;
    const q = debouncedSearch.toLowerCase();
    return items.filter(
      (item) => item.file_path?.toLowerCase().includes(q) || item.summary?.toLowerCase().includes(q),
    );
  }, [llmResults, debouncedSearch]);

  const filteredClusters = useMemo(() => {
    if (!debouncedSearch) return eventClusters;
    const q = debouncedSearch.toLowerCase();
    return eventClusters.filter(
      (c) =>
        c.event_type?.toLowerCase().includes(q) ||
        c.parent_directory?.toLowerCase().includes(q) ||
        c.llm_summary?.toLowerCase().includes(q),
    );
  }, [eventClusters, debouncedSearch]);

  /* ------------------------------ 批量队列 ------------------------------ */

  const historyRef = useRef(history.record);
  useEffect(() => {
    historyRef.current = history.record;
  }, [history.record]);

  const runQueueItem = useCallback(
    async (item: QueueItem): Promise<QueueRunResult> => {
      if (item.kind === 'task') {
        // 沿用研判中心现有的结果收集逻辑：任务结果 + 已分析事件簇。
        let descriptions: LlmDescriptionRow[] = [];
        let clusters: ClusterRow[] = [];
        let failures = 0;
        try {
          const results = (await getTaskResults(item.taskId)) as {
            llm_results?: { descriptions?: LlmDescriptionRow[] };
          };
          descriptions = results.llm_results?.descriptions ?? [];
        } catch {
          failures += 1;
        }
        try {
          const clusterData = (await getAnalyzedEventClusters(item.taskId)) as { clusters?: ClusterRow[] };
          clusters = clusterData?.clusters ?? [];
        } catch {
          failures += 1;
        }
        if (failures === 2) throw new Error('任务结果与事件簇接口均不可用');

        const snapshot: TaskResultSnapshot = {
          taskId: item.taskId,
          imagePath: item.imagePath,
          descriptions,
          clusters,
          finishedAt: Date.now(),
        };
        historyRef.current({
          taskId: item.taskId,
          imagePath: item.imagePath,
          savedAt: new Date().toISOString(),
          fileCount: descriptions.length,
          clusterCount: clusters.length,
          relevantCount: relevantFileCount(descriptions),
        });
        return { kind: 'task', snapshot };
      }

      // 单文件条目：与文件页一致走 analyzeContent，完成后触发既有刷新标记。
      const result = (await analyzeContent({
        taskId: item.taskId,
        filePath: item.filePath,
        filesDbPath: item.filesDbPath ?? null,
      })) as { analysis?: FileAnalysisResult };
      if (!result?.analysis) throw new Error('接口未返回分析结果');
      dispatch(setRefreshFlag({ type: 'files' }));
      return { kind: 'file', analysis: result.analysis };
    },
    [dispatch],
  );

  const handleItemFailed = useCallback((entry: QueueEntry) => {
    toastRef.current.error(`研判失败：${entryLabel(entry.item)}：${entry.error ?? '未知错误'}`);
  }, []);

  const handleAllSettled = useCallback((summary: QueueSettledSummary) => {
    if (summary.failed === 0) {
      toastRef.current.success(`批量研判完成：${summary.done} 项全部成功`);
    } else {
      toastRef.current.error(`批量研判完成：成功 ${summary.done} 项，失败 ${summary.failed} 项`);
    }
  }, []);

  const queue = useAnalysisQueue({
    runner: runQueueItem,
    onItemFailed: handleItemFailed,
    onAllSettled: handleAllSettled,
    concurrency: 2,
  });
  const queueEntries = queue.entries;

  const queueStats = useMemo(
    () => ({
      pending: queueEntries.filter((e) => e.status === 'pending').length,
      running: queueEntries.filter((e) => e.status === 'running').length,
      done: queueEntries.filter((e) => e.status === 'done').length,
      failed: queueEntries.filter((e) => e.status === 'failed').length,
    }),
    [queueEntries],
  );

  const applyEnqueueResult = useCallback(
    ({ added, retried }: { added: number; retried: number }) => {
      if (added > 0) toast.success(`已加入队列 ${added} 项${retried > 0 ? `，并重试失败项 ${retried} 项` : ''}`);
      else if (retried > 0) toast.info(`已重试 ${retried} 个失败条目`);
      else toast.info('所选条目已在队列中');
    },
    [toast],
  );

  const handleEnqueueTasks = useCallback(
    (taskIds: string[]) => {
      const items: QueueItem[] = taskIds.map((id) => {
        const t = tasks.find((x) => x.id === id);
        return {
          kind: 'task',
          taskId: id,
          label: basename(t?.image_path) || id,
          imagePath: t?.image_path,
        } satisfies TaskQueueItem;
      });
      applyEnqueueResult(queue.enqueue(items));
      setMode('queue');
    },
    [tasks, queue, applyEnqueueResult, setMode],
  );

  const handleRefillHistory = useCallback(
    (entry: AnalysisHistoryEntry) => {
      handleEnqueueTasks([entry.taskId]);
    },
    [handleEnqueueTasks],
  );

  /* --------------------------- 文件勾选入队 ----------------------------- */

  const [selectedFilePaths, setSelectedFilePaths] = useState<Set<string>>(new Set());

  const toggleFileSelected = (path: string) =>
    setSelectedFilePaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const allFilesSelected =
    filteredDescriptions.length > 0 &&
    filteredDescriptions.every((d) => !d.file_path || selectedFilePaths.has(d.file_path));

  const toggleAllFiles = () => {
    if (allFilesSelected) {
      setSelectedFilePaths(new Set());
    } else {
      setSelectedFilePaths(new Set(filteredDescriptions.map((d) => d.file_path).filter((p): p is string => !!p)));
    }
  };

  const enqueueSelectedFiles = () => {
    if (!activeContextId || selectedFilePaths.size === 0) return;
    const items: QueueItem[] = [...selectedFilePaths].map((filePath) => ({
      kind: 'file',
      taskId: activeContextId,
      filePath,
      filesDbPath,
    }));
    applyEnqueueResult(queue.enqueue(items));
    setSelectedFilePaths(new Set());
    setMode('queue');
  };

  /* ------------------------------ 详情 Drawer --------------------------- */

  const [drawerTarget, setDrawerTarget] = useState<DrawerTarget | null>(null);
  const openFileDrawer = useCallback(
    (taskId: string, row: LlmDescriptionRow) => setDrawerTarget({ kind: 'file', taskId, row }),
    [],
  );
  const openClusterDrawer = useCallback(
    (taskId: string, row: ClusterRow) => setDrawerTarget({ kind: 'cluster', taskId, row }),
    [],
  );

  /* -------------------------------- 对比 -------------------------------- */

  const comparePool = useMemo(() => {
    const pool: TaskResultSnapshot[] = [];
    const seen = new Set<string>();
    for (const entry of queueEntries) {
      if (entry.status !== 'done' || !entry.result || entry.result.kind !== 'task') continue;
      pool.push(entry.result.snapshot);
      seen.add(entry.result.snapshot.taskId);
    }
    const currentDescriptions = llmResults?.descriptions ?? [];
    if (
      activeContextId &&
      !seen.has(activeContextId) &&
      (currentDescriptions.length > 0 || eventClusters.length > 0)
    ) {
      pool.push({
        taskId: activeContextId,
        imagePath: currentTask?.image_path,
        descriptions: currentDescriptions,
        clusters: eventClusters,
        finishedAt: Date.now(),
      });
    }
    return pool;
  }, [queueEntries, llmResults, eventClusters, activeContextId, currentTask]);

  /* ------------------------------- 导出 --------------------------------- */

  const handleExportCSV = useCallback(
    (snapshot: TaskResultSnapshot) => {
      exportResultCSV(snapshot);
      toast.success(`已导出 analysis-${shortTaskId(snapshot.taskId)}.csv`);
    },
    [toast],
  );

  const handleExportJSON = useCallback(
    (snapshot: TaskResultSnapshot) => {
      exportResultJSON(snapshot);
      toast.success(`已导出 analysis-${shortTaskId(snapshot.taskId)}.json`);
    },
    [toast],
  );

  const currentSnapshot = useMemo<TaskResultSnapshot | null>(() => {
    const descriptions = llmResults?.descriptions ?? [];
    if (!activeContextId || (descriptions.length === 0 && eventClusters.length === 0)) return null;
    return {
      taskId: activeContextId,
      imagePath: currentTask?.image_path,
      descriptions,
      clusters: eventClusters,
      finishedAt: Date.now(),
    };
  }, [llmResults, eventClusters, activeContextId, currentTask]);

  /* --------------------------- 相关性标记（既有） ------------------------ */

  const handleToggleFileRelevance = async (item: LlmDescriptionRow) => {
    if (!activeContextId || !item.file_path) return;
    const next = !(item.is_relevant === 1 || item.is_relevant === true);
    try {
      await toggleFileRelevance(activeContextId, item.file_path, next);
      setLlmResults((prev) =>
        prev
          ? {
              ...prev,
              descriptions: prev.descriptions.map((d) =>
                d.file_path === item.file_path ? { ...d, is_relevant: next ? 1 : 0 } : d,
              ),
            }
          : prev,
      );
      toast.success(next ? '已标记为案情证据' : '已剔除出报告');
    } catch (err) {
      toast.error(`操作失败：${errorMessage(err)}`);
    }
  };

  const handleToggleClusterRelevance = async (cluster: ClusterRow) => {
    if (!activeContextId || cluster.timestamp === undefined) return;
    const next = !(cluster.llm_is_relevant === 1 || cluster.llm_is_relevant === true);
    try {
      await pythonApi.post('/api/llm/toggle-cluster-relevance', {
        task_id: activeContextId,
        time_window: Math.floor(cluster.timestamp / 60),
        event_type: cluster.event_type,
        is_relevant: next,
      });
      setEventClusters((prev) =>
        prev.map((c) =>
          c.timestamp === cluster.timestamp && c.event_type === cluster.event_type
            ? { ...c, llm_is_relevant: next ? 1 : 0 }
            : c,
        ),
      );
      toast.success(next ? '事件簇已标记为相关' : '事件簇已标记为无关');
    } catch (err) {
      toast.error(`操作失败：${errorMessage(err)}`);
    }
  };

  /* -------------------------------- 渲染 -------------------------------- */

  if (!activeContextId) {
    return (
      <Card>
        <EmptyState title="未选择任务" description="请选择一个任务进入研判中心。" />
      </Card>
    );
  }

  const showFiles = viewMode !== 'clusters';
  const showClusters = viewMode !== 'files';

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader
        icon={ScanSearch}
        tone="accent"
        title="研判中心"
        subtitle="证据批量研判、结果对比与复核"
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => void handleRetryFetch()}>
              <RefreshCw size={13} /> 刷新
            </Button>
            {currentSnapshot && (
              <>
                <Button variant="secondary" size="sm" onClick={() => handleExportCSV(currentSnapshot)} title="导出当前任务 CSV">
                  <FileDown size={13} /> CSV
                </Button>
                <Button variant="secondary" size="sm" onClick={() => handleExportJSON(currentSnapshot)} title="导出当前任务 JSON">
                  <FileJson size={13} /> JSON
                </Button>
              </>
            )}
          </>
        }
      />

      <StatStrip
        stats={[
          { label: '队列', value: queueEntries.length, dotClass: 'bg-accent-500' },
          { label: '等待', value: queueStats.pending, dotClass: 'bg-ink-300 dark:bg-ink-600' },
          { label: '进行中', value: queueStats.running, dotClass: 'bg-accent-500 animate-blink-soft' },
          { label: '完成', value: queueStats.done, dotClass: 'bg-emerald-500' },
          { label: '失败', value: queueStats.failed, dotClass: 'bg-rose-500' },
          { label: '历史', value: history.entries.length, dotClass: 'bg-sky-500' },
        ]}
      />

      {/* 工具栏：视图切换（持久化到 URL）+ 检索 + 证据类型过滤 */}
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={mode}
          onChange={(v) => setMode(v)}
          options={[
            { value: 'queue', label: '研判队列', icon: ListChecks, count: queueEntries.length },
            { value: 'compare', label: '结果对比', icon: Scale, count: comparePool.length },
          ]}
        />
        {mode === 'queue' && (
          <>
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
              <input
                type="text"
                className="input pl-8 py-1.5 text-xs"
                placeholder="搜索证据…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
              {(
                [
                  { key: 'all', label: '全部' },
                  { key: 'files', label: '文件证据' },
                  { key: 'clusters', label: '事件簇' },
                ] as const
              ).map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setViewMode(key)}
                  className={cx(
                    'px-3 py-1.5 text-xs font-medium transition-colors',
                    viewMode === key
                      ? 'bg-accent-600 text-white'
                      : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {loadError && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 dark:border-rose-500/30 dark:bg-rose-500/10">
          <AlertTriangle size={15} className="shrink-0 text-rose-500" />
          <span className="min-w-0 flex-1 text-xs text-rose-700 dark:text-rose-300">
            研判数据加载失败：{loadError}
          </span>
          <Button variant="secondary" size="sm" onClick={() => void handleRetryFetch()}>
            重试
          </Button>
        </div>
      )}

      {mode === 'compare' ? (
        <CompareView
          pool={comparePool}
          onExportCSV={handleExportCSV}
          onExportJSON={handleExportJSON}
          onOpenFile={openFileDrawer}
          onOpenCluster={openClusterDrawer}
          onGoQueue={() => setMode('queue')}
        />
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] items-start gap-4">
          <div className="space-y-4 min-w-0">
            {/* Case context */}
            <Card>
              <CardHeader title="案情背景" subtitle={currentTask ? currentTask.image_path : activeContextId} />
              <div className="flex gap-2">
                <textarea
                  rows={2}
                  className="input flex-1 resize-y text-sm"
                  placeholder="记录案情背景与分析方向…"
                  value={caseDescription}
                  onChange={(e) => setCaseDescription(e.target.value)}
                />
                <Button variant="primary" onClick={saveDescription} disabled={!caseDescription.trim()} className="self-end">
                  保存
                </Button>
              </div>
            </Card>

            {loading ? (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <Card padded={false}>
                  <SkeletonTable rows={5} cols={3} />
                </Card>
                <Card padded={false}>
                  <SkeletonTable rows={5} cols={3} />
                </Card>
              </div>
            ) : (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {/* File evidence */}
                {showFiles && (
                  <Card padded={false}>
                    <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center gap-1.5">
                      <FileText size={14} className="text-ink-400" />
                      <h3 className="card-title flex-1">文件证据（{filteredDescriptions.length}）</h3>
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 accent-accent-600"
                        checked={allFilesSelected}
                        onChange={toggleAllFiles}
                        aria-label="全选文件证据"
                        title="全选"
                      />
                      {selectedFilePaths.size > 0 && (
                        <Button variant="primary" size="sm" onClick={enqueueSelectedFiles}>
                          <ListPlus size={13} /> 加入队列（{selectedFilePaths.size}）
                        </Button>
                      )}
                    </div>
                    {filteredDescriptions.length === 0 ? (
                      <EmptyState title="暂无文件证据" description="先在文件页执行 AI 描述或批量分析。" />
                    ) : (
                      <ul className="divide-y divide-ink-100 dark:divide-ink-800 max-h-[600px] overflow-y-auto">
                        {filteredDescriptions.map((item) => {
                          const relevant = item.is_relevant === 1 || item.is_relevant === true;
                          return (
                            <li key={item.file_path} className="px-4 py-3">
                              <div className="flex items-start justify-between gap-2">
                                <input
                                  type="checkbox"
                                  className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-accent-600"
                                  checked={item.file_path ? selectedFilePaths.has(item.file_path) : false}
                                  onChange={() => item.file_path && toggleFileSelected(item.file_path)}
                                  aria-label="选择加入研判队列"
                                />
                                <div className="min-w-0 flex-1">
                                  <p className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate">
                                    {basename(item.file_path ?? '')}
                                  </p>
                                  <p className="text-2xs font-mono text-ink-400 truncate">{item.file_path}</p>
                                  {item.summary && (
                                    <p className="mt-1.5 text-xs text-ink-600 dark:text-ink-300 leading-relaxed line-clamp-3">
                                      {item.summary}
                                    </p>
                                  )}
                                  {item.keywords && item.keywords.length > 0 && (
                                    <div className="mt-1.5 flex flex-wrap gap-1">
                                      {item.keywords.slice(0, 6).map((kw) => (
                                        <span key={kw} className="chip bg-ink-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400">
                                          {kw}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                </div>
                                <div className="flex items-center gap-0.5 shrink-0">
                                  <button
                                    type="button"
                                    onClick={() => openFileDrawer(activeContextId, item)}
                                    className="p-1.5 rounded-md text-ink-300 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                                    title="研判详情"
                                  >
                                    <Info size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void handleToggleFileRelevance(item)}
                                    className={cx(
                                      'p-1.5 rounded-md transition-colors',
                                      relevant
                                        ? 'text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-500/10'
                                        : 'text-ink-300 hover:text-amber-500 hover:bg-ink-100 dark:hover:bg-ink-800',
                                    )}
                                    title={relevant ? '移出报告' : '标记为案情证据'}
                                  >
                                    {relevant ? <Star size={16} fill="currentColor" /> : <StarOff size={16} />}
                                  </button>
                                </div>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </Card>
                )}

                {/* Event clusters */}
                {showClusters && (
                  <Card padded={false}>
                    <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center gap-1.5">
                      <Layers size={14} className="text-ink-400" />
                      <h3 className="card-title">事件簇研判（{filteredClusters.length}）</h3>
                    </div>
                    {filteredClusters.length === 0 ? (
                      <EmptyState title="暂无事件簇分析" description="先在时间线页执行 AI 簇分析。" />
                    ) : (
                      <ul className="divide-y divide-ink-100 dark:divide-ink-800 max-h-[600px] overflow-y-auto">
                        {filteredClusters.map((cluster, i) => {
                          const relevant = cluster.llm_is_relevant === 1 || cluster.llm_is_relevant === true;
                          return (
                            <li key={`${cluster.timestamp}-${cluster.event_type}-${i}`} className="px-4 py-3">
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2 text-2xs text-ink-400">
                                    <span className="font-semibold text-ink-600 dark:text-ink-300">{cluster.event_type}</span>
                                    <span className="font-mono truncate">{cluster.parent_directory || '/'}</span>
                                  </div>
                                  {cluster.llm_summary && (
                                    <p className="mt-1 text-xs text-ink-600 dark:text-ink-300 leading-relaxed line-clamp-3">
                                      {cluster.llm_summary}
                                    </p>
                                  )}
                                </div>
                                <div className="flex items-center gap-0.5 shrink-0">
                                  <button
                                    type="button"
                                    onClick={() => openClusterDrawer(activeContextId, cluster)}
                                    className="p-1.5 rounded-md text-ink-300 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                                    title="研判详情"
                                  >
                                    <Info size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void handleToggleClusterRelevance(cluster)}
                                    className={cx(
                                      'p-1.5 rounded-md transition-colors',
                                      relevant
                                        ? 'text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-500/10'
                                        : 'text-ink-300 hover:text-amber-500 hover:bg-ink-100 dark:hover:bg-ink-800',
                                    )}
                                    title={relevant ? '标记为无关' : '标记为相关'}
                                  >
                                    {relevant ? <Star size={16} fill="currentColor" /> : <StarOff size={16} />}
                                  </button>
                                </div>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </Card>
                )}
              </div>
            )}
          </div>

          {/* 侧边：队列 + 历史 */}
          <div className="space-y-4 min-w-0">
            <QueuePanel
              entries={queueEntries}
              tasks={tasks}
              concurrency={2}
              onEnqueueTasks={handleEnqueueTasks}
              onRetry={queue.retry}
              onRemove={queue.remove}
              onClear={queue.clear}
              onOpenResult={(snapshot) => setDrawerTarget({ kind: 'task', snapshot })}
              onExportCSV={handleExportCSV}
            />
            <HistoryPanel
              entries={history.entries}
              onRefill={handleRefillHistory}
              onRemove={history.remove}
              onClear={history.clear}
            />
          </div>
        </div>
      )}

      <ResultDetailDrawer target={drawerTarget} onClose={() => setDrawerTarget(null)} />
    </div>
  );
}
