/**
 * FilterProfileSelector
 *
 * Dropdown component for selecting a filter profile.
 * Shows profile description and a summary of rules when selected.
 * Provides buttons to view details and create new profiles.
 */
import { useState, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchProfiles, fetchProfileDetail } from '../../store/filterSlice';

export default function FilterProfileSelector({ value, onChange, disabled }) {
  const dispatch = useDispatch();
  const { profiles, profileDetail, status } = useSelector((s) => s.filter);
  const [showRules, setShowRules] = useState(false);

  // Load profiles on mount
  useEffect(() => {
    if (profiles.length === 0 && status === 'idle') {
      dispatch(fetchProfiles());
    }
  }, [dispatch, profiles.length, status]);

  // Load detail when value changes
  useEffect(() => {
    if (value) {
      dispatch(fetchProfileDetail(value));
    }
  }, [dispatch, value]);

  const handleChange = (e) => {
    onChange(e.target.value || '');
  };

  return (
    <div className="space-y-2">
      {/* Selector dropdown */}
      <div className="flex gap-2">
        <select
          value={value}
          onChange={handleChange}
          disabled={disabled || status === 'loading'}
          className={inputCls}
        >
          <option value="">不使用过滤（分析全部文件）</option>
          {profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name} — {p.description}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => dispatch(fetchProfiles())}
          disabled={disabled || status === 'loading'}
          className="px-3 py-2 text-xs bg-slate-100 dark:bg-slate-600 text-slate-600 dark:text-slate-300 rounded-xl hover:bg-slate-200 dark:hover:bg-slate-500 disabled:opacity-50"
          title="刷新列表"
        >
          ↻
        </button>
      </div>

      {/* Profile detail summary */}
      {value && profileDetail && (
        <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-3 text-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-500 dark:text-slate-400">
              📋 {profileDetail.description}
            </span>
            <button
              type="button"
              onClick={() => setShowRules((v) => !v)}
              className="text-primary-600 dark:text-primary-400 hover:underline"
            >
              {showRules ? '收起规则' : '查看规则'}
            </button>
          </div>

          {showRules && <ProfileRulesView profile={profileDetail} />}
        </div>
      )}

      {/* Loading indicator */}
      {status === 'loading' && (
        <p className="text-xs text-slate-400">加载中...</p>
      )}
    </div>
  );
}

// ── Rules display ──────────────────────────────────────────────────────────────

function ProfileRulesView({ profile }) {
  const { include, exclude, combine_mode } = profile;

  const modeLabels = {
    exclude_wins: '排除优先',
    include_wins: '包含优先',
    include_only: '仅包含',
  };

  return (
    <div className="space-y-2 pt-1 border-t border-slate-200 dark:border-slate-600">
      {/* Combine mode */}
      <div className="flex items-center gap-1">
        <span className="text-slate-500 dark:text-slate-400">合并策略:</span>
        <span className="font-medium text-slate-700 dark:text-slate-200">
          {modeLabels[combine_mode] || combine_mode}
        </span>
      </div>

      {/* Include rules */}
      {include && (
        <RuleSection
          title="✅ 包含规则"
          extensions={include.extensions}
          pathPatterns={include.path_patterns}
          filenamePatterns={include.filename_patterns}
          minSize={include.min_size}
          maxSize={include.max_size}
          includeDeleted={include.include_deleted}
          includeAllocated={include.include_allocated}
        />
      )}

      {/* Exclude rules */}
      {exclude && (
        <RuleSection
          title="❌ 排除规则"
          extensions={exclude.extensions}
          pathPatterns={exclude.path_patterns}
          filenamePatterns={exclude.filename_patterns}
        />
      )}
    </div>
  );
}

function RuleSection({
  title,
  extensions,
  pathPatterns,
  filenamePatterns,
  minSize,
  maxSize,
  includeDeleted,
}) {
  const hasRules =
    (extensions && extensions.length > 0) ||
    (pathPatterns && pathPatterns.length > 0) ||
    (filenamePatterns && filenamePatterns.length > 0) ||
    minSize > 0 ||
    maxSize > 0;

  if (!hasRules) return null;

  return (
    <div>
      <p className="font-medium text-slate-600 dark:text-slate-300 mb-1">{title}</p>
      <div className="space-y-1 pl-2">
        {extensions?.length > 0 && (
          <TagList label="扩展名" items={extensions} />
        )}
        {pathPatterns?.length > 0 && (
          <TagList label="路径" items={pathPatterns} />
        )}
        {filenamePatterns?.length > 0 && (
          <TagList label="文件名" items={filenamePatterns} />
        )}
        {(minSize > 0 || maxSize > 0) && (
          <p className="text-slate-500 dark:text-slate-400">
            大小: {minSize > 0 ? formatSize(minSize) : '不限'} ~{' '}
            {maxSize > 0 ? formatSize(maxSize) : '不限'}
          </p>
        )}
        {includeDeleted !== undefined && (
          <p className="text-slate-500 dark:text-slate-400">
            已删除文件: {includeDeleted ? '包含' : '排除'}
          </p>
        )}
      </div>
    </div>
  );
}

function TagList({ label, items }) {
  const maxShow = 6;
  const shown = items.slice(0, maxShow);
  const remaining = items.length - maxShow;

  return (
    <div>
      <span className="text-slate-500 dark:text-slate-400">{label}: </span>
      <span className="text-slate-700 dark:text-slate-200">
        {shown.join(', ')}
        {remaining > 0 && <span className="text-slate-400"> +{remaining} more</span>}
      </span>
    </div>
  );
}

function formatSize(bytes) {
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(0)} GB`;
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(0)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

// ── Shared styles ──────────────────────────────────────────────────────────────

const inputCls =
  'flex-1 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';
