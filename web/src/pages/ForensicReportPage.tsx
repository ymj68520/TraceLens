import { useCallback, useEffect, useRef, useState } from 'react';
import {
  listReportVersions,
  getReportManifest,
  getReportCategoryPage,
} from '../services/reportService';
import { generateReport, getReportGeneration, getNarrativeReport } from '../services/reportGenerationService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import ProgressBar from '../components/ui/ProgressBar';
import { useToast } from '../components/ui/Toast';
import { errorMessage, formatDateTime } from '../lib/utils';
import { FileText, Plus } from 'lucide-react';

interface ReportVersionRow {
  report_id: string;
  status?: string;
  created_at?: string;
  report_kind?: string;
  [key: string]: unknown;
}

interface ManifestCategory {
  category_id: string;
  title?: string;
  count?: number;
  [key: string]: unknown;
}

interface Manifest {
  report_id?: string;
  schema_version?: string;
  categories?: ManifestCategory[];
  [key: string]: unknown;
}

interface Props {
  scopeType: 'task' | 'case';
  scopeId: string;
}

/**
 * R2 forensic/narrative report surface: version list + create/poll + category
 * paging. Narrative (llm_generation) versions render their markdown; snapshot
 * versions page through categories.
 */
export default function ForensicReportPage({ scopeType, scopeId }: Props) {
  const toast = useToast();
  const [versions, setVersions] = useState<ReportVersionRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageData, setPageData] = useState<{ records?: Record<string, unknown>[]; total?: number } | null>(null);
  const [narrative, setNarrative] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState(0);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = (await listReportVersions(scopeType, scopeId)) as
        | ReportVersionRow[]
        | { versions?: ReportVersionRow[] };
      const list = Array.isArray(res) ? res : (res.versions ?? []);
      setVersions(list);
      if (!selectedId && list.length > 0) setSelectedId(list[0].report_id);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [scopeType, scopeId, selectedId, toast]);

  useEffect(() => {
    void refresh();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeType, scopeId]);

  // Load the selected version's manifest / narrative.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    const selected = versions.find((v) => v.report_id === selectedId);

    if (selected?.report_kind === 'llm_generation') {
      getNarrativeReport(scopeId, selectedId)
        .then((res) => {
          if (cancelled) return;
          const r = res as { content?: string; markdown?: string };
          setNarrative(r.content ?? r.markdown ?? JSON.stringify(res, null, 2));
          setManifest(null);
        })
        .catch(() => !cancelled && setNarrative(null));
      return () => {
        cancelled = true;
      };
    }

    getReportManifest(selectedId)
      .then((m) => {
        if (cancelled) return;
        const mf = m as Manifest;
        setManifest(mf);
        setNarrative(null);
        setCategoryId(mf.categories?.[0]?.category_id ?? null);
        setPage(1);
      })
      .catch(() => !cancelled && setManifest(null));
    return () => {
      cancelled = true;
    };
  }, [selectedId, versions, scopeId]);

  // Category paging.
  useEffect(() => {
    if (!selectedId || !categoryId || narrative !== null) return;
    let cancelled = false;
    getReportCategoryPage(selectedId, categoryId, page)
      .then((d) => !cancelled && setPageData(d as { records?: Record<string, unknown>[]; total?: number }))
      .catch(() => !cancelled && setPageData(null));
    return () => {
      cancelled = true;
    };
  }, [selectedId, categoryId, page, narrative]);

  const handleGenerate = async () => {
    if (scopeType !== 'task') {
      toast.error('报告生成目前仅支持任务范围');
      return;
    }
    setGenerating(true);
    setGenProgress(0);
    try {
      const admission = (await generateReport(scopeId, {})) as { generation_id?: string };
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
            setGenProgress((g.progress ?? 0) * 100);
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
      await refresh();
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

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
      {/* Version list */}
      <Card padded={false} className="h-fit">
        <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
          <h3 className="card-title">报告版本</h3>
          {scopeType === 'task' && (
            <Button size="sm" variant="primary" onClick={handleGenerate} disabled={generating}>
              <Plus size={13} /> {generating ? '生成中' : '生成'}
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
                  className={`w-full text-left px-4 py-2.5 transition-colors ${
                    selectedId === v.report_id
                      ? 'bg-accent-50 dark:bg-accent-500/10'
                      : 'hover:bg-ink-50 dark:hover:bg-ink-900/50'
                  }`}
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

      {/* Viewer */}
      <Card>
        {narrative !== null ? (
          <div className="text-sm text-ink-800 dark:text-ink-200 leading-relaxed whitespace-pre-wrap font-normal">
            {narrative}
          </div>
        ) : manifest ? (
          <>
            <div className="flex flex-wrap gap-1.5 mb-4">
              {(manifest.categories ?? []).map((c) => (
                <button
                  key={c.category_id}
                  type="button"
                  onClick={() => {
                    setCategoryId(c.category_id);
                    setPage(1);
                  }}
                  className={`chip cursor-pointer ${
                    categoryId === c.category_id
                      ? 'bg-accent-600 text-white border border-accent-600'
                      : 'bg-ink-100 text-ink-600 border border-ink-200 dark:bg-ink-800 dark:text-ink-300 dark:border-ink-700'
                  }`}
                >
                  {c.title ?? c.category_id}
                  {c.count != null && ` (${c.count})`}
                </button>
              ))}
            </div>
            {pageData?.records?.length ? (
              <div className="overflow-x-auto border border-ink-200 dark:border-ink-800 rounded-md">
                <table className="table-shell">
                  <thead>
                    <tr>
                      {Object.keys(pageData.records[0]).slice(0, 5).map((k) => (
                        <th key={k}>{k}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pageData.records.map((r, i) => (
                      <tr key={i}>
                        {Object.keys(pageData.records![0]).slice(0, 5).map((k) => (
                          <td key={k} className="text-xs max-w-[220px] truncate">
                            {String(r[k] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="该分类暂无记录" />
            )}
            <div className="flex items-center justify-between mt-4 text-xs text-ink-500">
              <button type="button" className="btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                上一页
              </button>
              <span className="tabular-nums">第 {page} 页</span>
              <button type="button" className="btn-ghost btn-sm" onClick={() => setPage((p) => p + 1)}>
                下一页
              </button>
            </div>
          </>
        ) : (
          <EmptyState title="选择一个报告版本查看内容" />
        )}
      </Card>
    </div>
  );
}
