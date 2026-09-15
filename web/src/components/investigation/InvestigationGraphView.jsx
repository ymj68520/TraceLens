// InvestigationGraphView.jsx
// Investigation Graph 工作台视图（原 /investigation-graph 独立页并入）：
// 消费 C8b 冻结的 GET /api/investigation/graph（Base KG + Investigation
// Overlay 组合投影）。本组件不重算任何 graph 语义：节点/边完全来自后端
// authoritative read projection；前端只 render、处理 selection、展示
// 降级/空/错误状态。refreshSignal 由工作台在服务端状态变化（review/submit、
// event 变更）后递增，触发重新拉取。
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CircleAlert, RefreshCw } from 'lucide-react';
import Badge from '../common/Badge';
import Spinner from '../common/Spinner';
import InvestigationGraphCanvas from './InvestigationGraphCanvas';
import InvestigationNodeDetailPanel from './InvestigationNodeDetailPanel';
import {
    INVESTIGATION_NODE_COLORS,
    NODE_LEGEND,
} from './investigationGraphConstants';
import { useInvestigationGraph } from '../../hooks/useInvestigationGraph';
import { useTranslation } from '../../hooks/useTranslation';

const MAX_BASE_NODES_OPTIONS = [100, 200, 500];

// Badge 不透传 data-testid，用外层 span 承载测试锚点。
const TestBadge = ({ testid, variant = 'gray', children }) => (
    <span data-testid={testid}>
        <Badge variant={variant} size="sm">{children}</Badge>
    </span>
);

const InvestigationGraphView = ({ taskId, onNodeClick, refreshSignal = 0 }) => {
    const { t } = useTranslation();
    const [maxBaseNodes, setMaxBaseNodes] = useState(200);
    const [selectedNodeId, setSelectedNodeId] = useState(null);

    const { graph, loading, error, refresh } = useInvestigationGraph({ taskId, maxBaseNodes });

    // task 切换时清掉已选 graph 节点（§12）。
    useEffect(() => {
        setSelectedNodeId(null);
    }, [taskId]);

    // 跳过初次渲染（hook 自身已加载）；refreshSignal 递增（服务端状态变化）
    // 时重读。refresh 走 ref，避免 maxBaseNodes 变更引发的二次刷新。
    const mountedRef = useRef(false);
    const refreshRef = useRef(refresh);
    refreshRef.current = refresh;
    useEffect(() => {
        if (!mountedRef.current) {
            mountedRef.current = true;
            return;
        }
        refreshRef.current();
    }, [refreshSignal]);

    const baseNodeCount = useMemo(
        () => graph.nodes.filter((node) => node.source === 'base_kg').length,
        [graph.nodes],
    );
    const overlayNodeCount = graph.nodes.length - baseNodeCount;
    const baseUnavailable = (graph.warnings || []).includes('base_graph_unavailable');
    const selectedNode = useMemo(
        () => graph.nodes.find((node) => node.id === selectedNodeId) || null,
        [graph.nodes, selectedNodeId],
    );

    const handleNodeClick = (node) => {
        // 精确 ID selection：直接使用后端确定性节点 ID，不做任何合并/推断。
        setSelectedNodeId(node?.id ?? null);
        onNodeClick?.(node);
    };

    return (
        <div className="flex flex-col h-full min-h-0" data-testid="graph-view">
            {/* 工具栏：计数徽章 + 截断徽章 + Base 上限 + 刷新 */}
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b border-slate-200/60 dark:border-slate-700/50 shrink-0">
                <div className="flex items-center gap-2 flex-wrap">
                    <TestBadge testid="base-node-count">
                        {t('investigation_graph.base_nodes')}: {baseNodeCount}
                    </TestBadge>
                    <TestBadge testid="overlay-node-count" variant="blue">
                        {t('investigation_graph.overlay_nodes')}: {overlayNodeCount}
                    </TestBadge>
                    {graph.base_nodes_truncated && (
                        <TestBadge testid="base-node-truncated" variant="yellow">
                            {t('investigation_graph.base_nodes_truncated')} ({graph.base_max_nodes})
                        </TestBadge>
                    )}
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
                </div>
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

            {/* 命名空间图例：Investigation 四类 + Base KG + 虚线未确认 */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2 text-xs text-slate-500 dark:text-slate-400 shrink-0">
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
                    className="mx-4 mt-2 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-100/70 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 text-xs ring-1 ring-amber-200/60 dark:ring-amber-700/40 shrink-0">
                    <AlertTriangle size={15} className="shrink-0" />
                    {t('investigation_graph.base_unavailable_warning')}
                </div>
            )}

            <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-3 px-4 py-3">
                <div className="flex-1 min-w-0 min-h-[320px] glass rounded-2xl overflow-hidden relative"
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
                        <div className={taskId && graph.nodes.length === 0 && !loading ? 'h-full opacity-30 pointer-events-none' : 'h-full'}>
                            <InvestigationGraphCanvas
                                data={graph}
                                onNodeClick={handleNodeClick}
                                selectedNodeId={selectedNodeId}
                            />
                        </div>
                    )}
                </div>

                <aside className="w-full lg:w-80 shrink-0 glass rounded-2xl p-4 min-h-[320px] lg:min-h-0"
                    data-testid="node-detail-panel">
                    <InvestigationNodeDetailPanel node={selectedNode} />
                </aside>
            </div>
        </div>
    );
};

export default InvestigationGraphView;
