import { useMemo, useState } from 'react';
import { AlertTriangle, Download, FolderSearch, Search, SearchX, X } from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import { SkeletonTable } from '../../components/ui/PageScaffold';
import { useDebouncedValue } from '../../hooks/useUrlState';
import { downloadCSV } from '../../lib/exportUtils';
import { useToast } from '../../components/ui/Toast';
import OssDataTable from './OssDataTable';
import OssExtensionChart from './OssExtensionChart';
import OssRowDrawer from './OssRowDrawer';
import OssSummaryGrid from './OssSummaryGrid';
import {
  buildSummaryCsv,
  buildTableCsv,
  compareRows,
  getColumns,
  rowMatches,
  type OssColumn,
  type OssRow,
  type OssTab,
} from './ossUtils';

interface Props {
  tab: OssTab;
  taskId: string;
  rows: OssRow[];
  /** Raw summary payload (summary tab only). */
  summary: OssRow | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

const TAB_LABELS: Record<OssTab, string> = {
  objects: '对象列表',
  logs: '访问日志',
  summary: '摘要',
  stats: '扩展名统计',
};

const EMPTY_HINTS: Record<OssTab, string> = {
  objects: '该任务尚未解析出 OSS 对象。可点击右上角「启动 OSS 分析」，或刷新重试。',
  logs: '暂无访问日志记录。请确认任务包含 OSS 访问日志数据后刷新重试。',
  summary: '暂无摘要数据。可先启动 OSS 分析生成汇总信息。',
  stats: '暂无扩展名统计数据。可先启动 OSS 分析再刷新查看。',
};

/**
 * Per-tab data surface: debounced search toolbar with result count and CSV
 * export, complete data states (skeleton / load error / two empty variants),
 * then the sorted table (or summary cards).
 */
export default function OssTablePanel({ tab, taskId, rows, summary, loading, error, onRetry }: Props) {
  const toast = useToast();
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebouncedValue(query, 300);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [selectedRow, setSelectedRow] = useState<OssRow | null>(null);

  const columns = getColumns(tab);
  const isSummary = tab === 'summary';

  const sourceRows = useMemo<OssRow[]>(() => {
    if (tab !== 'summary') return rows;
    return Object.entries(summary ?? {}).map(([field, value]) => ({ field, value }));
  }, [tab, rows, summary]);

  const filtered = useMemo(
    () => sourceRows.filter((r) => rowMatches(r, debouncedQuery)),
    [sourceRows, debouncedQuery],
  );

  const sorted = useMemo(() => {
    const col = sortKey ? columns.find((c) => c.key === sortKey) : undefined;
    if (!col) return filtered;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => dir * compareRows(a, b, col.key, col.kind));
  }, [filtered, sortKey, sortDir, columns]);

  const hasQuery = debouncedQuery.trim() !== '';

  const handleSortChange = (col: OssColumn) => {
    if (isSummary) return;
    if (sortKey === col.key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(col.key);
      setSortDir(col.kind === 'text' ? 'asc' : 'desc');
    }
  };

  const handleExport = () => {
    const { data, headers } =
      tab === 'summary' ? buildSummaryCsv(summary ?? {}) : buildTableCsv(tab, sorted);
    if (data.length === 0) {
      toast.info('当前结果为空，没有可导出的内容');
      return;
    }
    downloadCSV(data, `oss-${tab}-${taskId.slice(0, 8)}.csv`, headers);
    toast.success(`已导出 ${data.length} 条记录到 CSV`);
  };

  return (
    <div>
      {/* Toolbar: debounced search · result count · CSV export */}
      <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-ink-200 dark:border-ink-800">
        <div className="relative">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400 dark:text-ink-500 pointer-events-none"
          />
          <input
            type="text"
            className="input w-52 py-1.5 pl-8 pr-7 text-xs"
            placeholder={isSummary ? '搜索字段名或值' : '搜索所有字段'}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 transition-colors"
              aria-label="清除搜索"
            >
              <X size={12} />
            </button>
          )}
        </div>

        <span className="ml-auto text-2xs text-ink-400 dark:text-ink-500 whitespace-nowrap">
          {hasQuery ? `${filtered.length} / ${sourceRows.length} 条匹配` : `共 ${sourceRows.length} 条`}
        </span>
        <Button size="sm" onClick={handleExport} disabled={sorted.length === 0} title="导出当前结果为 CSV">
          <Download size={13} /> 导出 CSV
        </Button>
      </div>

      {/* Data states */}
      {loading ? (
        <SkeletonTable rows={8} cols={Math.max(columns.length, 3)} />
      ) : error ? (
        <EmptyState
          icon={<AlertTriangle size={36} />}
          title={`${TAB_LABELS[tab]}加载失败`}
          description={error}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              重试
            </Button>
          }
        />
      ) : !hasQuery && sourceRows.length === 0 ? (
        <EmptyState
          icon={<FolderSearch size={36} />}
          title={`暂无${TAB_LABELS[tab]}数据`}
          description={EMPTY_HINTS[tab]}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              刷新
            </Button>
          }
        />
      ) : hasQuery && filtered.length === 0 ? (
        <EmptyState
          icon={<SearchX size={36} />}
          title="没有匹配的结果"
          description={`没有字段匹配「${debouncedQuery.trim()}」，可尝试其他关键字。`}
          action={
            <Button variant="secondary" size="sm" onClick={() => setQuery('')}>
              清除搜索
            </Button>
          }
        />
      ) : isSummary ? (
        <OssSummaryGrid rows={sorted} />
      ) : (
        <>
          {tab === 'stats' && <OssExtensionChart rows={sorted} />}
          <OssDataTable
            columns={columns}
            rows={sorted}
            sortKey={sortKey}
            sortDir={sortDir}
            query={debouncedQuery}
            onSortChange={handleSortChange}
            onSelectRow={setSelectedRow}
          />
        </>
      )}

      <OssRowDrawer row={selectedRow} tabLabel={TAB_LABELS[tab]} onClose={() => setSelectedRow(null)} />
    </div>
  );
}
