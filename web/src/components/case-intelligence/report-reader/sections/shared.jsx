/**
 * Shared components for the structured report sections.
 */

export function Field({ label, children, mono = false }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={`break-words text-slate-800 dark:text-slate-100 ${mono ? 'font-mono text-[12px]' : 'text-sm'}`}>
        {children}
      </dd>
    </div>
  );
}

export function SectionCard({ title, total, onEdit, children, action }) {
  return (
    <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-bold text-slate-900 dark:text-white">
          {title}
          {typeof total === 'number' && (
            <span className="ml-2 text-xs font-normal text-slate-500 dark:text-slate-400">
              （共 {total} 条）
            </span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          {action}
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              className="text-xs font-semibold px-2.5 py-1 rounded-lg border border-primary-300 text-primary-700 bg-primary-50 hover:bg-primary-100 dark:bg-primary-900/30 dark:text-primary-300 dark:border-primary-700"
            >
              ✎ 编辑
            </button>
          )}
        </div>
      </div>
      {children}
    </section>
  );
}

export function EmptySection({ text = '该分类暂无记录。' }) {
  return (
    <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 dark:border-slate-600 dark:text-slate-500">
      {text}
    </p>
  );
}

export function Badge({ children, className = '' }) {
  return <span className={`inline-block px-1.5 py-0.5 text-[10px] font-semibold rounded ${className}`}>{children}</span>;
}
