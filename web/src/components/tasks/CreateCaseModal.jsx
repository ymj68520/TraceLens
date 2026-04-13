/**
 * CreateCaseModal — form for creating a multi-image ForensicCase.
 *
 * The user provides:
 *  - Case name + description (mandatory)
 *  - One or more image paths ("+Add Image" button)
 *  - Shared priority + Android analyze flag
 *  LLM analysis is always enabled.
 */
import { useState } from 'react';
import Button from '../common/Button';

const INIT = {
  name:           '',
  description:    '',
  imagePaths:     [''],
  priority:       'normal',
  androidAnalyze: false,
};

export default function CreateCaseModal({ onSubmit, onClose }) {
  const [form, setForm] = useState(INIT);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');

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

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const validPaths = form.imagePaths.map((p) => p.trim()).filter(Boolean);
    if (!validPaths.length) { setError('请至少填写一个镜像路径'); return; }
    setIsCreating(true);
    try {
      await onSubmit({ ...form, imagePaths: validPaths });
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
                镜像路径列表 *
              </label>
              <button type="button" onClick={addImage}
                className="text-xs text-primary-600 hover:text-primary-700 font-medium">
                ＋ 添加镜像
              </button>
            </div>
            <div className="space-y-2">
              {form.imagePaths.map((p, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 w-6 flex-shrink-0">#{idx + 1}</span>
                  <input type="text" disabled={isCreating} value={p}
                    onChange={(e) => setImagePath(idx, e.target.value)}
                    className={`${inputCls} flex-1`}
                    placeholder="/path/to/image.E01 or .dd" />
                  {form.imagePaths.length > 1 && (
                    <button type="button" onClick={() => removeImage(idx)}
                      className="text-slate-400 hover:text-red-500 text-sm flex-shrink-0">✕</button>
                  )}
                </div>
              ))}
            </div>
          </div>

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
              LLM 智能分析已默认开启，将为每个镜像创建独立分析任务
            </span>
          </div>
        </form>

        <div className="flex justify-end space-x-3 px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex-shrink-0">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isCreating}>取消</Button>
          <Button type="submit" onClick={handleSubmit} disabled={isCreating}>
            {isCreating ? '创建中...' : `创建案件（${form.imagePaths.filter(Boolean).length} 个镜像）`}
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
