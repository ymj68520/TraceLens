/**
 * CreateTaskModal
 *
 * Simplified task creation form:
 *  - LLM analysis is ALWAYS enabled (no toggle)
 *  - Case description is a required top-level field
 *  - Windows / Linux type checkboxes removed (backend never had this param)
 *  - Android deep analysis kept as optional (backend has dedicated analyzer)
 *  - XFS mode hidden inside collapsible "Advanced" section
 */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { createTask, fetchTasks } from '../../store/taskSlice';
import { closeModal } from '../../store/uiSlice';
import Button from '../common/Button';
import { useToast } from '../common/ToastContext';

const INITIAL_FORM = {
  image_path: '',
  priority: 'normal',
  case_description: '',
  android_analyze: false,
  xfs_mode: 'auto',
  // llm_analyze is always true — NOT a user setting
};

export default function CreateTaskModal() {
  const dispatch = useDispatch();
  const toast = useToast();

  const [form, setForm] = useState(INITIAL_FORM);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsCreating(true);
    try {
      await dispatch(createTask({ ...form, llm_analyze: true, llm_mode: 'smart' })).unwrap();
      dispatch(closeModal());
      setForm(INITIAL_FORM);
      dispatch(fetchTasks({}));
      toast.success('Task created successfully!');
    } catch (err) {
      setError(err?.message || err?.toString() || 'Failed to create task.');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">Create New Task</h2>
          <button onClick={() => dispatch(closeModal())} className="text-slate-400 hover:text-slate-500 dark:hover:text-slate-300">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* Image Path */}
          <Field label="Image Path *">
            <input
              type="text" required disabled={isCreating}
              value={form.image_path}
              onChange={(e) => set('image_path', e.target.value)}
              className={inputCls}
              placeholder="/path/to/disk_image.dd or /path/to/image.E01"
            />
          </Field>

          {/* Case Description — always visible, required for LLM analysis */}
          <Field label="案情描述 *" hint="AI 将根据此描述筛选关键文件并生成分析报告">
            <textarea
              required disabled={isCreating}
              value={form.case_description}
              onChange={(e) => set('case_description', e.target.value)}
              rows={3}
              className={`${inputCls} resize-none`}
              placeholder="请输入案情描述，例如：一起涉嫌网络诈骗案件，嫌疑人使用 Android 手机..."
            />
          </Field>

          {/* Priority */}
          <Field label="Priority">
            <select disabled={isCreating} value={form.priority} onChange={(e) => set('priority', e.target.value)} className={inputCls}>
              {['low', 'normal', 'high', 'critical'].map((p) => (
                <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
              ))}
            </select>
          </Field>

          {/* Android deep analysis */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.android_analyze}
              disabled={isCreating}
              onChange={(e) => set('android_analyze', e.target.checked)}
              className="rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">启用深度 Android 分析</span>
            <span className="text-xs text-slate-400">（仅 Android 镜像需要）</span>
          </label>

          {/* Advanced options */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline"
            >
              {showAdvanced ? '▲ 收起高级选项' : '▼ 高级选项'}
            </button>
            {showAdvanced && (
              <div className="mt-2">
                <Field label="XFS Mode">
                  <select disabled={isCreating} value={form.xfs_mode} onChange={(e) => set('xfs_mode', e.target.value)} className={inputCls}>
                    <option value="auto">Auto（推荐）</option>
                    <option value="native">Native（仅 Linux）</option>
                    <option value="pure">Pure（跨平台）</option>
                  </select>
                </Field>
              </div>
            )}
          </div>

          {/* LLM always-on notice */}
          <div className="flex items-center gap-2 p-2 bg-primary-50 dark:bg-primary-900/20 rounded-lg">
            <span className="text-primary-600 dark:text-primary-400 text-sm">🤖</span>
            <span className="text-xs text-primary-700 dark:text-primary-300">
              LLM 智能分析已默认开启（Smart 模式）
            </span>
          </div>

          {/* Actions */}
          <div className="flex justify-end space-x-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => dispatch(closeModal())} disabled={isCreating}>Cancel</Button>
            <Button type="submit" disabled={isCreating}>{isCreating ? 'Creating...' : 'Create Task'}</Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const inputCls =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}
