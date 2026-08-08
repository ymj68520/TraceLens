export default function PersonDetail({ node, graphData, onClose }) {
    const connectedEdges = (graphData?.edges || graphData?.links || []).filter(
        (e) => {
            const src =
                typeof e.source === 'object' ? e.source.id : e.source;
            const tgt =
                typeof e.target === 'object' ? e.target.id : e.target;
            return src === node.id || tgt === node.id;
        }
    );

    return (
        <div className="bg-slate-800 rounded-xl p-4 space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <div className="text-lg font-medium text-slate-100">
                        {node.label || node.name || node.id}
                    </div>
                    <div className="text-xs text-slate-400">{node.id}</div>
                </div>
                <button
                    onClick={onClose}
                    className="text-slate-400 hover:text-slate-200"
                >
                    &#10005;
                </button>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">消息数</div>
                    <div className="text-slate-100 font-medium">
                        {node.message_count || 0}
                    </div>
                </div>
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">PageRank</div>
                    <div className="text-slate-100 font-medium">
                        {(node.pagerank || 0).toFixed(4)}
                    </div>
                </div>
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">中介中心性</div>
                    <div className="text-slate-100 font-medium">
                        {(node.betweenness || 0).toFixed(4)}
                    </div>
                </div>
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">社区</div>
                    <div className="text-slate-100 font-medium">
                        社区{node.community ?? node.cluster ?? 0}
                    </div>
                </div>
            </div>

            {/* Connected edges */}
            <div>
                <div className="text-sm text-slate-300 mb-1">
                    关联关系 ({connectedEdges.length})
                </div>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                    {connectedEdges.map((e, i) => {
                        const src =
                            typeof e.source === 'object'
                                ? e.source.id
                                : e.source;
                        const tgt =
                            typeof e.target === 'object'
                                ? e.target.id
                                : e.target;
                        const other = src === node.id ? tgt : src;
                        return (
                            <div
                                key={i}
                                className="flex justify-between text-xs text-slate-400 px-2 py-1"
                            >
                                <span>{other}</span>
                                <span>{e.weight || 0}条</span>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
