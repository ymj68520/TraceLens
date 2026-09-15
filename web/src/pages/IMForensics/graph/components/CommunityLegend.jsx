const COLORS = [
    '#3b82f6',
    '#ef4444',
    '#22c55e',
    '#f59e0b',
    '#8b5cf6',
    '#ec4899',
    '#06b6d4',
    '#f97316',
];

export default function CommunityLegend({ communities, selected, onSelect }) {
    if (!communities?.length) {
        return (
            <div className="text-slate-400 text-sm p-3">无社区数据</div>
        );
    }

    return (
        <div className="bg-slate-800 rounded-xl p-3">
            <div className="text-sm font-medium text-slate-200 mb-2">
                社区分组
            </div>
            <div className="space-y-1">
                {communities.map((c, index) => {
                    const cluster = c.cluster ?? c.community_id ?? c.id ?? index;
                    const members = c.members || [];
                    return (
                        <button
                            key={cluster}
                            onClick={() =>
                                onSelect(
                                    selected === cluster ? null : cluster
                                )
                            }
                            className={`flex items-center gap-2 w-full px-2 py-1 rounded text-sm ${
                                selected === cluster
                                    ? 'bg-slate-600'
                                    : 'hover:bg-slate-700'
                            }`}
                        >
                        <div
                            className="w-3 h-3 rounded-full"
                            style={{
                                background: COLORS[cluster % COLORS.length],
                            }}
                        />
                        <span className="text-slate-300">{c.label || `社区 ${Number(cluster) + 1}`}</span>
                        <span className="text-slate-500 text-xs ml-auto">
                            {members.length}人
                        </span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
