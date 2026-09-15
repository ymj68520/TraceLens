/**
 * 知识图谱页共用工具：实体类型配色/中文标签、度数统计、视图过滤、
 * 画布 PNG 导出。后端字段存在版本差异，所有解析容错，缺失字段由 UI 优雅降级。
 */

export interface KgNode {
  id: string;
  name?: string;
  type?: string;
  summary?: string;
  [key: string]: unknown;
}

export interface KgLink {
  source: unknown;
  target: unknown;
  type?: string;
  [key: string]: unknown;
}

export interface KgGraph {
  nodes: KgNode[];
  links: KgLink[];
}

/* ------------------------------ 实体类型 ------------------------------ */

export interface TypeMeta {
  key: string;
  label: string;
  color: string;
}

const KNOWN_TYPES: Record<string, { label: string; color: string }> = {
  person: { label: '人物', color: '#4f83cc' },
  file: { label: '文件', color: '#2e9b96' },
  process: { label: '进程', color: '#d45b6a' },
  network: { label: '网络', color: '#c98f2e' },
  location: { label: '位置', color: '#8f6bd4' },
  device: { label: '设备', color: '#0ea5e9' },
  account: { label: '账号', color: '#10b981' },
  org: { label: '组织', color: '#e0659a' },
  event: { label: '事件', color: '#f59e0b' },
  message: { label: '消息', color: '#64748b' },
};

// 未知类型按 key 哈希取稳定兜底色，保证同一类型在不同会话中颜色一致。
const FALLBACK_PALETTE = [
  '#8b9da2',
  '#4f83cc',
  '#d45b6a',
  '#c98f2e',
  '#0ea5e9',
  '#10b981',
  '#8f6bd4',
  '#e0659a',
  '#64748b',
];

export function typeMeta(t?: string): TypeMeta {
  const raw = typeof t === 'string' ? t.trim() : '';
  const key = raw.toLowerCase();
  const known = KNOWN_TYPES[key];
  if (known) return { key, label: known.label, color: known.color };
  if (!raw) return { key: 'other', label: '未标注', color: FALLBACK_PALETTE[0] };
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return { key, label: raw, color: FALLBACK_PALETTE[h % FALLBACK_PALETTE.length] };
}

/* ------------------------------ 节点 / 边 ------------------------------ */

const NAME_KEYS = ['name', 'label', 'title', 'display_name'];

/** 节点显示名：常用名称字段优先，否则回退到 id。 */
export function nodeName(n: KgNode): string {
  for (const k of NAME_KEYS) {
    const v = n[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return n.id;
}

const REL_KEYS = ['type', 'relationship_type', 'rel_type', 'relation', 'label'];

/** 边的关系类型标签。 */
export function linkType(l: KgLink): string {
  for (const k of REL_KEYS) {
    const v = l[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return '关联';
}

/** 宽松取端点 id：兼容字符串与 force-graph 初始化后的节点对象。 */
export function endpointId(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return String(v);
  if (v && typeof v === 'object') {
    const id = (v as { id?: unknown }).id;
    if (typeof id === 'string') return id;
    if (typeof id === 'number') return String(id);
  }
  return '';
}

/** 边的稳定标识（选中态高亮用）。 */
export function linkKey(l: KgLink): string {
  return `${endpointId(l.source)}→${endpointId(l.target)}|${linkType(l)}`;
}

/** 按端点聚合每个节点的关系数。 */
export function computeDegrees(links: KgLink[]): Map<string, number> {
  const m = new Map<string, number>();
  links.forEach((l) => {
    const s = endpointId(l.source);
    const t = endpointId(l.target);
    if (s) m.set(s, (m.get(s) ?? 0) + 1);
    if (t) m.set(t, (m.get(t) ?? 0) + 1);
  });
  return m;
}

export interface TypeStat {
  key: string;
  label: string;
  color: string;
  count: number;
}

/** 按实体类型聚合计数，降序。 */
export function buildTypeStats(nodes: KgNode[]): TypeStat[] {
  const counts = new Map<string, TypeStat>();
  nodes.forEach((n) => {
    const meta = typeMeta(n.type);
    const cur = counts.get(meta.key);
    if (cur) cur.count += 1;
    else counts.set(meta.key, { ...meta, count: 1 });
  });
  return [...counts.values()].sort((a, b) => b.count - a.count);
}

/** 名称或 ID 包含查询串（大小写不敏感）；空查询视为全匹配。 */
export function matchNode(n: KgNode, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return nodeName(n).toLowerCase().includes(q) || n.id.toLowerCase().includes(q);
}

/* ------------------------------ 视图过滤 ------------------------------ */

/** 类型过滤（空数组=全部）+ 最小关系数过滤；边随两端节点保留。 */
export function filterGraph(
  graph: KgGraph,
  activeTypes: string[],
  minDegree: number,
  degrees: Map<string, number>,
): KgGraph {
  const typeSet = activeTypes.length > 0 ? new Set(activeTypes) : null;
  const nodes = graph.nodes.filter((n) => {
    if (typeSet && !typeSet.has(typeMeta(n.type).key)) return false;
    if (minDegree > 0 && (degrees.get(n.id) ?? 0) < minDegree) return false;
    return true;
  });
  const kept = new Set(nodes.map((n) => n.id));
  const links = graph.links.filter(
    (l) => kept.has(endpointId(l.source)) && kept.has(endpointId(l.target)),
  );
  return { nodes, links };
}

/* ------------------------------ 画布配色 / 导出 ------------------------------ */

export interface CanvasPalette {
  text: string;
  halo: string;
  link: string;
  linkDim: string;
  linkFocus: string;
  bg: string;
}

export const CANVAS_LIGHT: CanvasPalette = {
  text: '#566970',
  halo: 'rgba(255,255,255,0.88)',
  link: 'rgba(107,127,133,0.38)',
  linkDim: 'rgba(107,127,133,0.10)',
  linkFocus: 'rgba(13,138,137,0.9)',
  bg: '#ffffff',
};

export const CANVAS_DARK: CanvasPalette = {
  text: '#d6dddf',
  halo: 'rgba(22,28,30,0.88)',
  link: 'rgba(139,157,162,0.26)',
  linkDim: 'rgba(139,157,162,0.08)',
  linkFocus: 'rgba(60,199,196,0.95)',
  bg: '#161c1e',
};

export const FOCUS_RING = '#f59e0b';
export const MATCH_RING = '#17aaa8';

/** 节点半径随关系数缓慢增大（4px 起，上限 10px）。 */
export function nodeRadius(n: KgNode, degrees: Map<string, number>): number {
  return 4 + Math.min(6, Math.sqrt(degrees.get(n.id) ?? 0));
}

/** force-graph 写入节点对象的模拟内部状态，不属于实体属性。 */
export const NODE_INTERNAL_FIELDS = ['x', 'y', 'vx', 'vy', 'fx', 'fy', 'index'];

/**
 * 将画布导出为 PNG。react-force-graph-2d 基于 Canvas2D（非 WebGL）渲染，
 * 画布始终保留绘制缓冲，无需 preserveDrawingBuffer；合成底色后 toDataURL 即可。
 */
export function exportGraphCanvasPng(
  container: HTMLElement | null,
  taskId: string,
  isDark: boolean,
): boolean {
  const canvas = container?.querySelector('canvas');
  if (!canvas || canvas.width === 0 || canvas.height === 0) return false;
  const out = document.createElement('canvas');
  out.width = canvas.width;
  out.height = canvas.height;
  const ctx = out.getContext('2d');
  if (!ctx) return false;
  ctx.fillStyle = isDark ? CANVAS_DARK.bg : CANVAS_LIGHT.bg;
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(canvas, 0, 0);
  try {
    const a = document.createElement('a');
    a.href = out.toDataURL('image/png');
    a.download = `graph-${taskId.slice(0, 8)}.png`;
    a.click();
    return true;
  } catch {
    return false;
  }
}

/** 导出用数据清洗：剥离模拟坐标，端点还原为节点 id。 */
export function serializeGraph(graph: KgGraph): {
  nodes: Record<string, unknown>[];
  links: Record<string, unknown>[];
} {
  const nodes = graph.nodes.map((n) => {
    const out: Record<string, unknown> = {};
    Object.entries(n).forEach(([k, v]) => {
      if (!NODE_INTERNAL_FIELDS.includes(k)) out[k] = v;
    });
    return out;
  });
  const links = graph.links.map((l) => ({
    ...l,
    source: endpointId(l.source),
    target: endpointId(l.target),
  }));
  return { nodes, links };
}
