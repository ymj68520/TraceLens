import { useEffect, useState } from 'react';
import Button from '../common/Button';

export default function ReportSearch({
  query, result, currentHit, cursor, loading, error, submit, next, previous,
}) {
  const [value, setValue] = useState(query || '');
  const hits = result?.hits || [];

  useEffect(() => { setValue(query || ''); }, [query]);

  return (
    <form
      role="search"
      className="space-y-2 border-b border-slate-200 pb-4 dark:border-slate-700"
      onSubmit={(event) => {
        event.preventDefault();
        void submit(value);
      }}
    >
      <label htmlFor="report-search" className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
        报告内搜索
      </label>
      <div className="flex gap-2">
        <input
          id="report-search"
          type="search"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="记录、路径或关键词"
          className="min-w-0 flex-1 rounded-lg border-slate-300 bg-white text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        />
        <Button type="submit" size="sm" loading={loading}>
          查找
        </Button>
      </div>
      {error && <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">搜索失败：{error.message || String(error)}</p>}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={previous}
          disabled={!hits.length}
          className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-200"
        >
          上一个
        </button>
        <button
          type="button"
          onClick={next}
          disabled={!hits.length}
          className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-200"
        >
          下一个
        </button>
        <output className="ml-auto text-xs tabular-nums text-slate-500 dark:text-slate-400">
          {hits.length && currentHit ? `${cursor + 1} / ${result.total || hits.length}` : '0 个命中'}
        </output>
      </div>
    </form>
  );
}
