import CategoryPagination from './CategoryPagination';
import { getReportRenderer } from './renderers/registry';
import { useReportCategory } from '../../hooks/useReportCategory';

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
  const Renderer = getReportRenderer(category?.renderer);

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
          <Renderer
            records={records}
            category={category}
            reportId={reportId}
            dataSource={dataSource}
          />
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
