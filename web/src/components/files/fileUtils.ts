import type { FileRecord } from '../../types/api';
import { formatDateTime } from '../../lib/utils';

/* ---------------------------------------------------------------------------
 * Shared helpers for the file management page. The C++ backend returns
 * loosely-shaped file records (`path` vs `file_path`, seconds vs ms
 * timestamps), so every accessor here is defensive by design.
 * ------------------------------------------------------------------------- */

export type FileSortKey = 'name' | 'size' | 'mtime';
export type FileSortDir = 'asc' | 'desc';
export type FileDensity = 'compact' | 'comfortable';

export const FILE_SORT_KEYS: FileSortKey[] = ['name', 'size', 'mtime'];

/** URL <-> state codec for the persisted sort spec, e.g. `size-desc`. */
export function parseSortSpec(spec: string | null | undefined): { key: FileSortKey; dir: FileSortDir } {
  const [rawKey, rawDir] = (spec ?? '').split('-');
  const key = (FILE_SORT_KEYS as string[]).includes(rawKey ?? '') ? (rawKey as FileSortKey) : 'size';
  const dir: FileSortDir = rawDir === 'asc' ? 'asc' : 'desc';
  return { key, dir };
}

export const formatSortSpec = (key: FileSortKey, dir: FileSortDir): string => `${key}-${dir}`;

/** The API uses `path` on newer payloads and `file_path` on older ones. */
export const getFilePath = (file: FileRecord): string =>
  ((file.path as string) || file.file_path || '') as string;

export const getFileSize = (file: FileRecord): number =>
  Number(file.file_size ?? file.size ?? 0) || 0;

/** Lowercase extension including the dot; '' for extensionless files. */
export const getFileExt = (path: string): string => {
  const base = path.split(/[\\/]/).pop() ?? '';
  const idx = base.lastIndexOf('.');
  return idx > 0 ? base.slice(idx).toLowerCase() : '';
};

const epochToMs = (n: number): number =>
  // Values below ~1e12 are epoch seconds (pre year-2001 in ms is impossible
  // for real evidence timestamps).
  n > 0 && n < 1e12 ? n * 1000 : n;

/** Coerce epoch seconds / epoch ms / numeric string / ISO string into ms. */
export function getFileTimeMs(value: unknown): number {
  if (value === null || value === undefined || value === '') return 0;
  if (typeof value === 'number' && Number.isFinite(value)) return epochToMs(value);
  const s = String(value).trim();
  if (/^\d+(\.\d+)?$/.test(s)) return epochToMs(Number(s));
  const t = new Date(s).getTime();
  return Number.isNaN(t) ? 0 : t;
}

export const formatFileTime = (value: unknown): string => {
  const ms = getFileTimeMs(value);
  return ms ? formatDateTime(ms) : '—';
};

/** mtime with created_time fallback — some sources only record one of them. */
export const getFileMtimeMs = (file: FileRecord): number =>
  getFileTimeMs(file.modified_time) || getFileTimeMs(file.created_time);

export const formatFileMtime = (file: FileRecord): string => {
  const ms = getFileMtimeMs(file);
  return ms ? formatDateTime(ms) : '—';
};

/** `deleted` arrives as boolean, 0/1 or '0'/'1' depending on the source. */
export const isDeletedFile = (file: FileRecord): boolean => {
  const d = file.deleted as unknown;
  return d === true || d === 1 || d === '1';
};

export const OFFICE_EXTS = ['.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt'];

export const isOfficePath = (path: string): boolean => OFFICE_EXTS.includes(getFileExt(path));

/** Clipboard write with an execCommand fallback for non-secure contexts. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
