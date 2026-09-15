import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { formatDistanceToNowStrict, parseISO } from 'date-fns';
import { zhCN } from 'date-fns/locale';

export const cx = (...inputs: ClassValue[]) => clsx(...inputs);

/** clsx + tailwind-merge — later classes win on conflicts. */
export const cn = (...inputs: ClassValue[]) => twMerge(clsx(...inputs));

export const formatBytes = (bytes?: number | null): string => {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '—';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log2(Math.abs(bytes)) / 10), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
};

export const formatDateTime = (value?: string | number | null): string => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

/** 「3 分钟前」style relative time; falls back to absolute for anything odd. */
export const formatRelativeTime = (value?: string | number | null): string => {
  if (!value) return '—';
  try {
    const d = typeof value === 'number' ? new Date(value) : parseISO(value);
    if (Number.isNaN(d.getTime())) return formatDateTime(value);
    return formatDistanceToNowStrict(d, { addSuffix: true, locale: zhCN });
  } catch {
    return formatDateTime(value);
  }
};

/**
 * Task creation epoch (ms). The C++ API exposes it under `timestamps.created`;
 * `created_at` is kept as a fallback for older payloads.
 */
export const getTaskCreatedMs = (task: unknown): number | null => {
  const t = task as { timestamps?: { created?: unknown }; created_at?: unknown };
  if (typeof t?.timestamps?.created === 'number' && t.timestamps.created > 0) {
    return t.timestamps.created;
  }
  if (typeof t?.created_at === 'string' && t.created_at) {
    const ms = new Date(t.created_at).getTime();
    if (!Number.isNaN(ms)) return ms;
  }
  return null;
};

export const formatDuration = (ms?: number | null): string => {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
};

export const truncate = (text: string, max = 60): string =>
  text.length > max ? `${text.slice(0, max - 1)}…` : text;

export const basename = (p?: string): string => {
  if (!p) return '';
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? p;
};

export const errorMessage = (err: unknown): string => {
  if (typeof err === 'string') return err;
  if (err && typeof err === 'object') {
    const e = err as { message?: string; data?: { detail?: string } };
    return e.data?.detail || e.message || '请求失败';
  }
  return '请求失败';
};
