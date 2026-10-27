import { describe, expect, it } from 'vitest';
import { ARTIFACT_COLUMNS } from './artifactColumns';

const column = (section, key) => ARTIFACT_COLUMNS[section].find((c) => c.key === key);

describe('Windows 解析结果展示', () => {
  it('将未知执行次数与真实零次执行分开', () => {
    const format = column('win_prefetch', 'run_count').format;
    expect(format(null)).toBe('未知');
    expect(format(undefined)).toBe('未知');
    expect(format(0)).toBe(0);
    expect(format(2)).toBe(2);
  });
  it('明确以 UTC 展示时间，空值不变成 1970 年', () => {
    const format = column('win_prefetch', 'last_run_time').format;
    expect(format(1747731064)).toBe('2025-05-20 08:51:04 UTC');
    expect(format(0)).toBe('1970-01-01 00:00:00 UTC');
    expect(format(null)).toBe('未知');
    expect(format('bad')).toBe('未知');
  });
  it('解析状态和 EVTX 级别使用中文', () => {
    expect(column('win_prefetch', 'parse_status').format('legacy_unverified')).toBe('旧版结果未复核');
    expect(column('win_event_logs', 'parse_status').format('error')).toBe('解析失败');
    expect(column('win_event_logs', 'level').format('LogAlways')).toBe('始终记录');
    expect(column('win_event_logs', 'level').format('Information')).toBe('信息');
    expect(column('win_event_logs', 'level').format(null)).toBe('未知');
  });
});
