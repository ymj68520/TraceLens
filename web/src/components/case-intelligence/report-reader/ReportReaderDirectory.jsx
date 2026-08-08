/**
 * ReportReaderDirectory
 * 参考目录树：概览 / 案件信息 / 文件证据 / 时间线 / 五章研判。
 * 每个节点显示标题与存在/相关/总数等统计。
 */
function Stat({ stats }) {
  if (!stats) return null;
  const parts = [];
  if (typeof stats.total === 'number') parts.push(`共 ${stats.total}`);
  if (typeof stats.deleted === 'number' && stats.deleted > 0) parts.push(`删除 ${stats.deleted}`);
  if (typeof stats.relevant === 'number' && stats.relevant > 0) parts.push(`相关 ${stats.relevant}`);
  if (!parts.length) return null;
  return <span className="ml-1 text-[10px] text-slate-400">（{parts.join(' · ')}）</span>;
}

export default function ReportReaderDirectory({ directory, selectedId, onSelect }) {
  if (!directory?.length) {
    return <p className="px-2 py-3 text-xs text-slate-500">报告目录为空。</p>;
  }
  return (
    <nav aria-label="报告目录" className="mt-3 space-y-0.5">
      {directory.map((node) => {
        const selected = node.id === selectedId;
        return (
          <button
            type="button"
            key={node.id}
            onClick={() => onSelect(node.id)}
            className={[
              'w-full text-left px-2 py-1.5 rounded-lg text-sm transition select-none',
              selected
                ? 'bg-primary-50 text-primary-700 font-semibold dark:bg-primary-900/30 dark:text-primary-300'
                : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
            ].join(' ')}
          >
            <span>{node.title}</span>
            <Stat stats={node.stats} />
          </button>
        );
      })}
    </nav>
  );
}
