import { useMemo, useState } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { associateTasks, fetchCases } from '../../store/caseSlice';
import { fetchTasks } from '../../store/taskSlice';
import { useToast } from '../ui/Toast';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import Badge from '../ui/Badge';
import { basename, errorMessage } from '../../lib/utils';

interface AddTasksToCaseModalProps {
  /** Set when the user picked a case first and is choosing tasks for it. */
  fixedCaseId?: string;
  /** Set when the user picked a task first and is choosing a target case. */
  fixedTaskId?: string;
  onClose: () => void;
}

/**
 * Associate already-completed tasks to a case. The backend pre-populates the
 * reuse state so the next cross-image run skips re-analysis.
 */
export default function AddTasksToCaseModal({ fixedCaseId, fixedTaskId, onClose }: AddTasksToCaseModalProps) {
  const dispatch = useAppDispatch();
  const { cases } = useAppSelector((state) => state.cases);
  const { tasks } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const [selectedCaseId, setSelectedCaseId] = useState(fixedCaseId || '');
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(
    fixedTaskId ? new Set([fixedTaskId]) : new Set(),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const candidateTasks = useMemo(() => {
    const completed = (tasks || []).filter(
      (t) => t.status === 'completed' && (t as { output_files_db?: string }).output_files_db,
    );
    if (!selectedCaseId) return completed;
    const target = cases.find((c) => c.id === selectedCaseId);
    const existing = new Set(target?.task_ids || []);
    return completed.filter((t) => !existing.has(t.id));
  }, [tasks, selectedCaseId, cases]);

  const toggleTask = (taskId: string) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const canSubmit = Boolean(selectedCaseId) && selectedTaskIds.size > 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    try {
      const result = (await dispatch(
        associateTasks({ caseId: selectedCaseId, taskIds: [...selectedTaskIds] }),
      ).unwrap()) as { reused?: unknown[] };
      const reused = result?.reused?.length ?? 0;
      toast.success(`已关联 ${selectedTaskIds.size} 个任务（复用分析 ${reused} 个）`);
      void dispatch(fetchCases());
      void dispatch(fetchTasks({}));
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="关联任务到案件" width="lg">
      <div className="space-y-4">
        {error && (
          <p className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-3 py-2 rounded-md">
            {error}
          </p>
        )}

        {!fixedCaseId && (
          <div>
            <label className="field-label">目标案件</label>
            <select
              className="select"
              value={selectedCaseId}
              onChange={(e) => setSelectedCaseId(e.target.value)}
            >
              <option value="">选择案件…</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}（{c.task_ids?.length ?? 0} 个任务）
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <p className="field-label">选择已完成任务（{selectedTaskIds.size} 已选）</p>
          {candidateTasks.length === 0 ? (
            <p className="text-xs text-ink-400 py-4 text-center">没有可关联的已完成任务</p>
          ) : (
            <ul className="max-h-64 overflow-y-auto border border-ink-200 dark:border-ink-700 rounded-md divide-y divide-ink-100 dark:divide-ink-800">
              {candidateTasks.map((task) => (
                <li key={task.id}>
                  <label className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-900/50">
                    <input
                      type="checkbox"
                      className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                      checked={selectedTaskIds.has(task.id)}
                      onChange={() => toggleTask(task.id)}
                    />
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm text-ink-800 dark:text-ink-200 truncate">
                        {basename(task.image_path)}
                      </span>
                      <span className="block text-2xs font-mono text-ink-400">{task.id}</span>
                    </span>
                    <Badge tone="success">已完成</Badge>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="text-2xs text-ink-500 dark:text-ink-400 leading-relaxed">
          注意：任务的既有文件描述是在其原始案情上下文中生成的，跨镜像分析将原样复用。
        </p>

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={submitting}>取消</Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? '关联中…' : `关联 ${selectedTaskIds.size} 个任务`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
