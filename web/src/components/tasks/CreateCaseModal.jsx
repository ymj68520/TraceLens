/**
 * CreateCaseModal — form for creating a multi-image ForensicCase.
 *
 * The user provides:
 *  - Case name + description (mandatory)
 *  - One or more new image paths ("+Add Image" button), OR
 *    associating one or more already-completed tasks (skip re-analysis).
 *  - Shared priority + Android analyze flag
 *  LLM analysis is always enabled for new image paths.
 */
import { useMemo, useState } from 'react';
import Button from '../common/Button';
import Badge from '../common/Badge';

const INIT = {
  name:           '',
  description:    '',
  imagePaths:     [''],
  priority:       'normal',
  androidAnalyze: false,
};

export default function CreateCaseModal({ onSubmit, onClose, existingTasks = [] }) {
  const [form, setForm] = useState(INIT);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [associateTaskIds, setAssociateTaskIds] = useState(new Set());

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const setImagePath = (idx, val) =>
    setForm((f) => {
      const paths = [...f.imagePaths];
      paths[idx] = val;
      return { ...f, imagePaths: paths };
    });

  const addImage = () => setForm((f) => ({ ...f, imagePaths: [...f.imagePaths, ''] }));
  const removeImage = (idx) =>
    setForm((f) => ({ ...f, imagePaths: f.imagePaths.filter((_, i) => i !== idx) }));

  // Tasks eligible for direct association: completed with a files.db.
  const associableTasks = useMemo(
    () => (existingTasks || []).filter(
      (t) => t.status === 'completed' && t.output_files_db
    ),
    [existingTasks]
  );

  const toggleAssociate = (taskId) =>
    setAssociateTaskIds((prev) => {
      const next = new Set(prev);
      next.has(taskId) ? next.delete(taskId) : next.add(taskId);
      return next;
    });

  // Valid (trimmed, de-duplicated) new image paths
  const validImagePaths = useMemo(() => {
    const seen = new Set();
    const out = [];
    for (const p of form.imagePaths) {
      const t = (p || '').trim();
      if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
  }, [form.imagePaths]);

  // total images for the submit button label
  const totalImages = validImagePaths.length + associateTaskIds.size;

  const handleSubmit = async (e) => {
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
        ...form,
        imagePaths: validImagePaths,
        associateTaskIds: [...associateTaskIds],
      });
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">新建多镜像案件</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-500">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 rounded-xl">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <Field label="案件名称 *">
            <input type="text" required disabled={isCreating} value={form.name}
              onChange={(e) => set('name', e.target.value)}
              className={inputCls} placeholder="例：某某网络诈骗案" />
          </Field>

          <Field label="案情描述 *" hint="LLM 将根据此描述跨镜像筛选关键文件">
            <textarea required disabled={isCreating} value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={3} className={`${inputCls} resize-none`}
              placeholder="请描述案情背景、涉案行为、需要查找的关键信息..." />
          </Field>

          {/* Image paths */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                新增镜像路径
              </label>
              <button type="button" onClick={addImage}
                className="text-xs text-primary-600 hover:text-primary-700 font-medium">
                ＋ 添加镜像
              </button>
            </div>
            <div className="space-y-2">
              {form.imagePaths.map((p, idx) => {
                const trimmed = (p || '').trim();
                const isEmpty = trimmed === '';
                // a duplicate if this trimmed value appears at an earlier index too
                const firstIdx = form.imagePaths.findIndex((x) => (x || '').trim() === trimmed);
                const isDup = !isEmpty && firstIdx !== idx;
                return (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="text-xs text-slate-400 w-6 flex-shrink-0">#{idx + 1}</span>
                    <input type="text" disabled={isCreating} value={p}
                      onChange={(e) => setImagePath(idx, e.target.value)}
                      className={`${inputCls} flex-1 ${isEmpty || isDup ? 'border-red-400 focus:ring-red-500' : ''}`}
                      placeholder="/path/to/image.E01 or .dd" />
                    {form.imagePaths.length > 1 && (
                      <button type="button" onClick={() => removeImage(idx)}
                        className="text-slate-400 hover:text-red-500 text-sm flex-shrink-0">✕</button>
                    )}
                  </div>
                );
              })}
            </div>
            {form.imagePaths.some((p) => (p || '').trim() === '') && (
              <p className="mt-1 text-xs text-amber-600">空行将被忽略；重复路径会自动去重</p>
            )}
          </div>

          {/* Associate existing tasks */}
          {associableTasks.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                关联已完成任务 <span className="text-xs text-slate-400">（直接复用分析结果，无需重新扫描）</span>
              </label>
              <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
                {associableTasks.map((t) => {
                  const checked = associateTaskIds.has(t.id);
                  return (
                    <label key={t.id}
                      className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-colors ${checked ? 'border-primary-400 bg-primary-50 dark:bg-primary-900/20' : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/40'}`}>
                      <input type="checkbox" checked={checked}
                        onChange={() => toggleAssociate(t.id)}
                        className="rounded border-slate-300 text-primary-600 focus:ring-primary-500" />
                      <span className="font-mono text-[11px] text-slate-400">{t.id.substring(0, 6)}</span>
                      <span className="text-xs text-slate-700 dark:text-slate-300 truncate flex-1" title={t.image_path}>
                        {t.image_path?.split('/').pop() || t.id}
                      </span>
                      <Badge variant="green">已完成</Badge>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          <Field label="优先级">
            <select disabled={isCreating} value={form.priority}
              onChange={(e) => set('priority', e.target.value)} className={inputCls}>
              {['low', 'normal', 'high', 'critical'].map((p) => (
                <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
              ))}
            </select>
          </Field>

          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.androidAnalyze} disabled={isCreating}
              onChange={(e) => set('androidAnalyze', e.target.checked)}
              className="rounded border-slate-300 text-primary-600 focus:ring-primary-500" />
            <span className="text-sm text-slate-700 dark:text-slate-300">启用深度 Android 分析</span>
            <span className="text-xs text-slate-400">（Android 镜像专用）</span>
          </label>

          <div className="flex items-center gap-2 p-2 bg-primary-50 dark:bg-primary-900/20 rounded-lg">
            <span className="text-primary-600 text-sm">🤖</span>
            <span className="text-xs text-primary-700 dark:text-primary-300">
              LLM 智能分析已默认开启，将为每个新镜像创建独立分析任务
            </span>
          </div>
        </form>

        <div className="flex justify-end space-x-3 px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex-shrink-0">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isCreating}>取消</Button>
          <Button type="submit" onClick={handleSubmit} disabled={isCreating || totalImages === 0}>
            {isCreating ? '创建中...' : `创建案件（${totalImages} 个镜像）`}
          </Button>
        </div>
      </div>
    </div>
  );
}

const inputCls = 'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}
