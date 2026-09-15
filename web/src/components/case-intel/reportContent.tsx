/**
 * 研判报告阅读器的展示子组件：记录表格、章节正文、关键结论卡、搜索结果。
 * 数据字段以 reportModel.ts 建模的实际后端返回为准，缺失即降级为空态。
 */
import { useMemo } from 'react';
import { ChevronRight, FileText, ListChecks } from 'lucide-react';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import EmptyState from '../ui/EmptyState';
import { SkeletonBlock } from '../ui/PageScaffold';
import { cx, formatBytes, formatDateTime } from '../../lib/utils';
import {
  nodeTitleOf,
  pickConfidence,
  summarizeDirectory,
  type DirectoryNode,
  type PageData,
  type ReportShape,
} from './reportModel';

/* ------------------------------ 记录表格 ------------------------------ */

export function RecordTable({ pageData }: { pageData: PageData }) {
  const records = pageData.records ?? [];
  if (records.length === 0) return <EmptyState title="该分类暂无记录" />;
  return (
    <div className="overflow-x-auto border border-ink-200 dark:border-ink-800 rounded-md">
      <table className="table-shell">
        <thead>
          <tr>
            <th className="w-10">#</th>
            <th>路径 / 标题</th>
            <th>类型</th>
            <th>大小</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r, i) => {
            const title = r.path || r.title || r.name || r.file_path || '—';
            const deleted = r.is_deleted === 1 || r.data_state === 'deleted';
            return (
              <tr key={r.id ?? i}>
                <td className="text-ink-400 text-2xs">
                  {(pageData.page - 1) * pageData.page_size + i + 1}
                </td>
                <td className="max-w-md">
                  <p className="text-xs font-medium text-ink-800 dark:text-ink-100 break-all">{title}</p>
                  {r.md5 && <p className="text-2xs text-ink-400 font-mono mt-0.5">md5: {r.md5}</p>}
                  {r.timestamp != null && (
                    <p className="text-2xs text-ink-400 mt-0.5">{formatDateTime(r.timestamp)}</p>
                  )}
                </td>
                <td className="text-xs">{r.category || r.event_type || ''}</td>
                <td className="text-xs font-mono">{formatBytes(Number(r.size ?? r.file_size ?? 0))}</td>
                <td className="space-x-1">
                  <span className={cx('chip', deleted
                    ? 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/20'
                    : 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20')}>
                    {deleted ? '已删除' : '存在'}
                  </span>
                  {(r.scene_relevant === 1 || r.llm_is_relevant === 1) && (
                    <span className="chip bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20">
                      相关
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------------------- 章节正文（轻量渲染） ---------------------------- */

interface ChapterBlock {
  type: 'heading' | 'item' | 'para';
  text: string;
  level: number;
}

function parseChapterBlocks(text: string): ChapterBlock[] {
  return text
    .split('\n')
    .map((rawLine) => {
      const line = rawLine.trimEnd();
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) return { type: 'heading' as const, text: heading[2].trim(), level: heading[1].length };
      const item = line.match(/^\s*(?:[-*•]|\d+[.、)])\s+(.*)$/);
      if (item) return { type: 'item' as const, text: item[1].trim(), level: 0 };
      return { type: 'para' as const, text: line.trim(), level: 0 };
    })
    .filter((block) => block.text.length > 0);
}

/** AI 研判章节正文：识别标题与列表行的轻量排版，不引入 markdown 依赖。 */
export function ChapterText({ text }: { text: string }) {
  const blocks = useMemo(() => parseChapterBlocks(text), [text]);
  if (blocks.length === 0) return <EmptyState title="章节内容为空" />;
  return (
    <div className="space-y-2 text-sm leading-relaxed text-ink-700 dark:text-ink-300">
      {blocks.map((block, i) =>
        block.type === 'heading' ? (
          <p
            key={i}
            className={cx(
              'font-semibold text-ink-900 dark:text-ink-100',
              block.level <= 2 ? 'text-[15px] mt-4' : 'mt-3',
            )}
          >
            {block.text}
          </p>
        ) : block.type === 'item' ? (
          <p key={i} className="flex gap-2 pl-1">
            <span aria-hidden className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-accent-500" />
            <span className="whitespace-pre-wrap">{block.text}</span>
          </p>
        ) : (
          <p key={i} className="whitespace-pre-wrap">{block.text}</p>
        ),
      )}
    </div>
  );
}

/* ------------------------------- 键值元数据 ------------------------------- */

export function MetaList({ rows, className }: { rows: [string, string][]; className?: string }) {
  if (rows.length === 0) return null;
  return (
    <dl className={cx('grid grid-cols-1 sm:grid-cols-2 gap-x-8 text-xs', className)}>
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-2 py-1.5 border-b border-ink-100 dark:border-ink-800/60">
          <dt className="w-24 shrink-0 text-ink-400 dark:text-ink-500">{label}</dt>
          <dd className="min-w-0 flex-1 break-all text-ink-800 dark:text-ink-200">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** device_info 章节：单条「中文标签 → 值」合成记录。 */
export function DeviceInfoList({ pageData }: { pageData: PageData }) {
  const rows = useMemo<[string, string][]>(() => {
    const record = pageData.records?.[0];
    if (!record) return [];
    return Object.entries(record)
      .filter(([key]) => !key.startsWith('_'))
      .map(([key, value]) => [key, value == null ? '' : String(value).trim()] as [string, string])
      .filter(([, value]) => value.length > 0);
  }, [pageData]);
  if (rows.length === 0) return <EmptyState title="暂无设备信息" />;
  return <MetaList rows={rows} />;
}

/* ------------------------------- 关键结论卡 ------------------------------- */

const EXCERPT_CHARS = 180;

function excerptOf(text: string): string {
  const joined = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 3)
    .join(' ');
  return joined.length > EXCERPT_CHARS ? `${joined.slice(0, EXCERPT_CHARS - 1)}…` : joined;
}

function FindingExcerpt({ label, nodeId, text, onJump }: {
  label: string;
  nodeId: string;
  text: string;
  onJump: (nodeId: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onJump(nodeId)}
      className="block w-full text-left rounded-lg border border-ink-100 dark:border-ink-800 bg-ink-50/60 dark:bg-ink-900/60 px-3.5 py-3 hover:border-accent-300 dark:hover:border-accent-500/30 transition-colors"
    >
      <p className="text-2xs font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500">{label}</p>
      <p className="mt-1 text-xs leading-relaxed text-ink-700 dark:text-ink-300">{excerptOf(text)}</p>
      <p className="mt-1.5 inline-flex items-center gap-0.5 text-2xs text-accent-600 dark:text-accent-400">
        查看章节 <ChevronRight size={11} />
      </p>
    </button>
  );
}

/**
 * 关键结论卡：徽章与摘录全部来自实际返回字段 —
 * 结论状态来自 analysis.conclusion / analysis.findings 章节是否生成，
 * 置信度仅在后端返回约定键名时展示，统计来自 directory 的 stats。
 */
export function KeyFindingsCard({ report, chapterTexts, loading, onJump }: {
  report: ReportShape;
  chapterTexts: Record<string, string>;
  loading: boolean;
  onJump: (nodeId: string) => void;
}) {
  const summary = summarizeDirectory(report.directory);
  const info = report.metadata;
  const generatedAt = info?.generated_at ? formatDateTime(info.generated_at) : null;
  const platforms = info?.platforms?.length ? info.platforms : null;
  const confidence = pickConfidence(
    report as Record<string, unknown>,
    info as Record<string, unknown> | null,
  );

  const conclusionNode = summary.chapterNodes.find((n) => n.id === 'analysis.conclusion') ?? null;
  const findingsNode = summary.chapterNodes.find((n) => n.id === 'analysis.findings') ?? null;
  const conclusionText = conclusionNode ? chapterTexts[conclusionNode.id] ?? null : null;
  const findingsText = findingsNode ? chapterTexts[findingsNode.id] ?? null : null;
  const hasChapters = summary.chapterNodes.length > 0;

  return (
    <Card className="border-accent-200/70 dark:border-accent-500/20">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-accent-100 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300">
          <ListChecks size={14} />
        </span>
        <h3 className="card-title">关键结论</h3>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {confidence != null && <Badge tone="warning">置信度 {Math.round(confidence)}%</Badge>}
          <Badge tone={conclusionText ? 'success' : 'neutral'} dot>
            结论与建议{conclusionText ? '已生成' : '未生成'}
          </Badge>
          <Badge tone={findingsText ? 'accent' : 'neutral'} dot>
            关键发现{findingsText ? '已生成' : '未生成'}
          </Badge>
        </div>
      </div>

      {loading ? (
        <div className="mt-3 space-y-2" aria-label="加载中">
          <SkeletonBlock className="h-3 w-3/4" />
          <SkeletonBlock className="h-3 w-full" />
          <SkeletonBlock className="h-3 w-5/6" />
        </div>
      ) : findingsText || conclusionText ? (
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
          {findingsText && findingsNode && (
            <FindingExcerpt label="关键发现" nodeId={findingsNode.id} text={findingsText} onJump={onJump} />
          )}
          {conclusionText && conclusionNode && (
            <FindingExcerpt label="结论与建议" nodeId={conclusionNode.id} text={conclusionText} onJump={onJump} />
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-500 dark:text-ink-400">
          {hasChapters
            ? '研判章节内容为空，以下为结构化证据数据汇总。'
            : '报告尚未生成 AI 研判章节（关键发现 / 结论与建议），以下为结构化证据数据汇总。'}
        </p>
      )}

      <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: '证据记录', value: summary.recordsTotal },
          { label: '已删除', value: summary.deletedTotal },
          { label: 'AI 标记相关', value: summary.relevantTotal },
          { label: '研判章节', value: summary.chapterNodes.length },
        ].map((item) => (
          <div key={item.label} className="rounded-lg border border-ink-100 dark:border-ink-800 px-3 py-2">
            <p className="text-2xs text-ink-400 dark:text-ink-500">{item.label}</p>
            <p className="mt-0.5 text-sm font-semibold text-ink-900 dark:text-ink-100 tabular-nums">
              {item.value.toLocaleString()}
            </p>
          </div>
        ))}
      </div>

      {(generatedAt || platforms) && (
        <p className="mt-3 text-2xs text-ink-400 dark:text-ink-500">
          {generatedAt && <span>生成时间 {generatedAt}</span>}
          {platforms && <span className={generatedAt ? 'ml-3' : ''}>检测平台 {platforms.join(' / ')}</span>}
        </p>
      )}
    </Card>
  );
}

/* ------------------------------- 搜索结果 ------------------------------- */

export function SearchHitsPanel({ hits, directory, onJump, onClose }: {
  hits: Record<string, unknown>[];
  directory: DirectoryNode[] | undefined;
  onJump: (nodeId: string) => void;
  onClose: () => void;
}) {
  return (
    <Card padded={false}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-ink-100 dark:border-ink-800">
        <h3 className="card-title">
          搜索结果
          <span className="ml-1.5 text-2xs font-normal text-ink-400">{hits.length} 条</span>
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="text-2xs text-ink-400 hover:text-ink-600 dark:hover:text-ink-200"
        >
          清除
        </button>
      </div>
      {hits.length === 0 ? (
        <EmptyState title="没有匹配内容" className="py-8" />
      ) : (
        <ul className="divide-y divide-ink-100 dark:divide-ink-800/60">
          {hits.map((hit, i) => {
            const category = String(hit.category ?? '');
            return (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => onJump(category)}
                  className="w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-ink-50 dark:hover:bg-ink-900/60 transition-colors"
                >
                  <FileText size={13} className="text-ink-400 shrink-0" />
                  <span className="min-w-0 flex-1 text-xs text-ink-800 dark:text-ink-200 truncate">
                    {String(hit.title ?? '')}
                  </span>
                  <Badge tone="neutral">{nodeTitleOf(directory, category)}</Badge>
                  <ChevronRight size={13} className="text-ink-300 dark:text-ink-600 shrink-0" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
