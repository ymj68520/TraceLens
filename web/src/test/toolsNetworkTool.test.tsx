import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import NetworkTool from '../pages/tools/NetworkTool';

/*
 * NetworkTool 本身无路由依赖（无需 Router 包裹）；但 ResultRow → CopyButton
 * → useToast 直连 ToastProvider，jsdom 下统一 stub 掉。
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

const MAIN_LABEL = 'IPv4 / CIDR 输入';
const CHECK_CIDR_LABEL = '网段（CIDR）';
const CHECK_IP_LABEL = '目标 IP';

/** 取 ResultRow 的值列（标签列的下一个兄弟 span）。 */
function rowValue(label: string): HTMLElement {
  const labelEl = screen.getByText(label);
  const valueEl = labelEl.parentElement?.nextElementSibling;
  if (!(valueEl instanceof HTMLElement)) throw new Error(`ResultRow 值未找到: ${label}`);
  return valueEl;
}

const type = (label: string, raw: string): void => {
  fireEvent.change(screen.getByLabelText(label), { target: { value: raw } });
};

/** 输入即算（useMemo 直连 state，无防抖），输入后同步断言即可。 */
const typeMain = (raw: string): void => type(MAIN_LABEL, raw);

describe('NetworkTool — 10.0.0.0/8 解析与计算', () => {
  it('给出掩码、网络/广播地址与可用主机数 16777214', () => {
    render(<NetworkTool />);
    typeMain('10.0.0.0/8');
    expect(screen.getByText('网段 /8')).toBeInTheDocument();
    expect(screen.getAllByText('私网地址（RFC 1918）').length).toBeGreaterThan(0);
    expect(rowValue('IP 整数').textContent).toBe('167772160');
    expect(rowValue('二进制').textContent).toBe('00001010.00000000.00000000.00000000');
    expect(rowValue('子网掩码').textContent).toBe('255.0.0.0');
    expect(rowValue('通配符掩码').textContent).toBe('0.255.255.255');
    expect(rowValue('网络地址').textContent).toBe('10.0.0.0');
    expect(rowValue('广播地址').textContent).toBe('10.255.255.255');
    expect(rowValue('可用范围').textContent).toBe('10.0.0.1 - 10.255.255.254');
    expect(rowValue('地址总数').textContent).toBe('16,777,216');
    expect(rowValue('可用主机').textContent).toBe('16,777,214');
    // 合法输入不应带警告描边
    expect(screen.getByLabelText(MAIN_LABEL).className).not.toContain('border-amber-400');
  });
});

describe('NetworkTool — /31 与 /32 特例', () => {
  it('/31 按 RFC 3021 点对点链路：2 个可用地址', () => {
    render(<NetworkTool />);
    typeMain('10.0.0.0/31');
    expect(screen.getByText('网段 /31')).toBeInTheDocument();
    expect(rowValue('子网掩码').textContent).toBe('255.255.255.254');
    expect(rowValue('网络地址').textContent).toBe('10.0.0.0');
    expect(rowValue('广播地址').textContent).toBe('10.0.0.1');
    expect(rowValue('可用范围').textContent).toBe('10.0.0.0 - 10.0.0.1');
    expect(rowValue('地址总数').textContent).toBe('2');
    expect(rowValue('可用主机').textContent).toBe('2（RFC 3021 点对点链路）');
  });

  it('裸 IP 192.168.1.10 按 /32 单主机处理：整数与二进制', () => {
    render(<NetworkTool />);
    typeMain('192.168.1.10');
    expect(screen.getByText('IP 地址（按 /32 计算）')).toBeInTheDocument();
    expect(screen.getAllByText('私网地址（RFC 1918）').length).toBeGreaterThan(0);
    expect(rowValue('IP 整数').textContent).toBe('3232235786');
    expect(rowValue('二进制').textContent).toBe('11000000.10101000.00000001.00001010');
    expect(rowValue('子网掩码').textContent).toBe('255.255.255.255');
    expect(rowValue('通配符掩码').textContent).toBe('0.0.0.0');
    expect(rowValue('网络地址').textContent).toBe('192.168.1.10');
    expect(rowValue('广播地址').textContent).toBe('192.168.1.10');
    expect(rowValue('可用范围').textContent).toBe('192.168.1.10');
    expect(rowValue('地址总数').textContent).toBe('1');
    expect(rowValue('可用主机').textContent).toBe('1（/32 单主机地址）');
  });

  it('显式 /32 前缀显示「网段 /32」徽章而非裸 IP 徽章', () => {
    render(<NetworkTool />);
    typeMain('192.168.1.10/32');
    expect(screen.getByText('网段 /32')).toBeInTheDocument();
    expect(screen.queryByText('IP 地址（按 /32 计算）')).not.toBeInTheDocument();
    expect(rowValue('可用主机').textContent).toBe('1（/32 单主机地址）');
  });
});

describe('NetworkTool — 分类徽章', () => {
  it.each([
    ['127.0.0.1', '回环地址（127/8）'],
    ['169.254.9.1', '链路本地（169.254/16）'],
    ['172.20.1.1', '私网地址（RFC 1918）'],
    ['8.8.8.8', '公网地址'],
  ])('%s 标记为「%s」', (ip, expected) => {
    render(<NetworkTool />);
    typeMain(ip);
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
  });
});

describe('NetworkTool — 归属判断', () => {
  it('172.20.3.45 落在 172.16.0.0/12 内：属于', () => {
    render(<NetworkTool />);
    type(CHECK_CIDR_LABEL, '172.16.0.0/12');
    type(CHECK_IP_LABEL, '172.20.3.45');
    expect(screen.getByText('属于网段 172.16.0.0/12')).toBeInTheDocument();
    expect(rowValue('网段范围').textContent).toBe('172.16.0.1 - 172.31.255.254');
    expect(rowValue('目标整数').textContent).toBe('2886992685');
    expect(rowValue('目标二进制').textContent).toBe('10101100.00010100.00000011.00101101');
  });

  it('192.168.1.10 不落在 10.0.0.0/8 内：不属于', () => {
    render(<NetworkTool />);
    type(CHECK_CIDR_LABEL, '10.0.0.0/8');
    type(CHECK_IP_LABEL, '192.168.1.10');
    expect(screen.getByText('不属于网段 10.0.0.0/8')).toBeInTheDocument();
  });
});

describe('NetworkTool — 无效输入', () => {
  it.each(['256.1.1.1', '10.0.0.0/33'])('主输入 %s 不崩溃并显示警告', (raw) => {
    render(<NetworkTool />);
    typeMain(raw);
    expect(screen.getByText('无法识别的 IPv4 / CIDR 格式')).toBeInTheDocument();
    expect(screen.getByText('输入有效 IP 或网段后在此显示解析结果')).toBeInTheDocument();
    expect(screen.queryByText('IP 整数')).not.toBeInTheDocument();
    // 非法输入给输入框加琥珀色描边
    expect(screen.getByLabelText(MAIN_LABEL).className).toContain('border-amber-400');
  });

  it('空输入显示格式提示，不渲染结果行', () => {
    render(<NetworkTool />);
    expect(screen.getByText('输入 IPv4 或 CIDR；裸 IP 按 /32 单主机处理')).toBeInTheDocument();
    expect(screen.getByText('输入有效 IP 或网段后在此显示解析结果')).toBeInTheDocument();
    expect(screen.queryByText('IP 整数')).not.toBeInTheDocument();
  });

  it('归属判断：网段格式无效时提示示例格式', () => {
    render(<NetworkTool />);
    type(CHECK_CIDR_LABEL, '300.1.1.0/24');
    type(CHECK_IP_LABEL, '8.8.8.8');
    expect(screen.getByText('网段格式无效，请输入如 10.0.0.0/8')).toBeInTheDocument();
  });

  it('归属判断：目标 IP 格式无效时提示且不渲染判断结果', () => {
    render(<NetworkTool />);
    type(CHECK_CIDR_LABEL, '10.0.0.0/8');
    type(CHECK_IP_LABEL, '256.1.1.1');
    expect(screen.getByText('目标 IP 格式无效')).toBeInTheDocument();
    expect(screen.getByText('输入网段与目标 IP 后在此显示判断结果')).toBeInTheDocument();
  });
});
