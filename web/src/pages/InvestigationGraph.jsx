// InvestigationGraph.jsx
// Investigation Graph 只读视图 (C8c)：消费 C8b 冻结的
// GET /api/investigation/graph（Base KG + Investigation Overlay 组合投影）。
//
// 本页不重算任何 graph 语义：节点/边完全来自后端 authoritative read
// projection；前端只 render、处理 selection、展示降级/空/错误状态。
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw, AlertTriangle, CircleAlert, MousePointerClick } from 'lucide-react';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import InvestigationGraphCanvas from '../components/investigation/InvestigationGraphCanvas';
import {
    INVESTIGATION_NODE_COLORS,
    NODE_LEGEND,
    getNodeColor,
    isUnconfirmed,
    parseNodeId,
} from '../components/investigation/investigationGraphConstants';
import { useInvestigationGraph } from '../hooks/useInvestigationGraph';
import { useTranslation } from '../hooks/useTranslation';

const MAX_BASE_NODES_OPTIONS = [100, 200, 500];

const ProvenanceRow = ({ label, value }) => (
    <div className="flex items-baseline justify-between gap-3 py-1">
        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">{label}</span>
        <span className="text-xs font-mono text-right break-all text-slate-700 dark:text-slate-200">
            {value === undefined || value === null || value === '' ? '-' : String(value)}
        </span>
    </div>
);

// §15：按 node 类型展示后端已冻结的 provenance 字段；不额外发请求。
const provenanceRows = (node) => {
    const provenance = node.provenance || {};
    if (node.source !== 'investigation') {
        return [
            { label: 'name', value: node.name },
            { label: 'label', value: node.label },
        ];
    }
    switch (node.label) {
        case 'InvestigationEvent':
            return [
                { label: 'title', value: node.name },
                { label: 'current version', value: provenance.version },
            ];
        case 'Analysis':
            return [
                { label: 'review_state', value: provenance.review_state },
                { label: 'confirmed', value: node.confirmed === null ? '-' : String(node.confirmed) },
                { label: 'version', value: provenance.version },
                { label: 'evidence_key', value: provenance.evidence_key },
            ];
        case 'Claim':
            return [
                { label: 'claim_type', value: provenance.claim_type },
                { label: 'grounding_status', value: provenance.grounding_status },
                { label: 'confirmed', value: node.confirmed === null ? '-' : String(node.confirmed) },
                { label: 'analysis_id', value: provenance.analysis_id },
            ];
        case 'Evidence':
            return [
                { label: 'evidence_key', value: provenance.evidence_key ?? node.name },
                { label: 'evidence_type', value: provenance.evidence_type },
            ];
        default:
            return [];
    }
};

const NodeDetailPanel = ({ node }) => {
    const { t } = useTranslation();
    if (!node) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-400 dark:text-slate-500 py-16">
                <MousePointerClick size={22} />
                <p className="text-xs">{t('investigation_graph.select_hint')}</p>
            </div>
        );
    }

    const { namespace, value } = parseNodeId(node.id);

    return (
        <div className="space-y-3 overflow-y-auto h-full">
            <div className="flex items-center gap-2 flex-wrap">
                <span
                    className="inline-block h-3 w-3 rounded-full shrink-0"
                    style={{ backgroundColor: getNodeColor(node) }}
                    aria-label={`color ${node.source}:${node.label}`}
                />
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100 break-all">
                    {node.name || node.id}
                </span>
                {node.confirmed === true && (
                    <Badge variant="green" size="sm">{t('investigation_graph.confirmed')}</Badge>
                )}
                {isUnconfirmed(node) && (
                    <Badge variant="yellow" size="sm">{t('investigation_graph.unconfirmed')}</Badge>
                )}
            </div>

            <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2">
                <div className="flex items-baseline justify-between gap-3 py-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">id</span>
                    <span className="text-xs font-mono text-right break-all text-slate-700 dark:text-slate-200">
                        {node.id}
                    </span>
                </div>
                <div className="flex items-baseline justify-between gap-3 py-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">namespace</span>
                    <span className="text-xs font-mono text-slate-700 dark:text-slate-200">{namespace}</span>
                </div>
                {namespace !== 'base_kg' && (
                    <div className="flex items-baseline justify-between gap-3 py-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">{namespace}_id</span>
                        <span className="text-xs font-mono text-right break-all text-slate-700 dark:text-slate-200">
                            {value}
                        </span>
                    </div>
                )}
                <div className="flex items-baseline justify-between gap-3 py-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">source</span>
                    <span className="text-xs font-mono text-slate-700 dark:text-slate-200">{node.source}</span>
                </div>
            </div>

            {node.summary && (
                <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words">
                    {node.summary}
                </p>
            )}

            <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2">
                {provenanceRows(node).map((row) => (
                    <ProvenanceRow key={row.label} label={row.label} value={row.value} />
                ))}
            </div>
        </div>
    );
};

const InvestigationGraph = () => {
    const { t } = useTranslation();
    const [searchParams] = useSearchParams();
    const taskId = searchParams.get('taskId') || searchParams.get('task_id');
    const [maxBaseNodes, setMaxBaseNodes] = useState(200);
    const [selectedNodeId, setSelectedNodeId] = useState(null);

    const { graph, loading, error, refresh } = useInvestigationGraph({ taskId, maxBaseNodes });

    // task 切换时清掉已选 graph 节点（§12）。
    useEffect(() => {
        setSelectedNodeId(null);
    }, [taskId]);

    const baseNodeCount = useMemo(
        () => graph.nodes.filter((node) => node.source === 'base_kg').length,
        [graph.nodes],
    );
    const overlayNodeCount = graph.nodes.length - baseNodeCount;
    const baseUnavailable = graph.warnings.includes('base_graph_unavailable');
    const selectedNode = useMemo(
        () => graph.nodes.find((node) => node.id === selectedNodeId) || null,
        [graph.nodes, selectedNodeId],
    );

    const handleNodeClick = (node) => {
        // 精确 ID selection：直接使用后端确定性节点 ID，不做任何合并/推断。
        setSelectedNodeId(node?.id ?? null);
    };

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
                        {t('investigation_graph.title')}
                    </h1>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                        {t('investigation_graph.subtitle')}
                    </p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant="gray" size="sm" data-testid="base-node-count">
                        {t('investigation_graph.base_nodes')}: {baseNodeCount}
                    </Badge>
                    <Badge variant="blue" size="sm" data-testid="overlay-node-count">
                        {t('investigation_graph.overlay_nodes')}: {overlayNodeCount}
                    </Badge>
                    <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400"
                        title={t('investigation_graph.max_base_nodes_hint')}>
                        <span className="hidden md:inline">{t('investigation_graph.max_base_nodes')}</span>
                        <select
                            data-testid="max-base-nodes"
                            value={maxBaseNodes}
                            onChange={(event) => setMaxBaseNodes(Number(event.target.value))}
                            className="block pl-2 pr-6 py-1 text-xs rounded-lg border-0 bg-white/60 dark:bg-slate-800/60 text-slate-700 dark:text-slate-200 ring-1 ring-slate-200/60 dark:ring-slate-700/50"
                        >
                            {MAX_BASE_NODES_OPTIONS.map((option) => (
                                <option key={option} value={option}>{option}</option>
                            ))}
                        </select>
                    </label>
                    <button
                        type="button"
                        data-testid="refresh-graph"
                        onClick={refresh}
                        disabled={!taskId || loading}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-xl bg-primary-500/10 text-primary-700 dark:text-primary-300 hover:bg-primary-500/20 disabled:opacity-50 transition-colors"
                    >
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                        {t('investigation_graph.refresh')}
                    </button>
                </div>
            </div>

            {/* 命名空间图例：Investigation 四类 + Base KG 沿用色 */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-slate-500 dark:text-slate-400">
                {NODE_LEGEND.map(({ key, label }) => (
                    <span key={key} className="inline-flex items-center gap-1.5">
                        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: INVESTIGATION_NODE_COLORS[key] }} />
                        {label}
                    </span>
                ))}
                <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-2.5 rounded-full bg-slate-400" />
                    Base KG
                </span>
                <span className="inline-flex items-center gap-1.5">
                    <svg width="26" height="10" aria-hidden="true">
                        <line x1="1" y1="5" x2="25" y2="5" stroke="#f8fafc" strokeWidth="1.5" strokeDasharray="3 3" />
                    </svg>
                    {t('investigation_graph.unconfirmed')}
                </span>
            </div>

            {/* Base KG 降级：非阻塞 warning，Overlay 继续显示（§8） */}
            {baseUnavailable && !error && (
                <div data-testid="base-unavailable-warning"
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-100/70 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 text-xs ring-1 ring-amber-200/60 dark:ring-amber-700/40">
                    <AlertTriangle size={15} className="shrink-0" />
                    {t('investigation_graph.base_unavailable_warning')}
                </div>
            )}

            <div className="flex flex-col lg:flex-row gap-4">
                <div className="flex-1 min-w-0 glass rounded-2xl overflow-hidden relative"
                    style={{ height: 'calc(100vh - 300px)', minHeight: 420 }}
                    data-testid="graph-canvas-container">
                    {!taskId && (
                        <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-400 dark:text-slate-500 z-10">
                            {t('investigation_graph.no_task')}
                        </div>
                    )}
                    {error && (
                        <div data-testid="graph-error"
                            className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10 px-6 text-center">
                            <CircleAlert size={26} className="text-rose-500" />
                            <p className="text-sm font-medium text-rose-600 dark:text-rose-400">
                                {t('investigation_graph.error')}
                                {error?.status ? ` (HTTP ${error.status})` : ''}
                            </p>
                            {error?.data?.detail && (
                                <p className="text-xs text-slate-500 dark:text-slate-400">{String(error.data.detail)}</p>
                            )}
                            <button type="button" onClick={refresh}
                                className="px-3 py-1.5 text-xs font-medium rounded-xl bg-rose-500/10 text-rose-700 dark:text-rose-300 hover:bg-rose-500/20 transition-colors">
                                {t('investigation_graph.retry')}
                            </button>
                        </div>
                    )}
                    {!error && taskId && graph.nodes.length === 0 && !loading && (
                        <div data-testid="graph-empty"
                            className="absolute inset-0 flex items-center justify-center text-sm text-slate-400 dark:text-slate-500 z-10">
                            {t('investigation_graph.empty')}
                        </div>
                    )}
                    {loading && graph.nodes.length === 0 && !error && (
                        <div className="absolute inset-0 flex items-center justify-center z-10 bg-white/30 dark:bg-slate-900/30">
                            <Spinner size="lg" />
                        </div>
                    )}
                    {!error && (
                        <div className={taskId && graph.nodes.length === 0 && !loading ? 'opacity-30 pointer-events-none h-full' : 'h-full'}>
                            <InvestigationGraphCanvas
                                data={graph}
                                onNodeClick={handleNodeClick}
                                selectedNodeId={selectedNodeId}
                            />
                        </div>
                    )}
                </div>

                <aside className="w-full lg:w-80 shrink-0 glass rounded-2xl p-4"
                    style={{ maxHeight: 'calc(100vh - 300px)', minHeight: 420 }}
                    data-testid="node-detail-panel">
                    <NodeDetailPanel node={selectedNode} />
                </aside>
            </div>
        </div>
    );
};

export default InvestigationGraph;
