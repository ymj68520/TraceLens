import { describe, expect, it } from 'vitest';
import {
  buildClusterDiff,
  buildFileDiff,
  clusterKey,
  fileKey,
  isRowRelevant,
  summarizeDiff,
} from '../pages/analysis/diff';
import type { ClusterRow, DiffRowStatus, LlmDescriptionRow } from '../pages/analysis/types';

describe('isRowRelevant', () => {
  it('only 1 and true count as relevant', () => {
    for (const v of [1, true] as (number | boolean | undefined)[]) {
      expect(isRowRelevant(v)).toBe(true);
    }
    for (const v of [0, false, null, undefined] as (number | boolean | null | undefined)[]) {
      expect(isRowRelevant(v)).toBe(false);
    }
    // Truthy garbage (e.g. the string "1") must not be mistaken for relevant.
    expect(isRowRelevant('1' as unknown as number)).toBe(false);
    expect(isRowRelevant(2)).toBe(false);
  });
});

describe('keys', () => {
  it('fileKey trims file_path and yields "" for missing paths', () => {
    expect(fileKey({ file_path: '  /a/b.txt  ' })).toBe('/a/b.txt');
    expect(fileKey({})).toBe('');
  });

  it('clusterKey is event_type@parent_directory, both trimmed', () => {
    expect(clusterKey({ event_type: ' create ', parent_directory: '/data ' })).toBe('create@/data');
    expect(clusterKey({})).toBe('@');
  });
});

describe('summarizeDiff', () => {
  it('counts each status bucket', () => {
    const rows = [
      { status: 'same' },
      { status: 'same' },
      { status: 'changed' },
      { status: 'only-a' },
      { status: 'only-b' },
    ] as { status: DiffRowStatus }[];
    expect(summarizeDiff(rows)).toEqual({ same: 2, changed: 1, onlyA: 1, onlyB: 1 });
  });

  it('sums to zero for empty input', () => {
    expect(summarizeDiff([])).toEqual({ same: 0, changed: 0, onlyA: 0, onlyB: 0 });
  });
});

describe('buildFileDiff', () => {
  it('marks single-side rows only-a / only-b with no field diffs', () => {
    const rows = buildFileDiff(
      [{ file_path: '/only-a.txt', summary: 'A' }],
      [{ file_path: '/only-b.txt', summary: 'B' }],
    );
    expect(rows).toHaveLength(2);
    const onlyA = rows.find((r) => r.key === '/only-a.txt');
    expect(onlyA).toMatchObject({ status: 'only-a', name: 'only-a.txt', b: null, fields: [] });
    const onlyB = rows.find((r) => r.key === '/only-b.txt');
    expect(onlyB).toMatchObject({ status: 'only-b', name: 'only-b.txt', a: null, fields: [] });
  });

  it('reports identical rows as same with no fields', () => {
    const row: LlmDescriptionRow = { file_path: '/a.txt', summary: 'x', keywords: ['k'], is_relevant: 1 };
    const rows = buildFileDiff([row], [{ ...row }]);
    expect(rows).toHaveLength(1);
    expect(rows[0].status).toBe('same');
    expect(rows[0].fields).toEqual([]);
  });

  it('ignores whitespace-only summary differences', () => {
    const a: LlmDescriptionRow = { file_path: '/a.txt', summary: '张三  于凌晨\n转账' };
    const b: LlmDescriptionRow = { file_path: '/a.txt', summary: '张三 于凌晨 转账' };
    expect(buildFileDiff([a], [b])[0].status).toBe('same');
  });

  it('collects summary / relevance / keyword differences as changed', () => {
    const a: LlmDescriptionRow = { file_path: '/a.txt', summary: 'left', keywords: ['b', 'a'], is_relevant: 1 };
    const b: LlmDescriptionRow = { file_path: '/a.txt', summary: 'right', keywords: ['c'], is_relevant: 0 };
    const rows = buildFileDiff([a], [b]);
    expect(rows).toHaveLength(1);
    expect(rows[0].status).toBe('changed');
    expect(rows[0].fields).toEqual([
      { label: '摘要', a: 'left', b: 'right' },
      { label: '相关性', a: '相关', b: '不相关' },
      { label: '关键词', a: 'a / b', b: 'c' },
    ]);
  });

  it('treats reordered or padded keywords as equal', () => {
    const a: LlmDescriptionRow = { file_path: '/k.txt', keywords: ['转账', '银行卡'] };
    const b: LlmDescriptionRow = { file_path: '/k.txt', keywords: [' 银行卡 ', '转账 '] };
    expect(buildFileDiff([a], [b])[0].status).toBe('same');
  });

  it('skips rows without a usable file path on either side', () => {
    const a: LlmDescriptionRow = { file_path: '', summary: 'orphan' };
    const b: LlmDescriptionRow = { file_path: '   ' };
    expect(buildFileDiff([a], [b])).toEqual([]);
  });

  it('sorts changed → only-a → only-b → same, then by key', () => {
    const a: LlmDescriptionRow[] = [
      { file_path: '/z-same.txt', summary: 'same' },
      { file_path: '/m-only-a.txt' },
      { file_path: '/a-changed.txt', summary: 'old' },
    ];
    const b: LlmDescriptionRow[] = [
      { file_path: '/z-same.txt', summary: 'same' },
      { file_path: '/b-only-b.txt' },
      { file_path: '/a-changed.txt', summary: 'new' },
    ];
    expect(buildFileDiff(a, b).map((r) => [r.status, r.key])).toEqual([
      ['changed', '/a-changed.txt'],
      ['only-a', '/m-only-a.txt'],
      ['only-b', '/b-only-b.txt'],
      ['same', '/z-same.txt'],
    ]);
  });
});

describe('buildClusterDiff', () => {
  it('skips rows whose event type and directory are both empty', () => {
    const a: ClusterRow[] = [{}, { event_type: '', parent_directory: '  ' }];
    const b: ClusterRow[] = [{}];
    expect(buildClusterDiff(a, b)).toEqual([]);
  });

  it('marks single-side clusters only-a / only-b', () => {
    const rows = buildClusterDiff(
      [{ event_type: 'create', parent_directory: '/a' }],
      [{ event_type: 'delete', parent_directory: '/b' }],
    );
    expect(rows.map((r) => r.status)).toEqual(['only-a', 'only-b']);
  });

  it('pairs on trimmed event_type@parent_directory keys', () => {
    const a: ClusterRow = { event_type: ' file_write ', parent_directory: ' /data ' };
    const b: ClusterRow = { event_type: 'file_write', parent_directory: '/data' };
    const rows = buildClusterDiff([a], [b]);
    expect(rows).toHaveLength(1);
    expect(rows[0].key).toBe('file_write@/data');
    expect(rows[0].status).toBe('same');
    expect(rows[0].fields).toEqual([]);
  });

  it('reports summary and relevance differences', () => {
    const rows = buildClusterDiff(
      [{ event_type: 'create', parent_directory: '/d', llm_summary: 'x', llm_is_relevant: true }],
      [{ event_type: 'create', parent_directory: '/d', llm_summary: 'y', llm_is_relevant: false }],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].status).toBe('changed');
    expect(rows[0].fields).toEqual([
      { label: '摘要', a: 'x', b: 'y' },
      { label: '相关性', a: '相关', b: '不相关' },
    ]);
  });

  it('reports identical clusters as same', () => {
    const rows = buildClusterDiff(
      [{ event_type: 'create', parent_directory: '/d', llm_summary: ' same ' }],
      [{ event_type: 'create', parent_directory: '/d', llm_summary: 'same' }],
    );
    expect(rows[0].status).toBe('same');
    expect(rows[0].fields).toEqual([]);
  });
});
