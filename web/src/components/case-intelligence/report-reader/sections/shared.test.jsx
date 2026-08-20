import { val, fileSize, fmtDuration, callTypeLabel, smsTypeLabel } from './shared';

describe('report section shared helpers', () => {
  test('val renders em dash for empty values', () => {
    expect(val(null)).toBe('—');
    expect(val(undefined)).toBe('—');
    expect(val('')).toBe('—');
    expect(val('有值')).toBe('有值');
    expect(val(0)).toBe('0');
  });

  test('fileSize formats byte counts', () => {
    expect(fileSize(512)).toBe('512 B');
    expect(fileSize(2048)).toBe('2.0 KB');
    expect(fileSize(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(fileSize(null)).toBe('—');
  });

  test('fmtDuration formats seconds in Chinese', () => {
    expect(fmtDuration(0)).toBe('0秒');
    expect(fmtDuration(45)).toBe('45秒');
    expect(fmtDuration(125)).toBe('2分5秒');
    expect(fmtDuration(3725)).toBe('1时2分5秒');
    expect(fmtDuration(null)).toBe('—');
  });

  test('callTypeLabel maps Android type codes', () => {
    expect(callTypeLabel(1)).toBe('呼入电话');
    expect(callTypeLabel(2)).toBe('呼出电话');
    expect(callTypeLabel(3)).toBe('未接电话');
    expect(callTypeLabel('')).toBe('—');
    expect(callTypeLabel(99)).toBe('99');
  });

  test('smsTypeLabel maps Android type codes', () => {
    expect(smsTypeLabel(1)).toBe('接收');
    expect(smsTypeLabel(2)).toBe('发送');
    expect(smsTypeLabel(null)).toBe('—');
  });
});
