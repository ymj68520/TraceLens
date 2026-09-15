import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  FILE_SORT_KEYS,
  copyText,
  formatFileMtime,
  formatFileTime,
  formatSortSpec,
  getFileExt,
  getFilePath,
  getFileMtimeMs,
  getFileSize,
  getFileTimeMs,
  isDeletedFile,
  isOfficePath,
  parseSortSpec,
} from '../components/files/fileUtils';
import type { FileRecord } from '../types/api';

const file = (over: Partial<FileRecord> = {}): FileRecord => ({
  file_path: '/evidence/img.bin',
  ...over,
});

/** Same as `file` but accepts loosely-typed payloads (string deleted flags, …). */
const rawFile = (over: Record<string, unknown>): FileRecord =>
  ({ file_path: '/evidence/img.bin', ...over }) as FileRecord;

describe('getFileTimeMs — timestamp normalisation', () => {
  it('converts epoch seconds (<1e12) to ms', () => {
    expect(getFileTimeMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(getFileTimeMs(1e12 - 1)).toBe((1e12 - 1) * 1000);
  });

  it('keeps epoch-ms values as-is', () => {
    expect(getFileTimeMs(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(getFileTimeMs(1e12)).toBe(1e12);
  });

  it('normalises numeric strings through the same rule', () => {
    expect(getFileTimeMs('1700000000')).toBe(1_700_000_000_000);
    expect(getFileTimeMs(' 1700000000000 ')).toBe(1_700_000_000_000);
  });

  it('parses ISO date strings', () => {
    expect(getFileTimeMs('2024-01-15T00:00:00Z')).toBe(Date.parse('2024-01-15T00:00:00Z'));
  });

  it('returns 0 for empty or unparseable input', () => {
    expect(getFileTimeMs(null)).toBe(0);
    expect(getFileTimeMs(undefined)).toBe(0);
    expect(getFileTimeMs('')).toBe(0);
    expect(getFileTimeMs('not-a-date')).toBe(0);
  });
});

describe('formatFileTime', () => {
  it('renders — when no usable timestamp remains', () => {
    expect(formatFileTime(0)).toBe('—');
    expect(formatFileTime('')).toBe('—');
    expect(formatFileTime('garbage')).toBe('—');
  });

  it('renders normalised timestamps in the absolute format', () => {
    expect(formatFileTime(1_700_000_000)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(formatFileTime(1_700_000_000)).toBe(formatFileTime(1_700_000_000_000));
  });
});

describe('isDeletedFile', () => {
  it.each([true, 1, '1'])('treats %p as deleted', (flag) => {
    expect(isDeletedFile(rawFile({ deleted: flag }))).toBe(true);
  });

  it.each([false, 0, '0', undefined])('treats %p as not deleted', (flag) => {
    expect(isDeletedFile(rawFile({ deleted: flag }))).toBe(false);
  });

  it('treats a missing flag as not deleted', () => {
    expect(isDeletedFile(file())).toBe(false);
  });
});

describe('sort spec codec', () => {
  it('parses valid specs', () => {
    expect(parseSortSpec('name-asc')).toEqual({ key: 'name', dir: 'asc' });
    expect(parseSortSpec('mtime-desc')).toEqual({ key: 'mtime', dir: 'desc' });
    expect(parseSortSpec('size-asc')).toEqual({ key: 'size', dir: 'asc' });
  });

  it('falls back to size-desc for anything invalid', () => {
    expect(parseSortSpec(null)).toEqual({ key: 'size', dir: 'desc' });
    expect(parseSortSpec(undefined)).toEqual({ key: 'size', dir: 'desc' });
    expect(parseSortSpec('')).toEqual({ key: 'size', dir: 'desc' });
    expect(parseSortSpec('bogus-key-asc')).toEqual({ key: 'size', dir: 'desc' });
    expect(parseSortSpec('name-weird')).toEqual({ key: 'name', dir: 'desc' });
  });

  it('round-trips every key/direction combination', () => {
    for (const key of FILE_SORT_KEYS) {
      for (const dir of ['asc', 'desc'] as const) {
        expect(parseSortSpec(formatSortSpec(key, dir))).toEqual({ key, dir });
      }
    }
  });
});

describe('loose record accessors', () => {
  it('getFilePath prefers path over file_path', () => {
    expect(getFilePath(rawFile({ path: '/new/path', file_path: '/old/path' }))).toBe('/new/path');
    expect(getFilePath(file({ file_path: '/only/file_path' }))).toBe('/only/file_path');
    expect(getFilePath(file({ file_path: '' }))).toBe('');
  });

  it('getFileSize coerces and never returns NaN', () => {
    expect(getFileSize(file({ file_size: 100 }))).toBe(100);
    expect(getFileSize(file({ size: 200 }))).toBe(200);
    expect(getFileSize(file())).toBe(0);
    expect(getFileSize(rawFile({ file_size: 'oops' }))).toBe(0);
  });

  it('getFileMtimeMs falls back from modified_time to created_time', () => {
    expect(getFileMtimeMs(file({ modified_time: '2024-01-15T00:00:00Z' }))).toBe(
      Date.parse('2024-01-15T00:00:00Z'),
    );
    expect(getFileMtimeMs(file({ created_time: '2023-06-01T00:00:00Z' }))).toBe(
      Date.parse('2023-06-01T00:00:00Z'),
    );
    expect(getFileMtimeMs(file())).toBe(0);
    expect(formatFileMtime(file())).toBe('—');
  });
});

describe('getFileExt / isOfficePath', () => {
  it('extracts a lowercased extension including the dot', () => {
    expect(getFileExt('report.DOCX')).toBe('.docx');
    expect(getFileExt('a/b/c.tar.gz')).toBe('.gz');
    expect(getFileExt('C:\\dir\\file.PDF')).toBe('.pdf');
  });

  it('returns empty for extensionless and dotfile names', () => {
    expect(getFileExt('noext')).toBe('');
    expect(getFileExt('.hidden')).toBe('');
    expect(getFileExt('dir/.hidden')).toBe('');
  });

  it('detects office documents only by final extension', () => {
    expect(isOfficePath('/docs/a.docx')).toBe(true);
    expect(isOfficePath('/docs/a.xls')).toBe(true);
    expect(isOfficePath('/docs/a.pptx')).toBe(true);
    expect(isOfficePath('/docs/a.txt')).toBe(false);
    expect(isOfficePath('/docs/a.docx.txt')).toBe(false);
  });
});

describe('copyText', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('writes via the async clipboard when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    await expect(copyText('hello')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('falls back to execCommand when the clipboard rejects', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    const execCommand = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true });
    await expect(copyText('fallback')).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
  });
});
