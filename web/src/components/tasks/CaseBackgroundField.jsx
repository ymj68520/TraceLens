/**
 * 案情背景预设选择器
 *
 * 供「创建任务 / 新建案件 / 组案 / 案情编辑」等入口复用：
 *  - 预设卡片按业务分组展示，点击即把整段背景写入案情描述框
 *  - 选中后仍可自由编辑；文本与预设不一致时自动显示为「自定义」
 *  - 预设若带有推荐的筛选场景/平台，可选地一键套用
 *
 * 组件内部不使用 <select>，避免打乱调用方对表单控件顺序的假设。
 */
import { useId, useState } from 'react';
import {
  PRESET_GROUPS,
  CASE_BACKGROUND_PRESETS,
  getPresetById,
  matchPresetId,
  presetsByGroup,
} from '../../config/caseBackgroundPresets';

/**
 * @param {Object}   props
 * @param {string}   props.value      当前案情描述文本
 * @param {(text:string)=>void} props.onSelect 选中预设时回调（传整段正文）
 * @param {(preset:Object)=>void} [props.onApplyRecommendation]
 *        点击「套用推荐场景」时回调；不传则不显示该按钮
 * @param {boolean}  [props.disabled]
 */
export function CaseBackgroundPresetPicker({ value, onSelect, onApplyRecommendation, disabled = false }) {
  const [open, setOpen] = useState(false);
  const [group, setGroup] = useState(PRESET_GROUPS[0].key);

  const selectedId = matchPresetId(value);
  const selected = getPresetById(selectedId);
  const groups = presetsByGroup();
  const activeGroup = groups.find((g) => g.key === group) || groups[0];

  const handlePick = (preset) => {
    onSelect(preset.background);
    setOpen(false);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {selected ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 text-xs font-medium truncate">
              <span>{selected.icon}</span>
              <span className="truncate">{selected.label}</span>
              <span className="text-primary-500/70 font-normal">预设</span>
            </span>
          ) : (
            <span className="text-xs text-slate-400">未使用预设，可手动输入</span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          disabled={disabled}
          aria-expanded={open}
          className="text-xs text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-medium disabled:opacity-50 flex-shrink-0"
        >
          {open ? '收起预设' : `📚 选择预设背景（${CASE_BACKGROUND_PRESETS.length}）`}
        </button>
      </div>

      {open && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-900/40 overflow-hidden">
          {/* 分组切换 */}
          <div className="flex gap-1 px-2 pt-2 overflow-x-auto custom-scrollbar">
            {groups.map((g) => (
              <button
                key={g.key}
                type="button"
                onClick={() => setGroup(g.key)}
                disabled={disabled}
                aria-pressed={activeGroup.key === g.key}
                className={[
                  'px-2.5 py-1 rounded-lg text-xs whitespace-nowrap transition-colors disabled:opacity-50',
                  activeGroup.key === g.key
                    ? 'bg-white dark:bg-slate-700 text-primary-700 dark:text-primary-300 shadow-sm font-medium'
                    : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200',
                ].join(' ')}
              >
                {g.label}
              </button>
            ))}
          </div>

          {/* 预设卡片 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 p-2 max-h-64 overflow-y-auto">
            {activeGroup.presets.map((p) => {
              const active = p.id === selectedId;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => handlePick(p)}
                  disabled={disabled}
                  aria-pressed={active}
                  className={[
                    'text-left p-2.5 rounded-lg border transition select-none disabled:opacity-50',
                    active
                      ? 'border-primary-500 ring-2 ring-primary-500/50 bg-primary-50 dark:bg-primary-900/20'
                      : 'border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 hover:border-primary-400 dark:hover:border-primary-500',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-base leading-none">{p.icon}</span>
                    <span className="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">
                      {p.label}
                    </span>
                    {active && <span className="ml-auto text-primary-600 dark:text-primary-400 text-xs">✓</span>}
                  </div>
                  <p className="mt-1 text-[11px] leading-snug text-slate-500 dark:text-slate-400 line-clamp-2">
                    {p.summary}
                  </p>
                </button>
              );
            })}
          </div>

          <p className="px-3 pb-2 text-[11px] text-slate-400 dark:text-slate-500">
            选择后可直接在下方修改；改动后自动视为自定义背景。
          </p>
        </div>
      )}

      {/* 选中预设的联动建议 */}
      {selected && (selected.filterProfiles?.length > 0 || selected.scenarios?.length > 0) && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          {selected.filterProfiles?.length > 0 && (
            <span>建议筛选场景：{selected.filterProfiles.join('、')}</span>
          )}
          {selected.scenarios?.length > 0 && (
            <span>建议平台：{selected.scenarios.join('、')}</span>
          )}
          {onApplyRecommendation && (
            <button
              type="button"
              onClick={() => onApplyRecommendation(selected)}
              disabled={disabled}
              className="text-primary-600 dark:text-primary-400 hover:underline font-medium disabled:opacity-50"
            >
              套用到分析场景
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * 案情背景输入字段：标签 + 预设选择器 + 文本框。
 * 保留 textarea 的 placeholder/required 语义，方便各入口按原样替换。
 */
export default function CaseBackgroundField({
  value,
  onChange,
  label = '案情背景',
  hint,
  placeholder = '请描述案情背景、涉案行为、需要查找的关键信息...',
  rows = 4,
  required = false,
  disabled = false,
  onApplyRecommendation,
  id,
}) {
  // 未显式指定 id 时生成一个，保证 label 与 textarea 正确关联。
  const generatedId = useId();
  const textareaId = id || `case-background-${generatedId}`;

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-1">
        <label htmlFor={textareaId} className="block text-sm font-medium text-slate-700 dark:text-slate-300">
          {label}{required ? ' *' : ''}
        </label>
      </div>

      <div className="mb-2">
        <CaseBackgroundPresetPicker
          value={value}
          onSelect={onChange}
          onApplyRecommendation={onApplyRecommendation}
          disabled={disabled}
        />
      </div>

      <textarea
        id={textareaId}
        required={required}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm resize-none"
        placeholder={placeholder}
      />
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}
