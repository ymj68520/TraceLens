function statusText(version) {
  if (version.status === 'generating' || version.status === 'queued') {
    return `${version.status} · ${version.progress ?? 0}%`;
  }
  return version.status;
}

// R2d：同一版本序列里两种 version 必须显式区分——类型来自服务端持久化的
// report_kind 标记（§11），绝不在前端用文件名/manifest 形状猜测。
function kindBadge(version) {
  return version.report_kind === 'llm_generation'
    ? { label: '叙事', testId: 'version-kind-narrative', className: 'text-purple-600 dark:text-purple-400' }
    : { label: '快照', testId: 'version-kind-snapshot', className: 'text-slate-400' };
}

export default function VersionHistory({ versions, selectedVersion, onSelect }) {
  return (
    <fieldset aria-label="版本历史" className="space-y-2">
      <legend className="text-sm font-semibold text-slate-700 dark:text-slate-200">版本历史</legend>
      {versions.map((version) => {
        const kind = kindBadge(version);
        return (
          <label key={version.report_id} className="flex cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input
              type="radio"
              name="report-version"
              aria-label={`版本 ${version.version}`}
              checked={selectedVersion?.report_id === version.report_id}
              onChange={() => onSelect(version)}
            />
            <span>版本 {version.version}</span>
            <span className={`text-[10px] font-semibold ${kind.className}`} data-testid={kind.testId}>
              {kind.label}
            </span>
            <span className="text-xs text-slate-400">{statusText(version)}</span>
          </label>
        );
      })}
    </fieldset>
  );
}
