import { useCallback, useEffect, useRef } from 'react';
import CategorySection from './CategorySection';
import ReportDirectory from './ReportDirectory';
import ReportSearch from './ReportSearch';

function hitKey(hit) {
  if (!hit?.category_id || !hit?.page) return null;
  return `${hit.category_id}::${hit.page}::${hit.record_id || ''}`;
}

export default function ReportWorkspace({
  manifest,
  dataSource,
  reportId,
  selectedCategory,
  selectedPage,
  onSelectCategory,
  onSelectPage,
  searchState,
  directoryOpen,
  onDirectoryOpenChange,
}) {
  const category = manifest.categories.find(
    (item) => item.category_id === selectedCategory,
  ) || null;
  const navigationRef = useRef(null);
  const pendingHitRef = useRef(null);
  const scrolledRef = useRef(null);

  const currentHitKey = hitKey(searchState.currentHit);
  const navigationActivation = searchState.activation ?? currentHitKey;
  const navigationKey = currentHitKey
    ? `${navigationActivation}::${currentHitKey}`
    : null;
  useEffect(() => {
    navigationRef.current = null;
    pendingHitRef.current = null;
    scrolledRef.current = null;
  }, [reportId]);

  useEffect(() => {
    if (!navigationKey || navigationRef.current === navigationKey) return;
    const hit = searchState.currentHit;
    navigationRef.current = navigationKey;
    pendingHitRef.current = hit.record_id ? hit : null;
    scrolledRef.current = null;
    onSelectCategory(hit.category_id, hit.page);
  }, [navigationKey, onSelectCategory, searchState.currentHit]);

  const scrollToPendingRecord = useCallback((container, pageData) => {
    const hit = pendingHitRef.current;
    if (
      !hit?.record_id
      || hit.category_id !== selectedCategory
      || Number(hit.page) !== Number(pageData?.page ?? selectedPage)
    ) return;

    const scrollKey = `${reportId}::${hitKey(hit)}`;
    if (scrolledRef.current === scrollKey) return;
    const target = [...container.querySelectorAll('[data-record-id]')]
      .find((node) => node.getAttribute('data-record-id') === hit.record_id);
    if (!target) return;

    scrolledRef.current = scrollKey;
    pendingHitRef.current = null;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [reportId, selectedCategory, selectedPage]);

  return (
    <div className="relative grid min-h-[70vh] min-w-0 grid-cols-1 gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <button
        type="button"
        className="rounded-xl border border-slate-300 bg-white/80 px-4 py-3 text-left text-sm font-semibold text-slate-800 shadow-sm lg:hidden dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-100"
        aria-expanded={directoryOpen}
        aria-controls="report-directory-panel"
        onClick={() => onDirectoryOpenChange(!directoryOpen)}
      >
        打开报告目录
      </button>
      {directoryOpen && (
        <button
          type="button"
          aria-label="关闭报告目录"
          className="fixed inset-0 z-40 bg-slate-950/55 lg:hidden"
          onClick={() => onDirectoryOpenChange(false)}
        />
      )}
      <aside
        id="report-directory-panel"
        aria-label="报告目录"
        className={`${directoryOpen ? 'fixed inset-y-0 left-0 z-50 block w-[min(90vw,24rem)] overflow-y-auto bg-white p-4 shadow-2xl dark:bg-slate-900' : 'hidden'} min-w-0 lg:sticky lg:top-20 lg:z-auto lg:block lg:h-[calc(100vh-7rem)] lg:w-auto lg:overflow-y-auto lg:rounded-2xl lg:border lg:border-slate-200 lg:bg-white/70 lg:p-4 lg:shadow-sm lg:backdrop-blur dark:lg:border-slate-700 dark:lg:bg-slate-900/70`}
      >
        <ReportSearch {...searchState} />
        <ReportDirectory
          directory={manifest.directory}
          onSelect={(categoryId, page) => {
            onSelectCategory(categoryId, page);
            onDirectoryOpenChange(false);
          }}
        />
      </aside>
      <main className="min-w-0 space-y-6" aria-label="报告正文">
        {category ? (
          <CategorySection
            reportId={reportId}
            category={category}
            page={selectedPage}
            dataSource={dataSource}
            onPageChange={onSelectPage}
            onPageRendered={scrollToPendingRecord}
          />
        ) : (
          <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
            请选择报告目录中的分类。
          </p>
        )}
      </main>
    </div>
  );
}
