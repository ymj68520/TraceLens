import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import Badge from '../../components/ui/Badge';
import Button from '../../components/ui/Button';
import { SkeletonBlock } from '../../components/ui/PageScaffold';
import { cx } from '../../lib/utils';
import { formatPlainValue, type CategoryPageState, type ReportSection } from './reportModel';
import MarkdownLite from './MarkdownLite';

interface Props {
  section: ReportSection;
  index: number;
  /** Current page state — table sections only. */
  state?: CategoryPageState;
  collapsed: boolean;
  onToggle: () => void;
  onRetryPage: () => void;
  onPageChange: (page: number) => void;
}

const NUMERIC_RE = /count|total|size|bytes|^id$|num$/i;

/**
 * One report section as a collapsible card with a stable anchor id
 * (`data-report-section`) for the TOC scroll-spy.
 */
export default function ReportSectionCard({
  section,
  index,
  state,
  collapsed,
  onToggle,
  onRetryPage,
  onPageChange,
}: Props) {
  const records = state?.records ?? [];
  const columns = records.length > 0 ? Object.keys(records[0]).slice(0, 6) : [];
  const total = state?.total ?? section.totalCount;
  const page = state?.page ?? 1;
  const hasMore = records.length > 0 && total !== undefined && page * records.length < total;

  return (
    <section id={section.id} data-report-section={section.id} className="card card-hover scroll-mt-24">
      <div className={cx('flex items-center gap-3 px-5 py-3', !collapsed && 'border-b border-ink-100 dark:border-ink-800')}>
        <span className="hidden sm:flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-ink-100 dark:bg-ink-800 font-mono text-2xs text-ink-500 dark:text-ink-300">
          {String(index + 1).padStart(2, '0')}
        </span>
        <h2 className="min-w-0 flex-1 text-sm font-semibold text-ink-900 dark:text-ink-100 truncate" title={section.title}>
          {section.title}
        </h2>
        {section.kind === 'table' && total !== undefined && (
          <Badge tone="neutral">
            <span className="font-mono tabular-nums">{total.toLocaleString('en-US')}</span> 条
          </Badge>
        )}
        <button
          type="button"
          onClick={onToggle}
          className="p-1.5 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors print:hidden"
          aria-label={collapsed ? '展开章节' : '收起章节'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        </button>
      </div>

      {!collapsed && (
        <div className="px-5 py-4">
          {section.kind === 'markdown' ? (
            <MarkdownLite blocks={section.blocks ?? []} />
          ) : state?.error ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="flex-1 min-w-0 text-xs text-rose-600 dark:text-rose-400">
                该章节记录加载失败：{state.error}
              </p>
              <Button size="sm" variant="secondary" onClick={onRetryPage}>
                <RefreshCw size={13} /> 重试
              </Button>
            </div>
          ) : !state || state.loading ? (
            <div className="space-y-2.5" aria-hidden>
              {Array.from({ length: 4 }).map((_, i) => (
                <SkeletonBlock key={i} className={cx('h-3.5', i % 2 === 0 ? 'w-3/4' : 'w-1/2')} />
              ))}
            </div>
          ) : records.length === 0 ? (
            <p className="text-xs text-ink-400 dark:text-ink-500">该章节暂无记录。</p>
          ) : (
            <>
              <div className="overflow-x-auto border border-ink-200 dark:border-ink-800 rounded-md">
                <table className="table-shell">
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((r, i) => (
                      <tr key={i}>
                        {columns.map((c) => {
                          const text = formatPlainValue(r[c]);
                          return (
                            <td
                              key={c}
                              title={text}
                              className={cx('text-xs max-w-[220px] truncate', NUMERIC_RE.test(c) && 'font-mono tabular-nums')}
                            >
                              {text || '—'}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-end gap-3 mt-3 text-2xs text-ink-500 dark:text-ink-400 print:hidden">
                <button
                  type="button"
                  className="btn-ghost btn-sm"
                  disabled={page <= 1}
                  onClick={() => onPageChange(page - 1)}
                >
                  上一页
                </button>
                <span className="tabular-nums font-mono">
                  第 {page} 页
                  {total !== undefined ? ` · 共 ${total.toLocaleString('en-US')} 条` : ''}
                </span>
                <button
                  type="button"
                  className="btn-ghost btn-sm"
                  disabled={!hasMore}
                  onClick={() => onPageChange(page + 1)}
                >
                  下一页
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
