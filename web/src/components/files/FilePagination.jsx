const FilePagination = ({ page, totalPages, total, pageSize = 100, onChange }) => {
  const safeTotalPages = Math.max(totalPages, 1);
  const prev = () => onChange(Math.max(page - 1, 1));
  const next = () => onChange(Math.min(page + 1, safeTotalPages));
  const canPrev = page > 1;
  const canNext = page < safeTotalPages;

  const btnBase = 'px-3 py-1.5 text-sm rounded-md border transition-colors disabled:opacity-40 disabled:cursor-not-allowed';
  const btnIdle = 'bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700';

  return (
    <div className="flex items-center justify-between mt-4 px-1 flex-wrap gap-2">
      <span className="text-sm text-slate-500 dark:text-slate-400">
        共 {total.toLocaleString()} 个文件 · 每页 {pageSize} 条
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={prev}
          disabled={!canPrev}
          className={`${btnBase} ${canPrev ? btnIdle : 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-400'}`}
        >
          ← 上一页
        </button>
        <span className="text-sm text-slate-600 dark:text-slate-300 px-2">
          第 {page} / {safeTotalPages} 页
        </span>
        <button
          onClick={next}
          disabled={!canNext}
          className={`${btnBase} ${canNext ? btnIdle : 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-400'}`}
        >
          下一页 →
        </button>
      </div>
    </div>
  );
};

export default FilePagination;
