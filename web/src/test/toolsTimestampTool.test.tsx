import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import TimestampTool from '../pages/tools/TimestampTool';

/*
 * TimestampTool 使用 ResultRow（内含 CopyButton → useToast），
 * jsdom 下无 ToastProvider，统一 stub 掉 sonner 相关实现。
 */
vi.mock('../components/ui/Toast', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
  useToast: () => ({
    push: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  }),
}));

/** 取 ResultRow 的值列（标签列的下一个兄弟 span）。 */
function rowValue(label: string): HTMLElement {
  const labelEl = screen.getByText(label);
  const valueEl = labelEl.parentElement?.nextElementSibling;
  if (!(valueEl instanceof HTMLElement)) throw new Error(`ResultRow 值未找到: ${label}`);
  return valueEl;
}

const type = (raw: string): void => {
  fireEvent.change(screen.getByLabelText('输入（Epoch 或日期字符串）'), { target: { value: raw } });
};

describe('TimestampTool — 空输入', () => {
  it('显示格式提示与占位文案，不渲染结果行', () => {
    render(<TimestampTool />);
    expect(screen.getByText(/支持自动识别：10\/13 位/)).toBeInTheDocument();
    expect(screen.getByText('输入有效时间后在此显示全部格式')).toBeInTheDocument();
    expect(screen.queryByText('Unix 秒')).not.toBeInTheDocument();
  });
});

describe('TimestampTool — Epoch 数字位数识别', () => {
  it('10 位按秒解析：1234567890 → 2009-02-13T23:31:30Z', () => {
    render(<TimestampTool />);
    type('1234567890');
    expect(screen.getByText('已识别：Epoch 秒（10 位）')).toBeInTheDocument();
    expect(rowValue('Unix 秒').textContent).toBe('1234567890');
    expect(rowValue('Unix 毫秒').textContent).toBe('1234567890000');
    expect(rowValue('ISO 8601').textContent).toBe('2009-02-13T23:31:30.000Z');
    expect(rowValue('UTC').textContent).toBe('2009-02-13 23:31:30 UTC');
    // 本地时间依赖运行环境时区，只断言格式
    expect(rowValue('本地时间').textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(rowValue('星期').textContent).toMatch(/^星期[一二三四五六日]$/);
  });

  it('13 位按毫秒解析：1234567890000', () => {
    render(<TimestampTool />);
    type('1234567890000');
    expect(screen.getByText('已识别：Epoch 毫秒（13 位）')).toBeInTheDocument();
    expect(rowValue('Unix 秒').textContent).toBe('1234567890');
    expect(rowValue('ISO 8601').textContent).toBe('2009-02-13T23:31:30.000Z');
  });

  it('16 位按微秒解析，毫秒值向下除以 1000', () => {
    render(<TimestampTool />);
    type('1234567890123456');
    expect(screen.getByText('已识别：Epoch 微秒（16 位）')).toBeInTheDocument();
    expect(rowValue('Unix 毫秒').textContent).toBe('1234567890123');
    expect(rowValue('ISO 8601').textContent).toBe('2009-02-13T23:31:30.123Z');
  });

  it('19 位按纳秒解析', () => {
    render(<TimestampTool />);
    type('1234567890123456789');
    expect(screen.getByText('已识别：Epoch 纳秒（19 位）')).toBeInTheDocument();
    expect(rowValue('Unix 毫秒').textContent).toBe('1234567890123');
    expect(rowValue('Unix 秒').textContent).toBe('1234567890');
  });

  it('负数 10 位 Epoch 同样按秒识别', () => {
    render(<TimestampTool />);
    type('-1000000000');
    expect(screen.getByText('已识别：Epoch 秒（10 位）')).toBeInTheDocument();
    expect(rowValue('ISO 8601').textContent).toBe('1938-04-24T22:13:20.000Z');
  });
});

describe('TimestampTool — 日期字符串解析', () => {
  it('ISO 8601（UTC）字符串', () => {
    render(<TimestampTool />);
    type('2026-08-29T12:30:00Z');
    expect(screen.getByText('已识别：日期字符串')).toBeInTheDocument();
    expect(rowValue('ISO 8601').textContent).toBe('2026-08-29T12:30:00.000Z');
    expect(rowValue('Unix 秒').textContent).toBe('1788006600');
    expect(rowValue('UTC').textContent).toBe('2026-08-29 12:30:00 UTC');
  });
});

describe('TimestampTool — 非法输入', () => {
  it.each(['not-a-date', '123', '12x3', '2026-13-99'])('无法识别 %s', (raw) => {
    render(<TimestampTool />);
    type(raw);
    expect(screen.getByText('无法识别的时间格式')).toBeInTheDocument();
    expect(screen.getByText('输入有效时间后在此显示全部格式')).toBeInTheDocument();
  });

  it('纯空格视同空输入，仍显示提示', () => {
    render(<TimestampTool />);
    type('   ');
    expect(screen.getByText(/支持自动识别/)).toBeInTheDocument();
  });
});

describe('TimestampTool — 工具栏按钮', () => {
  it('「当前时间」写入 13 位毫秒并识别', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-29T00:00:00Z'));
    try {
      render(<TimestampTool />);
      fireEvent.click(screen.getByRole('button', { name: /当前时间/ }));
      const input = screen.getByLabelText('输入（Epoch 或日期字符串）') as HTMLInputElement;
      expect(input.value).toBe('1787961600000');
      expect(screen.getByText('已识别：Epoch 毫秒（13 位）')).toBeInTheDocument();
      expect(rowValue('ISO 8601').textContent).toBe('2026-08-29T00:00:00.000Z');
    } finally {
      vi.useRealTimers();
    }
  });

  it('「清空」复位为空输入状态', () => {
    render(<TimestampTool />);
    type('1234567890');
    expect(screen.getByText('已识别：Epoch 秒（10 位）')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /清空/ }));
    expect((screen.getByLabelText('输入（Epoch 或日期字符串）') as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/支持自动识别/)).toBeInTheDocument();
    expect(screen.queryByText('Unix 秒')).not.toBeInTheDocument();
  });
});
