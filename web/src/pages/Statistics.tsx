import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  BarChart3,
  CalendarClock,
  Clock,
  Download,
  Files,
  RefreshCw,
  Trash2,
  Type,
  Zap,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { LucideIcon } from 'lucide-react';
import {
  getActivityPatterns,
  getDeletedFilesAnalysis,
  getFileDistribution,
  getStatisticsOverview,
} from '../services/forensicsService';
import { useAppSelector } from '../store';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { PageHeader, Segmented, SkeletonBlock, SkeletonTable } from '../components/ui/PageScaffold';
import { cx, errorMessage, formatBytes, formatDateTime } from '../lib/utils';
import { downloadCSV, downloadJSON } from '../lib/exportUtils';
import { emitAppEvent } from '../lib/appEvents';

/* ---------------------------------------------------------------------------
 * Defensive parsing — every statistics endpoint returns loosely-typed JSON
 * arrays of rows; missing fields degrade to 0 / '—' instead of crashing.
 * ------------------------------------------------------------------------- */

type Json = Record<string, unknown>;

const asRows = (value: unknown): Json[] =>
  (Array.isArray(value) ? value : []).filter((row): row is Json => row !== null && typeof row === 'object');

const firstRow = (value: unknown): Json => asRows(value)[0] ?? {};

const numOf = (value: unknown): number => {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
};

const strOf = (value: unknown): string => (value == null ? '' : String(value));

/** Backend stores epoch seconds; formatDateTime expects milliseconds. */
const formatEpoch = (value: unknown): string => {
  const n = numOf(value);
  if (n <= 0) return '—';
  return formatDateTime(n < 1e12 ? n * 1000 : n);
};

/* ------------------------- Independent data section ------------------------- */

interface SectionState {
  data: unknown;
  loading: boolean;
  error: string | null;
}

/** Each card owns its fetch — one failing endpoint never blocks the others. */
function useSectionData(taskId: string, reloadKey: number, fetcher: (taskId: string) => Promise<unknown>): SectionState {
  const [state, setState] = useState<SectionState>({ data: null, loading: true, error: null });

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    setState({ data: null, loading: true, error: null });
    fetcher(taskId)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // The fetcher is a stable service call; only task / manual reload matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, reloadKey]);

  return state;
}

/* ------------------------------ Small pieces ------------------------------ */

const KPI_TONES: Record<string, string> = {
  accent: 'bg-accent-100 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300',
  sky: 'bg-sky-100 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300',
  emerald: 'bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  rose: 'bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300',
};

function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
  loading,
}: {
  label: string;
  value: number;
  hint: string;
  icon: LucideIcon;
  tone: keyof typeof KPI_TONES;
  loading: boolean;
}) {
  return (
    <Card className="px-5 py-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-ink-500 dark:text-ink-400">{label}</p>
        <span className={cx('inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md', KPI_TONES[tone])}>
          <Icon size={14} strokeWidth={2} />
        </span>
      </div>
      <div className="mt-1 min-h-[36px]">
        {loading ? (
          <SkeletonBlock className="h-8 w-20" />
        ) : (
          <p className="text-[26px] leading-9 font-semibold text-ink-900 dark:text-white tabular-nums">
            {value.toLocaleString()}
          </p>
        )}
      </div>
      <p className="text-2xs text-ink-400 dark:text-ink-500 truncate" title={hint}>
        {hint || '—'}
      </p>
    </Card>
  );
}

function SectionError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <EmptyState
      icon={<RefreshCw size={26} />}
      title="数据加载失败"
      description={message}
      action={
        <Button size="sm" onClick={onRetry}>
          <RefreshCw size={13} />
          重试
        </Button>
      }
    />
  );
}

/* --------------------------------- Donut --------------------------------- */

interface DonutSlice {
  name: string;
  value: number;
  color: string;
}

const SLICE_COLORS = ['#0d8a89', '#17aaa8', '#10b981', '#0ea5e9', '#f59e0b', '#f43f5e', '#7c8fa0', '#8b9da2'];
const sliceColor = (index: number): string => SLICE_COLORS[index % SLICE_COLORS.length];

function DistributionDonut({ slices, unit, emptyText }: { slices: DonutSlice[]; unit: string; emptyText: string }) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  if (slices.length === 0 || total === 0) {
    return <EmptyState title={emptyText} className="py-10" />;
  }
  return (
    <div className="flex items-center gap-4">
      <div className="relative h-40 w-40 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0];
                return (
                  <div className="card shadow-pop px-2.5 py-1.5 text-xs">
                    <span className="font-medium text-ink-900 dark:text-ink-100">{p.name}</span>
                    <span className="ml-2 text-ink-500 dark:text-ink-400 tabular-nums">{p.value} {unit}</span>
                  </div>
                );
              }}
            />
            <Pie
              isAnimationActive
              animationDuration={800}
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius={54}
              outerRadius={76}
              paddingAngle={slices.length > 1 ? 3 : 0}
              strokeWidth={0}
              startAngle={90}
              endAngle={-270}
            >
              {slices.map((s) => (
                <Cell key={s.name} fill={s.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold text-ink-900 dark:text-white tabular-nums">{total.toLocaleString()}</span>
          <span className="text-2xs text-ink-400 dark:text-ink-500">{unit}</span>
        </div>
      </div>
      <ul className="min-w-0 flex-1 space-y-2">
        {slices.map((s) => (
          <li key={s.name} className="flex items-center gap-2 text-xs">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-sm" style={{ background: s.color }} />
            <span className="text-ink-600 dark:text-ink-300 truncate" title={s.name}>{s.name}</span>
            <span className="ml-auto font-mono text-ink-500 dark:text-ink-400 tabular-nums">{s.value.toLocaleString()}</span>
            <span className="w-10 text-right font-mono text-2xs text-ink-400 dark:text-ink-500 tabular-nums">
              {Math.round((s.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------ Activity bars ------------------------------ */

function PatternBars({ data, isDark }: { data: { label: string; count: number }[]; isDark: boolean }) {
  const axis = isDark ? '#6b7f85' : '#8b9da2';
  const grid = isDark ? '#242c2f' : '#ebeff0';
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke={grid} vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: axis, fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={6} />
          <YAxis tick={{ fill: axis, fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} width={40} />
          <Tooltip
            cursor={{ fill: isDark ? 'rgba(23, 170, 168, 0.08)' : 'rgba(13, 138, 137, 0.06)' }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const count = payload[0].value as number;
              return (
                <div className="card shadow-pop px-2.5 py-1.5 text-xs">
                  <span className="font-medium text-ink-900 dark:text-ink-100">{label}</span>
                  <span className="ml-2 text-ink-500 dark:text-ink-400 tabular-nums">{count} 条事件</span>
                </div>
              );
            }}
          />
          <Bar
            isAnimationActive
            animationDuration={700}
            dataKey="count"
            fill={isDark ? '#2f8f8b' : '#17aaa8'}
            radius={[3, 3, 0, 0]}
            maxBarSize={26}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------- Stat groups ------------------------------- */

function OverviewGroup({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="min-w-0">
      <p className="section-label mb-2">{title}</p>
      {rows.map(([label, value]) => (
        <div
          key={label}
          className="flex items-center justify-between gap-3 py-1.5 border-b border-ink-100 dark:border-ink-800/60 last:border-0"
        >
          <span className="text-xs text-ink-500 dark:text-ink-400 shrink-0">{label}</span>
          <span className="text-xs font-medium font-mono text-ink-900 dark:text-ink-100 tabular-nums truncate">{value}</span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------ Size buckets ------------------------------ */

const SIZE_LABELS: Record<string, string> = {
  empty: '空文件',
  small_1KB: '小于 1 KB',
  medium_1MB: '1 KB – 1 MB',
  large_1GB: '1 MB – 1 GB',
  very_large: '大于 1 GB',
};

/** Top directories by total size, rendered as lightweight CSS bars. */
function DirectoryBars({ rows }: { rows: { directory: string; fileCount: number; totalSize: number }[] }) {
  const max = Math.max(...rows.map((r) => r.totalSize), 1);
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.directory}>
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="font-mono text-ink-600 dark:text-ink-300 truncate" title={row.directory}>
              {row.directory || '/'}
            </span>
            <span className="shrink-0 font-mono text-2xs text-ink-400 dark:text-ink-500 tabular-nums">
              {formatBytes(row.totalSize)} · {row.fileCount.toLocaleString()} 个
            </span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-ink-100 dark:bg-ink-800 overflow-hidden">
            <div
              className="h-full rounded-full bg-accent-500/80 dark:bg-accent-500/60"
              style={{ width: `${Math.max((row.totalSize / max) * 100, 2)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/* --------------------------------- Page --------------------------------- */

export default function Statistics() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const theme = useAppSelector((state) => state.settings.theme);
  const isDark = theme === 'dark';

  const [reloadKey, setReloadKey] = useState(0);
  const [patternView, setPatternView] = useState<'hour' | 'weekday'>('hour');

  const overview = useSectionData(taskId ?? '', reloadKey, getStatisticsOverview);
  const fileDist = useSectionData(taskId ?? '', reloadKey, getFileDistribution);
  const activity = useSectionData(taskId ?? '', reloadKey, getActivityPatterns);
  const deleted = useSectionData(taskId ?? '', reloadKey, getDeletedFilesAnalysis);

  const reload = () => setReloadKey((key) => key + 1);

  const overviewData = overview.data as Json | null;
  const rawStats = firstRow(overviewData?.raw_database_stats);
  const eventStats = firstRow(overviewData?.events_database_stats);
  const fileStats = firstRow(overviewData?.files_database_stats);
  const deletedSummary = firstRow((deleted.data as Json | null)?.deleted_summary);

  const sizeSlices = useMemo<DonutSlice[]>(
    () =>
      asRows((fileDist.data as Json | null)?.size_distribution)
        .map((row, i) => ({
          name: SIZE_LABELS[strOf(row.size_category)] ?? (strOf(row.size_category) || '未知'),
          value: numOf(row.file_count),
          color: sliceColor(i),
        }))
        .filter((s) => s.value > 0),
    [fileDist.data],
  );

  const eventTypeSlices = useMemo<DonutSlice[]>(() => {
    const rows = asRows((activity.data as Json | null)?.event_type_distribution)
      .map((row) => ({ name: strOf(row.event_type) || '未知类型', value: numOf(row.count) }))
      .filter((row) => row.value > 0)
      .sort((a, b) => b.value - a.value);
    const top = rows.slice(0, 7).map((row, i) => ({ ...row, color: sliceColor(i) }));
    const restValue = rows.slice(7).reduce((sum, row) => sum + row.value, 0);
    if (restValue > 0) top.push({ name: '其他类型', value: restValue, color: '#8b9da2' });
    return top;
  }, [activity.data]);

  const patternData = useMemo(() => {
    if (patternView === 'hour') {
      const counts = new Map(
        asRows((activity.data as Json | null)?.daily_pattern).map((row) => [numOf(row.hour), numOf(row.activity_count)]),
      );
      // Zero-fill every hour so gaps read as quiet periods, not missing data.
      return Array.from({ length: 24 }, (_, hour) => ({
        label: String(hour).padStart(2, '0'),
        count: counts.get(hour) ?? 0,
      }));
    }
    const counts = new Map(
      asRows((activity.data as Json | null)?.weekly_pattern).map((row) => [numOf(row.day_of_week), numOf(row.activity_count)]),
    );
    // (timestamp / 86400) % 7 uses epoch day 0 = 1970-01-01, a Thursday.
    const order: { key: number; label: string }[] = [
      { key: 4, label: '周一' },
      { key: 5, label: '周二' },
      { key: 6, label: '周三' },
      { key: 0, label: '周四' },
      { key: 1, label: '周五' },
      { key: 2, label: '周六' },
      { key: 3, label: '周日' },
    ];
    return order.map(({ key, label }) => ({ label, count: counts.get(key) ?? 0 }));
  }, [activity.data, patternView]);

  const directoryRows = useMemo(
    () =>
      asRows((fileDist.data as Json | null)?.directory_sizes)
        .slice(0, 10)
        .map((row) => ({
          directory: strOf(row.directory),
          fileCount: numOf(row.file_count),
          totalSize: numOf(row.total_size),
        })),
    [fileDist.data],
  );

  const recentDeleted = useMemo(
    () => asRows((deleted.data as Json | null)?.recently_deleted),
    [deleted.data],
  );
  const deletedByType = useMemo(
    () => asRows((deleted.data as Json | null)?.deleted_by_type),
    [deleted.data],
  );

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<BarChart3 size={36} />}
          title="未选择任务"
          description="请先选择一个已完成的分析任务。"
        />
      </div>
    );
  }

  const hasAnyData = overview.data !== null || fileDist.data !== null || activity.data !== null || deleted.data !== null;

  const handleExport = () => {
    downloadJSON(
      {
        task_id: taskId,
        exported_at: new Date().toISOString(),
        overview: overview.data,
        file_distribution: fileDist.data,
        activity_patterns: activity.data,
        deleted_files_analysis: deleted.data,
      },
      `statistics-report-${taskId}`,
    );
    emitAppEvent({ kind: 'info', title: '已导出统计报告', detail: `statistics-report-${taskId}.json` });
  };

  const handleExportDeleted = () => {
    if (recentDeleted.length === 0) return;
    downloadCSV(
      recentDeleted.map((row) => ({
        name: strOf(row.name),
        path: strOf(row.path),
        type: strOf(row.type) || strOf(row.extension),
        size: numOf(row.size),
        mtime: formatEpoch(row.mtime),
      })),
      `deleted-files-${taskId}`,
      [
        { key: 'name', label: '文件名' },
        { key: 'path', label: '路径' },
        { key: 'type', label: '类型' },
        { key: 'size', label: '大小(字节)' },
        { key: 'mtime', label: '修改时间' },
      ],
    );
  };

  return (
    <div className="space-y-4 max-w-6xl">
      <PageHeader
        icon={BarChart3}
        tone="sky"
        title="统计分析"
        subtitle="任务维度的证据统计、分布与活动模式洞察"
        actions={
          <Button size="sm" variant="secondary" onClick={handleExport} disabled={!hasAnyData}>
            <Download size={14} />
            导出报告 JSON
          </Button>
        }
      />

      {/* KPI cards — fed by the overview endpoint, own loading / error states. */}
      {overview.error ? (
        <Card>
          <SectionError message={overview.error} onRetry={reload} />
        </Card>
      ) : (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard
            label="事件总数"
            value={numOf(eventStats.total_events)}
            hint={`事件类型 ${numOf(eventStats.event_types).toLocaleString()} · 涉及文件 ${numOf(eventStats.unique_files_affected).toLocaleString()}`}
            icon={Zap}
            tone="accent"
            loading={overview.loading}
          />
          <KpiCard
            label="文件总数"
            value={numOf(rawStats.total_files)}
            hint={`已分配 ${numOf(rawStats.allocated_files).toLocaleString()} · 合计 ${formatBytes(numOf(rawStats.total_size))}`}
            icon={Files}
            tone="sky"
            loading={overview.loading}
          />
          <KpiCard
            label="文件类型数"
            value={numOf(fileStats.unique_extensions)}
            hint={`已分类 ${numOf(fileStats.categorized_files).toLocaleString()} · ${numOf(fileStats.categories).toLocaleString()} 个分类`}
            icon={Type}
            tone="emerald"
            loading={overview.loading}
          />
          <KpiCard
            label="删除文件数"
            value={numOf(rawStats.deleted_files)}
            hint={`合计 ${formatBytes(numOf(deletedSummary.total_deleted_size))} · 大文件 ${numOf(deletedSummary.large_deleted_files).toLocaleString()} 个`}
            icon={Trash2}
            tone="rose"
            loading={overview.loading}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="文件大小分布" subtitle="按体积区间统计提取文件" />
          {fileDist.loading ? (
            <SkeletonBlock className="h-40 w-full" />
          ) : fileDist.error ? (
            <SectionError message={fileDist.error} onRetry={reload} />
          ) : (
            <DistributionDonut slices={sizeSlices} unit="个文件" emptyText="暂无文件分布数据" />
          )}
        </Card>

        <Card>
          <CardHeader title="事件类型分布" subtitle="事件库中的类型构成（前 7 类）" />
          {activity.loading ? (
            <SkeletonBlock className="h-40 w-full" />
          ) : activity.error ? (
            <SectionError message={activity.error} onRetry={reload} />
          ) : (
            <DistributionDonut slices={eventTypeSlices} unit="条事件" emptyText="暂无事件类型数据" />
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="活动模式"
            subtitle="事件在一天 / 一周中的时间分布"
            actions={
              <Segmented
                options={[
                  { value: 'hour', label: '按小时', icon: Clock },
                  { value: 'weekday', label: '按星期', icon: CalendarClock },
                ]}
                value={patternView}
                onChange={setPatternView}
              />
            }
          />
          {activity.loading ? (
            <SkeletonBlock className="h-48 w-full" />
          ) : activity.error ? (
            <SectionError message={activity.error} onRetry={reload} />
          ) : (
            <PatternBars data={patternData} isDark={isDark} />
          )}
        </Card>

        <Card>
          <CardHeader title="目录占用 Top 10" subtitle="按文件总体积排序的一级目录" />
          {fileDist.loading ? (
            <div className="space-y-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <SkeletonBlock key={i} className="h-6 w-full" />
              ))}
            </div>
          ) : fileDist.error ? (
            <SectionError message={fileDist.error} onRetry={reload} />
          ) : directoryRows.length === 0 ? (
            <EmptyState title="暂无目录数据" className="py-10" />
          ) : (
            <DirectoryBars rows={directoryRows} />
          )}
        </Card>

        <Card>
          <CardHeader title="数据概览" subtitle="三个证据库的关键指标" />
          {overview.loading ? (
            <div className="grid md:grid-cols-3 gap-6">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="space-y-2.5">
                  <SkeletonBlock className="h-2.5 w-16" />
                  <SkeletonBlock className="h-3 w-full" />
                  <SkeletonBlock className="h-3 w-full" />
                  <SkeletonBlock className="h-3 w-4/5" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid md:grid-cols-3 gap-6">
              <OverviewGroup
                title="原始文件库"
                rows={[
                  ['已分配文件', numOf(rawStats.allocated_files).toLocaleString()],
                  ['平均文件大小', formatBytes(numOf(rawStats.avg_file_size))],
                  ['最新修改时间', formatEpoch(rawStats.latest_modification)],
                ]}
              />
              <OverviewGroup
                title="事件库"
                rows={[
                  ['事件类型数', numOf(eventStats.event_types).toLocaleString()],
                  ['涉及唯一文件', numOf(eventStats.unique_files_affected).toLocaleString()],
                  ['最早事件', formatEpoch(eventStats.earliest_event)],
                  ['最晚事件', formatEpoch(eventStats.latest_event)],
                ]}
              />
              <OverviewGroup
                title="文件分类库"
                rows={[
                  ['已分类文件', numOf(fileStats.categorized_files).toLocaleString()],
                  ['分类数', numOf(fileStats.categories).toLocaleString()],
                  ['扩展名数', numOf(fileStats.unique_extensions).toLocaleString()],
                ]}
              />
            </div>
          )}
        </Card>

        <Card padded={false} className="lg:col-span-2">
          <div className="px-5 pt-5">
            <CardHeader
              title="删除文件分析"
              subtitle="已删除文件的汇总与最近删除清单（最多 100 条）"
              actions={
                <Button size="sm" variant="ghost" onClick={handleExportDeleted} disabled={recentDeleted.length === 0}>
                  <Download size={13} />
                  导出 CSV
                </Button>
              }
            />
            {deleted.error ? (
              <SectionError message={deleted.error} onRetry={reload} />
            ) : deleted.loading ? (
              <SkeletonTable rows={5} cols={4} />
            ) : numOf(deletedSummary.total_deleted) === 0 && recentDeleted.length === 0 ? (
              <EmptyState icon={<Trash2 size={30} />} title="未发现已删除文件" description="该任务的镜像中没有标记为已删除的文件。" />
            ) : (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: '删除文件总数', value: numOf(deletedSummary.total_deleted).toLocaleString() },
                    { label: '删除总体积', value: formatBytes(numOf(deletedSummary.total_deleted_size)) },
                    { label: '平均大小', value: formatBytes(numOf(deletedSummary.avg_deleted_size)) },
                    { label: '大于 1 MB', value: numOf(deletedSummary.large_deleted_files).toLocaleString() },
                  ].map((item) => (
                    <div key={item.label} className="rounded-lg border border-ink-100 dark:border-ink-800 px-3 py-2.5">
                      <p className="text-2xs text-ink-400 dark:text-ink-500">{item.label}</p>
                      <p className="mt-0.5 text-sm font-semibold text-ink-900 dark:text-ink-100 tabular-nums">{item.value}</p>
                    </div>
                  ))}
                </div>
                {deletedByType.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {deletedByType.map((row) => (
                      <Badge key={strOf(row.type)} tone="neutral">
                        {strOf(row.type) || '未知'} · {numOf(row.count).toLocaleString()} · {formatBytes(numOf(row.total_size))}
                      </Badge>
                    ))}
                  </div>
                )}
                {recentDeleted.length > 0 && (
                  <div className="mt-4 max-h-96 overflow-y-auto rounded-lg border border-ink-100 dark:border-ink-800">
                    <table className="table-shell text-xs">
                      <thead>
                        <tr>
                          <th>文件</th>
                          <th>类型</th>
                          <th className="text-right">大小</th>
                          <th className="text-right">修改时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentDeleted.map((row, i) => {
                          const path = strOf(row.path);
                          const name = strOf(row.name) || path.split(/[\\/]/).pop() || '—';
                          return (
                            <tr key={`${i}-${path}`}>
                              <td className="max-w-[320px]">
                                <p className="font-mono truncate" title={name}>{name}</p>
                                {path && path !== name && (
                                  <p className="text-2xs text-ink-400 dark:text-ink-500 font-mono truncate" title={path}>{path}</p>
                                )}
                              </td>
                              <td className="text-ink-500 dark:text-ink-400">{strOf(row.type) || strOf(row.extension) || '—'}</td>
                              <td className="text-right font-mono tabular-nums">{formatBytes(numOf(row.size))}</td>
                              <td className="text-right font-mono tabular-nums whitespace-nowrap text-ink-500 dark:text-ink-400">
                                {formatEpoch(row.mtime)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
          <div className="h-5" aria-hidden />
        </Card>
      </div>
    </div>
  );
}
