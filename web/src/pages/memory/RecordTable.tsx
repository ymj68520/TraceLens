import type { KeyboardEvent, ReactNode } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  Download,
  Inbox,
  RefreshCw,
  Search,
  SearchX,
  X,
} from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import { SkeletonTable, StatStrip, type StatItem } from '../../components/ui/PageScaffold';
import { downloadCSV } from '../../lib/exportUtils';
import { cn } from '../../lib/utils';

/* ---------------------------------------------------------------------------
 * Generic record-table toolkit for the memory forensics page. Backend rows
 * arrive loosely shaped (fields differ per Volatility plugin), so everything
 * here works on Record<string, unknown> and stays defensive by design:
 * sorting tolerates missing values, search scans every field of a row, and
 * the table truncates long cells with the full text in the title tooltip.
 * ------------------------------------------------------------------------- */

export type Row = Record<string, unknown>;
export type SortDir = 'asc' | 'desc';

export interface SortSpec {
  key: string;
  dir: SortDir;
}

export interface RecordColumn {
  /** Field key in the row record (also the default sort/filter field). */
  key: string;
  label: string;
  sortable?: boolean;
  /** Right-aligned mono cell with numeric ordering. */
  numeric?: boolean;
  mono?: boolean;
  render?: (row: Row) => ReactNode;
  /** Custom ordering key; defaults to the raw field value. */
  sortValue?: (row: Row) => string | number;
}

/** Rows rendered at once — the rest stays reachable via search and CSV. */
export const DEFAULT_MAX_ROWS = 500;

/** Display text for a raw cell value; empty values collapse to an em dash. */
export function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return '[对象]';
    }
  }
  return String(value);
}

/** Clicking a header toggles asc/desc on the active column, else sorts asc. */
export function nextSort(current: SortSpec, key: string): SortSpec {
  if (current.key === key) return { key, dir: current.dir === 'asc' ? 'desc' : 'asc' };
  return { key, dir: 'asc' };
}

export function sortRows(rows: Row[], columns: RecordColumn[], sort: SortSpec): Row[] {
  const col = columns.find((c) => c.key === sort.key);
  if (!col || rows.length < 2) return rows;
  const factor = sort.dir === 'desc' ? -1 : 1;
  const raw = col.sortValue ?? ((row: Row) => row[col.key]);
  return [...rows].sort((a, b) => {
    const va = raw(a);
    const vb = raw(b);
    if (col.numeric) return factor * ((Number(va) || 0) - (Number(vb) || 0));
    return factor * cellText(va).localeCompare(cellText(vb), undefined, { numeric: true, sensitivity: 'base' });
  });
}

/** Front-end search across every field of every row (case-insensitive). */
export function filterRows(rows: Row[], term: string): Row[] {
  const t = term.trim().toLowerCase();
  if (!t) return rows;
  return rows.filter((row) =>
    Object.values(row).some((v) => v != null && String(v).toLowerCase().includes(t)),
  );
}

const ROW_CONTAINER_KEYS = [
  'processes',
  'connections',
  'entries',
  'items',
  'rows',
  'records',
  'results',
  'list',
  'data',
  'apps',
  'databases',
  'artifacts',
];

/**
 * Pull the row array out of a loosely shaped API payload: either the payload
 * is an array itself, or it wraps one under a known container key.
 */
export function extractRows(data: unknown): Row[] {
  const candidate = Array.isArray(data) ? data : wrappedRows(data);
  return candidate.filter(
    (v): v is Row => v !== null && typeof v === 'object' && !Array.isArray(v),
  );
}

function wrappedRows(data: unknown): unknown[] {
  if (data !== null && typeof data === 'object') {
    for (const key of ROW_CONTAINER_KEYS) {
      const v = (data as Row)[key];
      if (Array.isArray(v)) return v;
    }
  }
  return [];
}

/** Key/value pairs of a plain object payload (summary, boot info, ...). */
export function extractKv(data: unknown): [string, unknown][] {
  if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
    return Object.entries(data as Row);
  }
  return [];
}

/**
 * CSV export that keeps every field found on the rows (first-appearance
 * order) so plugin-specific fields survive the round trip.
 */
export function exportRowsToCsv(
  rows: Row[],
  filename: string,
  labels?: Record<string, string>,
): number {
  if (rows.length === 0) return 0;
  const keys: string[] = [];
  const seen = new Set<string>();
  rows.forEach((row) =>
    Object.keys(row).forEach((k) => {
      if (!seen.has(k)) {
        seen.add(k);
        keys.push(k);
      }
    }),
  );
  downloadCSV(
    rows.map((row) => {
      const out: Row = {};
      keys.forEach((k) => {
        const v = row[k];
        out[k] =
          v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
      });
      return out;
    }),
    filename,
    keys.map((k) => ({ key: k, label: labels?.[k] ?? k })),
  );
  return rows.length;
}

function SortableHeader({
  column,
  sort,
  onSortChange,
}: {
  column: RecordColumn;
  sort: SortSpec;
  onSortChange: (key: string) => void;
}) {
  const active = sort.key === column.key;
  const Icon = active ? (sort.dir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th
      className={cn(column.numeric && 'text-right')}
      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={() => onSortChange(column.key)}
        title={active ? `切换为${sort.dir === 'asc' ? '降序' : '升序'}` : `按${column.label}排序`}
        className={cn(
          'inline-flex items-center gap-1 uppercase tracking-wider font-semibold',
          active
            ? 'text-accent-600 dark:text-accent-400'
            : 'text-ink-500 dark:text-ink-400 hover:text-ink-800 dark:hover:text-ink-200 transition-colors',
        )}
      >
        {column.label}
        <Icon
          size={12}
          strokeWidth={active ? 2.4 : 2}
          className={cn(!active && 'text-ink-300 dark:text-ink-600')}
        />
      </button>
    </th>
  );
}

interface RecordTableProps {
  rows: Row[];
  columns: RecordColumn[];
  sort: SortSpec;
  onSortChange: (key: string) => void;
  onOpenRow: (row: Row) => void;
  getRowKey?: (row: Row, index: number) => string;
  maxRows?: number;
}

/** Sortable, keyboard-navigable record table; rows open the detail drawer. */
export function RecordTable({
  rows,
  columns,
  sort,
  onSortChange,
  onOpenRow,
  getRowKey,
  maxRows = DEFAULT_MAX_ROWS,
}: RecordTableProps) {
  const visible = maxRows > 0 ? rows.slice(0, maxRows) : rows;
  const openRow = (row: Row) => () => onOpenRow(row);
  const rowKeyDown = (row: Row) => (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === 'Enter' && e.target === e.currentTarget) onOpenRow(row);
  };

  return (
    <div className="overflow-x-auto">
      <table className="table-shell">
        <thead>
          <tr>
            {columns.map((col) =>
              col.sortable ? (
                <SortableHeader key={col.key} column={col} sort={sort} onSortChange={onSortChange} />
              ) : (
                <th key={col.key} className={cn(col.numeric && 'text-right')}>
                  {col.label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => (
            <tr
              key={getRowKey ? getRowKey(row, i) : `row-${i}`}
              tabIndex={0}
              className="cursor-pointer"
              title="点击查看记录详情"
              onClick={openRow(row)}
              onKeyDown={rowKeyDown(row)}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    'text-xs max-w-[280px]',
                    col.numeric && 'text-right font-mono tabular-nums whitespace-nowrap',
                    col.mono && 'font-mono',
                  )}
                >
                  {col.render ? (
                    col.render(row)
                  ) : (
                    <span className="block truncate" title={cellText(row[col.key])}>
                      {cellText(row[col.key])}
                    </span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length < rows.length && (
        <p className="px-5 py-2.5 border-t border-ink-100 dark:border-ink-800/60 text-2xs text-ink-400 dark:text-ink-500">
          仅显示前 {visible.length} 条（共 {rows.length} 条），可通过搜索收窄范围，或导出 CSV 获取全部记录。
        </p>
      )}
    </div>
  );
}

/**
 * Key/value card grid for object-shaped tabs (summary, boot info, overview).
 * Optionally clickable — each pair then opens the detail drawer.
 */
export function KeyValueGrid({
  entries,
  labels,
  onSelect,
  className,
}: {
  entries: [string, unknown][];
  labels?: Record<string, string>;
  onSelect?: (key: string, value: unknown) => void;
  className?: string;
}) {
  if (entries.length === 0) return null;
  return (
    <div className={cn('grid grid-cols-2 md:grid-cols-3 gap-3', className)}>
      {entries.map(([key, value]) => {
        const interactive = typeof onSelect === 'function';
        const text = cellText(value);
        return (
          <div
            key={key}
            role={interactive ? 'button' : undefined}
            tabIndex={interactive ? 0 : undefined}
            onClick={interactive ? () => onSelect?.(key, value) : undefined}
            onKeyDown={
              interactive
                ? (e) => {
                    if (e.key === 'Enter') onSelect?.(key, value);
                  }
                : undefined
            }
            title={interactive ? '点击查看字段详情' : text}
            className={cn(
              'border border-ink-100 dark:border-ink-800 rounded-md px-3 py-2',
              interactive &&
                'cursor-pointer hover:border-accent-300 dark:hover:border-accent-500/40 transition-colors',
            )}
          >
            <p className="text-2xs text-ink-400 dark:text-ink-500 break-all">{labels?.[key] ?? key}</p>
            <p className="text-sm font-medium text-ink-900 dark:text-ink-100 mt-0.5 break-all">{text}</p>
          </div>
        );
      })}
    </div>
  );
}

interface RecordTableSectionProps {
  loading: boolean;
  error: string | null;
  /** Filtered + sorted rows — what the table and the CSV export show. */
  rows: Row[];
  /** Row count before filtering, for the "x / y 条" counter. */
  totalCount: number;
  onClearFilter: () => void;
  onExport: () => void;
  onRetry: () => void;
  emptyTitle: string;
  emptyDescription: string;
  columns?: RecordColumn[];
  sort?: SortSpec;
  onSortChange?: (key: string) => void;
  onOpenRow?: (row: Row) => void;
  getRowKey?: (row: Row, index: number) => string;
  search?: string;
  onSearchChange?: (v: string) => void;
  searchPlaceholder?: string;
  chips?: StatItem[];
  /** Custom body (KV grid, text tab) rendered instead of the table. */
  children?: ReactNode;
  skeletonCols?: number;
}

/**
 * Toolbar (search · counter · export) + full data-state handling
 * (skeleton / load failure / no data / no filter match / table) shared by
 * every record listing on the page.
 */
export function RecordTableSection({
  loading,
  error,
  rows,
  totalCount,
  onClearFilter,
  onExport,
  onRetry,
  emptyTitle,
  emptyDescription,
  columns,
  sort,
  onSortChange,
  onOpenRow,
  getRowKey,
  search,
  onSearchChange,
  searchPlaceholder,
  chips,
  children,
  skeletonCols,
}: RecordTableSectionProps) {
  const hasSearch = typeof onSearchChange === 'function';
  const hasCustomBody = Boolean(children);
  const countText =
    hasCustomBody || rows.length === totalCount
      ? `共 ${totalCount} 条`
      : `${rows.length} / ${totalCount} 条`;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-ink-200 dark:border-ink-800">
        {hasSearch && (
          <div className="relative">
            <Search
              size={13}
              aria-hidden
              className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-ink-400 dark:text-ink-500"
            />
            <input
              type="text"
              className="input w-60 pl-8 pr-7 py-1.5 text-xs"
              placeholder={searchPlaceholder ?? '搜索…'}
              value={search ?? ''}
              onChange={(e) => onSearchChange?.(e.target.value)}
            />
            {search ? (
              <button
                type="button"
                onClick={() => onSearchChange?.('')}
                aria-label="清除搜索"
                title="清除搜索"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-600 dark:hover:text-ink-200"
              >
                <X size={13} />
              </button>
            ) : null}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <span className="text-2xs text-ink-400 dark:text-ink-500 whitespace-nowrap">{countText}</span>
          <Button
            size="sm"
            onClick={onExport}
            disabled={rows.length === 0 && !hasCustomBody}
            title="导出当前结果为 CSV"
          >
            <Download size={13} /> 导出 CSV
          </Button>
        </div>
      </div>

      {chips && chips.length > 0 && (
        <div className="px-5 py-2.5 border-b border-ink-200 dark:border-ink-800">
          <StatStrip stats={chips} />
        </div>
      )}

      {loading ? (
        <SkeletonTable rows={8} cols={skeletonCols ?? Math.max(columns?.length ?? 0, 4)} />
      ) : error ? (
        <EmptyState
          icon={<AlertTriangle size={36} />}
          title="数据加载失败"
          description={error}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              <RefreshCw size={13} /> 重试
            </Button>
          }
        />
      ) : totalCount === 0 ? (
        <EmptyState
          icon={<Inbox size={36} />}
          title={emptyTitle}
          description={emptyDescription}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              <RefreshCw size={13} /> 刷新
            </Button>
          }
        />
      ) : hasCustomBody ? (
        children
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<SearchX size={36} />}
          title="没有匹配的记录"
          description="当前搜索或筛选条件没有命中任何记录，可尝试更换关键字或清除筛选。"
          action={
            <Button variant="secondary" size="sm" onClick={onClearFilter}>
              清除筛选
            </Button>
          }
        />
      ) : columns && sort && onSortChange && onOpenRow ? (
        <RecordTable
          rows={rows}
          columns={columns}
          sort={sort}
          onSortChange={onSortChange}
          onOpenRow={onOpenRow}
          getRowKey={getRowKey}
        />
      ) : null}
    </div>
  );
}
