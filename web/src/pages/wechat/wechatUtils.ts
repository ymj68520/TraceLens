/**
 * 微信关系分析页共用的宽松类型与解析工具。
 * 后端字段存在版本差异：所有解析都做容错，缺失字段一律返回 null 并由 UI 优雅降级。
 */

export interface WxNode {
  id: string;
  nickname?: string;
  name?: string;
  remark?: string;
  alias?: string;
  message_count?: number;
  [key: string]: unknown;
}

export interface WxEdge {
  source: unknown;
  target: unknown;
  edge_type?: string;
  chatroom?: string;
  message_count?: number;
  [key: string]: unknown;
}

export interface WxGraphData {
  nodes?: WxNode[];
  edges?: WxEdge[];
  links?: WxEdge[];
}

export interface ChatMessage {
  id?: string | number;
  sender?: string;
  content?: string;
  timestamp?: number | string;
  create_time?: number | string;
  [key: string]: unknown;
}

export const CHAT_PAGE_SIZE = 50;

/* ------------------------------ 节点 / 边 ------------------------------ */

export const isGroupNode = (n: WxNode): boolean =>
  (typeof n.id === 'string' && n.id.includes('@chatroom')) || n.is_group === true || n.isGroup === true;

export const isGroupEdge = (e: WxEdge): boolean =>
  e.edge_type === 'group' || (typeof e.chatroom === 'string' && e.chatroom.includes('@chatroom'));

const endpointId = (v: unknown): string => {
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return String(v);
  if (v && typeof v === 'object') {
    const id = (v as { id?: unknown }).id;
    if (typeof id === 'string') return id;
    if (typeof id === 'number') return String(id);
  }
  return '';
};

export const edgeEndpoints = (e: WxEdge): { src: string; tgt: string } => ({
  src: endpointId(e.source),
  tgt: endpointId(e.target),
});

/** 边的稳定标识：群会话按 chatroom，双人会话按排序后的两端 id。 */
export const edgeKey = (e: WxEdge): string => {
  if (isGroupEdge(e) && typeof e.chatroom === 'string' && e.chatroom) return `room:${e.chatroom}`;
  const { src, tgt } = edgeEndpoints(e);
  return [src, tgt].sort().join('|');
};

export const findEdgeByKey = (links: WxEdge[], key: string): WxEdge | null =>
  links.find((l) => edgeKey(l) === key) ?? null;

export const displayName = (n: WxNode): string => {
  const cand = [n.nickname, n.name, n.remark, n.alias].find(
    (v): v is string => typeof v === 'string' && v.trim().length > 0,
  );
  return cand ?? (typeof n.id === 'string' ? n.id : '');
};

/** /owner 接口可能直接返回对象，也可能包在 {owner|data|profile} 里；解不开返回 null。 */
export function unwrapOwner(res: unknown): Record<string, unknown> | null {
  if (!res || typeof res !== 'object') return null;
  const r = res as Record<string, unknown>;
  for (const k of ['owner', 'data', 'profile']) {
    const v = r[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) return v as Record<string, unknown>;
  }
  return r;
}

/** 消息总数：优先按会话边汇总（避免与节点重复计数），缺字段时按节点汇总。 */
export function computeMessageTotal(nodes: WxNode[], edges: WxEdge[]): { value: number | null; source: 'edge' | 'node' | null } {
  if (edges.some((e) => typeof e.message_count === 'number')) {
    return { value: edges.reduce((s, e) => s + (typeof e.message_count === 'number' ? e.message_count : 0), 0), source: 'edge' };
  }
  if (nodes.some((n) => typeof n.message_count === 'number')) {
    return { value: nodes.reduce((s, n) => s + (typeof n.message_count === 'number' ? n.message_count : 0), 0), source: 'node' };
  }
  return { value: null, source: null };
}

/* ------------------------------ 消息解析 ------------------------------ */

/** 统一换算成毫秒时间戳；无法解析返回 null（不猜值）。 */
export function msgTimeMs(m: ChatMessage): number | null {
  const raw = m.timestamp ?? m.create_time ?? m.time ?? m.ts;
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return raw > 1e12 ? raw : raw * 1000;
  if (typeof raw === 'string' && raw.trim()) {
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) return n > 1e12 ? n : n * 1000;
    const d = new Date(raw).getTime();
    return Number.isNaN(d) ? null : d;
  }
  return null;
}

export const messageKey = (m: ChatMessage): string =>
  `${m.id ?? ''}|${m.timestamp ?? m.create_time ?? ''}|${m.sender ?? ''}|${String(m.content ?? '').slice(0, 24)}`;

const MESSAGE_TYPE_FIELDS = ['msg_type', 'message_type', 'msgtype', 'type', 'content_type'];

// 微信原生 msgType 数值语义（业界通用映射；未收录的值原样展示）。
const NUMERIC_TYPE_LABELS: Record<number, string> = {
  1: '文本', 3: '图片', 34: '语音', 42: '名片', 43: '视频', 47: '表情',
  48: '位置', 49: '链接/文件', 50: '音视频通话', 10000: '系统', 10002: '撤回',
};

const STRING_TYPE_LABELS: Record<string, string> = {
  text: '文本', image: '图片', voice: '语音', video: '视频', emoji: '表情', sticker: '表情',
  link: '链接', file: '文件', location: '位置', system: '系统', card: '名片', call: '音视频通话',
};

export const typeLabelFor = (v: unknown): string => {
  if (typeof v === 'number') return NUMERIC_TYPE_LABELS[v] ?? `类型 ${v}`;
  if (typeof v === 'string') {
    const t = v.trim().toLowerCase();
    if (!t) return '未知';
    return STRING_TYPE_LABELS[t] ?? v;
  }
  return '未知';
};

export interface MessageTypeOption {
  value: string;
  label: string;
  count: number;
}

/** 探测消息类型字段；至少出现 2 种取值才启用筛选，否则返回 null（不提供筛选）。 */
export function buildMessageTypes(messages: ChatMessage[]): { field: string; options: MessageTypeOption[] } | null {
  const field = MESSAGE_TYPE_FIELDS.find((f) =>
    messages.some((m) => m[f] !== undefined && m[f] !== null && m[f] !== ''),
  );
  if (!field) return null;
  const counts = new Map<string, { label: string; count: number }>();
  messages.forEach((m) => {
    const v = m[field];
    if (v === undefined || v === null || v === '') return;
    const key = String(v);
    const entry = counts.get(key) ?? { label: typeLabelFor(v), count: 0 };
    entry.count += 1;
    counts.set(key, entry);
  });
  if (counts.size < 2) return null;
  const options = [...counts.entries()]
    .map(([value, info]) => ({ value, label: info.label, count: info.count }))
    .sort((a, b) => b.count - a.count);
  return { field, options };
}

/* ------------------------------ 时间线解析 ------------------------------ */

export interface TrendPoint {
  label: string;
  count: number;
  ts: number | null;
}

export interface TimelineSummary {
  points: TrendPoint[];
  total: number;
  peak: TrendPoint;
}

const TIMELINE_COUNT_KEYS = ['count', 'total', 'messages', 'message_count', 'value', 'cnt', 'num', 'msg_count'];
const TIMELINE_LABEL_KEYS = ['date', 'day', 'period', 'time', 'bucket', 'date_str', 'label', 'month', 'week'];

/** 宽松解析时间线接口：数组或 {timeline|data|...} 包裹均可；解析失败返回 null。 */
export function parseTimeline(res: unknown): TimelineSummary | null {
  let rows: unknown[] = [];
  if (Array.isArray(res)) rows = res;
  else if (res && typeof res === 'object') {
    for (const k of ['timeline', 'data', 'items', 'buckets', 'points', 'series', 'result']) {
      const v = (res as Record<string, unknown>)[k];
      if (Array.isArray(v)) {
        rows = v;
        break;
      }
    }
  }
  if (rows.length === 0) return null;

  const isFiniteNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
  const points: TrendPoint[] = [];
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    const r = row as Record<string, unknown>;
    const count = TIMELINE_COUNT_KEYS.map((k) => r[k]).find(isFiniteNumber);
    if (count === undefined) continue;
    let label: string | null = null;
    let ts: number | null = null;
    for (const k of TIMELINE_LABEL_KEYS) {
      const v = r[k];
      if (typeof v === 'string' && v.trim()) {
        label = v.trim();
        break;
      }
      if (typeof v === 'number' && v > 0) {
        ts = v > 1e12 ? v : v * 1000;
        try {
          label = new Date(ts).toISOString().slice(0, 10);
        } catch {
          label = String(v);
        }
        break;
      }
    }
    if (!label) continue;
    points.push({ label, count, ts });
  }
  if (points.length === 0) return null;
  points.sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0) || a.label.localeCompare(b.label));
  const total = points.reduce((s, p) => s + p.count, 0);
  const peak = points.reduce((m, p) => (p.count > m.count ? p : m), points[0]);
  return { points, total, peak };
}
