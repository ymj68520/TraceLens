import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import RegexTool from '../pages/tools/RegexTool';

/*
 * RegexTool 的正则与文本都经 useDebouncedValue(150ms)。
 * useCopy → useToast 依赖 ToastProvider，jsdom 下 stub。
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

/** 输入正则与文本后推进防抖时钟（async 推进以兼容 React 18 调度），等待匹配渲染。 */
async function run(pattern: string, text: string): Promise<void> {
  fireEvent.change(screen.getByLabelText('正则表达式'), { target: { value: pattern } });
  fireEvent.change(screen.getByLabelText('测试文本'), { target: { value: text } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(150);
  });
}

const marks = (container: HTMLElement): HTMLElement[] =>
  Array.from(container.querySelectorAll('mark'));

describe('RegexTool', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('初始状态：复制按钮禁用，提示暂无匹配', () => {
    render(<RegexTool />);
    expect(screen.getByRole('button', { name: '复制全部匹配' })).toBeDisabled();
    expect(screen.getByText('输入正则与文本后在此高亮匹配')).toBeInTheDocument();
    expect(screen.getByText('暂无匹配')).toBeInTheDocument();
  });

  it('匹配计数、mark 高亮与匹配列表一一对应', async () => {
    const { container } = render(<RegexTool />);
    await run('\\d+', 'a1 b22 c333');
    expect(marks(container)).toHaveLength(3);
    expect(marks(container).map((m) => m.textContent)).toEqual(['1', '22', '333']);
    expect(screen.getByText('3 处')).toBeInTheDocument();
    expect(container.querySelectorAll('ul > li')).toHaveLength(3);
    expect(screen.getByRole('button', { name: '复制全部匹配' })).toBeEnabled();
  });

  it('列出编号与命中位置 @index', async () => {
    const { container } = render(<RegexTool />);
    await run('b+', 'aabbb');
    const first = container.querySelector('ul > li');
    expect(first?.textContent).toContain('#1');
    expect(first?.textContent).toContain('@2');
    expect(first?.textContent).toContain('bbb');
  });

  it('分组捕获：$1 $2 逐组显示', async () => {
    render(<RegexTool />);
    await run('(\\w+)-(\\d+)', 'ab-12');
    expect(screen.getByText('$1=ab')).toBeInTheDocument();
    expect(screen.getByText('$2=12')).toBeInTheDocument();
  });

  it('命名捕获组以 $<name> 标签显示', async () => {
    render(<RegexTool />);
    await run('(?<year>\\d{4})-(?<month>\\d{2})', '2026-08-29');
    expect(screen.getByText('$<year>=2026')).toBeInTheDocument();
    expect(screen.getByText('$<month>=08')).toBeInTheDocument();
  });

  it('可选分组未参与匹配时标记「未捕获」', async () => {
    render(<RegexTool />);
    await run('a(b)?', 'a ab');
    expect(screen.getByText('$1=未捕获')).toBeInTheDocument();
    expect(screen.getByText('$1=b')).toBeInTheDocument();
  });

  it('勾选 i 忽略大小写后立即重新匹配', async () => {
    render(<RegexTool />);
    await run('abc', 'x ABC y');
    expect(screen.getByText('暂无匹配')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /忽略大小写/ }));
    expect(screen.getByText('1 处')).toBeInTheDocument();
  });

  it('取消 g 只保留首个匹配并提示', async () => {
    const { container } = render(<RegexTool />);
    await run('\\d+', 'a1 b22 c333');
    expect(marks(container)).toHaveLength(3);
    fireEvent.click(screen.getByRole('checkbox', { name: /全局/ }));
    expect(marks(container)).toHaveLength(1);
    expect(screen.getByText('1 处（未勾选 g，仅首个）')).toBeInTheDocument();
  });

  it('s 标志让 . 匹配换行', async () => {
    render(<RegexTool />);
    await run('a.b', 'a\nb');
    expect(screen.getByText('暂无匹配')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /dotAll/ }));
    expect(screen.getByText('1 处')).toBeInTheDocument();
  });

  it('无效正则显示错误、不高亮、不匹配', async () => {
    const { container } = render(<RegexTool />);
    await run('([', 'abc');
    expect(screen.getByText(/正则无效：/)).toBeInTheDocument();
    expect(screen.getByText('修正正则后显示高亮')).toBeInTheDocument();
    expect(marks(container)).toHaveLength(0);
    expect(screen.getByText('暂无匹配')).toBeInTheDocument();
    expect(screen.getByLabelText('正则表达式')).toHaveClass('border-rose-400');
  });

  it('零宽匹配不参与高亮、不产生死循环', async () => {
    const { container } = render(<RegexTool />);
    await run('a*', 'bb');
    // "bb" 上 a* 产生 3 个零宽命中（位置 0/1/2），不应卡死或高亮
    expect(marks(container)).toHaveLength(0);
    expect(screen.getByText('3 处')).toBeInTheDocument();
    expect(screen.getAllByText('（零宽匹配）')).toHaveLength(3);
  });

  it('匹配数达到上限时截断并提示 1000+', async () => {
    const { container } = render(<RegexTool />);
    await run('x', 'x'.repeat(1001));
    expect(container.querySelectorAll('ul > li')).toHaveLength(1000);
    expect(screen.getByText('1000+ 处')).toBeInTheDocument();
    expect(screen.getByText(/匹配数超过 1000/)).toBeInTheDocument();
  });

  it('「清空」复位全部输入与标志位', async () => {
    const { container } = render(<RegexTool />);
    await run('\\d+', 'a1 b22 c333');
    fireEvent.click(screen.getByRole('checkbox', { name: /忽略大小写/ }));
    fireEvent.click(screen.getByRole('button', { name: /清空/ }));
    expect((screen.getByLabelText('正则表达式') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('测试文本') as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByRole('checkbox', { name: /忽略大小写/ })).not.toBeChecked();
    // 防抖：清空后需等 150ms 结果才撤下
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(screen.getByText('暂无匹配')).toBeInTheDocument();
    expect(marks(container)).toHaveLength(0);
  });
});
