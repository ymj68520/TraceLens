import { cn } from '../../../lib/utils';
import { useTranslation } from '../../../hooks/useTranslation';
import type { TranslationKey } from '../../../locales/keys';

interface Row {
  label: string;
  value: number;
  tone: string;
}

const TONES: Record<string, string> = {
  low: 'bg-ink-300 dark:bg-ink-600',
  normal: 'bg-sky-500/80',
  high: 'bg-amber-500/80',
  critical: 'bg-rose-500/80',
};

/** Priority → translation key (task.priority.*). */
const LABEL_KEYS: Record<string, TranslationKey> = {
  critical: 'task.priority.critical',
  high: 'task.priority.high',
  normal: 'task.priority.normal',
  low: 'task.priority.low',
};

/** Tremor-style bar list: label, proportional bar, mono value. */
export default function PriorityBars({ tasks }: { tasks: { priority?: string }[] }) {
  const { t } = useTranslation();
  const order = ['critical', 'high', 'normal', 'low'];
  const counts = new Map<string, number>();
  for (const task of tasks) {
    const p = (task.priority ?? 'normal').toLowerCase();
    counts.set(p, (counts.get(p) ?? 0) + 1);
  }
  const max = Math.max(1, ...order.map((p) => counts.get(p) ?? 0));
  const rows: Row[] = order.map((p) => ({
    label: t(LABEL_KEYS[p]),
    value: counts.get(p) ?? 0,
    tone: TONES[p],
  }));

  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-3 text-xs">
          <span className="w-8 shrink-0 text-ink-600 dark:text-ink-300">{r.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800/80">
            <div
              className={cn('h-full rounded-full transition-[width] duration-500', r.tone)}
              style={{ width: `${Math.round((r.value / max) * 100)}%` }}
            />
          </div>
          <span className="w-6 text-right font-mono text-ink-500 dark:text-ink-400 tabular-nums">
            {r.value}
          </span>
        </li>
      ))}
    </ul>
  );
}
