import { useCallback, useEffect, useRef, useState } from 'react';
import { getInvestigationGraph } from '../services/investigationService';

export const EMPTY_GRAPH = {
    task_id: null,
    base_graph_available: true,
    base_max_nodes: 200,
    nodes: [],
    links: [],
    warnings: [],
};

const normalizeGraph = (response) => ({
    task_id: response?.task_id ?? null,
    base_graph_available: response?.base_graph_available !== false,
    base_max_nodes: Number(response?.base_max_nodes) || 200,
    nodes: Array.isArray(response?.nodes) ? response.nodes : [],
    links: Array.isArray(response?.links) ? response.links : [],
    warnings: Array.isArray(response?.warnings) ? response.warnings : [],
});

/**
 * 只读加载 Investigation Graph，复用 useReportSearch 的 requestId 防陈旧模式。
 *
 * 不变量：task A 的请求发出后用户切到 task B，A 的响应晚于 B 返回时
 * 绝不能覆盖 B 的 graph / error / loading 状态。
 */
export function useInvestigationGraph({
    taskId,
    maxBaseNodes = 200,
    fetchGraph = getInvestigationGraph,
}) {
    const [graph, setGraph] = useState(EMPTY_GRAPH);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const taskRef = useRef(taskId);
    const requestRef = useRef(0);

    // task 切换：使未完成请求失效，并清掉旧 task 的 graph/error。
    useEffect(() => {
        taskRef.current = taskId;
        requestRef.current += 1;
        setGraph(EMPTY_GRAPH);
        setError(null);
        setLoading(false);
    }, [taskId]);

    const load = useCallback(async () => {
        const requestTask = taskId;
        if (!requestTask) return undefined;

        const requestId = ++requestRef.current;
        setLoading(true);
        setError(null);

        try {
            const response = await fetchGraph(requestTask, { maxBaseNodes });
            if (requestRef.current !== requestId || taskRef.current !== requestTask) {
                return response;
            }
            setGraph(normalizeGraph(response));
            return response;
        } catch (nextError) {
            if (requestRef.current === requestId && taskRef.current === requestTask) {
                setGraph(EMPTY_GRAPH);
                setError(nextError);
            }
            return undefined;
        } finally {
            if (requestRef.current === requestId && taskRef.current === requestTask) {
                setLoading(false);
            }
        }
    }, [taskId, maxBaseNodes, fetchGraph]);

    useEffect(() => {
        load();
    }, [load]);

    return { graph, loading, error, refresh: load };
}
