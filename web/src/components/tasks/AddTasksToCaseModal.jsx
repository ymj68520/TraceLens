/**
 * AddTasksToCaseModal — reusable modal for associating already-completed tasks
 * to an existing ForensicCase.
 *
 * Supports two entry modes:
 *  - fixedCaseId provided: user picks one or more tasks to add to that case
 *  - fixedTaskId provided:  user picks a target case for that single task
 *  - both:                  direct confirm (rare)
 *
 * Shows a context warning for tasks that already carry file descriptions, since
 * those descriptions were produced against the task's original case context and
 * are reused verbatim by cross-image analysis.
 */
import { useMemo, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Button from '../common/Button';
import Badge from '../common/Badge';
import { associateTasks, fetchCases } from '../../store/caseSlice';
import { fetchTasks } from '../../store/taskSlice';
import { useToast } from '../common/ToastContext';

export default function AddTasksToCaseModal({ fixedCaseId, fixedTaskId, onClose }) {
  const dispatch = useDispatch();
  const { cases } = useSelector((state) => state.cases);
  const { tasks } = useSelector((state) => state.tasks);
  const toast = useToast();

  const [selectedCaseId, setSelectedCaseId] = useState(fixedCaseId || '');
  const [selectedTaskIds, setSelectedTaskIds] = useState(
    fixedTaskId ? new Set([fixedTaskId]) : new Set()
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Candidate tasks: completed with a files.db. When a fixed case is set,
  // exclude tasks already in that case.
  const candidateTasks = useMemo(() => {
    const completed = (tasks || []).filter(
      (t) => t.status === 'completed' && t.output_files_db
    );
    if (!selectedCaseId) return completed;
    const target = cases.find((c) => c.id === selectedCaseId);
    const existing = new Set(target?.task_ids || []);
    return completed.filter((t) => !existing.has(t.id));
  }, [tasks, selectedCaseId, cases]);

  // Whether a candidate task already has LLM descriptions (heuristic: presence
  // of an analyzed marker). We don't have a per-task flag, so we treat all
  // completed tasks with output_files_db as "potentially analyzed" and show the
  // context warning — it's conservative and never wrong.
  const toggleTask = (taskId) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      next.has(taskId) ? next.delete(taskId) : next.add(taskId);
      return next;
    });

  const canSubmit = selectedCaseId && selectedTaskIds.size > 0 && !submitting;

  const handleSubmit = async () => {
    setError('');
    setSubmitting(true);
    try {
      const result = await dispatch(
        associateTasks({ caseId: selectedCaseId, taskIds: [...selectedTaskIds] })
      ).unwrap();

      const a = result.associated?.length || 0;
      const reused = result.reused?.length || 0;
      const pending = result.pending_analysis?.length || 0;
      const skipped = result.skipped?.length || 0;

      if (a > 0) {
        toast.success(
          `已添加 ${a} 个任务` +
          (reused > 0 ? `（${reused} 个复用既有分析、${pending} 个待分析）` : '')
        );
      } else if (skipped > 0) {
        toast.info('所选任务已在该案件中，无需重复添加');
      } else {
        toast.warning('没有任务被添加，请检查任务是否已完成分析');
      }
      if (result.not_completed?.length) {
        toast.warning(`${result.not_completed.length} 个任务尚未完成分析，已忽略`);
      }

      // Refresh both lists; if the case was completed, the new tasks warrant a
      // fresh cross-image run, so the user re-triggers it from the case card.
      dispatch(fetchCases());
      dispatch(fetchTasks({ status: 'all', priority: 'all' }));
      onClose();
    } catch (err) {
      setError(err?.message || '添加失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
            {fixedCaseId ? '➕ 添加任务到案件' : '📂 加入案件'}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-500">✕</button>
        </div>

        <div className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 rounded-xl">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* Case selector — only when not fixed */}
          {!fixedCaseId && (
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                目标案件 *
              </label>
              {cases.length === 0 ? (
                <p className="text-xs text-slate-400">暂无案件，请先在「Cases」页创建案件。</p>
              ) : (
                <select
                  value={selectedCaseId}
                  onChange={(e) => setSelectedCaseId(e.target.value)}
                  disabled={submitting}
                  className={inputCls}
                >
                  <option value="">— 选择案件 —</option>
                  {cases.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}（{(c.task_ids || []).length} 个镜像）
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Task selector — only when not fixed to a single task */}
          {!fixedTaskId && (
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                选择已完成的任务 * <span className="text-xs text-slate-400">（仅显示已分析完成的镜像）</span>
              </label>
              <div className="space-y-1 max-h-60 overflow-y-auto pr-1">
                {candidateTasks.length === 0 ? (
                  <p className="text-xs text-slate-400 py-4 text-center">
                    {selectedCaseId ? '没有可添加的已完成任务（或已全部在本案件中）' : '暂无已完成的任务'}
                  </p>
                ) : (
                  candidateTasks.map((t) => {
                    const checked = selectedTaskIds.has(t.id);
                    return (
                      <label key={t.id}
                        className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-colors ${checked ? 'border-primary-400 bg-primary-50 dark:bg-primary-900/20' : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/40'}`}>
                        <input type="checkbox" checked={checked}
                          onChange={() => toggleTask(t.id)}
                          className="rounded border-slate-300 text-primary-600 focus:ring-primary-500" />
                        <span className="font-mono text-[11px] text-slate-400">{t.id.substring(0, 6)}</span>
                        <span className="text-xs text-slate-700 dark:text-slate-300 truncate flex-1" title={t.image_path}>
                          {t.image_path?.split('/').pop() || t.id}
                        </span>
                        <Badge variant="green">已完成</Badge>
                      </label>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {/* Context warning — reuse is not case-scoped */}
          {selectedTaskIds.size > 0 && (
            <div className="flex items-start gap-2 p-2 bg-amber-50 dark:bg-amber-900/20 rounded-lg">
              <span className="text-amber-600 text-sm">⚠️</span>
              <span className="text-[11px] text-amber-700 dark:text-amber-300 leading-relaxed">
                被复用任务的 AI 分析结论是基于其<strong>原始案情</strong>生成的，加入本案件后将原样纳入跨镜像分析。如本案件案情差异较大，建议在研判报告中重新筛选相关文件。
              </span>
            </div>
          )}
        </div>

        <div className="flex justify-end space-x-3 px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex-shrink-0">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>取消</Button>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? '添加中...' : `添加 ${selectedTaskIds.size || ''} 个任务`.trim()}
          </Button>
        </div>
      </div>
    </div>
  );
}

const inputCls = 'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';
