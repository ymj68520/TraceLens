import { ListChecks } from 'lucide-react';
import type { ForensicTask } from '../../types/api';
import Badge from '../ui/Badge';
import EmptyState from '../ui/EmptyState';
import { SkeletonBlock } from '../ui/PageScaffold';
import { basename, cn } from '../../lib/utils';

interface TaskCheckListProps {
  tasks: ForensicTask[];
  selected: Set<string>;
  onToggle: (taskId: string) => void;
  /** Renders skeleton rows instead of the list while data is loading. */
  loading?: boolean;
  skeletonRows?: number;
  emptyTitle?: string;
  emptyDescription?: string;
  maxHeightClass?: string;
  showStatusBadge?: boolean;
}

/**
 * Reusable checkbox list of (completed) forensic tasks, shared by the case
 * create wizard, compose-case and add-tasks modals. Carries its own loading
 * skeleton and empty state so call sites stay declarative.
 */
export function TaskCheckList({
  tasks,
  selected,
  onToggle,
  loading = false,
  skeletonRows = 4,
  emptyTitle = '没有可选任务',
  emptyDescription,
  maxHeightClass = 'max-h-56',
  showStatusBadge = true,
}: TaskCheckListProps) {
  if (loading) {
    return (
      <div
        className="rounded-md border border-ink-200 dark:border-ink-700 divide-y divide-ink-100 dark:divide-ink-800"
        aria-label="任务加载中"
      >
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-2.5" style={{ opacity: 1 - i * 0.15 }}>
            <SkeletonBlock className="h-3.5 w-3.5" />
            <div className="flex-1 space-y-1.5">
              <SkeletonBlock className="h-3 w-1/2" />
              <SkeletonBlock className="h-2 w-1/4" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <EmptyState
        className="py-8"
        icon={<ListChecks size={28} />}
        title={emptyTitle}
        description={emptyDescription}
      />
    );
  }

  return (
    <ul
      className={cn(
        maxHeightClass,
        'overflow-y-auto rounded-md border border-ink-200 dark:border-ink-700 divide-y divide-ink-100 dark:divide-ink-800',
      )}
    >
      {tasks.map((task) => (
        <li key={task.id}>
          <label className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-900/50">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={selected.has(task.id)}
              onChange={() => onToggle(task.id)}
              aria-label={`选择任务 ${basename(task.image_path) || task.id}`}
            />
            <span className="flex-1 min-w-0">
              <span className="block text-sm text-ink-800 dark:text-ink-200 truncate">
                {basename(task.image_path) || task.image_path}
              </span>
              <span className="block text-2xs font-mono text-ink-400">{task.id}</span>
            </span>
            {showStatusBadge && <Badge tone="success">已完成</Badge>}
          </label>
        </li>
      ))}
    </ul>
  );
}

export default TaskCheckList;
