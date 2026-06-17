// FileFilters.jsx
// Filter column: extension / min-size / max-size inputs.

const FileFilters = ({
  filterExtension,
  setFilterExtension,
  filterMinSize,
  setFilterMinSize,
  filterMaxSize,
  setFilterMaxSize,
}) => {
  return (
    <div className="lg:col-span-4 space-y-4 pr-0 lg:pr-6 lg:border-r border-slate-100 dark:border-slate-700">
      <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">🔍 筛选器</h4>
      <div className="space-y-3">
        <div className="relative">
          <span className="absolute left-3 top-2.5 text-slate-400">🏷️</span>
          <input
            type="text"
            value={filterExtension}
            onChange={(e) => setFilterExtension(e.target.value)}
            placeholder="扩展名 (如 .jpg)"
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input
            type="number"
            value={filterMinSize}
            onChange={(e) => setFilterMinSize(e.target.value)}
            placeholder="最小 KB"
            className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
          />
          <input
            type="number"
            value={filterMaxSize}
            onChange={(e) => setFilterMaxSize(e.target.value)}
            placeholder="最大 KB"
            className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
          />
        </div>
      </div>
    </div>
  );
};

export default FileFilters;
