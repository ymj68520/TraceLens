function DirectoryNode({ node, onSelect }) {
  const children = Array.isArray(node?.children) ? node.children : [];

  if (children.length) {
    return (
      <li>
        <section className="space-y-2">
          <h3 className="px-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {node.title || node.id}
          </h3>
          <ul className="space-y-1 border-l border-slate-200 pl-3 dark:border-slate-700">
            {children.map((child, index) => (
              <DirectoryNode
                key={child.category_id || child.id || `${child.title}-${index}`}
                node={child}
                onSelect={onSelect}
              />
            ))}
          </ul>
        </section>
      </li>
    );
  }

  if (!node?.category_id) return null;

  return (
    <li>
      <button
        type="button"
        aria-label={`打开 ${node.title}`}
        onClick={() => onSelect(node.category_id, 1)}
        className="group w-full rounded-xl border border-transparent px-3 py-2.5 text-left transition hover:border-primary-200 hover:bg-primary-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 dark:hover:border-primary-800 dark:hover:bg-primary-950/30"
      >
        <span className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-sm font-medium text-slate-800 dark:text-slate-100">
            {node.title}
          </span>
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs tabular-nums text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {node.total ?? 0}
          </span>
        </span>
        {(node.deleted > 0 || node.high_risk > 0 || node.relevant > 0) && (
          <span className="mt-1.5 flex flex-wrap gap-1 text-[11px]">
            {node.deleted > 0 && <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">已删除 {node.deleted}</span>}
            {node.high_risk > 0 && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">高风险 {node.high_risk}</span>}
            {node.relevant > 0 && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">重点 {node.relevant}</span>}
          </span>
        )}
      </button>
    </li>
  );
}

export default function ReportDirectory({ directory, onSelect }) {
  const nodes = Array.isArray(directory) ? directory : [];
  if (!nodes.length) {
    return <p className="px-2 py-3 text-sm text-slate-500 dark:text-slate-400">报告目录暂无分类。</p>;
  }

  return (
    <nav aria-label="报告分类" className="mt-4">
      <ul className="space-y-4">
        {nodes.map((node, index) => (
          <DirectoryNode key={node.id || node.category_id || `${node.title}-${index}`} node={node} onSelect={onSelect} />
        ))}
      </ul>
    </nav>
  );
}
