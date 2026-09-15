import { cx } from '../../lib/utils';
import type { ReportSection } from './reportModel';

interface Props {
  sections: ReportSection[];
  activeId: string | null;
  onSelect: (id: string) => void;
}

/** Sticky table of contents; the active entry tracks scroll position. */
export default function ReportToc({ sections, activeId, onSelect }: Props) {
  return (
    <nav aria-label="报告目录" className="card p-2">
      <p className="section-label px-2 pb-1.5 pt-1">目录</p>
      <ul className="space-y-0.5">
        {sections.map((s, i) => {
          const active = s.id === activeId;
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                title={s.title}
                aria-current={active ? 'true' : undefined}
                className={cx(
                  'w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                  active
                    ? 'bg-accent-50 text-accent-800 dark:bg-accent-500/10 dark:text-accent-200 font-medium'
                    : 'text-ink-500 dark:text-ink-400 hover:bg-ink-50 dark:hover:bg-ink-900/60 hover:text-ink-800 dark:hover:text-ink-200',
                )}
              >
                <span
                  className={cx(
                    'font-mono text-2xs tabular-nums shrink-0',
                    active ? 'text-accent-600 dark:text-accent-400' : 'text-ink-300 dark:text-ink-600',
                  )}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="truncate">{s.title}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
