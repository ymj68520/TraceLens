import type { ReactNode } from 'react';
import { cx } from '../../lib/utils';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cx('flex flex-col items-center justify-center py-14 px-6 text-center', className)}>
      {icon && <div className="mb-3 text-ink-300 dark:text-ink-600">{icon}</div>}
      <p className="text-sm font-medium text-ink-700 dark:text-ink-300">{title}</p>
      {description && (
        <p className="mt-1 text-xs text-ink-500 dark:text-ink-400 max-w-sm">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export default EmptyState;
