import { useMemo, useState } from 'react';
import { Database, Search } from 'lucide-react';
import Badge from '../../components/ui/Badge';
import EmptyState from '../../components/ui/EmptyState';
import { SkeletonTable } from '../../components/ui/PageScaffold';
import { basename, cx } from '../../lib/utils';

export interface EvidenceRow {
  evidence_key: string;
  kind?: string;
  file_path?: string;
  [key: string]: unknown;
}

const UNTYPED = '未分类';

const kindOf = (row: EvidenceRow) => {
  const k = typeof row.kind === 'string' ? row.kind.trim() : '';
  return k || UNTYPED;
};

interface EvidenceListPanelProps {
  rows: EvidenceRow[];
  loading: boolean;
  selectedKey: string | null;
  /** URL 持久化的证据类型过滤（'all' = 全部）。 */
  etype: string;
  onEtypeChange: (v: string) => void;
  onSelect: (row: EvidenceRow) => void;
}

/** 左侧证据/实体清单：搜索 + 类型过滤（计数徽章）+ 列表。 */
export default function EvidenceListPanel({
  rows,
  loading,
  selectedKey,
  etype,
  onEtypeChange,
  onSelect,
}: EvidenceListPanelProps) {
  const [query, setQuery] = useState('');

  // 类型维度聚合：kind 字段缺失的归入「未分类」。
  const typeCounts = useMemo(() => {
    const map = new Map<string, number>();
    rows.forEach((r) => {
      const k = kindOf(r);
      map.set(k, (map.get(k) ?? 0) + 1);
    });
    return [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (etype !== 'all' && kindOf(r) !== etype) return false;
      if (!q) return true;
      return (
        r.evidence_key.toLowerCase().includes(q) ||
        kindOf(r).toLowerCase().includes(q) ||
        (typeof r.file_path === 'string' && r.file_path.toLowerCase().includes(q))
      );
    });
  }, [rows, etype, query]);

  return (
    <div className="card flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Database size={14} className="text-ink-400 shrink-0" />
          <h3 className="card-title">证据清单</h3>
        </div>
        <Badge tone={filtered.length === rows.length ? 'neutral' : 'accent'}>
          {filtered.length}/{rows.length}
        </Badge>
      </div>

      {/* 搜索 */}
      <div className="px-3 pt-3 shrink-0">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" />
          <input
            type="text"
            className="input py-1.5 pl-8 text-xs"
            placeholder="搜索证据标识 / 路径 / 类型…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {/* 类型过滤 chips */}
      <div className="px-3 py-2.5 flex flex-wrap gap-1 shrink-0 border-b border-ink-100 dark:border-ink-800/60">
        {loading && rows.length === 0 ? null : (
          <>
            <button
              type="button"
              onClick={() => onEtypeChange('all')}
              className={cx(
                'rounded-md border px-1.5 py-0.5 text-2xs font-medium transition-colors',
                etype === 'all'
                  ? 'border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-300'
                  : 'border-ink-200 bg-white text-ink-500 hover:border-ink-300 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-400 dark:hover:border-ink-600',
              )}
            >
              全部 <span className="font-mono tabular-nums">{rows.length}</span>
            </button>
            {typeCounts.map(([kind, count]) => (
              <button
                key={kind}
                type="button"
                onClick={() => onEtypeChange(etype === kind ? 'all' : kind)}
                className={cx(
                  'rounded-md border px-1.5 py-0.5 text-2xs font-medium transition-colors max-w-[130px]',
                  etype === kind
                    ? 'border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-300'
                    : 'border-ink-200 bg-white text-ink-500 hover:border-ink-300 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-400 dark:hover:border-ink-600',
                )}
                title={kind}
              >
                <span className="truncate">{kind}</span>{' '}
                <span className="font-mono tabular-nums">{count}</span>
              </button>
            ))}
          </>
        )}
      </div>

      {/* 列表 */}
      {loading && rows.length === 0 ? (
        <SkeletonTable rows={8} cols={2} />
      ) : filtered.length === 0 ? (
        <EmptyState
          className="flex-1"
          icon={<Database size={30} />}
          title={rows.length === 0 ? '暂无证据' : '未匹配到证据'}
          description={rows.length === 0 ? '可从时间线/文件页捕获证据进入调查。' : '调整搜索词或类型过滤条件。'}
        />
      ) : (
        <ul className="flex-1 overflow-y-auto divide-y divide-ink-100 dark:divide-ink-800/60 min-h-0">
          {filtered.map((row) => (
            <li key={row.evidence_key}>
              <button
                type="button"
                onClick={() => onSelect(row)}
                className={cx(
                  'w-full text-left px-4 py-2.5 transition-colors',
                  row.evidence_key === selectedKey
                    ? 'bg-accent-50 dark:bg-accent-500/10'
                    : 'hover:bg-ink-50 dark:hover:bg-ink-900/50',
                )}
              >
                <p
                  className={cx(
                    'text-xs font-mono truncate',
                    row.evidence_key === selectedKey
                      ? 'text-accent-800 dark:text-accent-200 font-medium'
                      : 'text-ink-800 dark:text-ink-100',
                  )}
                  title={row.evidence_key}
                >
                  {row.evidence_key}
                </p>
                <div className="mt-0.5 flex items-center gap-1.5 min-w-0">
                  <span className="chip bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400 shrink-0">
                    {kindOf(row)}
                  </span>
                  {typeof row.file_path === 'string' && row.file_path && (
                    <span className="text-2xs text-ink-400 truncate" title={row.file_path}>
                      {basename(row.file_path)}
                    </span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
