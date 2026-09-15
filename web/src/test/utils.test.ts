import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatBytes, basename, formatDateTime, formatDuration, formatRelativeTime, getTaskCreatedMs } from '../lib/utils';

describe('formatDateTime', () => {
  it('returns — for empty input', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime(undefined)).toBe('—');
    expect(formatDateTime(0)).toBe('—');
    expect(formatDateTime('')).toBe('—');
  });

  it('formats epoch ms as local YYYY-MM-DD HH:mm:ss', () => {
    const ts = new Date(2024, 0, 15, 9, 5, 3).getTime();
    expect(formatDateTime(ts)).toBe('2024-01-15 09:05:03');
  });

  it('treats offset-less ISO strings as local time', () => {
    expect(formatDateTime('2024-01-15T08:30:00')).toBe('2024-01-15 08:30:00');
  });

  it('echoes the raw value when it cannot be parsed', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
  });
});

describe('formatRelativeTime', () => {
  const NOW = new Date(2024, 5, 1, 12, 0, 0).getTime();

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns — for empty input', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(formatRelativeTime(null)).toBe('—');
    expect(formatRelativeTime(undefined)).toBe('—');
    expect(formatRelativeTime('')).toBe('—');
    expect(formatRelativeTime(0)).toBe('—');
  });

  it('describes past epoch-ms values in Chinese', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(formatRelativeTime(NOW - 5 * 60_000)).toBe('5 分钟前');
    expect(formatRelativeTime(NOW - 3 * 3_600_000)).toBe('3 小时前');
  });

  it('parses ISO strings for the relative label', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(formatRelativeTime('2024-06-01T10:00:00')).toBe('2 小时前');
  });

  it('labels future values with 内 (zhCN future suffix)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(formatRelativeTime(NOW + 30_000)).toBe('30 秒内');
  });

  it('falls back to the raw value for garbage input', () => {
    expect(formatRelativeTime('not-a-date')).toBe('not-a-date');
  });
});

describe('formatDuration', () => {
  it('returns — only for null/undefined', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(undefined)).toBe('—');
  });

  it('renders sub-second spans in ms', () => {
    expect(formatDuration(0)).toBe('0ms');
    expect(formatDuration(999)).toBe('999ms');
  });

  it('renders seconds below one minute', () => {
    expect(formatDuration(1000)).toBe('1s');
    expect(formatDuration(59_999)).toBe('59s');
  });

  it('renders minutes with leftover seconds', () => {
    expect(formatDuration(60_000)).toBe('1m 0s');
    expect(formatDuration(61_000)).toBe('1m 1s');
    expect(formatDuration(3_599_000)).toBe('59m 59s');
  });

  it('renders hours with leftover minutes', () => {
    expect(formatDuration(3_600_000)).toBe('1h 0m');
    expect(formatDuration(5_400_000)).toBe('1h 30m');
    expect(formatDuration(7_320_000)).toBe('2h 2m');
  });
});

describe('getTaskCreatedMs', () => {
  it('prefers timestamps.created', () => {
    expect(getTaskCreatedMs({ timestamps: { created: 1_700_000_000_000 } })).toBe(1_700_000_000_000);
  });

  it('ignores non-positive timestamps.created and falls back to created_at', () => {
    expect(getTaskCreatedMs({ timestamps: { created: 0 }, created_at: '2024-01-15T08:30:00Z' })).toBe(
      Date.parse('2024-01-15T08:30:00Z'),
    );
  });

  it('parses created_at ISO strings', () => {
    expect(getTaskCreatedMs({ created_at: '2024-03-01T12:00:00Z' })).toBe(
      Date.parse('2024-03-01T12:00:00Z'),
    );
  });

  it('returns null when nothing usable is present', () => {
    expect(getTaskCreatedMs({})).toBeNull();
    expect(getTaskCreatedMs({ timestamps: {} })).toBeNull();
    expect(getTaskCreatedMs({ created_at: 'not-a-date' })).toBeNull();
    expect(getTaskCreatedMs(null)).toBeNull();
  });
});

describe('formatBytes / basename additional edges', () => {
  it('formatBytes scales into GB and TB', () => {
    expect(formatBytes(1024 ** 3)).toBe('1.0 GB');
    expect(formatBytes(5 * 1024 ** 4)).toBe('5.0 TB');
    expect(formatBytes(2 * 1024 ** 3 + 512 * 1024 ** 2)).toBe('2.5 GB');
  });

  it('formatBytes treats negatives by magnitude (implementation contract)', () => {
    // abs() based — matches the long-standing behavior other callers rely on.
    expect(formatBytes(-1024)).toBe('-1.0 KB');
  });

  it('basename keeps the final segment for both separators', () => {
    expect(basename('/home/user/evidence/disk.img')).toBe('disk.img');
    expect(basename('C:\\evidence\\disk.img')).toBe('disk.img');
    expect(basename('plainname.img')).toBe('plainname.img');
    expect(basename('')).toBe('');
    expect(basename(undefined)).toBe('');
  });
});
