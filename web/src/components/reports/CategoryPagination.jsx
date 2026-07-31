import { useEffect, useMemo, useState } from 'react';
import Button from '../common/Button';

function validPage(value, pageCount) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) return null;
  return Math.min(Math.max(parsed, 1), pageCount);
}

export default function CategoryPagination({
  page, pageSize, total, pages, onPageChange,
}) {
  const pageCount = Math.max(
    1,
    Number.isFinite(Number(pages)) && Number(pages) > 0
      ? Math.ceil(Number(pages))
      : Math.ceil(Math.max(0, Number(total) || 0) / Math.max(1, Number(pageSize) || 1)),
  );
  const currentPage = Math.min(Math.max(Number(page) || 1, 1), pageCount);
  const [draft, setDraft] = useState(String(currentPage));

  useEffect(() => { setDraft(String(currentPage)); }, [currentPage]);

  const displayPageSize = useMemo(() => Math.max(1, Number(pageSize) || 1), [pageSize]);
  const commit = () => {
    const nextPage = validPage(draft, pageCount);
    if (nextPage === null) {
      setDraft(String(currentPage));
      return;
    }
    setDraft(String(nextPage));
    if (nextPage !== currentPage) onPageChange(nextPage);
  };

  return (
    <nav aria-label="分类分页" className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
      <Button
        variant="outline"
        size="sm"
        disabled={currentPage <= 1}
        onClick={() => onPageChange(currentPage - 1)}
      >
        上一页
      </Button>
      <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
        第
        <input
          aria-label="页码"
          type="text"
          inputMode="numeric"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              event.currentTarget.blur();
            }
          }}
          className="w-16 rounded-lg border-slate-300 bg-white px-2 py-1 text-center font-mono tabular-nums dark:border-slate-700 dark:bg-slate-950"
        />
        / {pageCount} 页
      </label>
      <Button
        variant="outline"
        size="sm"
        disabled={currentPage >= pageCount}
        onClick={() => onPageChange(currentPage + 1)}
      >
        下一页
      </Button>
      <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
        每页 {displayPageSize} 条 · 共 {Math.max(0, Number(total) || 0)} 条
      </span>
    </nav>
  );
}
