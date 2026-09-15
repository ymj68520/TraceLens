import { useEffect, useRef, type RefObject } from 'react';
import { BarChart, Bar, ResponsiveContainer } from 'recharts';
import type { LucideIcon } from 'lucide-react';
import Card from '../../../components/ui/Card';
import { cx } from '../../../lib/utils';

interface KpiCardProps {
  label: string;
  value: number;
  hint: string;
  Icon: LucideIcon;
  iconClass: string;
  /** Per-day counts for the mini sparkline (oldest → newest). */
  spark?: number[];
  isDark: boolean;
  /** Stagger index for the entrance animation. */
  index?: number;
}

/** requestAnimationFrame count-up — subtle motion, no animation library. */
function useCountUp(target: number, valueRef: RefObject<HTMLSpanElement | null>, duration = 500): void {
  const displayRef = useRef(0);

  useEffect(() => {
    const from = displayRef.current;
    const el = valueRef.current;
    if (!el || from === target) {
      if (el) el.textContent = String(target);
      displayRef.current = target;
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      const current = Math.round(from + (target - from) * eased);
      el.textContent = String(current);
      displayRef.current = current;
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration, valueRef]);
}

export default function KpiCard({ label, value, hint, Icon, iconClass, spark, isDark, index = 0 }: KpiCardProps) {
  const valueRef = useRef<HTMLSpanElement>(null);
  useCountUp(value, valueRef);
  const sparkData = (spark ?? []).map((count, i) => ({ i, count }));
  const hasSpark = sparkData.some((d) => d.count > 0) && sparkData.length >= 3;

  return (
    <Card
      className="group px-5 py-4 animate-rise hover:shadow-card-hover hover:-translate-y-px transition-all duration-150"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-ink-500 dark:text-ink-400">{label}</p>
        <span className={cx('inline-flex h-6 w-6 items-center justify-center rounded-md', iconClass)}>
          <Icon size={14} strokeWidth={2} />
        </span>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[28px] leading-10 font-semibold text-ink-900 dark:text-white tabular-nums">
            <span ref={valueRef}>{value}</span>
          </p>
          <p className="text-2xs text-ink-400 dark:text-ink-500 truncate" title={hint}>
            {hint}
          </p>
        </div>
        {hasSpark && (
          <div className="h-9 w-20 shrink-0 opacity-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sparkData} barCategoryGap="25%" margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                <Bar isAnimationActive={false} dataKey="count" fill={isDark ? '#2f8f8b' : '#82d1cd'} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </Card>
  );
}
