import { Check } from 'lucide-react';
import { cn } from '../../lib/utils';

interface StepIndicatorProps {
  steps: string[];
  /** Zero-based index of the active step; earlier steps render as done. */
  current: number;
  className?: string;
}

/**
 * Wizard header: numbered circles with connecting hairlines. Done steps get a
 * check, the current step is accent-filled, upcoming steps stay muted.
 */
export function StepIndicator({ steps, current, className }: StepIndicatorProps) {
  return (
    <ol className={cn('flex items-center gap-2', className)} aria-label="向导步骤">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center gap-2 min-w-0">
            <span
              aria-current={active ? 'step' : undefined}
              className={cn(
                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-2xs font-mono font-medium transition-colors',
                active &&
                  'border-accent-500 bg-accent-500 text-white',
                done &&
                  'border-accent-300 bg-accent-50 text-accent-600 dark:border-accent-500/40 dark:bg-accent-500/10 dark:text-accent-300',
                !active &&
                  !done &&
                  'border-ink-200 bg-white text-ink-400 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-500',
              )}
            >
              {done ? <Check size={12} strokeWidth={2.5} /> : i + 1}
            </span>
            <span
              className={cn(
                'text-xs whitespace-nowrap',
                active ? 'font-medium text-ink-900 dark:text-ink-100' : 'text-ink-400 dark:text-ink-500',
              )}
            >
              {label}
            </span>
            {i < steps.length - 1 && (
              <span aria-hidden className="h-px w-8 sm:w-12 bg-ink-200 dark:bg-ink-700 shrink-0" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

export default StepIndicator;
