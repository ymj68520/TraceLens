import type { ReactNode } from 'react';
import { Drawer, DetailRow } from '../../components/ui/Drawer';
import { formatBytes, formatDateTime } from '../../lib/utils';
import { cellText, type Row } from './RecordTable';

/* ---------------------------------------------------------------------------
 * Detail drawer that auto-enumerates every field of the clicked record.
 * Values render mono; long values are truncated with the full text attached
 * as the native title tooltip. Time-like and size-like keys get human
 * formatting so raw epoch numbers stay readable for analysts.
 * ------------------------------------------------------------------------- */

const TIME_KEY_RE = /(time|timestamp|_at$|modified|created|accessed)/i;
const SIZE_KEY_RE = /(size|bytes)/i;
const LONG_VALUE_LENGTH = 72;

const epochToMs = (n: number): number => (n > 0 && n < 1e12 ? n * 1000 : n);

/** epoch seconds / epoch ms / numeric string / ISO string -> display time. */
export function formatTimestampValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    return Number.isFinite(value) ? formatDateTime(epochToMs(value)) : String(value);
  }
  if (typeof value !== 'string') return String(value);
  if (/^\d+(\.\d+)?$/.test(value.trim())) return formatDateTime(epochToMs(Number(value.trim())));
  return formatDateTime(value);
}

/** Numeric sort key for timestamp-ish values (epoch s/ms, numeric or ISO). */
export function timestampSortValue(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const s = value.trim();
    if (/^\d+(\.\d+)?$/.test(s)) return Number(s);
    const t = Date.parse(s);
    if (!Number.isNaN(t)) return t;
  }
  return 0;
}

/** Human-readable rendering of one field value, keyed by its field name. */
export function formatFieldValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    if (TIME_KEY_RE.test(key)) return formatTimestampValue(value);
    if (SIZE_KEY_RE.test(key)) return `${formatBytes(value)}（${value.toLocaleString('en-US')} 字节）`;
    return String(value);
  }
  if (typeof value === 'object') return cellText(value);
  const s = String(value);
  if (TIME_KEY_RE.test(key) && /^\d{10,13}$/.test(s.trim())) return formatTimestampValue(s);
  return s;
}

interface RecordDetailDrawerProps {
  row: Row | null;
  onClose: () => void;
  title: string;
  description?: string;
  /** Chinese display names for known backend field keys. */
  fieldLabels?: Record<string, string>;
  /** Per-key custom renderer; returning undefined falls back to plain text. */
  renderValue?: (key: string, value: unknown) => ReactNode | undefined;
}

/**
 * Slide-over that auto-enumerates every field of the clicked record, so new
 * backend fields show up without UI changes.
 */
export function RecordDetailDrawer({
  row,
  onClose,
  title,
  description,
  fieldLabels,
  renderValue,
}: RecordDetailDrawerProps) {
  if (!row) return null;
  const entries = Object.entries(row);

  return (
    <Drawer
      open
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <p className="text-2xs text-ink-400 dark:text-ink-500">
          共 {entries.length} 个字段 · 展示该记录的全部原始字段值
        </p>
      }
    >
      <div>
        <p className="section-label mb-1">全部字段</p>
        {entries.map(([key, value]) => {
          const custom = renderValue?.(key, value);
          const text = formatFieldValue(key, value);
          return (
            <DetailRow key={key} label={fieldLabels?.[key] ?? key} mono>
              {custom !== undefined && custom !== null ? (
                custom
              ) : text.length > LONG_VALUE_LENGTH ? (
                <span className="block truncate" title={text}>
                  {text}
                </span>
              ) : (
                text
              )}
            </DetailRow>
          );
        })}
      </div>
    </Drawer>
  );
}

export default RecordDetailDrawer;
