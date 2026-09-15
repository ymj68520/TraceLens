import { useMemo } from 'react';
import { Hourglass, Timer, Zap } from 'lucide-react';
import Card, { CardHeader } from '../../../components/ui/Card';
import EmptyState from '../../../components/ui/EmptyState';
import { SkeletonBlock } from '../../../components/ui/PageScaffold';
import { useTranslation } from '../../../hooks/useTranslation';
import { cx, formatDuration } from '../../../lib/utils';
import { summarizeDurations } from './durationUtils';
import type { ForensicTask } from '../../../types/api';

interface Props {
  tasks: ForensicTask[];
  loading: boolean;
}

/** Keep the bar list readable in the 2/3 column; slower rows float to the top. */
const MAX_BARS = 8;

/** Fastest/slowest marker chips — hidden when a single sample can't compare. */
function MarkChip({ kind }: { kind: 'fastest' | 'slowest' }) {
  const { t } = useTranslation();
  return (
    <span
      className={cx(
        'inline-flex items-center gap-0.5 rounded px-1 py-px text-2xs font-medium leading-4',
        kind === 'fastest'
          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
          : 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
      )}
    >
      {kind === 'fastest' ? <Zap size={9} /> : <Hourglass size={9} />}
      {kind === 'fastest' ? t('dashboard.duration.fastest') : t('dashboard.duration.slowest')}
    </span>
  );
}

/**
 * Task duration analysis — real `timestamps.execution_time_seconds` data:
 * average KPI on top, one horizontal bar per task below, with the fastest
 * and slowest runs annotated. Degrades to an explanation when the backend
 * has not recorded any durations yet.
 */
export default function DurationAnalysis({ tasks, loading }: Props) {
  const { t } = useTranslation();
  const summary = useMemo(() => summarizeDurations(tasks), [tasks]);
  const rows = summary ? summary.entries.slice(0, MAX_BARS) : [];
  const maxMs = rows.length > 0 ? rows[0].ms : 0;
  const comparable = summary != null && summary.count > 1;

  return (
    <Card className="px-5 py-4 animate-rise" style={ { animationDelay: '120ms' } }>
      <CardHeader
        title={ t('dashboard.duration.title') }
        subtitle={ t('dashboard.duration.subtitle') }
      />
      {loading ? (
        <div className="space-y-4 py-1" aria-label={ t('common.loading') }>
          <div className="flex gap-8">
            <SkeletonBlock className="h-10 w-24" />
            <SkeletonBlock className="h-10 w-24" />
            <SkeletonBlock className="h-10 w-24" />
          </div>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={ i } className="flex items-center gap-3" style={ { opacity: 1 - i * 0.15 } }>
              <SkeletonBlock className="h-2.5 w-20" />
              <SkeletonBlock className="h-2.5 flex-1" />
              <SkeletonBlock className="h-2.5 w-12" />
            </div>
          ))}
        </div>
      ) : !summary ? (
        <EmptyState
          className="py-10"
          icon={ <Timer size={28} strokeWidth={1.6} /> }
          title={ t('dashboard.duration.empty.title') }
          description={ t('dashboard.duration.empty.desc') }
        />
      ) : (
        <>
          {/* Summary strip: average / fastest / slowest */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div>
              <p className="section-label">{t('dashboard.duration.avg')}</p>
              <p className="mt-1 text-xl font-semibold text-ink-900 dark:text-white tabular-nums truncate">
                {formatDuration(summary.avgMs)}
              </p>
              <p className="text-2xs text-ink-400 dark:text-ink-500">
                {t('dashboard.duration.task_count').replace('{n}', String(summary.count))}
              </p>
            </div>
            <div>
              <p className="section-label">{t('dashboard.duration.fastest')}</p>
              <p className="mt-1 text-xl font-semibold text-emerald-600 dark:text-emerald-400 tabular-nums truncate">
                {formatDuration(summary.fastest.ms)}
              </p>
              <p className="text-2xs text-ink-400 dark:text-ink-500 truncate" title={ summary.fastest.image }>
                {summary.fastest.image}
              </p>
            </div>
            <div>
              <p className="section-label">{t('dashboard.duration.slowest')}</p>
              <p className="mt-1 text-xl font-semibold text-rose-600 dark:text-rose-400 tabular-nums truncate">
                {formatDuration(summary.slowest.ms)}
              </p>
              <p className="text-2xs text-ink-400 dark:text-ink-500 truncate" title={ summary.slowest.image }>
                {summary.slowest.image}
              </p>
            </div>
          </div>

          {/* Per-task horizontal bars, slowest first */}
          <div className="border-t border-ink-100 dark:border-ink-800/60 pt-3.5">
            <ul className="space-y-2.5">
              {rows.map((row) => {
                const isFastest = comparable && row.id === summary.fastest.id;
                const isSlowest = comparable && row.id === summary.slowest.id;
                return (
                  <li key={ row.id } className="flex items-center gap-3 text-xs">
                    <span
                      className="w-16 sm:w-24 shrink-0 truncate font-medium text-ink-600 dark:text-ink-300"
                      title={ row.image }
                    >
                      {row.image}
                    </span>
                    <div
                      className="h-2 flex-1 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800/80"
                      title={ t('dashboard.duration.bar_tooltip')
                        .replace('{name}', row.image)
                        .replace('{duration}', formatDuration(row.ms)) }
                    >
                      <div
                        className="h-full rounded-full bg-accent-500 dark:bg-accent-400 transition-[width] duration-500"
                        style={ { width: `${Math.max(2, Math.round((row.ms / maxMs) * 100))}%` } }
                      />
                    </div>
                    <span className="w-14 sm:w-16 shrink-0 text-right font-mono text-ink-500 dark:text-ink-400 tabular-nums">
                      {formatDuration(row.ms)}
                    </span>
                    <span className="w-10 shrink-0 flex justify-end">
                      {isFastest && <MarkChip kind="fastest" />}
                      {isSlowest && <MarkChip kind="slowest" />}
                    </span>
                  </li>
                );
              })}
            </ul>
            {summary.count > rows.length && (
              <p className="mt-2.5 text-2xs text-ink-400 dark:text-ink-500">
                {t('dashboard.duration.showing')
                  .replace('{shown}', String(rows.length))
                  .replace('{total}', String(summary.count))}
              </p>
            )}
          </div>
        </>
      ) }
    </Card>
  );
}
