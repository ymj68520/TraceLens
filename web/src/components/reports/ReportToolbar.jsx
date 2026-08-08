export default function ReportToolbar({
  manifest,
  version,
  generating = null,
  scopeType = 'task',
  onCreateVersion,
  onRefresh,
}) {
  const title = manifest?.title || version?.title || '取证报告';
  const generatedAt = manifest?.generated_at || version?.generated_at;
  const platforms = manifest?.platforms || [];

  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 pb-4 dark:border-slate-700">
      <div className="mr-auto">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{title}</h1>
        {version && <p className="text-sm text-slate-500">版本 {version.version}</p>}
        {generatedAt && <time className="text-xs text-slate-400" dateTime={generatedAt}>{generatedAt}</time>}
      </div>
      {platforms.map((platform) => (
        <span key={platform} className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {platform}
        </span>
      ))}
      {scopeType === 'task' ? (
        <button
          type="button"
          onClick={onCreateVersion}
          disabled={Boolean(generating)}
          title={generating ? '报告正在生成中' : '生成新版本'}
        >
          {generating ? '生成中…' : '生成新版本'}
        </button>
      ) : (
        <span className="text-xs text-slate-500 dark:text-slate-400">暂不支持案情级新版报告</span>
      )}
      <button type="button" onClick={onRefresh}>刷新</button>
      <button type="button" disabled>导出离线 HTML</button>
      <button type="button" disabled>版本历史</button>
    </header>
  );
}
