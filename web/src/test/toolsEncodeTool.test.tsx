import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import EncodeTool from '../pages/tools/EncodeTool';

/*
 * EncodeTool 经 ResultRow → CopyButton → useToast 依赖 ToastProvider，
 * jsdom 下统一 stub。
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

function rowValue(label: string): HTMLElement {
  const labelEl = screen.getByText(label);
  const valueEl = labelEl.parentElement?.nextElementSibling;
  if (!(valueEl instanceof HTMLElement)) throw new Error(`ResultRow 值未找到: ${label}`);
  return valueEl;
}

const type = (raw: string): void => {
  fireEvent.change(screen.getByLabelText('输入（编码或解码内容均可，自动双向转换）'), {
    target: { value: raw },
  });
};

const pickCodec = (name: string): void => {
  fireEvent.click(screen.getByRole('button', { name }));
};

describe('EncodeTool — 空输入', () => {
  it('显示占位文案且不显示字节计数', () => {
    render(<EncodeTool />);
    expect(rowValue('编码 Base64').textContent).toBe('输入内容后自动编码');
    expect(rowValue('解码 Base64').textContent).toBe('输入内容后自动解码');
    expect(screen.queryByText(/输入 \d+ 字符 \/ UTF-8 \d+ 字节/)).not.toBeInTheDocument();
    expect(screen.queryByText(/无法按/)).not.toBeInTheDocument();
  });
});

describe('EncodeTool — Base64', () => {
  it('中文按 UTF-8 口径编码：中文 → 5Lit5paH', () => {
    render(<EncodeTool />);
    type('中文');
    expect(rowValue('编码 Base64').textContent).toBe('5Lit5paH');
    expect(screen.getByText(/输入 2 字符 \/ UTF-8 6 字节/)).toBeInTheDocument();
  });

  it('ASCII 编码：hello → aGVsbG8=', () => {
    render(<EncodeTool />);
    type('hello');
    expect(rowValue('编码 Base64').textContent).toBe('aGVsbG8=');
  });

  it('粘贴编码结果即可解码出原文（往返）', () => {
    render(<EncodeTool />);
    type('5Lit5paH');
    expect(rowValue('解码 Base64').textContent).toBe('中文');
  });

  it('含 + / = 的原文编解码往返：a+b/c → YStiL2M=', () => {
    render(<EncodeTool />);
    type('a+b/c');
    expect(rowValue('编码 Base64').textContent).toBe('YStiL2M=');
    // 把编码结果贴回输入框验证解码方向
    type('YStiL2M=');
    expect(rowValue('解码 Base64').textContent).toBe('a+b/c');
  });

  it('长度非 4 的倍数时解码失败并给出警告', () => {
    render(<EncodeTool />);
    type('hello'); // 5 字符，非 4 的倍数
    expect(rowValue('解码 Base64').textContent).toBe('不是有效的编码');
    expect(screen.getByText(/当前输入无法按 Base64 解码/)).toBeInTheDocument();
  });
});

describe('EncodeTool — Hex', () => {
  it('中文编码为 UTF-8 十六进制：中文 → e4b8ade69687', () => {
    render(<EncodeTool />);
    pickCodec('Hex');
    type('中文');
    expect(rowValue('编码 Hex').textContent).toBe('e4b8ade69687');
  });

  it('解码容忍空格且大小写不敏感', () => {
    render(<EncodeTool />);
    pickCodec('Hex');
    type('E4B8AD e6 96 87');
    expect(rowValue('解码 Hex').textContent).toBe('中文');
  });

  it('奇数长度与非法字符均解码失败', () => {
    render(<EncodeTool />);
    pickCodec('Hex');
    type('abc');
    expect(rowValue('解码 Hex').textContent).toBe('不是有效的编码');
    expect(screen.getByText(/Hex 需偶数个 0-9a-f 字符/)).toBeInTheDocument();

    type('zz');
    expect(rowValue('解码 Hex').textContent).toBe('不是有效的编码');
  });

  it('已输入文本在切换进制后立即按新进制重编码', () => {
    render(<EncodeTool />);
    type('中文');
    expect(rowValue('编码 Base64').textContent).toBe('5Lit5paH');
    pickCodec('Hex');
    expect(rowValue('编码 Hex').textContent).toBe('e4b8ade69687');
    // 输入仍是「中文」，不是合法 hex，解码列提示无效
    expect(rowValue('解码 Hex').textContent).toBe('不是有效的编码');
    expect(screen.getByText(/Hex 需偶数个 0-9a-f 字符/)).toBeInTheDocument();
  });
});

describe('EncodeTool — Base64URL', () => {
  it('使用 - _ 且省略填充：??? → Pz8_（对比 Base64 为 Pz8/）', () => {
    render(<EncodeTool />);
    type('???');
    expect(rowValue('编码 Base64').textContent).toBe('Pz8/');
    pickCodec('Base64URL');
    expect(rowValue('编码 Base64URL').textContent).toBe('Pz8_');
  });

  it('往返解码：Pz8_ → ???，且无需补齐填充', () => {
    render(<EncodeTool />);
    pickCodec('Base64URL');
    type('Pz8_');
    expect(rowValue('解码 Base64URL').textContent).toBe('???');
  });

  it('中文往返：5Lit5paH', () => {
    render(<EncodeTool />);
    pickCodec('Base64URL');
    type('中文');
    expect(rowValue('编码 Base64URL').textContent).toBe('5Lit5paH');
    type('5Lit5paH');
    expect(rowValue('解码 Base64URL').textContent).toBe('中文');
  });
});

describe('EncodeTool — URL（encodeURIComponent 口径）', () => {
  it('特殊字符 +/&= 全部转义', () => {
    render(<EncodeTool />);
    pickCodec('URL');
    type('+/&=');
    expect(rowValue('编码 URL').textContent).toBe('%2B%2F%26%3D');
  });

  it('中文与空格的转义及往返', () => {
    render(<EncodeTool />);
    pickCodec('URL');
    type('中文 x');
    expect(rowValue('编码 URL').textContent).toBe('%E4%B8%AD%E6%96%87%20x');
    type('%E4%B8%AD%E6%96%87%20x');
    expect(rowValue('解码 URL').textContent).toBe('中文 x');
  });

  it('孤立 % 序列解码失败', () => {
    render(<EncodeTool />);
    pickCodec('URL');
    type('100%');
    expect(rowValue('解码 URL').textContent).toBe('不是有效的编码');
  });
});
