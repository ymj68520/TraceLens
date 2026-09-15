import { cx } from '../../lib/utils';
import { formatSummaryValue, isNumericSummary, type OssRow } from './ossUtils';

interface Props {
  /** `{ field, value }` rows derived from the summary payload. */
  rows: OssRow[];
}

/** Summary tab: key-value stat cards with human formatting and mono emphasis. */
export default function OssSummaryGrid({ rows }: Props) {
  return (
    <div className="p-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {rows.map((row) => {
        const field = String(row.field ?? '');
        const value = row.value;
        return (
          <div key={field} className="border border-ink-100 dark:border-ink-800 rounded-md px-3 py-2 min-w-0" title={field}>
            <p className="text-2xs text-ink-400 dark:text-ink-500 font-mono truncate">{field}</p>
            <p
              className={cx(
                'mt-0.5 text-sm font-medium text-ink-900 dark:text-ink-100 break-all',
                isNumericSummary(field, value) && 'font-mono tabular-nums',
              )}
            >
              {formatSummaryValue(field, value)}
            </p>
          </div>
        );
      })}
    </div>
  );
}
