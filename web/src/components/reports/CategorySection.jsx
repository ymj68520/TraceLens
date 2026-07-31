import CategoryPagination from './CategoryPagination';
import { useReportCategory } from '../../hooks/useReportCategory';

function displayRecord(record, index) {
  const title = record?.title || record?.record_id || `记录 ${index + 1}`;
  const fields = record?.fields && typeof record.fields === 'object'
    ? Object.entries(record.fields).slice(0, 6)
    : [];

  return (
    <article
      key={record?.record_id || `${title}-${index}`}
      data-record-id={record?.record_id}
      className="scroll-mt-24 rounded-xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70"
    >
      <h3 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
      {record?.source_path && <p className="mt-1 break-all font-mono text-xs text-slate-500">{record.source_path}</p>}
      {fields.length > 0 && (
        <dl className="mt-3 grid gap-x-5 gap-y-2 sm:grid-cols-2">
          {fields.map(([name, value]) => (
            <div key={name} className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{name}</dt>
              <dd className="break-words text-sm text-slate-700 dark:text-slate-200">
                {typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}

export default function CategorySection({
  reportId, category, page, dataSource, onPageChange, onPageRendered,
}) {
  const { data, loading, error } = useReportCategory({
    dataSource,
    reportId,
    categoryId: category?.category_id,
    page,
  });
  const records = Array.isArray(data?.records) ? data.records : [];

  return (
    <section aria-labelledby="report-category-title" className="min-w-0 space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 pb-4 dark:border-slate-700">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary-600 dark:text-primary-400">
            {category.platform}
          </p>
          <h2 id="report-category-title" className="mt-1 text-xl font-bold text-slate-900 dark:text-white">
            {category.title}
          </h2>
        </div>
        <p className="font-mono text-xs tabular-nums text-slate-500 dark:text-slate-400">
          {category.category_id}
        </p>
      </header>

      {loading && <div role="status" className="rounded-xl border border-slate-200 p-5 text-sm text-slate-500 dark:border-slate-700">正在加载分类记录…</div>}
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">分类加载失败：{error.message || String(error)}</div>}
      {!loading && !error && data && records.length === 0 && (
        <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">此分类当前没有记录。</p>
      )}
      {!loading && !error && records.length > 0 && (
        <div
          className="space-y-3"
          ref={(node) => {
            if (node) onPageRendered?.(node, data);
          }}
        >
          {records.map(displayRecord)}
        </div>
      )}

      {!loading && !error && data && (
        <CategoryPagination
          page={data.page ?? page}
          pageSize={data.page_size ?? category.page_size}
          total={data.total ?? category.total}
          pages={category.pages}
          onPageChange={onPageChange}
        />
      )}
    </section>
  );
}
