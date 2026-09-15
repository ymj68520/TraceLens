import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

const toneClass: Record<Tone, string> = {
  neutral: 'bg-ink-100 text-ink-600 border border-ink-200 dark:bg-ink-700/30 dark:text-ink-300 dark:border-ink-600/40',
  accent: 'bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20',
  success: 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20',
  warning: 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/20',
  danger: 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/20',
  info: 'bg-sky-50 text-sky-700 border border-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/20',
};

const dotClass: Record<Tone, string> = {
  neutral: 'bg-ink-400 dark:bg-ink-500',
  accent: 'bg-accent-500',
  success: 'bg-emerald-500',
  warning: 'bg-amber-400',
  danger: 'bg-rose-500',
  info: 'bg-sky-500',
};

interface BadgeProps {
  tone?: Tone;
  /** Prepends a status dot — for machine states where the pill alone is noise. */
  dot?: boolean;
  children: ReactNode;
  className?: string;
}

export function Badge({ tone = 'neutral', dot = false, children, className }: BadgeProps) {
  return (
    <span className={cn('chip', toneClass[tone], className)}>
      {dot && <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full shrink-0', dotClass[tone])} />}
      {children}
    </span>
  );
}

export default Badge;
