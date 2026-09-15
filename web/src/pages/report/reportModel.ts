/**
 * Report content model for the forensic report viewer: unified sections over
 * both payload shapes (narrative markdown + snapshot manifest categories),
 * markdown parsing into blocks, and serialization back to markdown / JSON
 * for export.
 */
import { formatDateTime } from '../../lib/utils';

export interface ManifestCategory {
  category_id: string;
  title?: string;
  count?: number;
  [key: string]: unknown;
}

export interface ReportManifest {
  report_id?: string;
  schema_version?: string;
  categories?: ManifestCategory[];
  [key: string]: unknown;
}

export type MarkdownBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'code'; text: string }
  | { type: 'table'; columns: string[]; rows: string[][] };

export interface ReportSection {
  id: string;
  title: string;
  kind: 'markdown' | 'table';
  /** markdown-kind sections (parsed narrative). */
  blocks?: MarkdownBlock[];
  /** table-kind sections (snapshot manifest categories). */
  categoryId?: string;
  totalCount?: number;
}

/** Load state of one snapshot category's current page. */
export interface CategoryPageState {
  page: number;
  loading: boolean;
  error: string | null;
  records: Record<string, unknown>[];
  total?: number;
}

export type CategoryStates = Record<string, CategoryPageState>;

/* ------------------------- markdown → sections ------------------------- */

const HEADING_RE = /^(#{1,4})\s+(.+?)\s*#*\s*$/;
const LIST_ITEM_RE = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/;
const FENCE_RE = /^\s*```/;
const TABLE_DIVIDER_RE = /^[\s|:+-]+$/;

const splitPipeRow = (line: string): string[] =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());

const isTableDivider = (line: string): boolean =>
  line.includes('|') && line.includes('-') && TABLE_DIVIDER_RE.test(line.trim());

/**
 * Block-level markdown parser: narrative content is split into sections at
 * `#` headings; each section body supports paragraphs, lists, fenced code
 * and pipe tables. Inline markup is left as plain text.
 */
export function parseMarkdownSections(content: string): ReportSection[] {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  type Draft = { title: string; blocks: MarkdownBlock[] };
  const sections: ReportSection[] = [];
  let draft: Draft | null = null;
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let codeLines: string[] | null = null;
  let tableLines: string[] | null = null;

  const ensureDraft = (title: string): Draft => {
    if (!draft) draft = { title, blocks: [] };
    return draft;
  };
  const flushParagraph = () => {
    if (draft && paragraph.length > 0) draft.blocks.push({ type: 'paragraph', text: paragraph.join('\n') });
    paragraph = [];
  };
  const flushList = () => {
    if (draft && listItems.length > 0) draft.blocks.push({ type: 'list', items: listItems });
    listItems = [];
  };
  const flushCode = () => {
    if (draft && codeLines) draft.blocks.push({ type: 'code', text: codeLines.join('\n') });
    codeLines = null;
  };
  const flushTable = () => {
    if (draft && tableLines) {
      const cells = tableLines.filter((l) => !isTableDivider(l)).map(splitPipeRow);
      if (cells.length > 0) {
        const columns = cells[0];
        const rows = cells.slice(1).map((r) => {
          const out = r.slice(0, columns.length);
          while (out.length < columns.length) out.push('');
          return out;
        });
        draft.blocks.push({ type: 'table', columns, rows });
      }
    }
    tableLines = null;
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
    flushCode();
    flushTable();
  };
  const pushDraft = () => {
    if (!draft) return;
    sections.push({
      id: `sec-${sections.length}`,
      title: draft.title || `章节 ${sections.length + 1}`,
      kind: 'markdown',
      blocks: draft.blocks,
    });
    draft = null;
  };

  for (const line of lines) {
    if (codeLines !== null) {
      if (FENCE_RE.test(line)) flushCode();
      else codeLines.push(line);
      continue;
    }
    if (FENCE_RE.test(line)) {
      flushAll();
      ensureDraft('概述');
      codeLines = [];
      continue;
    }
    if (tableLines !== null) {
      if (line.includes('|')) {
        if (!isTableDivider(line)) tableLines.push(line);
        continue;
      }
      flushTable();
    }
    const heading = HEADING_RE.exec(line);
    if (heading) {
      flushAll();
      pushDraft();
      draft = { title: heading[2].trim() || `章节 ${sections.length + 1}`, blocks: [] };
      continue;
    }
    if (line.includes('|') && line.trim().length > 2) {
      flushAll();
      ensureDraft('概述');
      tableLines = [line];
      continue;
    }
    const listItem = LIST_ITEM_RE.exec(line);
    if (listItem) {
      flushParagraph();
      ensureDraft('概述');
      listItems.push(listItem[1].trim());
      continue;
    }
    if (line.trim() === '') {
      flushParagraph();
      flushList();
      continue;
    }
    flushList();
    ensureDraft('概述');
    paragraph.push(line.trim());
  }
  flushAll();
  pushDraft();
  return sections;
}

/** Snapshot manifest → one table section per category. */
export function buildManifestSections(manifest: ReportManifest | null): ReportSection[] {
  const cats = manifest?.categories ?? [];
  return cats.map((c, index) => ({
    id: `cat-${index}`,
    title: c.title ?? c.category_id,
    kind: 'table' as const,
    categoryId: c.category_id,
    totalCount: typeof c.count === 'number' ? c.count : undefined,
  }));
}

/* ------------------------- serialization (export) ------------------------- */

export function formatPlainValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

const mdEscape = (s: string): string => s.replace(/\|/g, '\\|').replace(/\n/g, ' ');

export function tableToMarkdown(columns: string[], rows: string[][]): string {
  const header = `| ${columns.map(mdEscape).join(' | ')} |`;
  const divider = `| ${columns.map(() => '---').join(' | ')} |`;
  const body = rows.map((r) => `| ${r.map(mdEscape).join(' | ')} |`);
  return [header, divider, ...body].join('\n');
}

/**
 * Serialize the section model to a full markdown document. Snapshot table
 * sections embed the currently loaded page records.
 */
export function sectionsToMarkdown(sections: ReportSection[], tableData?: CategoryStates): string {
  const out: string[] = ['# 取证报告', ''];
  sections.forEach((section, i) => {
    out.push(`## ${i + 1}. ${section.title}`, '');
    if (section.kind === 'markdown') {
      (section.blocks ?? []).forEach((b) => {
        switch (b.type) {
          case 'paragraph':
            out.push(b.text, '');
            break;
          case 'list':
            b.items.forEach((item) => out.push(`- ${item}`));
            out.push('');
            break;
          case 'code':
            out.push('```', b.text, '```', '');
            break;
          case 'table':
            out.push(tableToMarkdown(b.columns, b.rows), '');
            break;
        }
      });
    } else if (section.categoryId) {
      const state = tableData?.[section.categoryId];
      if (!state || state.records.length === 0) {
        out.push('（暂无记录）', '');
      } else {
        const columns = Object.keys(state.records[0]).slice(0, 8);
        const rows = state.records.map((r) => columns.map((c) => formatPlainValue(r[c])));
        out.push(tableToMarkdown(columns, rows), '');
      }
    }
  });
  return `${out.join('\n').trim()}\n`;
}

/** Structured JSON export payload for either report kind. */
export function buildReportJson(args: {
  reportId: string;
  kind: 'narrative' | 'snapshot';
  narrative?: string | null;
  manifest?: ReportManifest | null;
  sections: ReportSection[];
  tableData?: CategoryStates;
}): Record<string, unknown> {
  const { reportId, kind, narrative, manifest, sections, tableData } = args;
  return {
    report_id: reportId,
    kind,
    exported_at: formatDateTime(Date.now()),
    ...(kind === 'narrative'
      ? { content: narrative ?? '' }
      : { manifest: manifest ?? {}, sections, category_pages: tableData ?? {} }),
  };
}
