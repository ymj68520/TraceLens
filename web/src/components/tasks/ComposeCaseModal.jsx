/**
 * ComposeCaseModal — compose a new ForensicCase from one or more
 * ALREADY-ANALYZED image tasks, reusing their existing analysis.
 *
 * Two modes:
 *  - preselectedTaskIds provided: opened with tasks already chosen (e.g. from
 *    the Tasks-page multi-select). Shows a read-only summary of the selection.
 *  - no preselection: shows a task picker so the user can choose completed
 *    tasks here (e.g. from the Cases-page quick entry).
 *
 * On submit it dispatches createCaseWithTasks with imagePaths=[] and the
 * chosen task IDs as associateTaskIds — the thunk creates the case and
 * pre-populates the reuse state, so no re-analysis happens.
 */
import { useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Button from '../common/Button';
import Badge from '../common/Badge';
import { createCaseWithTasks, fetchCases } from '../../store/caseSlice';
import { fetchTasks } from '../../store/taskSlice';
import { useToast } from '../common/ToastContext';

export default function ComposeCaseModal({ preselectedTaskIds = [], onClose }) {
  const dispatch = useDispatch();
  const { tasks } = useSelector((state) => state.tasks);
  const toast = useToast();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedTaskIds, setSelectedTaskIds] = useState(new Set(preselectedTaskIds));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Candidate tasks for the picker: completed with a files.db.
  const candidateTasks = useMemo(
    () => (tasks || []).filter((t) => t.status === 'completed' && t.output_files_db),
    [tasks]
  );

  const toggleTask = (taskId) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      next.has(taskId) ? next.delete(taskId) : next.add(taskId);
      return next;
    });

  const selectAll = () => setSelectedTaskIds(new Set(candidateTasks.map((t) => t.id)));
  const clearAll = () => setSelectedTaskIds(new Set());

  const selectedCount = selectedTaskIds.size;
  const canSubmit = name.trim() && description.trim() && selectedCount > 0 && !submitting;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!canSubmit) {
      if (!selectedCount) setError('请至少选择一个已完成的镜像任务');
      return;
    }
    setSubmitting(true);
    try {
      await dispatch(createCaseWithTasks({
        name: name.trim(),
        description: description.trim(),
        imagePaths: [],                       // no new scans
        associateTaskIds: [...selectedTaskIds], // reuse existing analysis
      })).unwrap();
      toast.success(`案件「${name.trim()}」已创建，复用 ${selectedCount} 个镜像的既有分析`);
      dispatch(fetchCases());
      dispatch(fetchTasks({ status: 'all', priority: 'all' }));
      onClose();
    } catch (err) {
      setError(err?.message || '组案失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">📂 从已分析镜像组建案件</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-500">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 rounded-xl">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">案件名称 *</label>
            <input type="text" required disabled={submitting} value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputCls} placeholder="例：某某网络诈骗案" />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              案情描述 *
              <span className="text-xs text-slate-400">（用于后续跨镜像研判时定位关键证据）</span>
            </label>
            <textarea required disabled={submitting} value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3} className={`${inputCls} resize-none`}
              placeholder="请描述案情背景、涉案行为、需要查找的关键信息..." />
          </div>

          {/* Task picker — only when no preselection, or always allow editing */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                已分析镜像 * <span className="text-xs text-slate-400">（已选 {selectedCount}）</span>
              </label>
              <div className="flex items-center gap-2 text-xs">
                <button type="button" onClick={selectAll} disabled={submitting}
                  className="text-primary-600 hover:text-primary-700 font-medium">全选</button>
                <button type="button" onClick={clearAll} disabled={submitting}
                  className="text-slate-500 hover:text-slate-700 font-medium">清空</button>
              </div>
            </div>
            <div className="space-y-1 max-h-52 overflow-y-auto pr-1">
              {candidateTasks.length === 0 ? (
                <p className="text-xs text-slate-400 py-4 text-center">暂无已完成的镜像任务</p>
              ) : (
                candidateTasks.map((t) => {
                  const checked = selectedTaskIds.has(t.id);
                  return (
                    <label key={t.id}
                      className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-colors ${checked ? 'border-primary-400 bg-primary-50 dark:bg-primary-900/20' : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/40'}`}>
                      <input type="checkbox" checked={checked} disabled={submitting}
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

          {/* Reuse + context warning */}
          <div className="flex items-start gap-2 p-2 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg">
            <span className="text-emerald-600 text-sm">♻️</span>
            <span className="text-[11px] text-emerald-700 dark:text-emerald-300 leading-relaxed">
              所选镜像的既有 AI 分析将被<strong>原样复用</strong>，组建案件时不会重新扫描或重新分析。
            </span>
          </div>
          <div className="flex items-start gap-2 p-2 bg-amber-50 dark:bg-amber-900/20 rounded-lg">
            <span className="text-amber-600 text-sm">⚠️</span>
            <span className="text-[11px] text-amber-700 dark:text-amber-300 leading-relaxed">
              这些任务的结论是基于其<strong>原始案情</strong>生成的。如本案件案情差异较大，建议建案后在研判报告中重新筛选。
            </span>
          </div>
        </form>

        <div className="flex justify-end space-x-3 px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex-shrink-0">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>取消</Button>
          <Button type="submit" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? '组建中...' : `组建案件（${selectedCount} 个镜像）`}
          </Button>
        </div>
      </div>
    </div>
  );
}

const inputCls = 'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';
