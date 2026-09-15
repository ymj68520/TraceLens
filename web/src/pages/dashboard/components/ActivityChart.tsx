import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { ForensicTask } from '../../../types/api';
import { getTaskCreatedMs } from '../../../lib/utils';

interface Props {
  tasks: ForensicTask[];
  isDark: boolean;
}

const DAY_MS = 86_400_000;
const WINDOW_DAYS = 14;

function shortDate(ms: number): string {
  const d = new Date(ms);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** Tasks created per day over the last 14 days, zero-filled. */
export function buildActivitySeries(tasks: ForensicTask[]): { day: number; label: string; count: number }[] {
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const start = todayStart.getTime() - (WINDOW_DAYS - 1) * DAY_MS;
  const buckets = new Map<number, number>();
  for (const t of tasks) {
    const ms = getTaskCreatedMs(t);
    if (ms == null) continue;
    const dayStart = new Date(ms);
    dayStart.setHours(0, 0, 0, 0);
    const key = dayStart.getTime();
    if (key >= start) buckets.set(key, (buckets.get(key) ?? 0) + 1);
  }
  return Array.from({ length: WINDOW_DAYS }, (_, i) => {
    const day = start + i * DAY_MS;
    return { day, label: shortDate(day), count: buckets.get(day) ?? 0 };
  });
}

/** Trend area chart of task creation volume (real `timestamps.created` data). */
export default function ActivityChart({ tasks, isDark }: Props) {
  const data = useMemo(() => buildActivitySeries(tasks), [tasks]);
  const axis = isDark ? '#6b7f85' : '#8b9da2';
  const grid = isDark ? '#242c2f' : '#ebeff0';

  return (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id="activityFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#17aaa8" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#17aaa8" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={grid} vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            tick={{ fill: axis, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            tick={{ fill: axis, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={34}
          />
          <Tooltip
            cursor={{ stroke: axis, strokeDasharray: '3 3' }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const count = payload[0].value as number;
              return (
                <div className="card shadow-pop px-2.5 py-1.5 text-xs">
                  <span className="font-medium text-ink-900 dark:text-ink-100">{label}</span>
                  <span className="ml-2 text-ink-500 dark:text-ink-400">
                    {count} 个任务
                  </span>
                </div>
              );
            }}
          />
          <Area
            isAnimationActive
            animationDuration={900}
            type="monotone"
            dataKey="count"
            stroke="#0d8a89"
            strokeWidth={2}
            fill="url(#activityFill)"
            dot={false}
            activeDot={{ r: 3, fill: '#0d8a89', strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
