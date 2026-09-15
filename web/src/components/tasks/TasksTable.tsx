import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { XCircle, Trash2, FolderInput, ArrowUp, ArrowDown, ChevronLeft, ChevronRight } from 'lucide-react';
import type { ForensicCase, ForensicTask } from '../../types/api';
import ProgressBar from '../ui/ProgressBar';
import Badge from '../ui/Badge';
import { basename, formatDateTime, getTaskCreatedMs, cn } from '../../lib/utils';
import { useTranslation } from '../../hooks/useTranslation';

const STATUS_TONE: Record<string, 'success' | 'danger' | 'accent' | 'neutral' | 'warning'> = {
  completed: 'success',
  failed: 'danger',
  running: 'accent',
  pending: 'warning',
  cancelled: 'neutral',
};

const PRIORITY_TONE: Record<string, 'success' | 'danger' | 'accent' | 'neutral' | 'warning' | 'info'> = {
  low: 'neutral',
  normal: 'info',
  high: 'warning',
  critical: 'danger',
};

const PRIORITY_ORDER: Record<string, number> = { critical: 3, high: 2, normal: 1, low: 0 };

type SortKey = 'created' | 'progress' | 'priority';
type SortDir = 'asc' | 'desc';

const PAGE_SIZES = [10, 20, 50];

interface TasksTableProps {
  tasks: ForensicTask[];
  taskCaseMap: Record<string, ForensicCase>;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onCancel: (taskId: string) => void;
  onDelete: (taskId: string) => void;
  onJoinCase: (taskId: string) => void;
}

export default function TasksTable({
  tasks,
  taskCaseMap,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  onCancel,
  onDelete,
  onJoinCase,
}: TasksTableProps) {
  const { t } = useTranslation();
  const [sortKey, setSortKey] = useState<SortKey>('created');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);

  const completedTasks = useMemo(
    () => tasks.filter((t) => t.status?.toLowerCase() === 'completed'),
    [tasks],
  );
  const allSelected =
    completedTasks.length > 0 && completedTasks.every((t) => selectedIds.has(t.id));

  const sorted = useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1;
    const val = (t: ForensicTask): number | string => {
      if (sortKey === 'created') return getTaskCreatedMs(t) ?? 0;
      if (sortKey === 'priority') return PRIORITY_ORDER[(t.priority ?? 'normal').toLowerCase()] ?? 1;
      const p = t.progress;
      return typeof p === 'object' && p !== null
        ? ((p as { overall_percentage?: number }).overall_percentage ?? 0)
        : ((t as Record<string, unknown>).progress as number) || 0;
    };
    return [...tasks].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (va === vb) return 0;
      return va > vb ? dir : -dir;
    });
  }, [tasks, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = sorted.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const rangeStart = sorted.length === 0 ? 0 : safePage * pageSize + 1;
  const rangeEnd = Math.min(sorted.length, safePage * pageSize + pageSize);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
    setPage(0);
  };

  const SortTh = ({ label, k, align }: { label: string; k: SortKey; align?: 'right' }) => (
    <th className={cn(align === 'right' && 'text-right')}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        className={cn(
          'inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-ink-800 dark:hover:text-ink-200',
          sortKey === k && 'text-accent-600 dark:text-accent-400',
        )}
      >
        {label}
        {sortKey === k &&
          (sortDir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
      </button>
    </th>
  );

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="table-shell">
          <thead>
            <tr>
              <th className="w-8">
                <input
                  type="checkbox"
                  className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                  checked={allSelected}
                  onChange={(e) => onToggleSelectAll(e.target.checked)}
                  aria-label="全选已完成任务"
                />
              </th>
              <th>任务</th>
              <th>状态</th>
              <SortTh label="优先级" k="priority" />
              <SortTh label="进度" k="progress" />
              <th>所属案件</th>
              <SortTh label="创建时间" k="created" />
              <th className="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((task) => {
              const parentCase = taskCaseMap[task.id];
              const status = (task.status || '').toLowerCase();
              const progress =
                typeof task.progress === 'object' && task.progress !== null
                  ? ((task.progress as { overall_percentage?: number }).overall_percentage ?? 0)
                  : ((task as Record<string, unknown>).progress as number) || 0;
              return (
                <tr key={task.id} className="animate-fade-in">
                  <td>
                    <input
                      type="checkbox"
                      className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                      checked={selectedIds.has(task.id)}
                      disabled={status !== 'completed'}
                      onChange={() => onToggleSelect(task.id)}
                      aria-label={`选择任务 ${task.id}`}
                    />
                  </td>
                  <td>
                    <div className="min-w-0">
                      <p className="font-medium text-ink-900 dark:text-ink-100 truncate max-w-[260px]" title={task.image_path}>
                        {basename(task.image_path)}
                      </p>
                      <p className="text-2xs font-mono text-ink-400">{task.id.substring(0, 8)}…</p>
                    </div>
                  </td>
                  <td>
                    <Badge tone={STATUS_TONE[status] ?? 'neutral'} dot>
                      {t(`task.status.${status}`)}
                    </Badge>
                  </td>
                  <td>
                    <Badge tone={PRIORITY_TONE[task.priority ?? 'normal'] ?? 'neutral'}>
                      {t(`task.priority.${task.priority ?? 'normal'}`)}
                    </Badge>
                  </td>
                  <td className="w-32">
                    <ProgressBar value={progress} showLabel />
                  </td>
                  <td>
                    {parentCase ? (
                      <Link
                        to={`/cases`}
                        className="text-xs text-accent-600 dark:text-accent-400 hover:underline"
                      >
                        {parentCase.name}
                      </Link>
                    ) : (
                      <span className="text-xs text-ink-400">—</span>
                    )}
                  </td>
                  <td className="text-xs text-ink-500 dark:text-ink-400 whitespace-nowrap">
                    {formatDateTime(getTaskCreatedMs(task))}
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-1">
                      {status === 'running' && (
                        <button
                          type="button"
                          onClick={() => onCancel(task.id)}
                          className="p-1.5 rounded text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-500/10 transition-colors"
                          title="取消任务"
                          aria-label={`取消任务 ${task.id}`}
                        >
                          <XCircle size={15} />
                        </button>
                      )}
                      {status === 'completed' && !parentCase && (
                        <button
                          type="button"
                          onClick={() => onJoinCase(task.id)}
                          className="p-1.5 rounded text-accent-600 hover:bg-accent-50 dark:hover:bg-accent-500/10 transition-colors"
                          title="加入案件"
                          aria-label={`将任务 ${task.id} 加入案件`}
                        >
                          <FolderInput size={15} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => onDelete(task.id)}
                        className="p-1.5 rounded text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10 transition-colors"
                        title="删除任务"
                        aria-label={`删除任务 ${task.id}`}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-t border-ink-100 dark:border-ink-800/60">
        <p className="text-2xs text-ink-400 dark:text-ink-500">
          第 <span className="font-mono">{rangeStart}</span>–<span className="font-mono">{rangeEnd}</span> 条，
          共 <span className="font-mono">{sorted.length}</span> 个任务
        </p>
        <div className="flex items-center gap-2">
          <select
            className="select w-24 py-1 text-2xs"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(0);
            }}
            aria-label="每页条数"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n} 条/页
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-secondary btn-sm"
            disabled={safePage === 0}
            onClick={() => setPage(safePage - 1)}
            aria-label="上一页"
          >
            <ChevronLeft size={13} />
          </button>
          <span className="text-2xs text-ink-500 dark:text-ink-400 font-mono tabular-nums px-1">
            {safePage + 1} / {pageCount}
          </span>
          <button
            type="button"
            className="btn-secondary btn-sm"
            disabled={safePage >= pageCount - 1}
            onClick={() => setPage(safePage + 1)}
            aria-label="下一页"
          >
            <ChevronRight size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
