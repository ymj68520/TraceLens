import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Loader2,
  RotateCcw,
  Search as SearchIcon,
  X,
} from 'lucide-react';
import {
  getIntelligenceReport,
  getIntelligenceRecords,
  searchIntelligenceReport,
  getReportMetadata,
} from '../../services/intelligenceReportService';
import Card from '../ui/Card';
import EmptyState from '../ui/EmptyState';
import { LoadingBlock } from '../ui/Spinner';
import { useToast } from '../ui/Toast';
import { cx } from '../../lib/utils';
import { downloadJSON } from '../../lib/exportUtils';
import {
  buildPlainText,
  buildTocEntries,
  chapterTextFromPage,
  groupMetadataFields,
  isRecordSection,
  KEY_FINDINGS_ANCHOR,
  sectionAnchorId,
  sectionKindLabel,
  type DirectoryNode,
  type PageData,
  type ReportShape,
  type SectionState,
  type TocEntry,
} from './reportModel';
import {
  ChapterText,
  DeviceInfoList,
  KeyFindingsCard,
  MetaList,
  RecordTable,
  SearchHitsPanel,
} from './reportContent';

const SECTION_PAGE_SIZE = 20;
/** scroll-spy 判定线：应用顶栏（3.5rem）下方一点。 */
const SPY_LINE_PX = 96;

/** 折叠章节的正文壳：标题行 + 展开/收起 + 分页与数据态。 */
function RecordSection({ node, state, open, onToggle, onRetry, onPageChange }: {
  node: DirectoryNode;
  state: SectionState | undefined;
  open: boolean;
  onToggle: () => void;
  onRetry: () => void;
  onPageChange: (page: number) => void;
}) {
  const data = state?.data ?? null;
  const total = data?.total ?? 0;
  const totalPages = total > 0 ? Math.max(1, Math.ceil(total / SECTION_PAGE_SIZE)) : 1;
  const chapterText = node.kind === 'chapter' ? chapterTextFromPage(data) : null;
  const kindLabel = sectionKindLabel(node.kind);

  return (
    <Card padded={false} id={sectionAnchorId(node.id)} className="scroll-mt-20">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-4 py-3 text-left"
      >
        {open
          ? <ChevronDown size={15} className="text-ink-400 shrink-0" />
          : <ChevronRight size={15} className="text-ink-400 shrink-0" />}
        <h3 className="card-title">{node.title}</h3>
        {node.stats?.total != null && (
          <span className="text-2xs text-ink-400 tabular-nums">（{node.stats.total}）</span>
        )}
        {state?.loading && <Loader2 size={13} className="text-accent-500 animate-spin" />}
        {kindLabel && (
          <span className="ml-auto text-2xs text-ink-400 dark:text-ink-500">{kindLabel}</span>
        )}
      </button>

      {open && (
        <div className={cx('px-4 pb-4', state?.loading && data && 'opacity-60 pointer-events-none')}>
          {state?.error ? (
            <div className="flex flex-col items-center gap-2 py-6">
              <p className="text-xs text-rose-600 dark:text-rose-400">章节加载失败：{state.error}</p>
              <button type="button" className="btn-secondary btn-sm" onClick={onRetry}>
                <RotateCcw size={13} />
                重试
              </button>
            </div>
          ) : !data ? (
            <LoadingBlock text="正在加载章节内容…" />
          ) : node.kind === 'chapter' ? (
            chapterText ? (
              <ChapterText text={chapterText} />
            ) : (
              <EmptyState title="章节内容为空" description="该章节尚未生成内容。" />
            )
          ) : node.kind === 'device_info' ? (
            <DeviceInfoList pageData={data} />
          ) : data.records && data.records.length > 0 ? (
            <>
              <RecordTable pageData={data} />
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-3 text-xs text-ink-500 dark:text-ink-400">
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    disabled={data.page <= 1}
                    onClick={() => onPageChange(data.page - 1)}
                  >
                    <ChevronLeft size={13} /> 上一页
                  </button>
                  <span className="tabular-nums">{data.page} / {totalPages}</span>
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    disabled={data.page >= totalPages}
                    onClick={() => onPageChange(data.page + 1)}
                  >
                    下一页 <ChevronRight size={13} />
                  </button>
                </div>
              )}
            </>
          ) : (
            <EmptyState title="该分类暂无记录" />
          )}
        </div>
      )}
    </Card>
  );
}

/** 静态章节壳（概览 / 案件信息 / 证据信息）：内容来自报告本体与元数据，无需分页。 */
function StaticSection({ node, children }: { node: DirectoryNode; children: ReactNode }) {
  return (
    <Card id={sectionAnchorId(node.id)} className="scroll-mt-20">
      <h3 className="card-title mb-2">{node.title}</h3>
      {children}
    </Card>
  );
}

/**
 * 历史研判报告阅读器：关键结论卡 + 目录侧栏（scroll-spy）+ 可折叠章节
 * + 搜索 + 导出（JSON / 复制文本）+ 顶部阅读进度条。
 * 数据获取沿用原阅读器的接口：报告与元数据并行加载，章节记录按需分页拉取
 * （AI 研判章节加载报告后即预取，供结论卡与文本导出使用）。
 */
export default function IntelligenceReportReader({ taskId }: { taskId: string }) {
  const [report, setReport] = useState<ReportShape | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown> | null>(null);
  const [loadingReport, setLoadingReport] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [sectionState, setSectionState] = useState<Record<string, SectionState>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState<Record<string, unknown>[] | null>(null);
  const [searching, setSearching] = useState(false);

  const [progress, setProgress] = useState(0);
  const [activeAnchor, setActiveAnchor] = useState<string>(KEY_FINDINGS_ANCHOR);

  const toast = useToast();
  const reqIdsRef = useRef<Record<string, number>>({});

  /* ---------------------- 报告本体 + 案件/证据元数据 ---------------------- */

  useEffect(() => {
    let cancelled = false;
    setLoadingReport(true);
    setError(null);
    setSectionState({});
    setExpanded({});
    setSearchHits(null);
    setSearchQuery('');
    Promise.all([getIntelligenceReport(taskId), getReportMetadata(taskId).catch(() => null)])
      .then(([data, meta]) => {
        if (cancelled) return;
        setReport(data as ReportShape);
        const m = meta as { metadata?: Record<string, unknown> } | null;
        if (m?.metadata) setMetadata(m.metadata);
      })
      .catch((err) => !cancelled && setError((err as Error).message))
      .finally(() => !cancelled && setLoadingReport(false));
    return () => {
      cancelled = true;
    };
  }, [taskId, reloadKey]);

  /* --------------------------- 章节记录分页拉取 --------------------------- */

  const fetchSection = useCallback((nodeId: string, page: number) => {
    if (!report) return;
    const node = (report.directory ?? []).find((n) => n.id === nodeId);
    if (!node || !isRecordSection(node)) return;
    const reqId = (reqIdsRef.current[nodeId] ?? 0) + 1;
    reqIdsRef.current[nodeId] = reqId;
    setSectionState((prev) => ({
      ...prev,
      [nodeId]: { page, data: prev[nodeId]?.data ?? null, loading: true, error: null },
    }));
    getIntelligenceRecords(taskId, nodeId, page, SECTION_PAGE_SIZE)
      .then((data) => {
        if (reqIdsRef.current[nodeId] !== reqId) return;
        setSectionState((prev) => ({
          ...prev,
          [nodeId]: { page, data: data as PageData, loading: false, error: null },
        }));
      })
      .catch((err) => {
        if (reqIdsRef.current[nodeId] !== reqId) return;
        setSectionState((prev) => ({
          ...prev,
          [nodeId]: { page, data: null, loading: false, error: (err as Error).message },
        }));
      });
  }, [report, taskId]);

  // AI 研判章节是报告的核心结论且只有一条 markdown 记录 — 报告加载后即预取；
  // 记录类章节保持折叠，展开时再取。
  useEffect(() => {
    if (!report) return;
    const nodes = report.directory ?? [];
    const defaults: Record<string, boolean> = {};
    nodes.forEach((n) => {
      defaults[n.id] = n.kind === 'chapter';
    });
    setExpanded(defaults);
    nodes.filter((n) => n.kind === 'chapter').forEach((n) => fetchSection(n.id, 1));
  }, [report, fetchSection]);

  const toggleSection = useCallback((node: DirectoryNode) => {
    const willOpen = !(expanded[node.id] ?? false);
    setExpanded((prev) => ({ ...prev, [node.id]: willOpen }));
    if (willOpen) {
      const state = sectionState[node.id];
      if (!state?.data && !state?.loading && !state?.error) fetchSection(node.id, 1);
    }
  }, [expanded, sectionState, fetchSection]);

  const scrollToAnchor = useCallback((anchorId: string) => {
    window.setTimeout(() => {
      document.getElementById(anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
  }, []);

  const openSection = useCallback((nodeId: string) => {
    if (!nodeId) {
      scrollToAnchor(KEY_FINDINGS_ANCHOR);
      return;
    }
    setExpanded((prev) => ({ ...prev, [nodeId]: true }));
    const state = sectionState[nodeId];
    const node = (report?.directory ?? []).find((n) => n.id === nodeId);
    if (node && isRecordSection(node) && !state?.data && !state?.loading && !state?.error) {
      fetchSection(node.id, 1);
    }
    scrollToAnchor(sectionAnchorId(nodeId));
  }, [report, sectionState, fetchSection, scrollToAnchor]);

  const foldableNodes = useMemo(() => (report?.directory ?? []).filter(isRecordSection), [report]);

  const setAllExpanded = (open: boolean) => {
    const next: Record<string, boolean> = {};
    foldableNodes.forEach((n) => {
      next[n.id] = open;
    });
    setExpanded((prev) => ({ ...prev, ...next }));
    if (open) {
      foldableNodes.forEach((n) => {
        const state = sectionState[n.id];
        if (!state?.data && !state?.loading && !state?.error) fetchSection(n.id, 1);
      });
    }
  };

  /* ------------------------------ 报告内搜索 ------------------------------ */

  const runSearch = useCallback(() => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchHits(null);
      return;
    }
    setSearching(true);
    searchIntelligenceReport(taskId, query)
      .then((data) => setSearchHits((data as { hits?: Record<string, unknown>[] }).hits ?? []))
      .catch(() => setSearchHits([]))
      .finally(() => setSearching(false));
  }, [taskId, searchQuery]);

  /* --------------------- 阅读进度条 + 目录 scroll-spy --------------------- */

  const tocEntries = useMemo<TocEntry[]>(() => buildTocEntries(report), [report]);

  useEffect(() => {
    if (!report) return;
    const ids = tocEntries.map((entry) => entry.anchorId);
    let raf = 0;
    const update = () => {
      raf = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const pct = max > 0 ? (window.scrollY / max) * 100 : 0;
      setProgress(Math.min(100, Math.max(0, pct)));
      let current = ids[0] ?? KEY_FINDINGS_ANCHOR;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= SPY_LINE_PX) current = id;
      }
      if (ids.length > 0 && max > 0 && window.scrollY >= max - 4) current = ids[ids.length - 1];
      setActiveAnchor(current);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [report, tocEntries]);

  /* --------------------------- 导出（JSON / 文本） --------------------------- */

  const chapterTexts = useMemo<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    (report?.directory ?? []).forEach((node) => {
      if (node.kind !== 'chapter') return;
      const text = chapterTextFromPage(sectionState[node.id]?.data);
      if (text) out[node.id] = text;
    });
    return out;
  }, [report, sectionState]);

  const chaptersLoading = useMemo(
    () => (report?.directory ?? []).some((n) => n.kind === 'chapter' && sectionState[n.id]?.loading),
    [report, sectionState],
  );

  const metaGroups = useMemo(() => groupMetadataFields(metadata), [metadata]);

  const handleExportJson = () => {
    if (!report) return;
    downloadJSON(
      {
        task_id: taskId,
        exported_at: new Date().toISOString(),
        report,
        case_metadata: metadata,
        chapters: chapterTexts,
      },
      `intelligence-report-${taskId.slice(0, 8)}.json`,
    );
  };

  const handleCopyText = async () => {
    if (!report) return;
    const text = buildPlainText({ taskId, report, meta: metadata, chapterTexts });
    try {
      await navigator.clipboard.writeText(text);
      toast.success('报告文本已复制到剪贴板');
    } catch {
      // 剪贴板 API 不可用（非安全上下文等）时降级为隐藏文本域复制。
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) toast.success('报告文本已复制到剪贴板');
      else toast.error('复制失败，请改用导出 JSON');
    }
  };

  /* -------------------------------- 渲染 -------------------------------- */

  if (loadingReport) return <Card><LoadingBlock text="正在加载研判报告…" /></Card>;
  if (error) {
    return (
      <Card>
        <EmptyState
          title="报告加载失败"
          description={error}
          action={
            <button type="button" className="btn-secondary btn-sm" onClick={() => setReloadKey((k) => k + 1)}>
              <RotateCcw size={13} />
              重试
            </button>
          }
        />
      </Card>
    );
  }
  if (!report) return <Card><EmptyState title="报告不存在" /></Card>;

  const directory = report.directory ?? [];
  const info = report.metadata;

  const renderNode = (node: DirectoryNode) => {
    if (node.kind === 'overview') {
      return (
        <StaticSection key={node.id} node={node}>
          <div className="text-sm text-ink-700 dark:text-ink-300 leading-relaxed whitespace-pre-wrap">
            {typeof report.overview === 'string' && report.overview.trim()
              ? report.overview
              : '本报告由智能研判引擎生成，包含案件信息、证据清单、时间线与 AI 研判章节；展开目录中的章节查看详细内容。'}
          </div>
          {info && (
            <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1 text-xs">
              {info.generated_at && (
                <div className="flex gap-2 py-1 border-b border-ink-100 dark:border-ink-800/60">
                  <dt className="w-24 shrink-0 text-ink-400 dark:text-ink-500">生成时间</dt>
                  <dd className="text-ink-800 dark:text-ink-200">{String(info.generated_at)}</dd>
                </div>
              )}
              {info.platforms?.length ? (
                <div className="flex gap-2 py-1 border-b border-ink-100 dark:border-ink-800/60">
                  <dt className="w-24 shrink-0 text-ink-400 dark:text-ink-500">检测平台</dt>
                  <dd className="text-ink-800 dark:text-ink-200">{info.platforms.join('、')}</dd>
                </div>
              ) : null}
              {info.image_path ? (
                <div className="flex gap-2 py-1 border-b border-ink-100 dark:border-ink-800/60 sm:col-span-2">
                  <dt className="w-24 shrink-0 text-ink-400 dark:text-ink-500">镜像路径</dt>
                  <dd className="min-w-0 flex-1 break-all font-mono text-ink-800 dark:text-ink-200">{String(info.image_path)}</dd>
                </div>
              ) : null}
            </dl>
          )}
        </StaticSection>
      );
    }
    if (node.kind === 'case' || node.kind === 'evidence_info') {
      const rows = node.kind === 'case' ? metaGroups.caseRows : metaGroups.evidenceRows;
      return (
        <StaticSection key={node.id} node={node}>
          {rows.length > 0 ? (
            <MetaList rows={rows} />
          ) : (
            <EmptyState title={`暂无${node.title}`} className="py-8" />
          )}
        </StaticSection>
      );
    }
    return (
      <RecordSection
        key={node.id}
        node={node}
        state={sectionState[node.id]}
        open={expanded[node.id] ?? false}
        onToggle={() => toggleSection(node)}
        onRetry={() => fetchSection(node.id, sectionState[node.id]?.page ?? 1)}
        onPageChange={(page) => fetchSection(node.id, page)}
      />
    );
  };

  return (
    <div className="space-y-4">
      {/* 阅读进度条 — 吸附在应用顶栏下方，随窗口滚动填充 */}
      <div
        aria-hidden
        className="sticky top-14 z-20 h-[3px] rounded-full bg-ink-200/70 dark:bg-ink-800/70 overflow-hidden"
      >
        <div className="h-full rounded-full bg-accent-500" style={{ width: `${progress}%` }} />
      </div>

      {/* 工具栏：报告内搜索 + 导出 */}
      <Card padded={false} className="px-4 py-2.5 flex flex-wrap items-center gap-2">
        <SearchIcon size={14} className="text-ink-400 shrink-0" />
        <input
          type="text"
          className="flex-1 min-w-[8rem] bg-transparent text-sm focus:outline-none"
          placeholder="在报告内搜索…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runSearch()}
        />
        {searchHits !== null && (
          <button
            type="button"
            onClick={() => {
              setSearchHits(null);
              setSearchQuery('');
            }}
            className="p-1 text-ink-400 hover:text-ink-600"
            aria-label="清除搜索"
          >
            <X size={14} />
          </button>
        )}
        <button type="button" onClick={runSearch} className="btn-ghost btn-sm" disabled={searching}>
          {searching ? '搜索中…' : '搜索'}
        </button>
        <div className="ml-auto flex items-center gap-1.5">
          <button type="button" className="btn-ghost btn-sm" onClick={() => void handleCopyText()}>
            <Copy size={13} />
            复制文本
          </button>
          <button type="button" className="btn-secondary btn-sm" onClick={handleExportJson}>
            <Download size={13} />
            导出 JSON
          </button>
        </div>
      </Card>

      {searchHits !== null && (
        <SearchHitsPanel
          hits={searchHits}
          directory={directory}
          onJump={openSection}
          onClose={() => {
            setSearchHits(null);
            setSearchQuery('');
          }}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[230px_1fr] gap-4 items-start">
        {/* 目录侧栏：scroll-spy 高亮当前章节 */}
        <Card padded={false} className="hidden lg:block lg:sticky lg:top-[4.5rem] max-h-[calc(100vh-7rem)] overflow-y-auto">
          <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800">
            <h3 className="card-title">报告目录</h3>
          </div>
          <nav className="p-2 space-y-0.5" aria-label="报告目录">
            {tocEntries.map((entry) => {
              const active = activeAnchor === entry.anchorId;
              return (
                <button
                  key={entry.anchorId}
                  type="button"
                  onClick={() => openSection(entry.nodeId)}
                  className={cx(
                    'w-full flex items-center gap-1.5 text-left px-2.5 py-1.5 rounded-md text-xs transition-colors',
                    active
                      ? 'bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300 font-medium'
                      : 'text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
                  )}
                >
                  <span
                    aria-hidden
                    className={cx(
                      'h-1.5 w-1.5 rounded-full shrink-0',
                      active ? 'bg-accent-500' : 'bg-ink-200 dark:bg-ink-700',
                    )}
                  />
                  <span className="truncate">{entry.title}</span>
                  {entry.count != null && (
                    <span className="ml-auto text-2xs text-ink-400 tabular-nums">{entry.count}</span>
                  )}
                </button>
              );
            })}
          </nav>
          {foldableNodes.length > 0 && (
            <div className="px-3 pb-3 flex gap-1.5">
              <button
                type="button"
                className="btn-ghost btn-sm flex-1 justify-center"
                onClick={() => setAllExpanded(true)}
              >
                全部展开
              </button>
              <button
                type="button"
                className="btn-ghost btn-sm flex-1 justify-center"
                onClick={() => setAllExpanded(false)}
              >
                全部收起
              </button>
            </div>
          )}
        </Card>

        {/* 正文：关键结论卡 + 按目录顺序排列的章节 */}
        <div className="space-y-4 min-w-0">
          <section id={KEY_FINDINGS_ANCHOR} className="scroll-mt-20" aria-label="关键结论">
            <KeyFindingsCard
              report={report}
              chapterTexts={chapterTexts}
              loading={chaptersLoading}
              onJump={openSection}
            />
          </section>
          {directory.map(renderNode)}
        </div>
      </div>
    </div>
  );
}
