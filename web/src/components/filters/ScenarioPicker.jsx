/**
 * ScenarioPicker
 *
 * Visual card-grid picker for the deterministic classifier's filter profile
 * (the "analysis scenario"). Cards are driven dynamically by the backend
 * profiles list (filterSlice.fetchProfiles); known scenario names get friendly
 * Chinese labels + icons, unknown/custom profiles fall back to a generic card.
 *
 * Selection writes the profile `name` back to the parent (same field the C++
 * FileFilter consumes as task.filter_profile).
 */
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchProfiles } from '../../store/filterSlice';

// Display metadata for the scenarios that ship in config/filter_profiles/.
// The CARD LIST itself is still dynamic (from the backend); this only maps
// known profile names to a friendly presentation.
const SCENARIO_META = {
  general_forensics: { icon: '🔍', label: '综合取证', desc: '通用取证，捕获大部分文件类型，仅排除系统噪声' },
  virus_intrusion: { icon: '🦠', label: '病毒入侵', desc: '可执行文件、启动项、系统配置、可疑脚本' },
  telecom_fraud: { icon: '📞', label: '电信诈骗', desc: '通讯录、短信、通话、即时通讯、资金记录' },
  data_breach: { icon: '🔓', label: '数据泄露', desc: '文档、数据库、归档、邮件、凭证文件' },
};

const DEFAULT_META = { icon: '⚙️', label: null, desc: '' };

/**
 * @param {string}   value    selected profile name (e.g. "general_forensics")
 * @param {(v:string)=>void} onChange called with the selected profile name
 * @param {boolean}  disabled
 */
export default function ScenarioPicker({ value, onChange, disabled }) {
  const dispatch = useDispatch();
  const { profiles, status } = useSelector((s) => s.filter);

  // Load profiles on mount (idempotent — filterSlice guards re-fetch).
  useEffect(() => {
    if (profiles.length === 0 && status === 'idle') {
      dispatch(fetchProfiles());
    }
  }, [dispatch, profiles.length, status]);

  // Build the card list entirely from the backend profiles.
  const cards = profiles.map((p) => {
    const meta = SCENARIO_META[p.name] || { ...DEFAULT_META };
    return {
      name: p.name,
      icon: meta.icon,
      label: meta.label || p.name,
      desc: meta.desc || p.description || '',
    };
  });

  // If the selected value isn't in the list yet (still loading, or a custom
  // profile the backend hasn't returned), synthesize a card so the current
  // choice is always visible and selectable.
  if (value && !cards.some((c) => c.name === value)) {
    const meta = SCENARIO_META[value] || { ...DEFAULT_META };
    cards.push({ name: value, icon: meta.icon, label: meta.label || value, desc: meta.desc });
  }

  const loading = status === 'loading';

  return (
    <div className="space-y-2">
      {loading && cards.length === 0 && (
        <p className="text-xs text-slate-400">加载场景中...</p>
      )}

      {cards.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {cards.map((c) => {
            const selected = c.name === value;
            return (
              <button
                type="button"
                key={c.name}
                disabled={disabled || loading}
                onClick={() => onChange(c.name)}
                className={[
                  'text-left p-3 rounded-xl border transition select-none',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                  selected
                    ? 'border-primary-500 ring-2 ring-primary-500/60 bg-primary-50 dark:bg-primary-900/20'
                    : 'border-slate-300 dark:border-slate-600 hover:border-primary-400 dark:hover:border-primary-500',
                ].join(' ')}
                aria-pressed={selected}
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-lg leading-none">{c.icon}</span>
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {c.label}
                  </span>
                  {selected && (
                    <span className="ml-auto text-primary-600 dark:text-primary-400 text-xs">✓</span>
                  )}
                </div>
                {c.desc && (
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {c.desc}
                  </p>
                )}
                {/* Show the raw backend name when it differs from the friendly label,
                    so custom/unknown profiles are still identifiable. */}
                {c.label !== c.name && (
                  <p className="mt-0.5 text-[10px] text-slate-400 dark:text-slate-500">{c.name}</p>
                )}
              </button>
            );
          })}
        </div>
      )}

      {!loading && cards.length === 0 && (
        <p className="text-xs text-slate-400">
          未能加载场景列表，将以默认（综合取证）启动。可在下方“高级”中手动选择。
        </p>
      )}
    </div>
  );
}
