/**
 * ReportReaderPagination
 * 参考底部 paginator：页码输入、跳转、上一页、返回目录、下一页。
 */
import { useState } from 'react';

export default function ReportReaderPagination({ page, totalPages, onPage, onBackToMenu }) {
  const [value, setValue] = useState(String(page));
  // keep input in sync when page changes externally
  if (String(page) !== value && document.activeElement?.tagName !== 'INPUT') {
    setValue(String(page));
  }
  const jump = () => {
    const n = Math.max(1, Math.min(totalPages, parseInt(value, 10) || 1));
    onPage(n);
  };

  return (
    <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white/90 px-3 py-2 text-xs shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-800/90">
      <input
        type="number"
        className="w-16 px-2 py-1 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-900 dark:text-white"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') jump(); }}
        min={1}
        max={totalPages}
      />
      <span className="text-slate-500 dark:text-slate-400">/ {totalPages}</span>
      <button type="button" onClick={jump} className="px-2 py-1 rounded-md border border-slate-300 dark:border-slate-600">跳转</button>
      <button
        type="button"
        onClick={() => onPage(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="px-2 py-1 rounded-md border border-slate-300 dark:border-slate-600 disabled:opacity-40"
      >上一页</button>
      {onBackToMenu && (
        <button type="button" onClick={onBackToMenu} className="px-2 py-1 rounded-md border border-slate-300 dark:border-slate-600">返回目录</button>
      )}
      <button
        type="button"
        onClick={() => onPage(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="px-2 py-1 rounded-md border border-slate-300 dark:border-slate-600 disabled:opacity-40"
      >下一页</button>
    </div>
  );
}
