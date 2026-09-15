import type { EventCluster } from '../../types/api';
import zh from '../../locales/zh';
import type { TranslationKey } from '../../locales/keys';

/* ---------------------------------------------------------------------------
 * Shared display vocabulary for the timeline page: event-type colors/labels,
 * unix-second time helpers and cluster identity. Kept framework-free so both
 * the list rows and the detail drawer render identical semantics.
 * ------------------------------------------------------------------------- */

export type TimelineEventType = 'CREATED' | 'MODIFIED' | 'DELETED' | 'OTHER';

/** Translation key per event type (OTHER = anything the backend buckets else).
 *  UI components resolve these through `t()`; the CSV export path resolves
 *  them against the zh base locale below so exported data stays stable. */
export const EVENT_TYPE_LABEL: Record<TimelineEventType, TranslationKey> = {
  CREATED: 'timeline.filter.created',
  MODIFIED: 'timeline.filter.modified',
  DELETED: 'timeline.filter.deleted',
  OTHER: 'timeline.chip.other',
};

/** Canonical event-type palette: emerald / sky / rose / neutral ink. */
export const EVENT_TYPE_DOT: Record<TimelineEventType, string> = {
  CREATED: 'bg-emerald-500',
  MODIFIED: 'bg-sky-500',
  DELETED: 'bg-rose-500',
  OTHER: 'bg-ink-400 dark:bg-ink-500',
};

export const EVENT_TYPE_TEXT: Record<TimelineEventType, string> = {
  CREATED: 'text-emerald-600 dark:text-emerald-400',
  MODIFIED: 'text-sky-600 dark:text-sky-400',
  DELETED: 'text-rose-600 dark:text-rose-400',
  OTHER: 'text-ink-500 dark:text-ink-400',
};

export const normalizeEventType = (raw?: string | null): TimelineEventType => {
  if (raw === 'CREATED' || raw === 'MODIFIED' || raw === 'DELETED') return raw;
  return 'OTHER';
};

/** Display label of an event type for data exports (CSV), resolved against
 *  the zh base locale — exports keep stable values regardless of UI language. */
export const typeLabel = (raw?: string | null): string =>
  zh[EVENT_TYPE_LABEL[normalizeEventType(raw)]];

/** Hex palette for recharts series (no dark variant — mid-tones read on both). */
export const EVENT_TYPE_HEX: Record<TimelineEventType, string> = {
  CREATED: '#10b981',
  MODIFIED: '#3b82f6',
  DELETED: '#f43f5e',
  OTHER: '#8b9da2',
};

/** Backend timestamps are unix seconds (string or number); UI wants ms. */
export const toUnixMs = (ts?: number | string | null): number | null => {
  if (ts === null || ts === undefined || ts === '') return null;
  const n = typeof ts === 'string' ? Number(ts) : ts;
  if (!Number.isFinite(n) || n <= 0) return null;
  return n * 1000;
};

/** One event row as returned by /timeline/details. */
export interface ClusterDetailEvent {
  timestamp?: number | string;
  event_type?: string;
  file_path?: string;
  file_size?: number | string;
  [key: string]: unknown;
}

/** Stable identity for a cluster across refreshes (its group descriptor). */
export const clusterIdentity = (cluster: EventCluster): string =>
  JSON.stringify(cluster?.group_descriptor || null);
