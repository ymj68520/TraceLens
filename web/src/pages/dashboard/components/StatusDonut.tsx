import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { useTranslation } from '../../../hooks/useTranslation';
import type { TranslationKey } from '../../../locales/keys';

interface Slice {
  name: string;
  value: number;
  color: string;
}

const PALETTE: Record<string, string> = {
  completed: '#10b981',
  failed: '#f43f5e',
  running: '#2e9b96',
  pending: '#f59e0b',
  cancelled: '#8b9da2',
};

/** Status → translation key (task.status.*); unknown statuses render verbatim. */
const LABEL_KEYS: Record<string, TranslationKey> = {
  completed: 'task.status.completed',
  failed: 'task.status.failed',
  running: 'task.status.running',
  pending: 'task.status.pending',
  cancelled: 'task.status.cancelled',
};

/** Status distribution donut with a center total and inline legend. */
export default function StatusDonut({ tasks }: { tasks: { status: string }[] }) {
  const { t } = useTranslation();
  const counts = new Map<string, number>();
  for (const task of tasks) {
    const s = (task.status || '').toLowerCase();
    counts.set(s, (counts.get(s) ?? 0) + 1);
  }
  const slices: Slice[] = [...counts.entries()].map(([status, value]) => {
    const key = LABEL_KEYS[status];
    return {
      name: key ? t(key) : status,
      value,
      color: PALETTE[status] ?? '#8b9da2',
    };
  });
  const total = tasks.length;

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
                    <span className="ml-2 text-ink-500 dark:text-ink-400">
                      {t('dashboard.distribution.count').replace('{n}', String(p.value))}
                    </span>
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
          <span className="text-2xl font-semibold text-ink-900 dark:text-white tabular-nums">{total}</span>
          <span className="text-2xs text-ink-400 dark:text-ink-500">{t('dashboard.distribution.tasks')}</span>
        </div>
      </div>
      <ul className="min-w-0 flex-1 space-y-2">
        {slices.map((s) => (
          <li key={s.name} className="flex items-center gap-2 text-xs">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-sm" style={{ background: s.color }} />
            <span className="text-ink-600 dark:text-ink-300">{s.name}</span>
            <span className="ml-auto font-mono text-ink-500 dark:text-ink-400 tabular-nums">{s.value}</span>
            <span className="w-10 text-right font-mono text-2xs text-ink-400 dark:text-ink-500 tabular-nums">
              {total > 0 ? Math.round((s.value / total) * 100) : 0}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
