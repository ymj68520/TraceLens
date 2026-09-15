import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  Clock,
  Database,
  Download,
  FileSearch,
  RefreshCw,
  Search as SearchIcon,
  X,
} from 'lucide-react';
import { searchFulltext, createSearchIndex } from '../services/searchService';
import { useAppSelector } from '../store';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { Drawer, DetailRow } from '../components/ui/Drawer';
import { useToast } from '../components/ui/Toast';
import { PageHeader, Segmented, SkeletonTable } from '../components/ui/PageScaffold';
import { useDebouncedValue, useUrlState } from '../hooks/useUrlState';
import { errorMessage, formatBytes } from '../lib/utils';
import { downloadCSV } from '../lib/exportUtils';
import HighlightText from '../components/search/HighlightText';
import {
  groupHits,
  hitPath,
  loadSearchHistory,
  pushSearchHistory,
  saveSearchHistory,
  type SearchHit,
  type SearchResponse,
} from '../components/search/searchUtils';

/** Extra primitive fields surfaced in the detail drawer (capped for noise). */
const EXTRA_FIELD_LIMIT = 8;
const RESERVED_HIT_FIELDS = new Set(['path', 'file_path', 'snippet', 'score', 'size']);

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const currentTask = tasks.find((t) => t.id === taskId);

  const [view, setView] = useState<'search' | 'index'>('search');
  const [input, setInput] = useState(() => searchParams.get('q') ?? '');
  const debouncedQuery = useDebouncedValue(input, 350);
  const [urlQuery, setUrlQuery] = useUrlState('q', '');
  const [groupParam, setGroupParam] = useUrlState('tab', 'all');

  const [index, setIndex] = useState('');
  const [sourcePath, setSourcePath] = useState('');
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [history, setHistory] = useState<string[]>(loadSearchHistory);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selected, setSelected] = useState<SearchHit | null>(null);

  const searchBoxRef = useRef<HTMLDivElement>(null);

  const query = debouncedQuery.trim();

  /* Default the index / source paths whenever the selected task changes. */
  useEffect(() => {
    if (taskId) {
      setIndex(`search_index_${taskId.substring(0, 8)}`);
      setSourcePath(
        (currentTask as { extraction_directory?: string } | undefined)?.extraction_directory ||
          `../build/data/tasks/${taskId}/extracted_files`,
      );
    }
  }, [taskId, currentTask]);

  /* Keep the text field in sync when the URL query changes externally
   * (browser back/forward, shared links). */
  useEffect(() => {
    setInput((prev) => (prev.trim() === urlQuery ? prev : urlQuery));
  }, [urlQuery]);

  /* Commit the debounced query into the URL so views are shareable. */
  useEffect(() => {
    if (query !== urlQuery) setUrlQuery(query);
  }, [query, urlQuery, setUrlQuery]);

  /* Debounced auto-search. A missing query or index resets the result area. */
  useEffect(() => {
    if (!query || !index) {
      setResults(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    searchFulltext(query, index, { limit: 200 })
      .then((data) => {
        if (cancelled) return;
        setResults(data as SearchResponse);
        setHistory((prev) => pushSearchHistory(prev, query));
      })
      .catch((err) => {
        if (cancelled) return;
        setResults(null);
        setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query, index, reloadKey]);

  /* Persist history whenever it changes. */
  useEffect(() => {
    saveSearchHistory(history);
  }, [history]);

  /* Close the history dropdown on any click outside the search box. */
  useEffect(() => {
    if (!historyOpen) return;
    const onDocMouseDown = (event: MouseEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(event.target as Node)) {
        setHistoryOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [historyOpen]);

  const hits = useMemo(() => results?.results ?? results?.hits ?? [], [results]);
  const groups = useMemo(() => groupHits(hits), [hits]);
  const activeGroupKey = groups.some((g) => g.key === groupParam) ? groupParam : 'all';
  const activeHits = useMemo(
    () => (activeGroupKey === 'all' ? hits : groups.find((g) => g.key === activeGroupKey)?.hits ?? []),
    [activeGroupKey, groups, hits],
  );
  const activeGroupLabel = activeGroupKey === 'all' ? '全部' : groups.find((g) => g.key === activeGroupKey)?.label ?? '全部';

  const hasIndexConfig = index.trim() !== '';
  const hasAnyResult = hits.length > 0;

  const handleCreateIndex = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!sourcePath.trim() || !index.trim()) return;
    setIndexing(true);
    try {
      await createSearchIndex(sourcePath, index, true);
      toast.success('索引创建完成，可以开始搜索');
      setView('search');
    } catch (err) {
      toast.error(`索引创建失败：${errorMessage(err)}`);
    } finally {
      setIndexing(false);
    }
  };

  const applyHistory = (item: string) => {
    setHistoryOpen(false);
    if (item === input.trim()) setReloadKey((key) => key + 1);
    else setInput(item);
  };

  const removeHistory = (item: string) => {
    setHistory((prev) => prev.filter((entry) => entry !== item));
  };

  const handleExport = () => {
    if (activeHits.length === 0) return;
    downloadCSV(
      activeHits.map((hit) => ({
        path: hitPath(hit),
        size: typeof hit.size === 'number' ? hit.size : '',
        score: typeof hit.score === 'number' ? hit.score : '',
        snippet: typeof hit.snippet === 'string' ? hit.snippet : '',
      })),
      `search-results-${index.trim() || 'index'}`,
      [
        { key: 'path', label: '路径' },
        { key: 'size', label: '大小(字节)' },
        { key: 'score', label: '相关度' },
        { key: 'snippet', label: '片段' },
      ],
    );
  };

  const groupOptions = [
    { value: 'all', label: '全部', count: hits.length },
    ...groups.map((g) => ({ value: g.key, label: g.label, count: g.hits.length })),
  ];

  const renderResultBody = () => {
    if (error) {
      return (
        <EmptyState
          icon={<AlertTriangle size={34} />}
          title="搜索失败"
          description={error}
          action={
            <Button size="sm" onClick={() => setReloadKey((key) => key + 1)}>
              <RefreshCw size={13} />
              重试
            </Button>
          }
        />
      );
    }
    if (!query) {
      return <EmptyState icon={<FileSearch size={34} />} title="输入关键词开始检索" description="支持文件名与文件内容全文检索，结果按文件类型分组。" />;
    }
    if (!hasIndexConfig) {
      return (
        <EmptyState
          icon={<Database size={34} />}
          title="尚未配置索引"
          description="请先填写索引名称，或前往索引管理对提取目录建立全文索引。"
          action={
            <Button size="sm" onClick={() => setView('index')}>
              <Database size={13} />
              前往索引管理
            </Button>
          }
        />
      );
    }
    if (loading) {
      return <SkeletonTable rows={6} cols={3} />;
    }
    if (query && results && !hasAnyResult) {
      return <EmptyState icon={<FileSearch size={34} />} title="没有匹配结果" description={`索引中未找到包含 “${query}” 的内容，请尝试其他关键词。`} />;
    }
    if (results && hasAnyResult && activeHits.length === 0) {
      return <EmptyState icon={<FileSearch size={34} />} title={`${activeGroupLabel}分组为空`} description="该分组下没有命中结果，请切换其他分组查看。" />;
    }
    if (!results) return null;

    return (
      <ul className="divide-y divide-ink-100 dark:divide-ink-800">
        {activeHits.map((hit, i) => {
          const path = hitPath(hit);
          return (
            <li key={`${i}-${path}`}>
              <button
                type="button"
                onClick={() => setSelected(hit)}
                className="w-full px-5 py-3 text-left hover:bg-ink-50 dark:hover:bg-ink-900/60 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <p className="min-w-0 flex-1 truncate text-xs font-mono text-accent-700 dark:text-accent-300">
                    <HighlightText text={path} query={query} />
                  </p>
                  {typeof hit.score === 'number' && (
                    <span className="shrink-0 font-mono text-2xs text-ink-400 dark:text-ink-500 tabular-nums">
                      {hit.score.toFixed(2)}
                    </span>
                  )}
                </div>
                {typeof hit.snippet === 'string' && hit.snippet && (
                  <p className="mt-1 text-xs leading-relaxed text-ink-600 dark:text-ink-300 line-clamp-3">
                    <HighlightText text={hit.snippet} query={query} />
                  </p>
                )}
                {typeof hit.size === 'number' && (
                  <p className="mt-0.5 text-2xs text-ink-400 dark:text-ink-500">{formatBytes(hit.size)}</p>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="space-y-4 max-w-5xl">
      <PageHeader
        icon={SearchIcon}
        tone="accent"
        title="全文搜索"
        subtitle="跨提取目录的全文检索，支持关键词高亮与类型分组"
        actions={
          <>
            <Segmented
              options={[
                { value: 'search', label: '检索', icon: SearchIcon },
                { value: 'index', label: '索引管理', icon: Database },
              ]}
              value={view}
              onChange={setView}
            />
            <Button size="sm" variant="secondary" onClick={handleExport} disabled={loading || activeHits.length === 0}>
              <Download size={14} />
              导出 CSV
            </Button>
          </>
        }
      />

      {view === 'index' && (
        <Card>
          <CardHeader title="创建全文索引" subtitle="对提取目录建立搜索索引（首次使用前必需）" />
          <form onSubmit={handleCreateIndex} className="space-y-3">
            <div>
              <label className="field-label" htmlFor="search-source-path">源目录</label>
              <input
                id="search-source-path"
                type="text"
                className="input font-mono text-xs"
                value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="search-index-name">索引名称</label>
              <input
                id="search-index-name"
                type="text"
                className="input font-mono text-xs"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
              />
            </div>
            <Button variant="primary" type="submit" disabled={indexing}>
              {indexing ? '创建中…' : '创建索引'}
            </Button>
          </form>
        </Card>
      )}

      {view === 'search' && (
        <>
          <Card>
            <form onSubmit={(event) => event.preventDefault()} className="flex gap-2">
              <div ref={searchBoxRef} className="relative flex-1 min-w-0">
                <SearchIcon size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 dark:text-ink-500" />
                <input
                  type="text"
                  className="input pl-9 pr-8"
                  placeholder="搜索文件名与内容关键词…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onFocus={() => history.length > 0 && setHistoryOpen(true)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setHistoryOpen(false);
                  }}
                  aria-label="搜索关键词"
                  autoComplete="off"
                />
                {input && (
                  <button
                    type="button"
                    onClick={() => setInput('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-ink-300 hover:text-ink-600 dark:text-ink-600 dark:hover:text-ink-300 transition-colors"
                    aria-label="清空输入"
                  >
                    <X size={14} />
                  </button>
                )}
                {historyOpen && history.length > 0 && (
                  <div className="absolute left-0 right-0 top-full z-30 mt-1.5 card shadow-pop overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-ink-100 dark:border-ink-800">
                      <span className="section-label">最近搜索</span>
                      <button
                        type="button"
                        className="text-2xs text-ink-400 hover:text-rose-600 dark:hover:text-rose-400 transition-colors"
                        onClick={() => setHistory([])}
                      >
                        清空历史
                      </button>
                    </div>
                    <ul className="max-h-64 overflow-y-auto py-1">
                      {history.map((item) => (
                        <li key={item} className="group flex items-center gap-2 px-3 py-1.5 hover:bg-ink-50 dark:hover:bg-ink-800/60 transition-colors">
                          <Clock size={13} className="shrink-0 text-ink-300 dark:text-ink-600" />
                          <button
                            type="button"
                            className="min-w-0 flex-1 truncate text-left text-xs font-mono text-ink-700 dark:text-ink-200"
                            onClick={() => applyHistory(item)}
                          >
                            {item}
                          </button>
                          <button
                            type="button"
                            className="shrink-0 p-0.5 text-ink-300 opacity-0 group-hover:opacity-100 hover:text-rose-500 dark:text-ink-600 dark:hover:text-rose-400 transition-all"
                            aria-label={`删除历史 ${item}`}
                            onClick={() => removeHistory(item)}
                          >
                            <X size={12} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              <input
                type="text"
                className="input w-44 shrink-0 font-mono text-xs"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                placeholder="索引名称"
                aria-label="索引名称"
              />
            </form>
          </Card>

          <Card padded={false}>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-ink-100 dark:border-ink-800">
              <p className="text-xs text-ink-500 dark:text-ink-400">
                {results ? (
                  <>
                    命中 <span className="font-mono font-semibold text-ink-800 dark:text-ink-100 tabular-nums">{results.count ?? results.total ?? hits.length}</span> 条
                    {query && (
                      <>
                        {' '}· 关键词 <span className="font-mono text-accent-600 dark:text-accent-400">“{query}”</span>
                      </>
                    )}
                  </>
                ) : (
                  <span className="text-ink-400 dark:text-ink-500">输入关键词后将自动检索</span>
                )}
              </p>
              {hasAnyResult && !loading && !error && (
                <Segmented options={groupOptions} value={activeGroupKey} onChange={setGroupParam} />
              )}
            </div>
            {renderResultBody()}
          </Card>
        </>
      )}

      <Drawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? hitPath(selected).split(/[\\/]/).pop() || '结果详情' : '结果详情'}
        description={selected ? hitPath(selected) : undefined}
        width="lg"
      >
        {selected && (
          <div>
            <DetailRow label="路径" mono>
              {hitPath(selected) || '—'}
            </DetailRow>
            {typeof selected.snippet === 'string' && selected.snippet && (
              <DetailRow label="内容片段">
                <span className="leading-relaxed">
                  <HighlightText text={selected.snippet} query={query} />
                </span>
              </DetailRow>
            )}
            {typeof selected.size === 'number' && (
              <DetailRow label="大小">
                {formatBytes(selected.size)}（{selected.size.toLocaleString()} 字节）
              </DetailRow>
            )}
            {typeof selected.score === 'number' && (
              <DetailRow label="相关度评分">{selected.score.toFixed(3)}</DetailRow>
            )}
            {Object.entries(selected)
              .filter(
                ([key, value]) =>
                  !RESERVED_HIT_FIELDS.has(key) && ['string', 'number', 'boolean'].includes(typeof value),
              )
              .slice(0, EXTRA_FIELD_LIMIT)
              .map(([key, value]) => (
                <DetailRow key={key} label={key} mono>
                  {String(value)}
                </DetailRow>
              ))}
          </div>
        )}
      </Drawer>
    </div>
  );
}
