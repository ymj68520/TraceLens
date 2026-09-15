import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Plus,
  ClipboardList,
  Download,
  Search,
  Upload,
  ListTodo,
  Play,
  CheckCircle2,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks, fetchTaskStatistics } from '../store/taskSlice';
import { exportToon } from '../services/systemService';
import { downloadJSON } from '../lib/exportUtils';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Tooltip from '../components/ui/Tooltip';
import { useToast } from '../components/ui/Toast';
import { SkeletonTable } from '../components/ui/PageScaffold';
import EmptyState from '../components/ui/EmptyState';
import ServiceHealthStrip from './dashboard/components/ServiceHealthStrip';
import ActivityChart from './dashboard/components/ActivityChart';
import StatusDonut from './dashboard/components/StatusDonut';
import KpiCard from './dashboard/components/KpiCard';
import PriorityBars from './dashboard/components/PriorityBars';
import DurationAnalysis from './dashboard/components/DurationAnalysis';
import ActivityFeed from './dashboard/components/ActivityFeed';
import { summarizeDurations } from './dashboard/components/durationUtils';
import { basename, formatRelativeTime, formatDateTime, getTaskCreatedMs } from '../lib/utils';
import { useTranslation } from '../hooks/useTranslation';
import { LayoutDashboard } from 'lucide-react';
import { PageHeader } from '../components/ui/PageScaffold';

const STATUS_TONE: Record<string, 'success' | 'danger' | 'accent' | 'neutral' | 'warning'> = {
  completed: 'success',
  failed: 'danger',
  running: 'accent',
  pending: 'warning',
  cancelled: 'neutral',
};

const DAY_MS = 86_400_000;

export default function Dashboard() {
  const dispatch = useAppDispatch();
  const { tasks, status } = useAppSelector((state) => state.tasks);
  const theme = useAppSelector((state) => state.settings.theme);
  const { autoRefresh, refreshInterval } = useAppSelector((state) => state.settings);
  const [exporting, setExporting] = useState(false);
  const toast = useToast();
  const { t } = useTranslation();
  const isDark = theme === 'dark';

  useEffect(() => {
    void dispatch(fetchTasks({ limit: 10 }));
    void dispatch(fetchTaskStatistics());
  }, [dispatch]);

  useEffect(() => {
    if (!autoRefresh) return;
    if (!tasks.some((t) => t.status === 'running')) return;
    const id = setInterval(() => {
      void dispatch(fetchTasks({ limit: 10 }));
    }, refreshInterval || 5000);
    return () => clearInterval(id);
  }, [autoRefresh, refreshInterval, tasks, dispatch]);

  const stats = useMemo(
    () => ({
      total: tasks.length,
      running: tasks.filter((t) => t.status === 'running').length,
      completed: tasks.filter((t) => t.status === 'completed').length,
      failed: tasks.filter((t) => t.status === 'failed').length,
    }),
    [tasks],
  );

  /** Daily created counts, oldest → newest (KPI sparkline source). */
  const dailyCounts = useMemo(() => {
    const days = 14;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const start = today.getTime() - (days - 1) * DAY_MS;
    const buckets = new Array<number>(days).fill(0);
    for (const task of tasks) {
      const ms = getTaskCreatedMs(task);
      if (ms == null || ms < start) continue;
      const idx = Math.min(days - 1, Math.floor((ms - start) / DAY_MS));
      buckets[idx] += 1;
    }
    return buckets;
  }, [tasks]);

  const completionRate = stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : null;

  /** Recent tasks, newest first — feeds the activity stream and JSON export. */
  const recentTasks = useMemo(
    () =>
      [...tasks]
        .map((task) => ({ task, createdMs: getTaskCreatedMs(task) }))
        .sort((a, b) => (b.createdMs ?? 0) - (a.createdMs ?? 0))
        .slice(0, 10),
    [tasks],
  );

  const kpis: {
    label: string;
    value: number;
    hint: string;
    Icon: LucideIcon;
    iconClass: string;
    spark?: number[];
  }[] = [
    { label: t('dashboard.kpi.total'), value: stats.total, hint: t('dashboard.kpi.total_hint'), Icon: ListTodo, iconClass: 'text-accent-600 dark:text-accent-400 bg-accent-50 dark:bg-accent-500/10', spark: dailyCounts },
    {
      label: t('dashboard.kpi.running'),
      value: stats.running,
      hint: stats.running > 0 ? t('dashboard.kpi.running_hint_on') : t('dashboard.kpi.running_hint_idle'),
      Icon: Play,
      iconClass: 'text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-500/10',
    },
    { label: t('dashboard.kpi.completed'), value: stats.completed, hint: completionRate != null ? t('dashboard.kpi.success_rate').replace('{n}', String(completionRate)) : '—', Icon: CheckCircle2, iconClass: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10', spark: dailyCounts },
    { label: t('dashboard.kpi.failed'), value: stats.failed, hint: stats.failed > 0 ? t('dashboard.kpi.failed_hint_attention') : t('dashboard.kpi.failed_hint_ok'), Icon: XCircle, iconClass: 'text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10' },
  ];

  const handleToonExport = async () => {
    const completedTask = tasks.find((t) => t.status === 'completed');
    if (!completedTask) return;
    setExporting(true);
    try {
      await exportToon(completedTask.id);
    } catch {
      // best effort
    } finally {
      setExporting(false);
    }
  };

  /** Whole-dashboard JSON summary: stats + recent activities + duration stats. */
  const handleJsonExport = () => {
    const duration = summarizeDurations(tasks);
    const payload = {
      exported_at: new Date().toISOString(),
      stats: {
        total: stats.total,
        running: stats.running,
        completed: stats.completed,
        failed: stats.failed,
        completion_rate: completionRate,
      },
      activities: recentTasks.map(({ task, createdMs }) => ({
        id: task.id,
        image: basename(task.image_path),
        image_path: task.image_path,
        status: task.status,
        priority: task.priority ?? 'normal',
        created_at: createdMs != null ? new Date(createdMs).toISOString() : null,
      })),
      duration: duration
        ? {
            task_count: duration.count,
            total_ms: duration.totalMs,
            avg_ms: duration.avgMs,
            avg_seconds: Number((duration.avgMs / 1000).toFixed(3)),
            fastest: duration.fastest,
            slowest: duration.slowest,
            per_task: duration.entries.map((e) => ({
              id: e.id,
              image: e.image,
              seconds: Number((e.ms / 1000).toFixed(3)),
              ms: e.ms,
            })),
          }
        : null,
    };
    downloadJSON(payload, `dashboard-summary-${new Date().toISOString().slice(0, 10)}`);
    toast.success(t('dashboard.toast.exported'));
  };

  const copyTaskId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
      toast.success(t('dashboard.toast.id_copied'));
    } catch {
      toast.error(t('dashboard.toast.copy_failed'));
    }
  };

  return (
    <div className="space-y-5 max-w-7xl">
      <PageHeader
        icon={ LayoutDashboard }
        tone="accent"
        title={t('nav.dashboard')}
        subtitle={t('dashboard.subtitle')}
        actions={
          <button
            type="button"
            onClick={handleJsonExport}
            disabled={tasks.length === 0}
            className="btn-secondary"
          >
            <Download size={15} /> {t('dashboard.export_summary')}
          </button>
        }
      />
      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map(({ label, value, hint, Icon, iconClass, spark }, i) => (
          <KpiCard
            key={label}
            label={label}
            value={value}
            hint={hint}
            Icon={Icon}
            iconClass={iconClass}
            spark={spark}
            isDark={isDark}
            index={i}
          />
        ))}
      </div>

      {/* Main grid: left 2/3 = trend + duration analysis, right 1/3 = donut + activity feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div className="lg:col-span-2 space-y-4 min-w-0">
          <Card className="px-5 py-4">
            <CardHeader title={t('dashboard.trend.title')} subtitle={t('dashboard.trend.subtitle')} />
            <ActivityChart tasks={tasks} isDark={isDark} />
          </Card>
          <DurationAnalysis tasks={tasks} loading={status === 'loading'} />
        </div>
        <div className="space-y-4 min-w-0">
          <Card className="px-5 py-4">
            <CardHeader title={t('dashboard.distribution.title')} subtitle={t('dashboard.distribution.subtitle')} />
            <StatusDonut tasks={tasks} />
            <div className="mt-4 border-t border-ink-100 dark:border-ink-800/60 pt-3">
              <p className="section-label mb-2.5">{t('dashboard.priority')}</p>
              <PriorityBars tasks={tasks} />
            </div>
          </Card>
          <ActivityFeed tasks={tasks} loading={status === 'loading'} max={6} />
        </div>
      </div>

      <ServiceHealthStrip />

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2.5">
        <Link to="/tasks" className="btn-primary">
          <Plus size={15} /> {t('tasks.new')}
        </Link>
        <Link to="/tasks" className="btn-secondary">
          <ClipboardList size={15} /> {t('nav.tasks')}
        </Link>
        <Link to="/search" className="btn-secondary">
          <Search size={15} /> {t('dashboard.action.fulltext_search')}
        </Link>
        <button
          type="button"
          onClick={handleToonExport}
          disabled={exporting || !tasks.some((t) => t.status === 'completed')}
          className="btn-secondary"
        >
          <Upload size={15} /> {exporting ? t('dashboard.action.exporting') : t('dashboard.action.toon_export')}
        </button>
      </div>

      {/* Recent tasks */}
      <Card padded={false}>
        <div className="px-5 pt-4">
          <CardHeader title={t('dashboard.recent.title')} subtitle={t('dashboard.recent.subtitle')} />
        </div>
        {status === 'loading' ? (
          <SkeletonTable rows={5} cols={5} />
        ) : tasks.length === 0 ? (
          <EmptyState title={t('dashboard.empty.title')} description={t('dashboard.empty.desc')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-shell">
              <thead>
                <tr>
                  <th>{t('dashboard.table.task_id')}</th>
                  <th>{t('dashboard.table.image')}</th>
                  <th>{t('dashboard.table.status')}</th>
                  <th>{t('dashboard.table.created')}</th>
                  <th className="text-right">{t('dashboard.table.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {tasks.slice(0, 6).map((task, ri) => {
                  const createdMs = getTaskCreatedMs(task);
                  return (
                    <tr key={task.id} className="animate-fade-in" style={{ animationDelay: `${ri * 40}ms` }}>
                      <td>
                        <Tooltip content={t('dashboard.table.copy_id_tooltip')}>
                          <button
                            type="button"
                            onClick={() => void copyTaskId(task.id)}
                            className="inline-flex items-center gap-1.5 font-mono text-xs text-ink-600 dark:text-ink-300 hover:text-accent-600 dark:hover:text-accent-400 transition-colors"
                          >
                            {task.id.substring(0, 8)}…
                          </button>
                        </Tooltip>
                      </td>
                      <td className="max-w-[280px] truncate" title={task.image_path}>
                        {basename(task.image_path)}
                      </td>
                      <td>
                        <Badge tone={STATUS_TONE[task.status] ?? 'neutral'} dot>
                          {t(`task.status.${(task.status || '').toLowerCase()}`) || task.status}
                        </Badge>
                      </td>
                      <td
                        className="text-xs text-ink-500 dark:text-ink-400 whitespace-nowrap"
                        title={createdMs != null ? formatDateTime(createdMs) : undefined}
                      >
                        {formatRelativeTime(createdMs)}
                      </td>
                      <td className="text-right text-xs">
                        {task.status === 'completed' ? (
                          <span className="space-x-3">
                            <Link
                              to={`/timeline?task_id=${task.id}`}
                              className="text-accent-600 dark:text-accent-400 hover:underline"
                            >
                              {t('dashboard.link.timeline')}
                            </Link>
                            <Link
                              to={`/files?task_id=${task.id}`}
                              className="text-accent-600 dark:text-accent-400 hover:underline"
                            >
                              {t('dashboard.link.files')}
                            </Link>
                          </span>
                        ) : (
                          <Link to="/tasks" className="text-accent-600 dark:text-accent-400 hover:underline">
                            {t('dashboard.link.view')}
                          </Link>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
