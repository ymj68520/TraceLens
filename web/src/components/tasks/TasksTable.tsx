import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { XCircle, Trash2, FolderInput } from 'lucide-react';
import type { ForensicCase, ForensicTask } from '../../types/api';
import ProgressBar from '../ui/ProgressBar';
import { STATUS_CHIP, PRIORITY_CHIP } from '../../lib/constants';
import { basename, formatDateTime } from '../../lib/utils';
import { useTranslation } from '../../hooks/useTranslation';
import { cx } from '../../lib/utils';

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
  const completedOnPage = useMemo(
    () => tasks.filter((t) => t.status?.toLowerCase() === 'completed'),
    [tasks],
  );
  const allSelected =
    completedOnPage.length > 0 && completedOnPage.every((t) => selectedIds.has(t.id));

  return (
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
            <th>优先级</th>
            <th>进度</th>
            <th>所属案件</th>
            <th>创建时间</th>
            <th className="text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => {
            const parentCase = taskCaseMap[task.id];
            const status = (task.status || '').toLowerCase();
            const progress =
              typeof task.progress === 'object' && task.progress !== null
                ? ((task.progress as { overall_percentage?: number }).overall_percentage ?? 0)
                : ((task as Record<string, unknown>).progress as number) || 0;
            return (
              <tr key={task.id}>
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
                  <span className={cx('chip', STATUS_CHIP[status] ?? STATUS_CHIP.cancelled)}>
                    {t(`task.status.${status}`)}
                  </span>
                </td>
                <td>
                  <span className={cx('chip', PRIORITY_CHIP[task.priority ?? 'normal'] ?? PRIORITY_CHIP.normal)}>
                    {t(`task.priority.${task.priority ?? 'normal'}`)}
                  </span>
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
                  {formatDateTime(task.created_at)}
                </td>
                <td>
                  <div className="flex items-center justify-end gap-1">
                    {status === 'running' && (
                      <button
                        type="button"
                        onClick={() => onCancel(task.id)}
                        className="p-1.5 rounded text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-500/10"
                        title="取消任务"
                      >
                        <XCircle size={15} />
                      </button>
                    )}
                    {status === 'completed' && !parentCase && (
                      <button
                        type="button"
                        onClick={() => onJoinCase(task.id)}
                        className="p-1.5 rounded text-accent-600 hover:bg-accent-50 dark:hover:bg-accent-500/10"
                        title="加入案件"
                      >
                        <FolderInput size={15} />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => onDelete(task.id)}
                      className="p-1.5 rounded text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10"
                      title="删除任务"
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
  );
}
