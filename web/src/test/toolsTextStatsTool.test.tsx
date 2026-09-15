import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import TextStatsTool from '../pages/tools/TextStatsTool';

const INPUT_LABEL = '文本输入';

/** 统计值经 useDebouncedValue(200ms)；async 推进时钟以兼容 React 18 的调度。 */
async function type(raw: string): Promise<void> {
  fireEvent.change(screen.getByLabelText(INPUT_LABEL), { target: { value: raw } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });
}

/** 字符分布 / 频率条行（左标签 + 计数）的整行文本。 */
function distRowText(label: string): string {
  return screen.getByText(label).parentElement?.textContent ?? '';
}

/** StatStrip 中某指标值（标签 span 的前一个兄弟 span）。 */
function statValue(label: string): string {
  const labelEl = screen.getByText(label);
  return labelEl.previousElementSibling?.textContent ?? '';
}

describe('TextStatsTool', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('空输入只显示占位文案', () => {
    render(<TextStatsTool />);
    expect(screen.getByText('输入文本后在此显示统计结果')).toBeInTheDocument();
  });

  it('输入先经防抖：未到 200ms 前不出结果', async () => {
    render(<TextStatsTool />);
    fireEvent.change(screen.getByLabelText(INPUT_LABEL), { target: { value: 'abc' } });
    expect(screen.getByText('输入文本后在此显示统计结果')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(199);
    });
    expect(screen.getByText('输入文本后在此显示统计结果')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.queryByText('输入文本后在此显示统计结果')).not.toBeInTheDocument();
  });

  it('中英混排文本：字符 / 字节 / 行数 / 词数与分布', async () => {
    render(<TextStatsTool />);
    await type('Hello 世界\nworld 123 ###');
    // chars=22, bytes=26（世界 6 字节）, lines=2, words=3 英文词 + 2 CJK
    expect(statValue('字符（码点）')).toBe('22');
    expect(statValue('UTF-8 字节')).toBe('26');
    expect(statValue('行数')).toBe('2');
    expect(statValue('词数')).toBe('5');
    expect(screen.getByText('词数 = 3 个英文单词 + 2 个中日韩字符')).toBeInTheDocument();
    // 字符分布（总数 22）
    expect(distRowText('中日韩')).toContain('2（9.1%）');
    expect(distRowText('英文字母')).toContain('10（45.5%）');
    expect(distRowText('数字')).toContain('3（13.6%）');
    expect(distRowText('空白')).toContain('4（18.2%）'); // 2 空格 + 换行
    expect(distRowText('其他')).toContain('3（13.6%）'); // 3 个 #
    // Top 频率：# 与 l 各 3 次，并列最高
    expect(distRowText('#')).toContain('3（13.6%）');
    expect(distRowText('l')).toContain('3（13.6%）');
  });

  it('emoji 代理对计 1 字符、4 UTF-8 字节', async () => {
    render(<TextStatsTool />);
    await type('👍');
    expect(statValue('UTF-8 字节')).toBe('4'); // 中英混排用例已验证 chars 口径
    expect(statValue('字符（码点）')).toBe('1');
    expect(statValue('词数')).toBe('0');
    expect(screen.getByText('词数 = 0 个英文单词 + 0 个中日韩字符')).toBeInTheDocument();
  });

  it('日文 / 韩文均计入 CJK 词数', async () => {
    render(<TextStatsTool />);
    await type('한국어カタカナ');
    expect(screen.getByText('词数 = 0 个英文单词 + 7 个中日韩字符')).toBeInTheDocument();
    expect(distRowText('中日韩')).toContain('7（100.0%）');
  });

  it('多行文本：5 个字符 3 行，行数按换行计', async () => {
    render(<TextStatsTool />);
    await type('a\nb\nc');
    expect(statValue('字符（码点）')).toBe('5');
    expect(statValue('UTF-8 字节')).toBe('5');
    expect(statValue('行数')).toBe('3');
    expect(statValue('词数')).toBe('3');
    expect(screen.getByText('词数 = 3 个英文单词 + 0 个中日韩字符')).toBeInTheDocument();
  });

  it('「清空」复位到占位状态', async () => {
    render(<TextStatsTool />);
    await type('Hello 世界\nworld 123 ###');
    expect(statValue('字符（码点）')).toBe('22');
    fireEvent.click(screen.getByRole('button', { name: /清空/ }));
    expect((screen.getByLabelText(INPUT_LABEL) as HTMLTextAreaElement).value).toBe('');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(screen.getByText('输入文本后在此显示统计结果')).toBeInTheDocument();
  });
});
