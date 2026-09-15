import { createContext, useContext } from 'react';
import type { HTMLAttributes, TableHTMLAttributes } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import HighlightText from '../../components/search/HighlightText';
import { cx } from '../../lib/utils';
import { formatCell, type OssColumn, type OssRow } from './ossUtils';

interface OssDataTableProps {
  columns: OssColumn[];
  rows: OssRow[];
  sortKey: string | null;
  sortDir: 'asc' | 'desc';
  /** Active search query — matched text is highlighted in text cells. */
  query: string;
  onSortChange: (col: OssColumn) => void;
  onSelectRow: (row: OssRow) => void;
}

/** Row click handler flows through context because Virtuoso renders rows itself. */
const RowSelectContext = createContext<(row: OssRow) => void>(() => {});

type VirtuosoRowProps = HTMLAttributes<HTMLTableRowElement> & {
  item?: unknown;
  context?: unknown;
  'data-index'?: number | string;
  'data-known-size'?: number | string;
};

function VirtuosoTableRow({ item, ...props }: VirtuosoRowProps) {
  const onSelect = useContext(RowSelectContext);
  return (
    <tr
      {...props}
      tabIndex={0}
      title="点击查看字段详情"
      className={cx('cursor-pointer', props.className)}
      onClick={(e) => {
        props.onClick?.(e);
        if (item) onSelect(item as OssRow);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && e.target === e.currentTarget && item) onSelect(item as OssRow);
      }}
    />
  );
}

const VirtuosoTable = (props: TableHTMLAttributes<HTMLTableElement>) => (
  <table {...props} className={cx('table-shell', props.className)} />
);

// Stable identity — Virtuoso remounts rows when the components object changes.
const VIRTUOSO_COMPONENTS = { Table: VirtuosoTable, TableRow: VirtuosoTableRow };

function SortableHeader({
  col,
  sortKey,
  sortDir,
  onSortChange,
}: {
  col: OssColumn;
  sortKey: string | null;
  sortDir: 'asc' | 'desc';
  onSortChange: (col: OssColumn) => void;
}) {
  const active = sortKey === col.key;
  const Icon = active ? (sortDir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th
      className={cx('sticky top-0 z-10 bg-white dark:bg-ink-925', col.align === 'right' && 'text-right')}
      aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={() => onSortChange(col)}
        title={active ? `切换为${sortDir === 'asc' ? '降序' : '升序'}` : `按${col.label}排序`}
        className={cx(
          'inline-flex items-center gap-1 uppercase tracking-wider font-semibold',
          active
            ? 'text-accent-600 dark:text-accent-400'
            : 'text-ink-500 dark:text-ink-400 hover:text-ink-800 dark:hover:text-ink-200 transition-colors',
        )}
      >
        {col.label}
        <Icon size={12} strokeWidth={active ? 2.4 : 2} className={cx(!active && 'text-ink-300 dark:text-ink-600')} />
      </button>
    </th>
  );
}

/** Virtualized evidence table: sticky sortable headers, row-click detail, search highlight. */
export default function OssDataTable({
  columns,
  rows,
  sortKey,
  sortDir,
  query,
  onSortChange,
  onSelectRow,
}: OssDataTableProps) {
  return (
    <RowSelectContext.Provider value={onSelectRow}>
      <div className="h-[560px]">
        <TableVirtuoso
          style={{ height: '100%' }}
          data={rows}
          components={VIRTUOSO_COMPONENTS}
          fixedHeaderContent={() => (
            <tr>
              {columns.map((col) => (
                <SortableHeader key={col.key} col={col} sortKey={sortKey} sortDir={sortDir} onSortChange={onSortChange} />
              ))}
            </tr>
          )}
          itemContent={(_index, row) => (
            <>
              {columns.map((col) => {
                const text = formatCell(row[col.key], col.kind);
                return (
                  <td
                    key={col.key}
                    title={text}
                    className={cx(
                      'text-xs',
                      col.align === 'right' && 'text-right',
                      (col.kind !== 'text' || col.mono) && 'font-mono tabular-nums whitespace-nowrap',
                      col.kind === 'text' && 'max-w-[300px] truncate',
                    )}
                  >
                    {col.kind === 'text' ? <HighlightText text={text} query={query} /> : text}
                  </td>
                );
              })}
            </>
          )}
        />
      </div>
    </RowSelectContext.Provider>
  );
}
