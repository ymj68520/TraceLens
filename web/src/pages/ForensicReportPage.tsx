import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Copy,
  FileDown,
  FileJson,
  FileText,
  Maximize2,
  Minimize2,
  Plus,
  Printer,
  RefreshCw,
} from 'lucide-react';
import {
  listReportVersions,
  getReportManifest,
  getReportCategoryPage,
} from '../services/reportService';
import {
  generateReport,
  getReportGeneration,
  getNarrativeReport,
} from '../services/reportGenerationService';
import { downloadJSON, downloadText } from '../lib/exportUtils';
import { copyText } from '../components/files/fileUtils';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import ProgressBar from '../components/ui/ProgressBar';
import { SkeletonBlock } from '../components/ui/PageScaffold';
import { useToast } from '../components/ui/Toast';
import { emitAppEvent } from '../lib/appEvents';
import { cx, errorMessage, formatDateTime } from '../lib/utils';
import ReportToc from './report/ReportToc';
import ReportSectionCard from './report/ReportSectionCard';
import GenerateReportModal, {
  type GenerateFormValues,
  type ReportExportFormat,
} from './report/GenerateReportModal';
import {
  buildManifestSections,
  buildReportJson,
  parseMarkdownSections,
  sectionsToMarkdown,
  type CategoryStates,
  type ReportManifest,
  type ReportSection,
} from './report/reportModel';

interface ReportVersionRow {
  report_id: string;
  status?: string;
  created_at?: string;
  report_kind?: string;
  [key: string]: unknown;
}

interface Props {
  scopeType: 'task' | 'case';
  scopeId: string;
}

/**
 * R2 forensic/narrative report surface: version rail + sectioned viewer with
 * a scroll-spy TOC, collapsible section cards, print-friendly layout, and
 * JSON / Markdown exports. Narrative (llm_generation) versions render their
 * markdown as parsed sections; snapshot versions page through categories.
 */
export default function ForensicReportPage({ scopeType, scopeId }: Props) {
  const toast = useToast();
  const [versions, setVersions] = useState<ReportVersionRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ReportManifest | null>(null);
  const [narrative, setNarrative] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const [catStates, setCatStates] = useState<CategoryStates>({});
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState(0);
  const [genModalOpen, setGenModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async (): Promise<ReportVersionRow[]> => {
    try {
      const res = (await listReportVersions(scopeType, scopeId)) as
        | ReportVersionRow[]
        | { versions?: ReportVersionRow[] };
      const list = Array.isArray(res) ? res : (res.versions ?? []);
      setVersions(list);
      setSelectedId((prev) => prev ?? list[0]?.report_id ?? null);
      return list;
    } catch (err) {
      toast.error(`报告版本加载失败：${errorMessage(err)}`);
      return [];
    } finally {
      setLoading(false);
    }
    // toast identity is not stable; keeping it out avoids refresh loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeType, scopeId]);

  useEffect(() => {
    void refresh();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeType, scopeId]);

  // Load the selected version's manifest / narrative.
  useEffect(() => {
    if (!selectedId) {
      setNarrative(null);
      setManifest(null);
      setLoadError(null);
      setContentLoading(false);
      return;
    }
    let cancelled = false;
    setContentLoading(true);
    setLoadError(null);
    const selected = versions.find((v) => v.report_id === selectedId);

    const fail = (err: unknown) => {
      if (cancelled) return;
      const msg = errorMessage(err);
      setLoadError(msg);
      setContentLoading(false);
      toast.error(`报告内容加载失败：${msg}`);
    };

    if (selected?.report_kind === 'llm_generation') {
      getNarrativeReport(scopeId, selectedId)
        .then((res) => {
          if (cancelled) return;
          const r = res as { content?: string; markdown?: string };
          setNarrative(r.content ?? r.markdown ?? JSON.stringify(res, null, 2));
          setManifest(null);
          setContentLoading(false);
        })
        .catch(fail);
    } else {
      getReportManifest(selectedId)
        .then((m) => {
          if (cancelled) return;
          setManifest((m ?? {}) as ReportManifest);
          setNarrative(null);
          setContentLoading(false);
        })
        .catch(fail);
    }
    return () => {
      cancelled = true;
    };
    // toast is intentionally excluded (unstable identity).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, versions, scopeId, retryTick]);

  // Fresh version → reset viewer view state.
  useEffect(() => {
    setCollapsedIds(new Set());
    setActiveSectionId(null);
  }, [selectedId]);

  const narrativeSections = useMemo(
    () => (narrative ? parseMarkdownSections(narrative) : []),
    [narrative],
  );
  const manifestSections = useMemo(() => buildManifestSections(manifest), [manifest]);
  const isNarrative = narrativeSections.length > 0;
  const sections: ReportSection[] = isNarrative ? narrativeSections : manifestSections;

  const fetchCategoryPage = useCallback(
    async (categoryId: string, page: number) => {
      if (!selectedId) return;
      setCatStates((prev) => ({
        ...prev,
        [categoryId]: {
          ...(prev[categoryId] ?? { records: [] }),
          page,
          loading: true,
          error: null,
        },
      }));
      try {
        const d = (await getReportCategoryPage(selectedId, categoryId, page)) as {
          records?: Record<string, unknown>[];
          total?: number;
        };
        setCatStates((prev) => ({
          ...prev,
          [categoryId]: { page, loading: false, error: null, records: d.records ?? [], total: d.total },
        }));
      } catch (err) {
        setCatStates((prev) => ({
          ...prev,
          [categoryId]: { page, loading: false, error: errorMessage(err), records: [] },
        }));
      }
    },
    [selectedId],
  );

  // Snapshot reports: fetch page 1 of every category in parallel.
  useEffect(() => {
    if (manifestSections.length === 0) {
      setCatStates({});
      return;
    }
    manifestSections.forEach((s) => {
      if (s.categoryId) void fetchCategoryPage(s.categoryId, 1);
    });
  }, [manifestSections, fetchCategoryPage]);

  // Scroll-spy: highlight the topmost visible section in the TOC.
  useEffect(() => {
    const rootEl = contentRef.current;
    if (!rootEl || sections.length === 0) return;
    const targets = Array.from(rootEl.querySelectorAll<HTMLElement>('[data-report-section]'));
    if (targets.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) setActiveSectionId(visible[0].target.id);
      },
      { rootMargin: '-90px 0px -62% 0px', threshold: [0, 0.1, 0.25] },
    );
    targets.forEach((t) => observer.observe(t));
    return () => observer.disconnect();
  }, [sections]);

  const scrollToSection = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const toggleSection = (id: string) =>
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const expandAll = () => setCollapsedIds(new Set());
  const collapseAll = () => setCollapsedIds(new Set(sections.map((s) => s.id)));

  // Paper output should contain every section, collapsed or not.
  useEffect(() => {
    const onBeforePrint = () => setCollapsedIds(new Set());
    window.addEventListener('beforeprint', onBeforePrint);
    return () => window.removeEventListener('beforeprint', onBeforePrint);
  }, []);

  const currentKind: 'narrative' | 'snapshot' = isNarrative ? 'narrative' : 'snapshot';
  const tableData = isNarrative ? undefined : catStates;
  const totalRecords = manifestSections.reduce((sum, s) => sum + (s.totalCount ?? 0), 0);

  const handleCopyMarkdown = async () => {
    if (!selectedId) return;
    const md = sectionsToMarkdown(sections, tableData);
    const ok = await copyText(md);
    if (ok) {
      toast.success('报告 Markdown 已复制到剪贴板');
      emitAppEvent({ kind: 'info', title: '已复制报告 Markdown' });
    } else toast.error('复制失败，请手动复制');
  };

  const handleDownloadMarkdown = () => {
    if (!selectedId) return;
    downloadText(
      sectionsToMarkdown(sections, tableData),
      `report-${selectedId.slice(0, 8)}.md`,
      'text/markdown;charset=utf-8',
    );
    toast.success('报告 Markdown 已下载');
    emitAppEvent({ kind: 'info', title: '已导出报告 Markdown', detail: `report-${selectedId.slice(0, 8)}.md` });
  };

  const handleExportJson = () => {
    if (!selectedId) return;
    downloadJSON(
      buildReportJson({
        reportId: selectedId,
        kind: currentKind,
        narrative,
        manifest,
        sections,
        tableData: currentKind === 'snapshot' ? catStates : undefined,
      }),
      `report-${selectedId.slice(0, 8)}.json`,
    );
    toast.success('报告 JSON 已导出');
    emitAppEvent({ kind: 'info', title: '已导出报告 JSON', detail: `report-${selectedId.slice(0, 8)}.json` });
  };

  // Auto-download the freshly generated version in the requested format.
  const exportNewestVersion = async (
    format: ReportExportFormat,
    reportId: string,
    reportKind: string | undefined,
  ) => {
    if (format === 'none') return;
    try {
      if (reportKind === 'llm_generation') {
        const res = (await getNarrativeReport(scopeId, reportId)) as {
          content?: string;
          markdown?: string;
        };
        const text = res.content ?? res.markdown ?? '';
        if (text) {
          if (format === 'markdown') {
            downloadText(text, `report-${reportId.slice(0, 8)}.md`, 'text/markdown;charset=utf-8');
          } else {
            downloadJSON({ report_id: reportId, kind: 'narrative', content: text }, `report-${reportId.slice(0, 8)}.json`);
          }
        }
      } else {
        const m = (await getReportManifest(reportId)) as ReportManifest;
        if (format === 'json') {
          downloadJSON({ report_id: reportId, kind: 'snapshot', manifest: m }, `report-${reportId.slice(0, 8)}.json`);
        } else {
          downloadText(
            sectionsToMarkdown(buildManifestSections(m)),
            `report-${reportId.slice(0, 8)}.md`,
            'text/markdown;charset=utf-8',
          );
        }
      }
      toast.success('新版报告已自动导出');
    } catch {
      toast.info('自动导出失败，可稍后在页面中手动导出');
    }
  };

  const handleGenerate = async ({ requestedBy, format }: GenerateFormValues) => {
    if (scopeType !== 'task') {
      toast.error('报告生成目前仅支持任务范围');
      return;
    }
    setGenerating(true);
    setGenProgress(0);
    try {
      const admission = (await generateReport(scopeId, { requestedBy })) as { generation_id?: string };
      const generationId = admission.generation_id;
      if (!generationId) throw new Error('未返回 generation_id');

      await new Promise<void>((resolve, reject) => {
        pollRef.current = setInterval(async () => {
          try {
            const g = (await getReportGeneration(scopeId, generationId)) as {
              status?: string;
              progress?: number;
              error?: string;
            };
            setGenProgress(Math.min(100, Math.round((g.progress ?? 0) * 100)));
            if (g.status === 'completed') {
              if (pollRef.current) clearInterval(pollRef.current);
              resolve();
            } else if (g.status === 'failed') {
              if (pollRef.current) clearInterval(pollRef.current);
              reject(new Error(g.error || '生成失败'));
            }
          } catch (e) {
            if (pollRef.current) clearInterval(pollRef.current);
            reject(e as Error);
          }
        }, 3000);
      });

      toast.success('报告生成完成');
      const list = await refresh();
      const newest = list[0];
      if (newest) {
        setSelectedId(newest.report_id);
        await exportNewestVersion(format, newest.report_id, newest.report_kind);
      }
      setGenModalOpen(false);
    } catch (err) {
      toast.error(`生成失败：${errorMessage(err)}`);
    } finally {
      setGenerating(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <LoadingBlock text="正在加载报告版本…" />
      </Card>
    );
  }

  const canExport = Boolean(selectedId) && sections.length > 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] gap-4 items-start print:block">
        {/* Version rail */}
        <Card padded={false} className="h-fit lg:sticky lg:top-20 print:hidden">
          <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
            <h3 className="card-title">报告版本</h3>
            {scopeType === 'task' && (
              <Button size="sm" variant="primary" onClick={() => setGenModalOpen(true)} disabled={generating}>
                <Plus size={13} /> {versions.length > 0 ? '重新生成' : '生成'}
              </Button>
            )}
          </div>
          {generating && (
            <div className="px-4 py-3 border-b border-ink-100 dark:border-ink-800">
              <ProgressBar value={genProgress} showLabel />
            </div>
          )}
          {versions.length === 0 ? (
            <EmptyState icon={<FileText size={30} />} title="暂无报告版本" description="点击「生成」创建第一版报告。" />
          ) : (
            <ul className="divide-y divide-ink-100 dark:divide-ink-800">
              {versions.map((v) => (
                <li key={v.report_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(v.report_id)}
                    className={cx(
                      'w-full text-left px-4 py-2.5 transition-colors',
                      selectedId === v.report_id
                        ? 'bg-accent-50 dark:bg-accent-500/10'
                        : 'hover:bg-ink-50 dark:hover:bg-ink-900/50',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-mono text-ink-600 dark:text-ink-300">
                        {v.report_id.substring(0, 12)}…
                      </span>
                      <Badge tone={v.status === 'ready' || v.status === 'completed' ? 'success' : 'warning'}>
                        {v.status ?? 'unknown'}
                      </Badge>
                    </div>
                    <p className="text-2xs text-ink-400 mt-0.5">{formatDateTime(v.created_at)}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Viewer column */}
        <div className="min-w-0 space-y-4">
          {/* Toolbar (hidden on paper) */}
          <Card padded={false} className="print:hidden">
            <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
              <span className="text-2xs text-ink-400 dark:text-ink-500 min-w-0 truncate">
                {selectedId ? (
                  <>
                    报告 <span className="font-mono">{selectedId.slice(0, 12)}…</span>
                  </>
                ) : (
                  '未选择报告版本'
                )}
                {isNarrative && ' · 叙述报告'}
                {!isNarrative && manifestSections.length > 0 && ` · ${manifestSections.length} 个章节`}
              </span>
              <div className="ml-auto flex items-center gap-1.5 flex-wrap">
                <Button size="sm" variant="ghost" onClick={expandAll} disabled={sections.length === 0} title="展开全部章节">
                  <Maximize2 size={13} /> 全部展开
                </Button>
                <Button size="sm" variant="ghost" onClick={collapseAll} disabled={sections.length === 0} title="收起全部章节">
                  <Minimize2 size={13} /> 全部收起
                </Button>
                <span className="w-px h-5 bg-ink-200 dark:bg-ink-700 mx-1" aria-hidden />
                <Button size="sm" variant="ghost" onClick={() => void handleCopyMarkdown()} disabled={!canExport} title="复制全文 Markdown">
                  <Copy size={13} /> 复制 Markdown
                </Button>
                <Button size="sm" variant="ghost" onClick={handleDownloadMarkdown} disabled={!canExport} title="下载 Markdown 文件">
                  <FileDown size={13} /> Markdown
                </Button>
                <Button size="sm" variant="ghost" onClick={handleExportJson} disabled={!canExport} title="导出报告 JSON">
                  <FileJson size={13} /> JSON
                </Button>
                <Button size="sm" variant="ghost" onClick={() => window.print()} title="打印报告">
                  <Printer size={13} /> 打印
                </Button>
              </div>
            </div>
          </Card>

          {/* TOC + sections */}
          <div ref={contentRef} className="grid grid-cols-1 xl:grid-cols-[210px_minmax(0,1fr)] gap-4 items-start print:block">
            <div className="hidden xl:block xl:sticky xl:top-20 print:hidden">
              {sections.length > 0 && (
                <ReportToc sections={sections} activeId={activeSectionId} onSelect={scrollToSection} />
              )}
            </div>

            <div className="min-w-0 space-y-4">
              {manifest && !isNarrative && (
                <Card>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="min-w-0">
                      <p className="section-label">报告 ID</p>
                      <p className="mt-1 text-xs font-mono text-ink-800 dark:text-ink-200 break-all">{selectedId ?? '—'}</p>
                    </div>
                    <div className="min-w-0">
                      <p className="section-label">Schema 版本</p>
                      <p className="mt-1 text-xs font-mono text-ink-800 dark:text-ink-200 break-all">
                        {manifest.schema_version ?? '—'}
                      </p>
                    </div>
                    <div>
                      <p className="section-label">章节数</p>
                      <p className="mt-1 text-xs font-mono tabular-nums text-ink-800 dark:text-ink-200">
                        {manifestSections.length}
                      </p>
                    </div>
                    <div>
                      <p className="section-label">记录总数</p>
                      <p className="mt-1 text-xs font-mono tabular-nums text-ink-800 dark:text-ink-200">
                        {totalRecords.toLocaleString('en-US')}
                      </p>
                    </div>
                  </div>
                </Card>
              )}

              {contentLoading ? (
                <Card>
                  <div className="space-y-2.5">
                    <SkeletonBlock className="h-4 w-1/3" />
                    {Array.from({ length: 6 }).map((_, i) => (
                      <SkeletonBlock key={i} className={cx('h-3', i % 3 === 2 ? 'w-2/5' : 'w-3/4')} />
                    ))}
                  </div>
                </Card>
              ) : loadError ? (
                <Card>
                  <EmptyState
                    icon={<AlertTriangle size={36} />}
                    title="报告内容加载失败"
                    description={loadError}
                    action={
                      <Button variant="secondary" size="sm" onClick={() => setRetryTick((t) => t + 1)}>
                        <RefreshCw size={13} /> 重试
                      </Button>
                    }
                  />
                </Card>
              ) : sections.length === 0 ? (
                <Card>
                  {selectedId ? (
                    <EmptyState
                      icon={<FileText size={36} />}
                      title="该版本暂无内容"
                      description="报告数据尚未生成或为空，可尝试重新生成报告。"
                    />
                  ) : (
                    <EmptyState
                      icon={<FileText size={36} />}
                      title="选择一个报告版本查看内容"
                      description="左侧选择历史版本，或生成一份新的取证报告。"
                    />
                  )}
                </Card>
              ) : (
                sections.map((section, i) => (
                  <ReportSectionCard
                    key={section.id}
                    section={section}
                    index={i}
                    state={section.categoryId ? catStates[section.categoryId] : undefined}
                    collapsed={collapsedIds.has(section.id)}
                    onToggle={() => toggleSection(section.id)}
                    onRetryPage={() => {
                      if (section.categoryId) {
                        void fetchCategoryPage(section.categoryId, catStates[section.categoryId]?.page ?? 1);
                      }
                    }}
                    onPageChange={(p) => {
                      if (section.categoryId) void fetchCategoryPage(section.categoryId, p);
                    }}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {scopeType === 'task' && (
        <GenerateReportModal
          open={genModalOpen}
          scopeLabel={scopeId}
          submitting={generating}
          progress={genProgress}
          onSubmit={(v) => void handleGenerate(v)}
          onClose={() => setGenModalOpen(false)}
        />
      )}
    </div>
  );
}
