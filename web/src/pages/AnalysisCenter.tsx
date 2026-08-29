import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FileText, Layers, Search, Star, StarOff } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks } from '../store/taskSlice';
import { clearRefreshFlag } from '../store/intelligenceSlice';
import { getTaskResults } from '../services/taskService';
import { getAnalyzedEventClusters } from '../services/forensicsService';
import { toggleFileRelevance } from '../services/llmService';
import { saveCaseDescription } from '../services/caseAnalysisService';
import { pythonApi } from '../services/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import { useToast } from '../components/ui/Toast';
import { basename, cx, errorMessage } from '../lib/utils';

interface LlmDescriptionRow {
  file_path?: string;
  summary?: string;
  description?: string;
  keywords?: string[];
  is_relevant?: number | boolean;
  size?: number;
  [key: string]: unknown;
}

interface ClusterRow {
  timestamp?: number;
  event_type?: string;
  parent_directory?: string;
  llm_summary?: string;
  llm_is_relevant?: number | boolean;
  file_path?: string;
  [key: string]: unknown;
}

type ViewMode = 'all' | 'files' | 'clusters';

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

  const currentTask = tasks.find((t) => t.id === activeContextId);

  useEffect(() => {
    void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
  }, [dispatch]);

  const fetchData = useCallback(async () => {
    if (!activeContextId) return;
    setLoading(true);
    try {
      try {
        const results = (await getTaskResults(activeContextId)) as {
          llm_results?: { descriptions?: LlmDescriptionRow[] };
        };
        setLlmResults(results.llm_results ? { descriptions: results.llm_results.descriptions ?? [] } : { descriptions: [] });
      } catch {
        setLlmResults({ descriptions: [] });
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

  const saveDescription = async () => {
    if (!activeContextId || !caseDescription.trim()) return;
    try {
      await saveCaseDescription(activeContextId, caseDescription.trim());
      toast.success('案情描述已保存');
    } catch (err) {
      toast.error(`保存失败：${errorMessage(err)}`);
    }
  };

  const filteredDescriptions = useMemo(() => {
    const items = llmResults?.descriptions || [];
    if (!searchQuery) return items;
    const q = searchQuery.toLowerCase();
    return items.filter(
      (item) => item.file_path?.toLowerCase().includes(q) || item.summary?.toLowerCase().includes(q),
    );
  }, [llmResults, searchQuery]);

  const filteredClusters = useMemo(() => {
    if (!searchQuery) return eventClusters;
    const q = searchQuery.toLowerCase();
    return eventClusters.filter(
      (c) =>
        c.event_type?.toLowerCase().includes(q) ||
        c.parent_directory?.toLowerCase().includes(q) ||
        c.llm_summary?.toLowerCase().includes(q),
    );
  }, [eventClusters, searchQuery]);

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

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
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
      </div>

      {loading ? (
        <Card>
          <LoadingBlock text="正在加载研判数据…" />
        </Card>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* File evidence */}
          {showFiles && (
            <Card padded={false}>
              <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center gap-1.5">
                <FileText size={14} className="text-ink-400" />
                <h3 className="card-title">文件证据（{filteredDescriptions.length}）</h3>
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
                          <button
                            type="button"
                            onClick={() => void handleToggleFileRelevance(item)}
                            className={cx(
                              'p-1.5 rounded-md transition-colors shrink-0',
                              relevant
                                ? 'text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-500/10'
                                : 'text-ink-300 hover:text-amber-500 hover:bg-ink-100 dark:hover:bg-ink-800',
                            )}
                            title={relevant ? '移出报告' : '标记为案情证据'}
                          >
                            {relevant ? <Star size={16} fill="currentColor" /> : <StarOff size={16} />}
                          </button>
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
                          <button
                            type="button"
                            onClick={() => void handleToggleClusterRelevance(cluster)}
                            className={cx(
                              'p-1.5 rounded-md transition-colors shrink-0',
                              relevant
                                ? 'text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-500/10'
                                : 'text-ink-300 hover:text-amber-500 hover:bg-ink-100 dark:hover:bg-ink-800',
                            )}
                            title={relevant ? '标记为无关' : '标记为相关'}
                          >
                            {relevant ? <Star size={16} fill="currentColor" /> : <StarOff size={16} />}
                          </button>
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
  );
}
