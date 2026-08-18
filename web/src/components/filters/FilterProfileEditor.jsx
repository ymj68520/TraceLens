/**
 * FilterProfileEditor
 *
 * Modal form for creating or editing a filter profile.
 * Supports all FilterCondition fields with tag-style array inputs.
 */
import { useState, useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { saveProfile, fetchProfiles } from '../../store/filterSlice';
import Button from '../common/Button';
import { useToast } from '../common/useToast';

const EMPTY_PROFILE = {
  name: '',
  description: '',
  version: '1.0',
  combine_mode: 'exclude_wins',
  include: {
    extensions: [],
    path_patterns: [],
    filename_patterns: [],
    min_size: 0,
    max_size: 0,
    include_deleted: true,
    include_allocated: true,
  },
  exclude: {
    extensions: [],
    path_patterns: [],
    filename_patterns: [],
  },
};

export default function FilterProfileEditor({ profile, onClose }) {
  const dispatch = useDispatch();
  const toast = useToast();
  const isEdit = !!profile;

  const [form, setForm] = useState(EMPTY_PROFILE);
  const [saving, setSaving] = useState(false);

  // Load existing profile data if editing
  useEffect(() => {
    if (profile) {
      setForm({
        name: profile.name || '',
        description: profile.description || '',
        version: profile.version || '1.0',
        combine_mode: profile.combine_mode || 'exclude_wins',
        include: {
          extensions: profile.include?.extensions || [],
          path_patterns: profile.include?.path_patterns || [],
          filename_patterns: profile.include?.filename_patterns || [],
          min_size: profile.include?.min_size || 0,
          max_size: profile.include?.max_size || 0,
          include_deleted: profile.include?.include_deleted ?? true,
          include_allocated: profile.include?.include_allocated ?? true,
        },
        exclude: {
          extensions: profile.exclude?.extensions || [],
          path_patterns: profile.exclude?.path_patterns || [],
          filename_patterns: profile.exclude?.filename_patterns || [],
        },
      });
    }
  }, [profile]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) {
      toast.error('请输入配置名称');
      return;
    }

    setSaving(true);
    try {
      await dispatch(saveProfile(form)).unwrap();
      await dispatch(fetchProfiles());
      toast.success(isEdit ? '配置已更新' : '配置已创建');
      onClose();
    } catch (err) {
      const msg = typeof err === 'string' ? err : err?.message || '保存失败';
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const setField = (key, val) => setForm((f) => ({ ...f, [key]: val }));
  const setInclude = (key, val) =>
    setForm((f) => ({ ...f, include: { ...f.include, [key]: val } }));
  const setExclude = (key, val) =>
    setForm((f) => ({ ...f, exclude: { ...f.exclude, [key]: val } }));

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
            {isEdit ? '编辑过滤配置' : '创建新过滤配置'}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-500 dark:hover:text-slate-300"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {/* Basic info */}
          <Section title="基本信息">
            <Field label="配置名称 *">
              <input
                type="text"
                required
                disabled={isEdit || saving}
                value={form.name}
                onChange={(e) => setField('name', e.target.value)}
                className={inputCls}
                placeholder="例如: custom_fraud_analysis"
              />
            </Field>
            <Field label="描述">
              <input
                type="text"
                disabled={saving}
                value={form.description}
                onChange={(e) => setField('description', e.target.value)}
                className={inputCls}
                placeholder="简要描述此配置的用途"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="版本">
                <input
                  type="text"
                  disabled={saving}
                  value={form.version}
                  onChange={(e) => setField('version', e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="合并策略">
                <select
                  disabled={saving}
                  value={form.combine_mode}
                  onChange={(e) => setField('combine_mode', e.target.value)}
                  className={inputCls}
                >
                  <option value="exclude_wins">排除优先 (推荐)</option>
                  <option value="include_wins">包含优先</option>
                  <option value="include_only">仅包含</option>
                </select>
              </Field>
            </div>
          </Section>

          {/* Include rules */}
          <Section title="✅ 包含规则">
            <TagInput
              label="文件扩展名"
              value={form.include.extensions}
              onChange={(v) => setInclude('extensions', v)}
              placeholder=".pdf, .doc, .jpg"
              disabled={saving}
            />
            <TagInput
              label="路径匹配模式"
              value={form.include.path_patterns}
              onChange={(v) => setInclude('path_patterns', v)}
              placeholder="*/com.tencent.mm/*"
              disabled={saving}
            />
            <TagInput
              label="文件名匹配模式"
              value={form.include.filename_patterns}
              onChange={(v) => setInclude('filename_patterns', v)}
              placeholder="*.log, contacts*"
              disabled={saving}
            />
            <div className="grid grid-cols-2 gap-3">
              <Field label="最小文件大小 (字节)">
                <input
                  type="number"
                  min="0"
                  disabled={saving}
                  value={form.include.min_size}
                  onChange={(e) => setInclude('min_size', Number(e.target.value))}
                  className={inputCls}
                />
              </Field>
              <Field label="最大文件大小 (字节)">
                <input
                  type="number"
                  min="0"
                  disabled={saving}
                  value={form.include.max_size}
                  onChange={(e) => setInclude('max_size', Number(e.target.value))}
                  className={inputCls}
                  placeholder="0 = 不限"
                />
              </Field>
            </div>
            <div className="flex gap-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.include.include_deleted}
                  disabled={saving}
                  onChange={(e) => setInclude('include_deleted', e.target.checked)}
                  className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm text-slate-700 dark:text-slate-300">包含已删除文件</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.include.include_allocated}
                  disabled={saving}
                  onChange={(e) => setInclude('include_allocated', e.target.checked)}
                  className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm text-slate-700 dark:text-slate-300">包含已分配文件</span>
              </label>
            </div>
          </Section>

          {/* Exclude rules */}
          <Section title="❌ 排除规则">
            <TagInput
              label="文件扩展名"
              value={form.exclude.extensions}
              onChange={(v) => setExclude('extensions', v)}
              placeholder=".tmp, .cache"
              disabled={saving}
            />
            <TagInput
              label="路径匹配模式"
              value={form.exclude.path_patterns}
              onChange={(v) => setExclude('path_patterns', v)}
              placeholder="*/proc/*, */sys/*"
              disabled={saving}
            />
            <TagInput
              label="文件名匹配模式"
              value={form.exclude.filename_patterns}
              onChange={(v) => setExclude('filename_patterns', v)}
              placeholder="*.tmp"
              disabled={saving}
            />
          </Section>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2 border-t border-slate-200 dark:border-slate-700">
            <Button
              type="button"
              variant="secondary"
              onClick={onClose}
              disabled={saving}
            >
              取消
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? '保存中...' : isEdit ? '更新配置' : '创建配置'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h3>
      <div className="space-y-3 pl-1">{children}</div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}

/**
 * TagInput - comma-separated input for array fields.
 * Displays existing items as removable tags.
 */
function TagInput({ label, value = [], onChange, placeholder, disabled }) {
  const [input, setInput] = useState('');

  const addItems = () => {
    const items = input
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s && !value.includes(s));
    if (items.length > 0) {
      onChange([...value, ...items]);
    }
    setInput('');
  };

  const removeItem = (item) => {
    onChange(value.filter((v) => v !== item));
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addItems();
    }
  };

  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
        {label}
      </label>
      {/* Tags */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {value.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 rounded-lg text-xs"
            >
              {item}
              {!disabled && (
                <button
                  type="button"
                  onClick={() => removeItem(item)}
                  className="text-primary-400 hover:text-primary-600 dark:hover:text-primary-200"
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      {/* Input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={addItems}
          disabled={disabled}
          className={inputCls}
          placeholder={placeholder}
        />
      </div>
      <p className="mt-0.5 text-xs text-slate-400">输入后按回车或逗号添加，支持批量粘贴（逗号分隔）</p>
    </div>
  );
}

// ── Shared styles ──────────────────────────────────────────────────────────────

const inputCls =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';
