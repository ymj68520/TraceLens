import { useCallback, useEffect, useState } from 'react';
import { Camera, FlaskConical, Check, X } from 'lucide-react';
import {
  getInvestigationSnapshot,
  listInvestigationAnalyses,
  reviewSecondaryAnalysis,
  pollAnalysisJob,
  startEvidenceAnalysis,
} from '../../services/investigationService';
import Button from '../ui/Button';
import EmptyState from '../ui/EmptyState';
import { LoadingBlock } from '../ui/Spinner';
import { useToast } from '../ui/Toast';
import { errorMessage, formatDateTime } from '../../lib/utils';

interface AnalysisRow {
  analysis_id: string;
  version?: number;
  status?: string;
  created_at?: string;
  summary?: string;
  [key: string]: unknown;
}

interface EvidenceDetailPanelProps {
  taskId: string;
  evidenceKey: string | null;
  onCapture: (key: string) => Promise<void>;
  onChanged: () => void;
}

export default function EvidenceDetailPanel({ taskId, evidenceKey, onCapture, onChanged }: EvidenceDetailPanelProps) {
  const toast = useToast();
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [analyses, setAnalyses] = useState<AnalysisRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    if (!evidenceKey) return;
    setLoading(true);
    setSnapshot(null);
    setAnalyses([]);
    try {
      const [snap, ana] = await Promise.all([
        getInvestigationSnapshot(taskId, evidenceKey).catch(() => null),
        listInvestigationAnalyses(taskId, evidenceKey).catch(() => null),
      ]);
      setSnapshot(snap as Record<string, unknown> | null);
      const list = ana as { analyses?: AnalysisRow[] } | AnalysisRow[] | null;
      setAnalyses(Array.isArray(list) ? list : (list?.analyses ?? []));
    } finally {
      setLoading(false);
    }
  }, [taskId, evidenceKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAnalyze = async () => {
    if (!evidenceKey) return;
    setAnalyzing(true);
    try {
      const admission = (await startEvidenceAnalysis(taskId, {
        evidence_key: evidenceKey,
        analyst_note: note || null,
      })) as { job_id?: string };
      if (admission?.job_id) {
        await pollAnalysisJob(taskId, admission.job_id);
      }
      toast.success('二次分析完成');
      setNote('');
      await load();
      onChanged();
    } catch (err) {
      toast.error(`二次分析失败：${errorMessage(err)}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleReview = async (analysisId: string, decision: 'accept' | 'reject') => {
    try {
      await reviewSecondaryAnalysis(taskId, analysisId, {
        decision,
        reviewer: localStorage.getItem('auth_user') || 'analyst',
      });
      toast.success(decision === 'accept' ? '已采纳' : '已拒绝');
      await load();
      onChanged();
    } catch (err) {
      toast.error(`操作失败：${errorMessage(err)}`);
    }
  };

  return (
    <div className="card min-h-[300px]">
      <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
        <h3 className="card-title">证据详情</h3>
        {evidenceKey && (
          <Button size="sm" variant="ghost" onClick={() => void onCapture(evidenceKey)}>
            <Camera size={13} /> 重新捕获快照
          </Button>
        )}
      </div>

      {!evidenceKey ? (
        <EmptyState title="选择一条证据查看详情" />
      ) : loading ? (
        <LoadingBlock />
      ) : (
        <div className="p-4 space-y-4">
          <p className="text-2xs font-mono text-ink-500 break-all">{evidenceKey}</p>

          {snapshot ? (
            <pre className="code-block max-h-56 overflow-auto text-2xs">
              {JSON.stringify(snapshot, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-ink-400">尚未捕获快照。点击右上角「重新捕获快照」。</p>
          )}

          <div>
            <h4 className="text-xs font-semibold text-ink-700 dark:text-ink-300 mb-2">二次分析版本</h4>
            {analyses.length === 0 ? (
              <p className="text-2xs text-ink-400">暂无分析版本</p>
            ) : (
              <ul className="space-y-2">
                {analyses.map((a) => (
                  <li key={a.analysis_id} className="border border-ink-200 dark:border-ink-700 rounded-md p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-2xs font-mono text-ink-500">
                        {a.analysis_id.substring(0, 12)}… · v{a.version ?? '?'} · {a.status ?? 'unknown'}
                      </span>
                      <span className="flex gap-1">
                        <button
                          type="button"
                          className="p-1 rounded text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10"
                          title="采纳"
                          onClick={() => void handleReview(a.analysis_id, 'accept')}
                        >
                          <Check size={13} />
                        </button>
                        <button
                          type="button"
                          className="p-1 rounded text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10"
                          title="拒绝"
                          onClick={() => void handleReview(a.analysis_id, 'reject')}
                        >
                          <X size={13} />
                        </button>
                      </span>
                    </div>
                    {a.summary && (
                      <p className="mt-1 text-2xs text-ink-500 line-clamp-3">{a.summary}</p>
                    )}
                    <p className="text-2xs text-ink-400 mt-1">{formatDateTime(a.created_at)}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-ink-100 dark:border-ink-800 pt-3 space-y-2">
            <textarea
              rows={2}
              className="input text-xs resize-y"
              placeholder="分析员备注（可选）…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <Button variant="primary" size="sm" onClick={() => void handleAnalyze()} disabled={analyzing}>
              <FlaskConical size={13} />
              {analyzing ? '分析中…' : '发起二次分析'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
