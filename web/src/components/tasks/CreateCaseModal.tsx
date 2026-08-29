import { useMemo, useState, type FormEvent } from 'react';
import { Plus, X } from 'lucide-react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import type { ForensicTask } from '../../types/api';
import type { CreateCaseWithTasksArgs } from '../../store/caseSlice';
import { basename } from '../../lib/utils';

interface CreateCaseModalProps {
  onSubmit: (data: CreateCaseWithTasksArgs) => Promise<void>;
  onClose: () => void;
  existingTasks?: ForensicTask[];
}

interface FormState {
  name: string;
  description: string;
  imagePaths: string[];
  priority: string;
  androidAnalyze: boolean;
}

const INIT: FormState = {
  name: '',
  description: '',
  imagePaths: [''],
  priority: 'normal',
  androidAnalyze: false,
};

/** Create a multi-image case: N new image paths and/or M existing completed tasks. */
export default function CreateCaseModal({ onSubmit, onClose, existingTasks = [] }: CreateCaseModalProps) {
  const [form, setForm] = useState<FormState>(INIT);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [associateTaskIds, setAssociateTaskIds] = useState<Set<string>>(new Set());

  const set = <K extends keyof FormState>(key: K, val: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: val }));

  const setImagePath = (idx: number, val: string) =>
    setForm((f) => {
      const paths = [...f.imagePaths];
      paths[idx] = val;
      return { ...f, imagePaths: paths };
    });

  const addImage = () => setForm((f) => ({ ...f, imagePaths: [...f.imagePaths, ''] }));
  const removeImage = (idx: number) =>
    setForm((f) => ({ ...f, imagePaths: f.imagePaths.filter((_, i) => i !== idx) }));

  const associableTasks = useMemo(
    () =>
      (existingTasks || []).filter(
        (t) => t.status === 'completed' && (t as { output_files_db?: string }).output_files_db,
      ),
    [existingTasks],
  );

  const toggleAssociate = (taskId: string) =>
    setAssociateTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const validImagePaths = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const p of form.imagePaths) {
      const trimmed = (p || '').trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        out.push(trimmed);
      }
    }
    return out;
  }, [form.imagePaths]);

  const totalImages = validImagePaths.length + associateTaskIds.size;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (totalImages === 0) {
      setError('请至少填写一个镜像路径，或勾选一个已完成的任务');
      return;
    }
    if (!form.name.trim() || !form.description.trim()) {
      setError('请填写案件名称与案情描述');
      return;
    }
    setIsCreating(true);
    try {
      await onSubmit({
        name: form.name.trim(),
        description: form.description.trim(),
        imagePaths: validImagePaths,
        priority: form.priority,
        androidAnalyze: form.androidAnalyze,
        associateTaskIds: [...associateTaskIds],
      });
    } catch (err) {
      setError((err as Error)?.message || String(err));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="新建案件" width="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <p className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-3 py-2 rounded-md">
            {error}
          </p>
        )}

        <div>
          <label className="field-label" htmlFor="case-name">案件名称 *</label>
          <input
            id="case-name"
            type="text"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            className="input"
            placeholder="例如：XX 专案"
          />
        </div>

        <div>
          <label className="field-label" htmlFor="case-desc">案情描述 *</label>
          <textarea
            id="case-desc"
            rows={3}
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            className="input resize-y"
            placeholder="案件背景说明，将作为跨镜像分析的上下文…"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="field-label mb-0">新镜像路径（每个镜像创建一个任务）</span>
            <button
              type="button"
              onClick={addImage}
              className="text-2xs text-accent-600 dark:text-accent-400 hover:underline inline-flex items-center gap-0.5"
            >
              <Plus size={12} /> 添加镜像
            </button>
          </div>
          <div className="space-y-2">
            {form.imagePaths.map((path, idx) => (
              <div key={idx} className="flex gap-2">
                <input
                  type="text"
                  value={path}
                  onChange={(e) => setImagePath(idx, e.target.value)}
                  className="input font-mono text-xs flex-1"
                  placeholder="/path/to/image.dd"
                />
                {form.imagePaths.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeImage(idx)}
                    className="p-2 text-ink-400 hover:text-rose-500 transition-colors"
                    aria-label="移除该镜像"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {associableTasks.length > 0 && (
          <div>
            <p className="field-label">或关联已完成任务（复用既有分析，{associateTaskIds.size} 已选）</p>
            <ul className="max-h-40 overflow-y-auto border border-ink-200 dark:border-ink-700 rounded-md divide-y divide-ink-100 dark:divide-ink-800">
              {associableTasks.map((task) => (
                <li key={task.id}>
                  <label className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-900/50">
                    <input
                      type="checkbox"
                      className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                      checked={associateTaskIds.has(task.id)}
                      onChange={() => toggleAssociate(task.id)}
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
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field-label" htmlFor="case-priority">任务优先级</label>
            <select
              id="case-priority"
              value={form.priority}
              onChange={(e) => set('priority', e.target.value)}
              className="select"
            >
              <option value="low">低</option>
              <option value="normal">普通</option>
              <option value="high">高</option>
              <option value="critical">紧急</option>
            </select>
          </div>
          <label className="flex items-center gap-2 pt-6 text-sm text-ink-700 dark:text-ink-300">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={form.androidAnalyze}
              onChange={(e) => set('androidAnalyze', e.target.checked)}
            />
            执行安卓专项分析
          </label>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={isCreating}>取消</Button>
          <Button variant="primary" type="submit" disabled={isCreating || totalImages === 0}>
            {isCreating ? '创建中…' : `创建案件（${totalImages} 个镜像）`}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
