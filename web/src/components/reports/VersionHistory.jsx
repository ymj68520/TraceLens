function statusText(version) {
  if (version.status === 'generating' || version.status === 'queued') {
    return `${version.status} · ${version.progress ?? 0}%`;
  }
  return version.status;
}

export default function VersionHistory({ versions, selectedVersion, onSelect }) {
  return (
    <fieldset aria-label="版本历史" className="space-y-2">
      <legend className="text-sm font-semibold text-slate-700 dark:text-slate-200">版本历史</legend>
      {versions.map((version) => (
        <label key={version.report_id} className="flex cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input
            type="radio"
            name="report-version"
            aria-label={`版本 ${version.version}`}
            checked={selectedVersion?.report_id === version.report_id}
            onChange={() => onSelect(version)}
          />
          <span>版本 {version.version}</span>
          <span className="text-xs text-slate-400">{statusText(version)}</span>
        </label>
      ))}
    </fieldset>
  );
}
