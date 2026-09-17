import { useEffect, useMemo, useState } from 'react';
import { Clock, RefreshCw } from 'lucide-react';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import { pythonApi } from '../../../services/api';

/**
 * File Timeline for the final report page (mvp-phase1-acceptance SPEC §6.1).
 *
 * Data source is the filtered/selected FILES of the task (not events): every
 * file contributes up to four forensic timestamps (created/modified/accessed/
 * changed), placed proportionally on a shared axis that starts at the earliest
 * of all timestamps and ends at the latest.
 */

const PAGE_SIZE = 200;

const TIME_TYPES = [
  { key: 'crtime', label: '创建', dot: 'bg-emerald-500', chip: 'text-emerald-700 dark:text-emerald-300' },
  { key: 'mtime', label: '修改', dot: 'bg-blue-500', chip: 'text-blue-700 dark:text-blue-300' },
  { key: 'atime', label: '访问', dot: 'bg-amber-500', chip: 'text-amber-700 dark:text-amber-300' },
  { key: 'ctime', label: '变更', dot: 'bg-purple-500', chip: 'text-purple-700 dark:text-purple-300' },
];

export const formatFileTime = (value) => {
  const n = Number(value);
  if (!n) return null;
  const date = new Date(n * 1000);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
};

const fileTimes = (file) => TIME_TYPES
  .map(({ key, label, dot, chip }) => ({ key, label, dot, chip, value: file[key] }))
  .filter((entry) => Number(entry.value) > 0);

export default function FileTimestampTimeline({ taskId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  useEffect(() => {
    if (!taskId) return undefined;
    let alive = true;
    setLoading(true);
    setError(null);
    pythonApi
      .get('/api/associations/file-timeline', { params: { task_id: taskId } })
      .then((payload) => {
        if (alive) setData(payload);
      })
      .catch((err) => {
        if (alive) setError(err);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [taskId]);

  const axis = useMemo(() => data?.axis || { start: null, end: null }, [data]);

  const positionPct = (value) => {
    const start = Number(axis.start);
    const end = Number(axis.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 50;
    const pct = ((Number(value) - start) / (end - start)) * 100;
    return Math.min(100, Math.max(0, pct));
  };

  if (!taskId) return null;
  if (loading) return <div className="rounded-2xl glass p-8 flex justify-center" data-testid="file-timeline-loading"><Spinner size="lg" /></div>;
  if (error) {
    return (
      <div className="rounded-2xl glass p-5 text-sm text-rose-700 dark:text-rose-300" data-testid="file-timeline-error">
        文件时间线加载失败：{error.message || error}
      </div>
    );
  }

  const files = data?.files || [];

  return (
    <section className="rounded-2xl glass p-5" aria-label="File timeline" data-testid="file-timeline">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2"><Clock size={18} className="text-primary-500" />文件时间线</h2>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            筛选范围文件的四类时间戳（创建/修改/访问/变更），轴范围为全部时间的最早到最新。
            {typeof data?.scope_size === 'number' && ` 范围文件 ${data.scope_size} 个。`}
          </p>
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 font-mono" data-testid="file-timeline-axis">
          {formatFileTime(axis.start) || '—'} → {formatFileTime(axis.end) || '—'}
        </div>
      </div>

      {files.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 p-6 text-center text-sm text-slate-500 dark:text-slate-400">
          筛选范围内暂无带时间戳的文件。
        </div>
      ) : (
        <>
          <ul className="mt-4 space-y-3">
            {files.slice(0, visibleCount).map((file) => {
              const times = fileTimes(file);
              return (
                <li key={file.path} className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-3" data-testid="file-timeline-row">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm font-semibold text-slate-800 dark:text-slate-200 break-all">{file.name || file.path}</span>
                    <span className="text-xs text-slate-400 font-mono break-all">{file.path}</span>
                  </div>
                  <div className="relative mt-3 h-2 rounded-full bg-slate-200/80 dark:bg-slate-800" data-testid="file-timeline-track">
                    {times.map(({ key, value, dot, label }) => (
                      <span
                        key={key}
                        title={`${label} ${formatFileTime(value) || value}`}
                        aria-label={`${label}: ${formatFileTime(value) || value}`}
                        className={`absolute -top-1 h-4 w-4 rounded-full border-2 border-white dark:border-slate-900 ${dot}`}
                        style={{ left: `calc(${positionPct(value)}% - 8px)` }}
                        data-testid={`file-timeline-marker-${key}`}
                      />
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
                    {times.map(({ key, label, value, chip }) => (
                      <span key={key} className={chip} data-testid={`file-timeline-time-${key}`}>
                        {label} {formatFileTime(value) || value}
                      </span>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
          {files.length > visibleCount && (
            <div className="mt-4 flex justify-center">
              <Button size="sm" variant="secondary" icon={RefreshCw} onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
                加载更多（已显示 {visibleCount}/{files.length}）
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
