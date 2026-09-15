/**
 * 研判报告的数据模型与纯函数工具。
 *
 * 字段全部按后端 python_service intelligence_report 路由的实际返回建模：
 *  - 报告本体：{ scope_type, scope_id, metadata{title,generated_at,platforms…}, directory[] }
 *  - /records：{ category, page, page_size, total, total_pages, records[] }
 *    chapter 类章节的 records 只有一条 { _category, markdown, title }
 *    device_info 类章节的 records 只有一条「中文标签 → 值」的合成记录
 *  - /search：{ total, offset, limit, hits[{category,page,record_id,title}] }（无摘要字段）
 *  - /metadata：{ task_id, metadata{案件信息+证据信息字段}, updated_at }
 * 所有解析对缺失字段降级（空数组 / null），不抛错。
 */

export interface DirectoryNodeStats {
  total?: number;
  deleted?: number;
  relevant?: number;
}

export interface DirectoryNode {
  id: string;
  title: string;
  /** overview | case | evidence_info | device_info | records | chapter */
  kind: string;
  stats?: DirectoryNodeStats;
}

export interface ReportMetadataInfo {
  task_id?: string;
  title?: string;
  image_path?: string | null;
  files_db?: string | null;
  events_db?: string | null;
  generated_at?: string | null;
  platforms?: string[];
  [key: string]: unknown;
}

export interface ReportShape {
  scope_type?: string;
  scope_id?: string;
  metadata?: ReportMetadataInfo;
  directory?: DirectoryNode[];
  overview?: string;
  [key: string]: unknown;
}

export interface RecordRow {
  id?: string | number;
  path?: string;
  title?: string;
  name?: string;
  file_path?: string;
  timestamp?: string | number;
  category?: string;
  event_type?: string;
  description?: string;
  llm_summary?: string;
  size?: number;
  file_size?: number;
  md5?: string;
  is_deleted?: number;
  data_state?: string;
  scene_relevant?: number;
  llm_is_relevant?: number;
  [key: string]: unknown;
}

export interface PageData {
  records?: RecordRow[];
  page: number;
  page_size: number;
  total?: number;
  total_pages?: number;
  [key: string]: unknown;
}

/** 单个章节的记录分页状态。 */
export interface SectionState {
  page: number;
  data: PageData | null;
  loading: boolean;
  error: string | null;
}

/** 需要走 /records 接口分页拉取的章节类型。 */
export const RECORD_KINDS: ReadonlySet<string> = new Set(['records', 'chapter', 'device_info']);

export const isRecordSection = (node: DirectoryNode): boolean => RECORD_KINDS.has(node.kind);

export const isChapterSection = (node: DirectoryNode): boolean => node.kind === 'chapter';

export const sectionKindLabel = (kind: string): string => {
  switch (kind) {
    case 'records':
      return '证据记录';
    case 'chapter':
      return 'AI 研判';
    case 'device_info':
      return '设备信息';
    case 'overview':
      return '概览';
    case 'case':
    case 'evidence_info':
      return '元数据';
    default:
      return '';
  }
};

/* ------------------------------- 目录锚点 ------------------------------- */

export const KEY_FINDINGS_ANCHOR = 'intel-sec-key-findings';

export const sectionAnchorId = (nodeId: string): string => `intel-sec-${nodeId}`;

export interface TocEntry {
  anchorId: string;
  /** 关键结论为伪章节，nodeId 为空串。 */
  nodeId: string;
  title: string;
  kind: string;
  count?: number;
}

export function buildTocEntries(report: ReportShape | null): TocEntry[] {
  const entries: TocEntry[] = [
    { anchorId: KEY_FINDINGS_ANCHOR, nodeId: '', title: '关键结论', kind: 'findings' },
  ];
  (report?.directory ?? []).forEach((node) => {
    entries.push({
      anchorId: sectionAnchorId(node.id),
      nodeId: node.id,
      title: node.title,
      kind: node.kind,
      count: node.stats?.total,
    });
  });
  return entries;
}

/* --------------------------- 案件 / 证据元数据 --------------------------- */

type MetaField = readonly [key: string, label: string];

/** 案件信息字段（后端 report_metadata 表的实际列）。 */
export const CASE_META_FIELDS: readonly MetaField[] = [
  ['case_name', '案件名称'],
  ['case_number', '案件编号'],
  ['case_type', '案件类型'],
  ['law_case_number', '立案号'],
  ['law_case_category', '司法案件类别'],
  ['law_case_name', '司法案件名称'],
  ['collector_name', '采集人'],
  ['collector_id', '采集人证件类型'],
  ['collector_id_card', '采集人证件号码'],
  ['collector_unit', '采集单位'],
  ['submitter1_name', '提交人一'],
  ['submitter1_id', '提交人一证件号'],
  ['submitter2_name', '提交人二'],
  ['submitter2_id', '提交人二证件号'],
  ['submitter_unit', '提交单位'],
  ['inspection_number', '检验编号'],
  ['alarm_id', '报警编号'],
  ['alarm_code', '报警代码'],
  ['remarks', '备注'],
];

/** 证据信息字段（后端 report_metadata 表的实际列）。 */
export const EVIDENCE_META_FIELDS: readonly MetaField[] = [
  ['evidence_name', '证据名称'],
  ['evidence_number', '证据编号'],
  ['phone1', '手机号码一'],
  ['phone2', '手机号码二'],
  ['holder', '持有人'],
  ['holder_id', '持有人证件号'],
  ['holder_type', '持有人类型'],
  ['id_type', '证件类型'],
  ['id_number', '证件号码'],
  ['holder_gender', '性别'],
  ['holder_ethnicity', '民族'],
  ['birth_date', '出生日期'],
  ['current_address', '现住址'],
  ['registered_address', '户籍地址'],
  ['id_issue_authority', '签发机关'],
  ['id_valid_from', '证件有效期起'],
  ['id_valid_to', '证件有效期止'],
  ['extract_start', '提取开始时间'],
  ['extract_end', '提取结束时间'],
  ['evidence_remarks', '证据备注'],
];

export interface MetaGroups {
  caseRows: [string, string][];
  evidenceRows: [string, string][];
}

/** 按实际列名分组元数据，空值字段直接跳过（缺失即不展示）。 */
export function groupMetadataFields(meta: Record<string, unknown> | null | undefined): MetaGroups {
  const pick = (fields: readonly MetaField[]): [string, string][] =>
    fields
      .map(([key, label]) => {
        const value = meta?.[key];
        const text = value == null ? '' : String(value).trim();
        return [label, text] as [string, string];
      })
      .filter(([, text]) => text.length > 0);
  return { caseRows: pick(CASE_META_FIELDS), evidenceRows: pick(EVIDENCE_META_FIELDS) };
}

/* ------------------------------ 目录统计汇总 ----------------------------- */

export interface DirectorySummary {
  recordsTotal: number;
  deletedTotal: number;
  relevantTotal: number;
  recordSections: number;
  chapterNodes: DirectoryNode[];
}

export function summarizeDirectory(directory?: DirectoryNode[]): DirectorySummary {
  const summary: DirectorySummary = {
    recordsTotal: 0,
    deletedTotal: 0,
    relevantTotal: 0,
    recordSections: 0,
    chapterNodes: [],
  };
  (directory ?? []).forEach((node) => {
    if (node.kind === 'chapter') {
      summary.chapterNodes.push(node);
      return;
    }
    if (node.kind === 'records') {
      summary.recordSections += 1;
      summary.recordsTotal += Number(node.stats?.total ?? 0);
      summary.deletedTotal += Number(node.stats?.deleted ?? 0);
      summary.relevantTotal += Number(node.stats?.relevant ?? 0);
    }
  });
  return summary;
}

/* -------------------------------- 结论提取 ------------------------------- */

const CONFIDENCE_KEYS = ['overall_confidence', 'report_confidence', 'confidence'];

/**
 * 报告级置信度。当前后端模型没有该字段，这里按约定键名防御性提取；
 * 找不到时返回 null（关键结论卡随之隐藏置信度徽章）。
 */
export function pickConfidence(
  ...sources: (Record<string, unknown> | null | undefined)[]
): number | null {
  for (const source of sources) {
    if (!source) continue;
    for (const key of CONFIDENCE_KEYS) {
      const raw = source[key];
      if (raw == null) continue;
      const n = typeof raw === 'number' ? raw : Number(raw);
      if (!Number.isFinite(n) || n < 0) continue;
      return n <= 1 ? n * 100 : n;
    }
  }
  return null;
}

/** chapter 章节正文：/records 只返回一条 { markdown } 记录。 */
export function chapterTextFromPage(data: PageData | null | undefined): string | null {
  const record = data?.records?.[0] as { markdown?: unknown } | undefined;
  const markdown = record?.markdown;
  return typeof markdown === 'string' && markdown.trim().length > 0 ? markdown.trim() : null;
}

/* -------------------------------- 文本导出 ------------------------------- */

export interface PlainTextSource {
  taskId: string;
  report: ReportShape;
  meta: Record<string, unknown> | null;
  chapterTexts: Record<string, string>;
}

/** 拼接纯文本报告，用于「复制文本」。未加载的章节显式标注。 */
export function buildPlainText({ taskId, report, meta, chapterTexts }: PlainTextSource): string {
  const lines: string[] = [];
  const info = report.metadata;
  lines.push(`证据研判报告：${info?.title || taskId}`);
  if (info?.generated_at) lines.push(`生成时间：${info.generated_at}`);
  if (info?.platforms?.length) lines.push(`检测平台：${info.platforms.join('、')}`);
  lines.push('');

  if (typeof report.overview === 'string' && report.overview.trim()) {
    lines.push(`【报告概览】${report.overview.trim()}`, '');
  }
  const { caseRows, evidenceRows } = groupMetadataFields(meta);
  if (caseRows.length) {
    lines.push('【案件信息】');
    caseRows.forEach(([label, value]) => lines.push(`${label}：${value}`));
    lines.push('');
  }
  if (evidenceRows.length) {
    lines.push('【证据信息】');
    evidenceRows.forEach(([label, value]) => lines.push(`${label}：${value}`));
    lines.push('');
  }
  (report.directory ?? []).forEach((node) => {
    if (node.kind !== 'chapter') return;
    lines.push(`【${node.title}】`);
    lines.push(chapterTexts[node.id] ?? '（章节内容未加载）', '');
  });
  return `${lines.join('\n').trim()}\n`;
}

/** 搜索命中的 category → 章节标题。 */
export function nodeTitleOf(directory: DirectoryNode[] | undefined, category: string): string {
  return directory?.find((node) => node.id === category)?.title ?? category;
}
