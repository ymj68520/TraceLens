import { cx } from '../../lib/utils';

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizes = {
  sm: 'w-3.5 h-3.5 border-2',
  md: 'w-5 h-5 border-2',
  lg: 'w-8 h-8 border-[3px]',
};

export function Spinner({ size = 'md', className }: SpinnerProps) {
  return (
    <div
      className={cx(
        'rounded-full border-ink-200 dark:border-ink-700 border-t-accent-500 animate-spin',
        sizes[size],
        className,
      )}
      role="status"
      aria-label="loading"
    />
  );
}

export function LoadingBlock({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-ink-500 dark:text-ink-400">
      <Spinner size="lg" />
      <span className="text-sm">{text}</span>
    </div>
  );
}

export default Spinner;
