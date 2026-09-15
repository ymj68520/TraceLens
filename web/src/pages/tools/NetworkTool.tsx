import { useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import Card, { CardHeader } from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { cn } from '../../lib/utils';
import { ResultRow } from './shared';

/* ---------------------------------------------------------------------------
 * IP/网络计算器：IPv4 / CIDR 解析 + 归属网段判断。
 * 取证日志里出现 IP 时快速得到整数、二进制、掩码、网段范围与类别（RFC 1918
 * 私网与 RFC 5735 常见特殊段）。全部位运算本地计算，无网络请求。
 * ------------------------------------------------------------------------- */

const u32 = (n: number): number => n >>> 0;

/** 严格解析点分十进制 IPv4，返回无符号 32 位整数；非法输入返回 null。 */
function parseIPv4(text: string): number | null {
  const parts = text.trim().split('.');
  if (parts.length !== 4) return null;
  let value = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return null;
    const octet = Number(part);
    if (octet > 255) return null;
    value = value * 256 + octet;
  }
  return u32(value);
}

const ipToString = (n: number): string =>
  [24, 16, 8, 0].map((shift) => String((n >>> shift) & 255)).join('.');

const ipToBinary = (n: number): string =>
  [24, 16, 8, 0].map((shift) => ((n >>> shift) & 255).toString(2).padStart(8, '0')).join('.');

interface ParsedCidr {
  ip: number;
  prefix: number; // 0-32；裸 IP 视为 /32
}

/** 解析 "a.b.c.d" 或 "a.b.c.d/nn"；前缀越界或格式非法返回 null。 */
function parseCidrInput(raw: string): ParsedCidr | null {
  const s = raw.trim();
  if (!s) return null;
  const slash = s.indexOf('/');
  const ip = parseIPv4(slash === -1 ? s : s.slice(0, slash));
  if (ip === null) return null;
  if (slash === -1) return { ip, prefix: 32 };
  const prefixText = s.slice(slash + 1);
  if (!/^\d{1,2}$/.test(prefixText)) return null;
  const prefix = Number(prefixText);
  return prefix > 32 ? null : { ip, prefix };
}

interface Subnet {
  network: number;
  broadcast: number;
  mask: number;
  wildcard: number;
  prefix: number;
}

function toSubnet({ ip, prefix }: ParsedCidr): Subnet {
  // JS 位移计数按 32 取模，/0 需单独处理，否则 0xffffffff << 32 不会得到 0
  const mask = prefix === 0 ? 0 : u32(0xffffffff << (32 - prefix));
  const network = u32(ip & mask);
  const wildcard = u32(~mask);
  return { network, broadcast: u32(network | wildcard), mask, wildcard, prefix };
}

/** 可用主机范围文本；/31（RFC 3021）与 /32 如实标注。 */
function usableRangeText(s: Subnet): string {
  if (s.prefix === 32) return ipToString(s.network);
  if (s.prefix === 31) return `${ipToString(s.network)} - ${ipToString(s.broadcast)}`;
  return `${ipToString(s.network + 1)} - ${ipToString(s.broadcast - 1)}`;
}

type ChipTone = 'accent' | 'sky' | 'emerald' | 'violet' | 'amber' | 'rose';

const CHIP_TONES: Record<ChipTone, string> = {
  accent: 'bg-accent-50 text-accent-700 dark:bg-accent-500/10 dark:text-accent-300',
  sky: 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300',
  emerald: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  violet: 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300',
  amber: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  rose: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
};

interface SpecialRange {
  label: string;
  network: number;
  prefix: number;
  tone: ChipTone;
}

const v4 = (s: string): number => parseIPv4(s) ?? 0;

/** RFC 1918 私网与 RFC 5735 / 5737 常见特殊段；日志内网/保留段判别常用。 */
const SPECIAL_RANGES: SpecialRange[] = [
  { label: '私网地址（RFC 1918）', network: v4('10.0.0.0'), prefix: 8, tone: 'accent' },
  { label: '私网地址（RFC 1918）', network: v4('172.16.0.0'), prefix: 12, tone: 'accent' },
  { label: '私网地址（RFC 1918）', network: v4('192.168.0.0'), prefix: 16, tone: 'accent' },
  { label: '回环地址（127/8）', network: v4('127.0.0.0'), prefix: 8, tone: 'violet' },
  { label: '链路本地（169.254/16）', network: v4('169.254.0.0'), prefix: 16, tone: 'amber' },
  { label: '本网络段（0/8）', network: v4('0.0.0.0'), prefix: 8, tone: 'rose' },
  { label: '运营商级 NAT（100.64/10）', network: v4('100.64.0.0'), prefix: 10, tone: 'amber' },
  { label: '基准测试段（198.18/15）', network: v4('198.18.0.0'), prefix: 15, tone: 'rose' },
  { label: '文档测试段（TEST-NET）', network: v4('192.0.2.0'), prefix: 24, tone: 'rose' },
  { label: '文档测试段（TEST-NET）', network: v4('198.51.100.0'), prefix: 24, tone: 'rose' },
  { label: '文档测试段（TEST-NET）', network: v4('203.0.113.0'), prefix: 24, tone: 'rose' },
  { label: '组播地址（224/4）', network: v4('224.0.0.0'), prefix: 4, tone: 'rose' },
  { label: '保留地址（240/4）', network: v4('240.0.0.0'), prefix: 4, tone: 'rose' },
];

function classifyIp(ip: number): Array<{ label: string; tone: ChipTone }> {
  const hit = SPECIAL_RANGES.filter((r) => {
    const mask = r.prefix === 0 ? 0 : u32(0xffffffff << (32 - r.prefix));
    return u32(ip & mask) === r.network;
  }).map((r) => ({ label: r.label, tone: r.tone }));
  return hit.length > 0 ? hit : [{ label: '公网地址', tone: 'sky' }];
}

interface ResultRowItem {
  label: string;
  note?: string;
  value: string;
}

export default function NetworkTool() {
  const [mainInput, setMainInput] = useState('');
  const [checkCidr, setCheckCidr] = useState('');
  const [checkIp, setCheckIp] = useState('');

  const parsedMain = useMemo(() => parseCidrInput(mainInput), [mainInput]);
  const subnet = useMemo(() => (parsedMain ? toSubnet(parsedMain) : null), [parsedMain]);

  const mainRows = useMemo<ResultRowItem[]>(() => {
    if (!parsedMain || !subnet) return [];
    const total = 2 ** (32 - subnet.prefix);
    const usable =
      subnet.prefix === 31
        ? '2（RFC 3021 点对点链路）'
        : subnet.prefix === 32
          ? '1（/32 单主机地址）'
          : (total - 2).toLocaleString('zh-CN');
    return [
      { label: 'IP 整数', note: '无符号 32 位', value: String(parsedMain.ip) },
      { label: '二进制', note: '点分 4×8 位', value: ipToBinary(parsedMain.ip) },
      { label: '子网掩码', note: `/${subnet.prefix}`, value: ipToString(subnet.mask) },
      { label: '通配符掩码', value: ipToString(subnet.wildcard) },
      { label: '网络地址', value: ipToString(subnet.network) },
      { label: '广播地址', value: ipToString(subnet.broadcast) },
      { label: '可用范围', value: usableRangeText(subnet) },
      { label: '地址总数', value: total.toLocaleString('zh-CN') },
      { label: '可用主机', value: usable },
    ];
  }, [parsedMain, subnet]);

  const mainStatus = (() => {
    if (!mainInput.trim()) {
      return (
        <span className="text-2xs text-ink-400 dark:text-ink-500">
          输入 IPv4 或 CIDR；裸 IP 按 /32 单主机处理
        </span>
      );
    }
    if (!parsedMain || !subnet) {
      return <span className={cn('chip', CHIP_TONES.amber)}>无法识别的 IPv4 / CIDR 格式</span>;
    }
    const bareIp = !mainInput.includes('/');
    return (
      <>
        <span className={cn('chip', CHIP_TONES.accent)}>
          {bareIp ? 'IP 地址（按 /32 计算）' : `网段 /${parsedMain.prefix}`}
        </span>
        {classifyIp(parsedMain.ip).map((c) => (
          <span key={c.label} className={cn('chip', CHIP_TONES[c.tone])}>
            {c.label}
          </span>
        ))}
      </>
    );
  })();

  /* 归属判断：目标 IP 是否落在网段内 */
  const parsedCheckCidr = useMemo(() => parseCidrInput(checkCidr), [checkCidr]);
  const checkSubnet = useMemo(() => (parsedCheckCidr ? toSubnet(parsedCheckCidr) : null), [parsedCheckCidr]);
  const targetIp = useMemo(() => (checkIp.trim() ? parseIPv4(checkIp) : null), [checkIp]);
  const inNetwork =
    checkSubnet !== null && targetIp !== null && u32(targetIp & checkSubnet.mask) === checkSubnet.network;

  const checkRows = useMemo<ResultRowItem[]>(() => {
    if (!checkSubnet || targetIp === null) return [];
    return [
      { label: '网段范围', note: `/${checkSubnet.prefix}`, value: usableRangeText(checkSubnet) },
      { label: '目标整数', note: '无符号 32 位', value: String(targetIp) },
      { label: '目标二进制', value: ipToBinary(targetIp) },
    ];
  }, [checkSubnet, targetIp]);

  const checkStatus = (() => {
    const hasCidr = checkCidr.trim().length > 0;
    const hasIp = checkIp.trim().length > 0;
    if (!hasCidr && !hasIp) {
      return (
        <span className="text-2xs text-ink-400 dark:text-ink-500">
          输入网段与目标 IP，判断其是否落在该网段内
        </span>
      );
    }
    if (!hasCidr) {
      return <span className="text-2xs text-ink-400 dark:text-ink-500">请输入网段（CIDR）</span>;
    }
    if (!parsedCheckCidr || !checkSubnet) {
      return <span className={cn('chip', CHIP_TONES.amber)}>网段格式无效，请输入如 10.0.0.0/8</span>;
    }
    if (!hasIp) {
      return <span className="text-2xs text-ink-400 dark:text-ink-500">请输入待判断的目标 IP</span>;
    }
    if (targetIp === null) {
      return <span className={cn('chip', CHIP_TONES.amber)}>目标 IP 格式无效</span>;
    }
    const scope = `${ipToString(checkSubnet.network)}/${checkSubnet.prefix}`;
    return inNetwork ? (
      <span className={cn('chip', CHIP_TONES.emerald)}>属于网段 {scope}</span>
    ) : (
      <span className={cn('chip', CHIP_TONES.amber)}>不属于网段 {scope}</span>
    );
  })();

  const clearAll = () => {
    setMainInput('');
    setCheckCidr('');
    setCheckIp('');
  };

  return (
    <Card>
      <CardHeader
        title="IP / 网络计算器"
        subtitle="IPv4 与 CIDR 解析、归属网段判断，输入即算，数据不出浏览器"
        actions={
          <Button variant="ghost" size="sm" onClick={clearAll}>
            <Trash2 size={13} />
            清空
          </Button>
        }
      />

      <label className="field-label" htmlFor="net-main-input">IPv4 / CIDR 输入</label>
      <input
        id="net-main-input"
        type="text"
        className={cn('input font-mono', mainInput && !parsedMain && 'border-amber-400 dark:border-amber-500/60')}
        placeholder="例如 192.168.1.10 或 10.0.0.0/8"
        value={mainInput}
        spellCheck={false}
        onChange={(e) => setMainInput(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">{mainStatus}</div>

      <div className="mt-4">
        {mainRows.length > 0 ? (
          mainRows.map((row) => <ResultRow key={row.label} label={row.label} note={row.note} value={row.value} />)
        ) : (
          <p className="text-xs text-ink-400 dark:text-ink-500">输入有效 IP 或网段后在此显示解析结果</p>
        )}
      </div>

      {/* 归属判断 */}
      <div className="mt-5 border-t border-ink-100 pt-4 dark:border-ink-800/60">
        <p className="section-label mb-3">归属判断</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="field-label" htmlFor="net-check-cidr">网段（CIDR）</label>
            <input
              id="net-check-cidr"
              type="text"
              className={cn('input font-mono', checkCidr && !parsedCheckCidr && 'border-amber-400 dark:border-amber-500/60')}
              placeholder="例如 172.16.0.0/12"
              value={checkCidr}
              spellCheck={false}
              onChange={(e) => setCheckCidr(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="net-check-ip">目标 IP</label>
            <input
              id="net-check-ip"
              type="text"
              className={cn('input font-mono', checkIp && targetIp === null && 'border-amber-400 dark:border-amber-500/60')}
              placeholder="例如 172.20.3.45"
              value={checkIp}
              spellCheck={false}
              onChange={(e) => setCheckIp(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">{checkStatus}</div>
        <div className="mt-3">
          {checkRows.length > 0 ? (
            checkRows.map((row) => <ResultRow key={row.label} label={row.label} note={row.note} value={row.value} />)
          ) : (
            <p className="text-xs text-ink-400 dark:text-ink-500">输入网段与目标 IP 后在此显示判断结果</p>
          )}
        </div>
      </div>

      <p className="mt-3 text-2xs leading-relaxed text-ink-400 dark:text-ink-500">
        裸 IP 按 /32 单主机处理；/31 按 RFC 3021 点对点链路（2 个可用地址）、/32 按单主机如实标注。
        分类徽章覆盖 RFC 1918 私网与 RFC 5735 / 5737 常见特殊段，未命中时标记为公网地址。
      </p>
    </Card>
  );
}
