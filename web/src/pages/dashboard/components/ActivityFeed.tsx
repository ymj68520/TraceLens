import { useMemo } from 'react';
import Card, { CardHeader } from '../../../components/ui/Card';
import Badge from '../../../components/ui/Badge';
import EmptyState from '../../../components/ui/EmptyState';
import { SkeletonBlock } from '../../../components/ui/PageScaffold';
import { cx, basename, formatRelativeTime, getTaskCreatedMs } from '../../../lib/utils';
import { useTranslation } from '../../../hooks/useTranslation';
import type { ForensicTask } from '../../../types/api';

interface Props {
  tasks: ForensicTask[];
  loading: boolean;
  /** How many recent tasks to render (newest first). */
  max?: number;
}

type BadgeTone = 'success' | 'danger' | 'accent' | 'warning' | 'neutral';

const BADGE_TONE: Record<string, BadgeTone> = {
  completed: 'success',
  failed: 'danger',
  running: 'accent',
  pending: 'warning',
  cancelled: 'neutral',
};

/** Timeline dot per status; running keeps a soft pulse. */
const DOT_CLASS: Record<string, string> = {
  completed: 'bg-emerald-500',
  failed: 'bg-rose-500',
  running: 'bg-accent-500 animate-pulse',
  pending: 'bg-amber-400',
  cancelled: 'bg-ink-300 dark:bg-ink-600',
};

/**
 * Vertical activity feed of the most recent tasks — status dot, image name,
 * status badge and relative time on a connected timeline rail.
 */
export default function ActivityFeed({ tasks, loading, max = 6 }: Props) {
  const { t } = useTranslation();

  const items = useMemo(
    () =>
      [...tasks]
        .map((task) => ({ task, createdMs: getTaskCreatedMs(task) }))
        .sort((a, b) => (b.createdMs ?? 0) - (a.createdMs ?? 0))
        .slice(0, max),
    [tasks, max],
  );

  return (
    <Card padded={ false } className="animate-rise" style={ { animationDelay: '180ms' } }>
      <div className="px-5 pt-4">
        <CardHeader title={ t('dashboard.feed.title') } subtitle={ t('dashboard.feed.subtitle') } />
      </div>
      {loading ? (
        <div className="px-5 pb-6 space-y-4" aria-label={ t('common.loading') }>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={ i } className="flex items-center gap-3" style={ { opacity: 1 - i * 0.15 } }>
              <SkeletonBlock className="h-3 w-3 shrink-0 rounded-full" />
              <SkeletonBlock className="h-3 flex-1" />
              <SkeletonBlock className="h-3 w-12" />
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          className="py-10"
          title={ t('dashboard.feed.empty.title') }
          description={ t('dashboard.feed.empty.desc') }
        />
      ) : (
        <ol className="px-5 pb-5">
          {items.map(({ task, createdMs }, i) => {
            const statusKey = (task.status || '').toLowerCase();
            const progress = typeof task.progress === 'number' ? Math.round(task.progress) : null;
            return (
              <li key={ task.id } className="relative pl-6 pb-4 last:pb-0">
                {i < items.length - 1 && (
                  <span
                    aria-hidden
                    className="absolute left-[6px] top-4 bottom-0 w-px bg-ink-200 dark:bg-ink-800"
                  />
                )}
                <span
                  aria-hidden
                  className={ cx(
                    'absolute left-0 top-0.5 h-3 w-3 rounded-full ring-2 ring-white dark:ring-ink-925',
                    DOT_CLASS[statusKey] ?? 'bg-ink-300 dark:bg-ink-600',
                  ) }
                />
                <div className="flex items-baseline justify-between gap-2 min-w-0">
                  <span
                    className="truncate text-xs font-medium text-ink-800 dark:text-ink-100"
                    title={ task.image_path }
                  >
                    {basename(task.image_path) || task.id}
                  </span>
                  <span
                    className="shrink-0 text-2xs text-ink-400 dark:text-ink-500 whitespace-nowrap"
                    title={ task.id }
                  >
                    {formatRelativeTime(createdMs)}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <Badge tone={ BADGE_TONE[statusKey] ?? 'neutral' } dot>
                    {t(`task.status.${statusKey}`) || task.status}
                  </Badge>
                  {task.status === 'running' && progress != null && (
                    <span className="font-mono text-2xs text-accent-600 dark:text-accent-400 tabular-nums">
                      {progress}%
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      ) }
    </Card>
  );
}
