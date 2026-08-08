/**
 * ReportReaderSearch
 * 报告全文搜索框，显示命中总数与上一条/下一条跳转。
 */
import { useCallback } from 'react';

export default function ReportReaderSearch({
  query, onQueryChange, onSubmit, onClear, searching, result, onHit, submitted,
}) {
  const handleKey = useCallback((e) => {
    if (e.key === 'Enter') onSubmit();
  }, [onSubmit]);

  return (
    <div className="space-y-1">
      <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">报告搜索</h3>
      <div className="flex gap-1">
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder="搜索文件/事件…"
          className="flex-1 min-w-0 px-2 py-1 text-xs border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-800 dark:text-white"
        />
        <button
          type="button"
          onClick={onSubmit}
          disabled={searching || !query.trim()}
          className="px-2 py-1 text-xs rounded-md bg-primary-600 text-white disabled:opacity-50"
        >查找</button>
        {submitted && (
          <button
            type="button"
            onClick={onClear}
            className="px-2 py-1 text-xs rounded-md border border-slate-300 dark:border-slate-600"
          >清空</button>
        )}
      </div>
      {searching && <p className="text-[10px] text-slate-400">正在搜索…</p>}
      {!searching && result && (
        <div className="text-[10px] text-slate-500 dark:text-slate-400 space-y-1">
          <p>命中 {result.total} 条</p>
          {result.hits?.slice(0, 5).map((hit, i) => (
            <button
              type="button"
              key={`${hit.category}-${hit.record_id}-${i}`}
              onClick={() => onHit(hit)}
              className="block w-full text-left truncate hover:text-primary-600"
              title={hit.title}
            >
              · {hit.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
