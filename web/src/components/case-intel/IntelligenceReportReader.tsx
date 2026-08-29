import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Search as SearchIcon, X } from 'lucide-react';
import {
  getIntelligenceReport,
  getIntelligenceRecords,
  searchIntelligenceReport,
  getReportMetadata,
} from '../../services/intelligenceReportService';
import Card from '../ui/Card';
import EmptyState from '../ui/EmptyState';
import { LoadingBlock } from '../ui/Spinner';
import { cx, formatBytes } from '../../lib/utils';

export interface DirectoryNode {
  id: string;
  title: string;
  kind: string;
  stats?: { total?: number; deleted?: number; relevant?: number };
}

interface ReportShape {
  directory?: DirectoryNode[];
  overview?: string;
  [key: string]: unknown;
}

interface RecordRow {
  id?: string | number;
  path?: string;
  title?: string;
  name?: string;
  file_path?: string;
  category?: string;
  event_type?: string;
  size?: number;
  file_size?: number;
  md5?: string;
  is_deleted?: number;
  data_state?: string;
  scene_relevant?: number;
  llm_is_relevant?: number;
  [key: string]: unknown;
}

interface PageData {
  records?: RecordRow[];
  page: number;
  page_size: number;
  total?: number;
  [key: string]: unknown;
}

function RecordTable({ pageData }: { pageData: PageData }) {
  const records = pageData.records || [];
  if (!records.length) return <EmptyState title="该分类暂无记录" />;
  return (
    <div className="overflow-x-auto border border-ink-200 dark:border-ink-800 rounded-md">
      <table className="table-shell">
        <thead>
          <tr>
            <th className="w-10">#</th>
            <th>路径 / 标题</th>
            <th>类型</th>
            <th>大小</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r, i) => {
            const title = r.path || r.title || r.name || r.file_path || '—';
            const deleted = r.is_deleted === 1 || r.data_state === 'deleted';
            return (
              <tr key={r.id ?? i}>
                <td className="text-ink-400 text-2xs">
                  {(pageData.page - 1) * pageData.page_size + i + 1}
                </td>
                <td className="max-w-md">
                  <p className="text-xs font-medium text-ink-800 dark:text-ink-100 break-all">{title}</p>
                  {r.md5 && <p className="text-2xs text-ink-400 font-mono mt-0.5">md5: {r.md5}</p>}
                </td>
                <td className="text-xs">{r.category || r.event_type || ''}</td>
                <td className="text-xs font-mono">{formatBytes(Number(r.size ?? r.file_size ?? 0))}</td>
                <td className="space-x-1">
                  <span className={cx('chip', deleted
                    ? 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/20'
                    : 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20')}>
                    {deleted ? '已删除' : '存在'}
                  </span>
                  {(r.scene_relevant === 1 || r.llm_is_relevant === 1) && (
                    <span className="chip bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20">
                      相关
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 历史研判报告阅读器：左侧目录 + 正文 + 分页/搜索。 */
export default function IntelligenceReportReader({ taskId }: { taskId: string }) {
  const [report, setReport] = useState<ReportShape | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState('overview');
  const [page, setPage] = useState(1);
  const [pageData, setPageData] = useState<PageData | null>(null);
  const [loadingReport, setLoadingReport] = useState(true);
  const [loadingPage, setLoadingPage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown> | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState<Record<string, unknown>[] | null>(null);
  const [searching, setSearching] = useState(false);

  const reqIdRef = useRef(0);
  const pageSize = 50;

  useEffect(() => {
    let cancelled = false;
    setLoadingReport(true);
    setError(null);
    Promise.all([getIntelligenceReport(taskId), getReportMetadata(taskId).catch(() => null)])
      .then(([data, meta]) => {
        if (cancelled) return;
        setReport(data as ReportShape);
        const m = meta as { metadata?: Record<string, unknown> } | null;
        if (m?.metadata) setMetadata(m.metadata);
        setSelectedNodeId('overview');
        setPage(1);
      })
      .catch((err) => !cancelled && setError((err as Error).message))
      .finally(() => !cancelled && setLoadingReport(false));
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const currentNode = useMemo(
    () => report?.directory?.find((n) => n.id === selectedNodeId) || null,
    [report, selectedNodeId],
  );

  useEffect(() => {
    if (!report || !currentNode) return;
    const needsPaging = ['records', 'chapter', 'device_info'].includes(currentNode.kind);
    if (!needsPaging) {
      setPageData(null);
      return;
    }
    const reqId = ++reqIdRef.current;
    setLoadingPage(true);
    getIntelligenceRecords(taskId, currentNode.id, page, pageSize)
      .then((data) => {
        if (reqId === reqIdRef.current) setPageData(data as PageData);
      })
      .catch((err) => {
        if (reqId === reqIdRef.current) setError((err as Error).message);
      })
      .finally(() => {
        if (reqId === reqIdRef.current) setLoadingPage(false);
      });
  }, [report, currentNode, taskId, page]);

  const runSearch = useCallback(() => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchHits(null);
      return;
    }
    setSearching(true);
    searchIntelligenceReport(taskId, query)
      .then((data) => setSearchHits((data as { hits?: Record<string, unknown>[] }).hits ?? []))
      .catch(() => setSearchHits([]))
      .finally(() => setSearching(false));
  }, [taskId, searchQuery]);

  if (loadingReport) return <Card><LoadingBlock text="正在加载研判报告…" /></Card>;
  if (error) return <Card><EmptyState title="报告加载失败" description={error} /></Card>;
  if (!report) return <Card><EmptyState title="报告不存在" /></Card>;

  const totalPages = pageData?.total ? Math.max(1, Math.ceil(pageData.total / pageSize)) : 1;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
      {/* Directory */}
      <Card padded={false} className="h-fit">
        <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800">
          <h3 className="card-title">报告目录</h3>
        </div>
        <nav className="p-2 space-y-0.5">
          {(report.directory ?? []).map((node) => {
            const selected = node.id === selectedNodeId;
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => {
                  setSelectedNodeId(node.id);
                  setPage(1);
                  setSearchHits(null);
                }}
                className={cx(
                  'w-full text-left px-2.5 py-1.5 rounded-md text-xs transition-colors',
                  selected
                    ? 'bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300 font-medium'
                    : 'text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
                )}
              >
                {node.title}
                {node.stats?.total != null && (
                  <span className="ml-1 text-2xs text-ink-400">（{node.stats.total}）</span>
                )}
              </button>
            );
          })}
        </nav>
      </Card>

      {/* Content */}
      <div className="space-y-3 min-w-0">
        <Card padded={false} className="px-4 py-2.5 flex items-center gap-2">
          <SearchIcon size={14} className="text-ink-400 shrink-0" />
          <input
            type="text"
            className="flex-1 bg-transparent text-sm focus:outline-none"
            placeholder="在报告内搜索…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runSearch()}
          />
          {searchHits !== null && (
            <button type="button" onClick={() => { setSearchHits(null); setSearchQuery(''); }} className="p-1 text-ink-400 hover:text-ink-600">
              <X size={14} />
            </button>
          )}
          <button type="button" onClick={runSearch} className="btn-ghost btn-sm" disabled={searching}>
            {searching ? '搜索中…' : '搜索'}
          </button>
        </Card>

        <Card>
          {searchHits !== null ? (
            searchHits.length === 0 ? (
              <EmptyState title="没有匹配内容" />
            ) : (
              <ul className="space-y-3">
                {searchHits.map((hit, i) => (
                  <li key={i} className="text-xs">
                    <p className="font-medium text-ink-800 dark:text-ink-100">{String(hit.title ?? hit.category ?? '')}</p>
                    <p className="mt-0.5 text-ink-600 dark:text-ink-300 leading-relaxed">{String(hit.snippet ?? hit.text ?? '')}</p>
                  </li>
                ))}
              </ul>
            )
          ) : currentNode?.kind === 'overview' ? (
            <div className="prose-sm text-sm text-ink-700 dark:text-ink-300 leading-relaxed whitespace-pre-wrap">
              {typeof report.overview === 'string' ? report.overview : '暂无概览内容。'}
              {metadata && (
                <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-xs not-prose">
                  {Object.entries(metadata).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-ink-400">{k}</dt>
                      <dd className="text-ink-800 dark:text-ink-200">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          ) : loadingPage ? (
            <LoadingBlock />
          ) : pageData ? (
            <>
              <RecordTable pageData={pageData} />
              <div className="flex items-center justify-between mt-4 text-xs text-ink-500">
                <button type="button" className="btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  <ChevronLeft size={13} /> 上一页
                </button>
                <span className="tabular-nums">{page} / {totalPages}</span>
                <button type="button" className="btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  下一页 <ChevronRight size={13} />
                </button>
              </div>
            </>
          ) : (
            <EmptyState title="该章节暂无可展示内容" />
          )}
        </Card>
      </div>
    </div>
  );
}
