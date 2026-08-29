import { useMemo, useState, type FormEvent } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { createCaseWithTasks, fetchCases } from '../../store/caseSlice';
import { fetchTasks } from '../../store/taskSlice';
import { useToast } from '../ui/Toast';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import { basename, errorMessage } from '../../lib/utils';

interface ComposeCaseModalProps {
  preselectedTaskIds?: string[];
  onClose: () => void;
}

/**
 * Compose a case from one or more already-analyzed tasks. No new scans are
 * launched; the thunk creates the case with imagePaths=[] and associates the
 * selected tasks, so existing analysis is reused as-is.
 */
export default function ComposeCaseModal({ preselectedTaskIds = [], onClose }: ComposeCaseModalProps) {
  const dispatch = useAppDispatch();
  const { tasks } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set(preselectedTaskIds));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const candidateTasks = useMemo(
    () =>
      (tasks || []).filter(
        (t) => t.status === 'completed' && (t as { output_files_db?: string }).output_files_db,
      ),
    [tasks],
  );

  const toggleTask = (taskId: string) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const canSubmit = name.trim() && description.trim() && selectedTaskIds.size > 0 && !submitting;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (!canSubmit) {
      if (selectedTaskIds.size === 0) setError('请至少选择一个已完成的镜像任务');
      return;
    }
    setSubmitting(true);
    try {
      await dispatch(
        createCaseWithTasks({
          name: name.trim(),
          description: description.trim(),
          imagePaths: [],
          associateTaskIds: [...selectedTaskIds],
        }),
      ).unwrap();
      toast.success(`案件「${name.trim()}」已创建，复用 ${selectedTaskIds.size} 个镜像的既有分析`);
      void dispatch(fetchCases());
      void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
      onClose();
    } catch (err) {
      setError(errorMessage(err) || '组案失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="从已有任务组建案件" width="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <p className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-3 py-2 rounded-md">
            {error}
          </p>
        )}

        <div>
          <label className="field-label" htmlFor="compose-name">案件名称 *</label>
          <input
            id="compose-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input"
            placeholder="例如：XX 专案"
            required
          />
        </div>

        <div>
          <label className="field-label" htmlFor="compose-desc">案情描述 *</label>
          <textarea
            id="compose-desc"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="input resize-y"
            placeholder="案件背景说明…"
            required
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="field-label mb-0">选择镜像任务（{selectedTaskIds.size} 已选）</span>
            <span className="space-x-2 text-2xs">
              <button
                type="button"
                className="text-accent-600 dark:text-accent-400 hover:underline"
                onClick={() => setSelectedTaskIds(new Set(candidateTasks.map((t) => t.id)))}
              >
                全选
              </button>
              <button
                type="button"
                className="text-ink-500 hover:underline"
                onClick={() => setSelectedTaskIds(new Set())}
              >
                清空
              </button>
            </span>
          </div>
          {candidateTasks.length === 0 ? (
            <p className="text-xs text-ink-400 py-4 text-center">没有已完成且含文件库的任务</p>
          ) : (
            <ul className="max-h-56 overflow-y-auto border border-ink-200 dark:border-ink-700 rounded-md divide-y divide-ink-100 dark:divide-ink-800">
              {candidateTasks.map((task) => (
                <li key={task.id}>
                  <label className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-900/50">
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
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={submitting}>取消</Button>
          <Button variant="primary" type="submit" disabled={!canSubmit}>
            {submitting ? '创建中…' : '创建案件'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
