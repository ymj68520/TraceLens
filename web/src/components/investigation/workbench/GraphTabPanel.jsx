// GraphTabPanel.jsx
// Workbench 中栏 Graph 视图：直接复用 C8c 的 InvestigationGraphCanvas 与
// useInvestigationGraph（不实现第二份 Graph）。节点点击交给页面统一为
// Workbench selection（event:/evidence:/analysis:/claim: 命名空间）。
// C9b：refreshSignal 变化时重新拉取服务端 Graph（review/submit 后由页面
// 递增）——前端从不增删节点或改 confirmed，一切以服务端 C8b selection 为准。
import { useEffect, useRef } from 'react';
import { AlertTriangle, CircleAlert, RefreshCw } from 'lucide-react';
import Spinner from '../../common/Spinner';
import InvestigationGraphCanvas from '../InvestigationGraphCanvas';
import { useInvestigationGraph } from '../../../hooks/useInvestigationGraph';
import { useTranslation } from '../../../hooks/useTranslation';

const GraphTabPanel = ({ taskId, selectedNodeId, onNodeClick, refreshSignal = 0 }) => {
    const { t } = useTranslation();
    const { graph, loading, error, refresh } = useInvestigationGraph({ taskId });

    // 跳过初次渲染（hook 自身已加载），之后每次信号递增都重读服务端状态。
    const mountedRef = useRef(false);
    useEffect(() => {
        if (!mountedRef.current) {
            mountedRef.current = true;
            return;
        }
        refresh();
    }, [refreshSignal, refresh]);

    const baseUnavailable = (graph.warnings || []).includes('base_graph_unavailable');

    return (
        <div className="flex flex-col h-full" data-testid="graph-tab">
            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-white/10 dark:border-slate-700/40">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {t('investigation_workbench.graph_title')}
                </h2>
                <button
                    type="button"
                    onClick={refresh}
                    disabled={!taskId || loading}
                    className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 disabled:opacity-50"
                    title={t('investigation_workbench.refresh')}
                >
                    <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div className="flex-1 relative min-h-0">
                {baseUnavailable && !error && (
                    <div data-testid="workbench-base-unavailable"
                        className="mx-3 mt-2 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-100/70 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 text-[11px] ring-1 ring-amber-200/60 dark:ring-amber-700/40">
                        <AlertTriangle size={12} className="shrink-0" />
                        {t('investigation_graph.base_unavailable_warning')}
                    </div>
                )}
                {error ? (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 z-10 px-6 text-center">
                        <CircleAlert size={20} className="text-rose-500" />
                        <p className="text-xs text-rose-600 dark:text-rose-400">
                            {t('investigation_graph.error')}
                            {error?.status ? ` (HTTP ${error.status})` : ''}
                        </p>
                        <button type="button" onClick={refresh}
                            className="px-2.5 py-1 text-xs rounded-lg bg-rose-500/10 text-rose-700 dark:text-rose-300 hover:bg-rose-500/20">
                            {t('investigation_graph.retry')}
                        </button>
                    </div>
                ) : (
                    <>
                        {loading && graph.nodes.length === 0 && (
                            <div className="absolute inset-0 flex items-center justify-center z-10">
                                <Spinner size="lg" />
                            </div>
                        )}
                        {!loading && taskId && graph.nodes.length === 0 && (
                            <div className="absolute inset-0 flex items-center justify-center z-10 text-xs text-slate-400 dark:text-slate-500">
                                {t('investigation_graph.empty')}
                            </div>
                        )}
                        <div className={graph.nodes.length === 0 && !loading ? 'h-full opacity-30 pointer-events-none' : 'h-full'}>
                            <InvestigationGraphCanvas
                                data={graph}
                                onNodeClick={onNodeClick}
                                selectedNodeId={selectedNodeId}
                            />
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default GraphTabPanel;
