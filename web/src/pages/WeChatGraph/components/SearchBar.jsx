export default function SearchBar({ query, onChange, onRefresh }) {
    return (
        <div className="flex items-center gap-3">
            <div className="flex-1 relative">
                <input
                    type="text"
                    value={query}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder="搜索联系人..."
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
            </div>
            <button
                onClick={onRefresh}
                className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300 hover:bg-slate-700"
            >
                刷新
            </button>
        </div>
    );
}
