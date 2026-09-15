/**
 * 研判结果对比：按文件路径 / 事件簇键匹配两侧条目，逐字段计算差异。
 * 文本归一化（压缩空白）后再比较，避免仅换行/空格差异造成噪音。
 */
import { basename } from '../../lib/utils';
import type {
  ClusterDiffRow,
  ClusterRow,
  DiffRowStatus,
  DiffSummary,
  FieldDiff,
  FileDiffRow,
  LlmDescriptionRow,
} from './types';

export const isRowRelevant = (v?: number | boolean | null): boolean => v === 1 || v === true;

const normText = (s?: string): string => (s ?? '').replace(/\s+/g, ' ').trim();

const normKeywords = (kw?: string[]): string =>
  (kw ?? [])
    .map((k) => k.trim())
    .filter(Boolean)
    .sort()
    .join(' / ');

export const fileKey = (row: LlmDescriptionRow): string => (row.file_path ?? '').trim();

export const clusterKey = (row: ClusterRow): string =>
  `${(row.event_type ?? '').trim()}@${(row.parent_directory ?? '').trim()}`;

const STATUS_ORDER: Record<DiffRowStatus, number> = {
  changed: 0,
  'only-a': 1,
  'only-b': 2,
  same: 3,
};

/** 汇总差异计数。 */
export function summarizeDiff<T extends { status: DiffRowStatus }>(rows: T[]): DiffSummary {
  return {
    same: rows.filter((r) => r.status === 'same').length,
    changed: rows.filter((r) => r.status === 'changed').length,
    onlyA: rows.filter((r) => r.status === 'only-a').length,
    onlyB: rows.filter((r) => r.status === 'only-b').length,
  };
}

/** 文件证据对比：按 file_path 匹配；仅单侧存在的条目标记 only-a / only-b。 */
export function buildFileDiff(aRows: LlmDescriptionRow[], bRows: LlmDescriptionRow[]): FileDiffRow[] {
  const merged = new Map<string, { a?: LlmDescriptionRow; b?: LlmDescriptionRow }>();
  for (const row of aRows) {
    const key = fileKey(row);
    if (!key) continue;
    merged.set(key, { ...(merged.get(key) ?? {}), a: row });
  }
  for (const row of bRows) {
    const key = fileKey(row);
    if (!key) continue;
    merged.set(key, { ...(merged.get(key) ?? {}), b: row });
  }

  const rows: FileDiffRow[] = [];
  merged.forEach((pair, key) => {
    const name = basename(pair.a?.file_path ?? pair.b?.file_path ?? key) || key;
    if (!pair.a || !pair.b) {
      rows.push({
        key,
        name,
        a: pair.a ?? null,
        b: pair.b ?? null,
        status: pair.a ? 'only-a' : 'only-b',
        fields: [],
      });
      return;
    }
    const fields: FieldDiff[] = [];
    if (normText(pair.a.summary) !== normText(pair.b.summary)) {
      fields.push({ label: '摘要', a: pair.a.summary ?? '', b: pair.b.summary ?? '' });
    }
    if (isRowRelevant(pair.a.is_relevant) !== isRowRelevant(pair.b.is_relevant)) {
      fields.push({
        label: '相关性',
        a: isRowRelevant(pair.a.is_relevant) ? '相关' : '不相关',
        b: isRowRelevant(pair.b.is_relevant) ? '相关' : '不相关',
      });
    }
    if (normKeywords(pair.a.keywords) !== normKeywords(pair.b.keywords)) {
      fields.push({ label: '关键词', a: normKeywords(pair.a.keywords), b: normKeywords(pair.b.keywords) });
    }
    rows.push({ key, name, a: pair.a, b: pair.b, status: fields.length > 0 ? 'changed' : 'same', fields });
  });

  return rows.sort(
    (x, y) => STATUS_ORDER[x.status] - STATUS_ORDER[y.status] || x.key.localeCompare(y.key),
  );
}

/** 事件簇对比：按 事件类型@目录 匹配。 */
export function buildClusterDiff(aRows: ClusterRow[], bRows: ClusterRow[]): ClusterDiffRow[] {
  const merged = new Map<string, { a?: ClusterRow; b?: ClusterRow }>();
  for (const row of aRows) {
    const key = clusterKey(row);
    if (!key || key === '@') continue;
    merged.set(key, { ...(merged.get(key) ?? {}), a: row });
  }
  for (const row of bRows) {
    const key = clusterKey(row);
    if (!key || key === '@') continue;
    merged.set(key, { ...(merged.get(key) ?? {}), b: row });
  }

  const rows: ClusterDiffRow[] = [];
  merged.forEach((pair, key) => {
    if (!pair.a || !pair.b) {
      rows.push({
        key,
        a: pair.a ?? null,
        b: pair.b ?? null,
        status: pair.a ? 'only-a' : 'only-b',
        fields: [],
      });
      return;
    }
    const fields: FieldDiff[] = [];
    if (normText(pair.a.llm_summary) !== normText(pair.b.llm_summary)) {
      fields.push({ label: '摘要', a: pair.a.llm_summary ?? '', b: pair.b.llm_summary ?? '' });
    }
    if (isRowRelevant(pair.a.llm_is_relevant) !== isRowRelevant(pair.b.llm_is_relevant)) {
      fields.push({
        label: '相关性',
        a: isRowRelevant(pair.a.llm_is_relevant) ? '相关' : '不相关',
        b: isRowRelevant(pair.b.llm_is_relevant) ? '相关' : '不相关',
      });
    }
    rows.push({ key, a: pair.a, b: pair.b, status: fields.length > 0 ? 'changed' : 'same', fields });
  });

  return rows.sort(
    (x, y) => STATUS_ORDER[x.status] - STATUS_ORDER[y.status] || x.key.localeCompare(y.key),
  );
}
