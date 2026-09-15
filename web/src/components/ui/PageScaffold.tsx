import type { CSSProperties, ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';

/* ---------------------------------------------------------------------------
 * Page scaffolding shared by every page: header, stat strip, segmented
 * control and skeleton placeholders. Keeping these in one place is what
 * makes twenty pages feel like one product.
 * ------------------------------------------------------------------------- */

const ICON_TONES: Record<string, string> = {
  accent: 'bg-accent-100 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300',
  sky: 'bg-sky-100 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300',
  emerald: 'bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  rose: 'bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300',
  amber: 'bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300',
  violet: 'bg-violet-100 dark:bg-violet-500/15 text-violet-700 dark:text-violet-300',
  slate: 'bg-ink-100 dark:bg-ink-800 text-ink-600 dark:text-ink-300',
};

export function PageHeader({
  icon: Icon,
  tone = 'accent',
  title,
  subtitle,
  actions,
  className,
}: {
  icon: LucideIcon;
  tone?: keyof typeof ICON_TONES;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3 mb-5', className)}>
      <div className="flex items-center gap-3.5 min-w-0">
        <span
          className={cn(
            'hidden sm:flex h-10 w-10 shrink-0 items-center justify-center rounded-xl animate-rise',
            ICON_TONES[tone],
          )}
        >
          <Icon size={19} strokeWidth={1.9} />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-ink-900 dark:text-white tracking-tight animate-rise" style={{ animationDelay: '40ms' } as CSSProperties}>
            {title}
          </h1>
          {subtitle && (
            <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400 truncate animate-rise" style={{ animationDelay: '80ms' } as CSSProperties}>
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 animate-rise" style={{ animationDelay: '120ms' } as CSSProperties}>{actions}</div>}
    </div>
  );
}

export interface StatItem {
  label: string;
  value: number | string;
  dotClass?: string;
  active?: boolean;
  onClick?: () => void;
}

/** Horizontal mini-stat chips; optionally clickable to drive filters. */
export function StatStrip({ stats, className }: { stats: StatItem[]; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {stats.map((s) => {
        const Tag = s.onClick ? 'button' : 'div';
        return (
          <Tag
            key={s.label}
            type={s.onClick ? 'button' : undefined}
            onClick={s.onClick}
            className={cn(
              'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-all duration-150',
              s.onClick && 'cursor-pointer hover:-translate-y-px active:scale-[0.98]',
              s.active
                ? 'border-accent-300 bg-accent-50 text-accent-800 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-200'
                : 'border-ink-200/80 bg-white text-ink-600 dark:border-ink-800 dark:bg-ink-925 dark:text-ink-300 hover:border-ink-300 dark:hover:border-ink-700',
            )}
          >
            {s.dotClass && <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', s.dotClass)} />}
            <span className="font-mono font-medium tabular-nums">{s.value}</span>
            <span>{s.label}</span>
          </Tag>
        );
      })}
    </div>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
  count?: number;
}

/** Flat segmented control for switching views/filters. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={cn('inline-flex items-center gap-0.5 rounded-lg border border-ink-200/80 bg-ink-50 dark:border-ink-800 dark:bg-ink-900 p-0.5', className)}>
      {options.map((o) => {
        const Icon = o.icon;
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-[7px] px-2.5 py-1 text-xs font-medium transition-all duration-150 active:scale-[0.97]',
              active
                ? 'bg-white dark:bg-ink-700 text-ink-900 dark:text-white shadow-sm'
                : 'text-ink-500 dark:text-ink-400 hover:text-ink-800 dark:hover:text-ink-200',
            )}
            aria-pressed={active}
          >
            {Icon && <Icon size={13} strokeWidth={active ? 2.2 : 1.8} />}
            {o.label}
            {o.count != null && (
              <span className={cn('font-mono text-2xs tabular-nums', active ? 'text-accent-600 dark:text-accent-400' : 'text-ink-400')}>
                {o.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------ Skeletons ------------------------------ */

export function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-ink-100 dark:bg-ink-800/70', className)}
      aria-hidden
    />
  );
}

/** Shimmering table placeholder with `rows` skeleton lines. */
export function SkeletonTable({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="px-5 py-4 space-y-4" aria-label="加载中">
      <div className="flex gap-6">
        {Array.from({ length: cols }).map((_, i) => (
          <SkeletonBlock key={i} className="h-3 w-20" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-6" style={{ opacity: 1 - r * 0.12 }}>
          {Array.from({ length: cols }).map((_, c) => (
            <SkeletonBlock key={c} className={cn('h-3.5', c === 0 ? 'w-24' : c === cols - 1 ? 'w-14 ml-auto' : 'w-32')} />
          ))}
        </div>
      ))}
    </div>
  );
}

export default PageHeader;
