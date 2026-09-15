/* ---------------------------------------------------------------------------
 * Full-text search helpers: localStorage-backed search history (last 10
 * queries), client-side result grouping by file category, and query
 * tokenization for keyword highlighting.
 * ------------------------------------------------------------------------- */

export interface SearchHit {
  path?: string;
  file_path?: string;
  snippet?: string;
  score?: number;
  size?: number;
  [key: string]: unknown;
}

export interface SearchResponse {
  query?: string;
  results?: SearchHit[];
  hits?: SearchHit[];
  count?: number;
  total?: number;
  [key: string]: unknown;
}

/** Prefer `path` (backend contract) but tolerate `file_path`-shaped payloads. */
export const hitPath = (hit: SearchHit): string => {
  if (typeof hit.path === 'string' && hit.path) return hit.path;
  if (typeof hit.file_path === 'string' && hit.file_path) return hit.file_path;
  return '';
};

/* ------------------------------ History ------------------------------ */

const HISTORY_LIMIT = 10;
const HISTORY_KEY = 'tracelens:search-history:v1';

export function loadSearchHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is string => typeof item === 'string' && item.trim() !== '').slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

export function saveSearchHistory(items: string[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, HISTORY_LIMIT)));
  } catch {
    // Private mode / quota errors: history is a nice-to-have, never fatal.
  }
}

/** Most-recent-first, de-duplicated, capped at 10. Pure — persist separately. */
export function pushSearchHistory(existing: string[], query: string): string[] {
  const q = query.trim();
  if (!q) return existing;
  return [q, ...existing.filter((item) => item !== q)].slice(0, HISTORY_LIMIT);
}

/* ------------------------------ Grouping ------------------------------ */

export interface HitGroup {
  key: string;
  label: string;
  hits: SearchHit[];
}

const EXT_GROUPS: { key: string; label: string; extensions: string[] }[] = [
  { key: 'docs', label: '文档', extensions: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'md', 'rtf', 'csv', 'odt'] },
  { key: 'image', label: '图片', extensions: ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp', 'ico', 'tiff', 'heic'] },
  { key: 'media', label: '音视频', extensions: ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a'] },
  { key: 'archive', label: '压缩包', extensions: ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'iso'] },
  { key: 'exec', label: '可执行', extensions: ['exe', 'dll', 'so', 'bin', 'bat', 'cmd', 'sh', 'apk', 'jar', 'app', 'deb', 'rpm', 'dmg'] },
  { key: 'data', label: '数据/日志', extensions: ['db', 'sqlite', 'sqlite3', 'json', 'xml', 'yaml', 'yml', 'ini', 'log', 'reg', 'plist'] },
];

const extensionOf = (path: string): string => {
  const base = path.split(/[\\/]/).pop() ?? '';
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
};

/** Group hits by file category derived from the path extension. */
export function groupHits(hits: SearchHit[]): HitGroup[] {
  const buckets = new Map<string, SearchHit[]>();
  for (const hit of hits) {
    const ext = extensionOf(hitPath(hit));
    const group = EXT_GROUPS.find((g) => g.extensions.includes(ext));
    const key = group ? group.key : 'other';
    const list = buckets.get(key);
    if (list) list.push(hit);
    else buckets.set(key, [hit]);
  }
  const groups: HitGroup[] = [];
  for (const g of EXT_GROUPS) {
    const list = buckets.get(g.key);
    if (list) groups.push({ key: g.key, label: g.label, hits: list });
  }
  const other = buckets.get('other');
  if (other) groups.push({ key: 'other', label: '其他', hits: other });
  return groups;
}

/* --------------------------- Highlight regex --------------------------- */

const escapeRegExp = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Alternation regex over the query tokens (>= 2 chars, max 5). Falls back to
 * the whole trimmed query when every token is a single character.
 */
export function buildHighlightRegex(query: string): RegExp | null {
  const trimmed = query.trim();
  if (!trimmed) return null;
  const tokens = trimmed.split(/\s+/).filter((token) => token.length >= 2).slice(0, 5);
  const sources = tokens.length > 0 ? tokens : [trimmed];
  try {
    return new RegExp(`(${sources.map(escapeRegExp).join('|')})`, 'gi');
  } catch {
    return null;
  }
}
