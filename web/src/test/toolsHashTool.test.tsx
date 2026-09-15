import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import HashTool from '../pages/tools/HashTool';

/*
 * HashTool 直连 useToast，且 ResultRow → CopyButton → useCopy 也会用到；
 * jsdom 下无 ToastProvider，统一 stub。
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

/*
 * crypto.subtle 在 jsdom 不存在，但 vitest 的 worker 里 globalThis.crypto
 * 可能泄漏为 Node webcrypto（其真实异步摘要与 fake timers 相互竞争，
 * 导致结果不确定）。这里统一 stub 掉 subtle，锁死组件文档化的降级路径
 * （shaAll 捕获异常 → SHA 行显示占位符）。MD5 为纯 JS 实现，不受影响，
 * 其正确性由 toolsMd5.test.ts 对 RFC 1321 向量覆盖。
 */
const MD5_ABC = '900150983cd24fb0d6963f7d28e17f72';

const TEXT_LABEL = '文本输入';

/** 文本哈希经 useDebouncedValue(250ms)；async 推进时钟以兼容 React 18 的调度。 */
async function typeText(raw: string): Promise<void> {
  fireEvent.change(screen.getByLabelText(TEXT_LABEL), { target: { value: raw } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
}

/** 取文本哈希区 ResultRow 的值列。 */
function textRowValue(label: string): HTMLElement {
  const labelEl = screen.getByText(label);
  const valueEl = labelEl.parentElement?.nextElementSibling;
  if (!(valueEl instanceof HTMLElement)) throw new Error(`ResultRow 值未找到: ${label}`);
  return valueEl;
}

describe('HashTool', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { getRandomValues: () => new Uint8Array(0), subtle: undefined });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('初始状态：占位文案，且无 MD5 结果行', () => {
    render(<HashTool />);
    expect(screen.getByText('输入文本后在此显示哈希结果')).toBeInTheDocument();
    expect(screen.queryByText('MD5')).not.toBeInTheDocument();
  });

  it('文本防抖 250ms 后才计算', async () => {
    render(<HashTool />);
    fireEvent.change(screen.getByLabelText(TEXT_LABEL), { target: { value: 'abc' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(249);
    });
    expect(screen.getByText('输入文本后在此显示哈希结果')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(textRowValue('MD5').textContent).toBe(MD5_ABC);
  });

  it('MD5（纯 JS）与 RFC 1321 向量一致；subtle 不可用时 SHA 行降级为 —', async () => {
    render(<HashTool />);
    await typeText('abc');
    expect(textRowValue('MD5').textContent).toBe(MD5_ABC);
    expect(textRowValue('SHA-1').textContent).toBe('—');
    expect(textRowValue('SHA-256').textContent).toBe('—');
    expect(textRowValue('SHA-512').textContent).toBe('—');
  });

  it('中文输入按 UTF-8 字节计算 MD5', async () => {
    render(<HashTool />);
    await typeText('中文');
    expect(textRowValue('MD5').textContent).toBe('a7bac2239fcdcb3a067903d8077c4a07');
  });

  it('「清空」复位文本与结果（等防抖生效）', async () => {
    render(<HashTool />);
    await typeText('abc');
    expect(screen.getByText('MD5')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /清空/ }));
    expect((screen.getByLabelText(TEXT_LABEL) as HTMLTextAreaElement).value).toBe('');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.getByText('输入文本后在此显示哈希结果')).toBeInTheDocument();
    expect(screen.queryByText('MD5')).not.toBeInTheDocument();
  });

  it('文件哈希：读取文件后给出文件名与 MD5', async () => {
    const { container } = render(<HashTool />);
    const file = new File(['abc'], 'evidence.txt', { type: 'text/plain' });
    // jsdom 未实现 Blob.arrayBuffer，注入与真实行为一致的桩
    const bytes = new TextEncoder().encode('abc');
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.resolve(bytes.buffer),
      configurable: true,
    });
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input as HTMLInputElement);

    // handleFile 异步：arrayBuffer → shaAll → setFileResult，冲刷微任务与定时器
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(0);
    });

    const fileSection = screen.getByText('文件哈希').closest('div');
    expect(fileSection).not.toBeNull();
    const scoped = within(fileSection as HTMLElement);
    expect(scoped.getByText('evidence.txt')).toBeInTheDocument();
    const md5Label = scoped.getByText('MD5');
    const valueEl = md5Label.parentElement?.nextElementSibling;
    expect(valueEl?.textContent).toBe(MD5_ABC);
    expect(screen.getByText('3.0 B')).toBeInTheDocument(); // formatBytes(3)
  });
});
