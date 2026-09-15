/**
 * Shared helpers for the OSS analysis page: tab/column model, cell
 * formatting (human-readable sizes, normalized timestamps), client-side
 * search, raw-value sorting and CSV shaping.
 */
import { formatBytes, formatDateTime } from '../../lib/utils';
import { getFileTimeMs, formatFileTime } from '../../components/files/fileUtils';

export type OssTab = 'objects' | 'logs' | 'summary' | 'stats';

export const OSS_TAB_KEYS: OssTab[] = ['objects', 'logs', 'summary', 'stats'];

export const isOssTab = (v: string): v is OssTab => (OSS_TAB_KEYS as string[]).includes(v);

/** Loosely-shaped OSS record from the C++ backend. */
export type OssRow = Record<string, unknown>;

export type OssCellKind = 'text' | 'size' | 'time' | 'number';

export interface OssColumn {
  key: string;
  label: string;
  kind: OssCellKind;
  align?: 'right';
  /** Render text cells in mono (paths, IPs, hashes). */
  mono?: boolean;
}

export const OSS_COLUMNS: Record<Exclude<OssTab, 'summary'>, OssColumn[]> = {
  objects: [
    { key: 'key', label: '对象键', kind: 'text', mono: true },
    { key: 'size', label: '大小', kind: 'size', align: 'right' },
    { key: 'storage_class', label: '存储类别', kind: 'text' },
    { key: 'last_modified', label: '最后修改', kind: 'time' },
  ],
  logs: [
    { key: 'time', label: '时间', kind: 'time' },
    { key: 'operation', label: '操作', kind: 'text' },
    { key: 'bucket', label: '存储桶', kind: 'text', mono: true },
    { key: 'key', label: '对象键', kind: 'text', mono: true },
    { key: 'remote_ip', label: '来源 IP', kind: 'text', mono: true },
  ],
  stats: [
    { key: 'extension', label: '扩展名', kind: 'text', mono: true },
    { key: 'count', label: '对象数', kind: 'number', align: 'right' },
    { key: 'total_size', label: '总大小', kind: 'size', align: 'right' },
  ],
};

export const SUMMARY_COLUMNS: OssColumn[] = [
  { key: 'field', label: '字段', kind: 'text' },
  { key: 'value', label: '值', kind: 'text' },
];

export const getColumns = (tab: OssTab): OssColumn[] =>
  tab === 'summary' ? SUMMARY_COLUMNS : OSS_COLUMNS[tab];

/** Extract the row array from loosely-shaped API payloads (`objects`/`items`/…). */
export function extractRows(data: unknown, ...keys: string[]): OssRow[] {
  if (Array.isArray(data)) return data as OssRow[];
  const obj = (data ?? {}) as OssRow;
  for (const k of keys) {
    if (Array.isArray(obj[k])) return obj[k] as OssRow[];
  }
  return [];
}

/** Display text for one cell; raw values are kept for sorting and exports. */
export function formatCell(value: unknown, kind: OssCellKind): string {
  if (value === null || value === undefined || value === '') return '—';
  switch (kind) {
    case 'size': {
      const n = Number(value);
      return Number.isFinite(n) ? formatBytes(n) : String(value);
    }
    case 'time':
      return formatFileTime(value);
    case 'number': {
      const n = Number(value);
      return Number.isFinite(n) ? n.toLocaleString('en-US') : String(value);
    }
    default:
      return String(value);
  }
}

/** Ordering value per column kind: numbers for sizes/counts/times, lowercased text otherwise. */
export function sortValue(value: unknown, kind: OssCellKind): number | string {
  if (kind === 'text') return String(value ?? '').toLowerCase();
  if (kind === 'time') return getFileTimeMs(value);
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function compareRows(a: OssRow, b: OssRow, key: string, kind: OssCellKind): number {
  const va = sortValue(a[key], kind);
  const vb = sortValue(b[key], kind);
  if (typeof va === 'number' && typeof vb === 'number') return va - vb;
  return String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: 'base' });
}

/** Case-insensitive substring match across every field of the row. */
export function rowMatches(row: OssRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return Object.values(row).some((v) => v != null && String(v).toLowerCase().includes(q));
}

export interface CsvShape {
  data: Record<string, unknown>[];
  headers: { key: string; label: string }[];
}

/** Export rows for a table tab; size columns carry both human text and raw bytes. */
export function buildTableCsv(tab: OssTab, rows: OssRow[]): CsvShape {
  const cols = OSS_COLUMNS[tab === 'summary' ? 'objects' : tab];
  const headers: CsvShape['headers'] = [];
  cols.forEach((c) => {
    headers.push({ key: c.key, label: c.label });
    if (c.kind === 'size') headers.push({ key: `${c.key}_bytes`, label: `${c.label}(字节)` });
  });
  const data = rows.map((row) => {
    const out: Record<string, unknown> = {};
    cols.forEach((c) => {
      if (c.kind === 'time') out[c.key] = formatCell(row[c.key], 'time');
      else if (c.kind === 'size' || c.kind === 'number') {
        const n = Number(row[c.key]);
        out[c.key] = Number.isFinite(n) ? n : '';
      } else out[c.key] = row[c.key] ?? '';
      if (c.kind === 'size') {
        const n = Number(row[c.key]);
        out[`${c.key}_bytes`] = Number.isFinite(n) ? n : '';
      }
    });
    return out;
  });
  return { data, headers };
}

/** Summary is a key-value record — exported as a two-column table. */
export function buildSummaryCsv(summary: OssRow): CsvShape {
  return {
    data: Object.entries(summary).map(([field, value]) => ({
      field,
      value: value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value),
    })),
    headers: [
      { key: 'field', label: '字段' },
      { key: 'value', label: '值' },
    ],
  };
}

/** Human formatting for summary values: sizes and timestamps get normalized. */
export function formatSummaryValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'object') return JSON.stringify(value);
  const k = key.toLowerCase();
  if (/size|bytes/.test(k)) {
    const n = Number(value);
    if (Number.isFinite(n)) return `${formatBytes(n)}（${n.toLocaleString('en-US')} 字节）`;
  }
  if (/time|date|modified|created/.test(k)) {
    const ms = getFileTimeMs(value);
    if (ms) return formatDateTime(ms);
  }
  return String(value);
}

/** Numeric-looking summary entries get mono emphasis in the card grid. */
export const isNumericSummary = (key: string, value: unknown): boolean =>
  typeof value === 'number' || /count|total|objects|requests/.test(key.toLowerCase());
