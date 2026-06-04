import { useState, useCallback, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    getWeChatGraph,
    getWeChatTimeline,
    getWeChatCommunity,
    getWeChatChat,
    getWeChatGroupChat,
    invalidateWeChatCache,
} from '../../../services/wechatService';

/**
 * WeChat 聊天关系图谱 Hook
 * 管理图谱数据获取、聊天记录加载、节点/边交互等状态
 */
export default function useWeChatGraph() {
    const [searchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');

    // Graph state
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [timelineData, setTimelineData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Selection state
    const [selectedNode, setSelectedNode] = useState(null);
    const [selectedEdge, setSelectedEdge] = useState(null);

    // Chat state
    const [chatMessages, setChatMessages] = useState([]);
    const [chatTotal, setChatTotal] = useState(0);
    const [chatLoading, setChatLoading] = useState(false);

    // Filter state
    const [timeRange, setTimeRange] = useState(null);
    const [selectedCommunity, setSelectedCommunity] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');

    /**
     * 获取图谱数据和时间线
     */
    const fetchGraph = useCallback(async () => {
        if (!taskId) return;
        setLoading(true);
        setError(null);
        try {
            const [graphResult, timelineResult] = await Promise.all([
                getWeChatGraph(taskId),
                getWeChatTimeline(taskId),
            ]);
            setGraphData({
                nodes: graphResult.nodes || [],
                links: graphResult.links || [],
            });
            setTimelineData(timelineResult.timeline || []);
        } catch (err) {
            setError('获取微信图谱数据失败: ' + (err.message || '未知错误'));
        } finally {
            setLoading(false);
        }
    }, [taskId]);

    /**
     * 加载私聊聊天记录 (分页)
     * @param {string} user1 - 用户 1
     * @param {string} user2 - 用户 2
     * @param {number} offset - 偏移量
     * @param {number} limit - 每页数量
     */
    const loadChatHistory = useCallback(async (user1, user2, offset = 0, limit = 50) => {
        if (!taskId) return;
        setChatLoading(true);
        try {
            const result = await getWeChatChat(taskId, user1, user2, offset, limit);
            if (offset === 0) {
                setChatMessages(result.messages || []);
            } else {
                setChatMessages((prev) => [...prev, ...(result.messages || [])]);
            }
            setChatTotal(result.total || 0);
        } catch (err) {
            setError('加载聊天记录失败: ' + (err.message || '未知错误'));
        } finally {
            setChatLoading(false);
        }
    }, [taskId]);

    /**
     * 加载群聊聊天记录 (分页)
     * @param {string} chatroom - 群聊 ID
     * @param {number} offset - 偏移量
     * @param {number} limit - 每页数量
     */
    const loadGroupChat = useCallback(async (chatroom, offset = 0, limit = 50) => {
        if (!taskId) return;
        setChatLoading(true);
        try {
            const result = await getWeChatGroupChat(taskId, chatroom, offset, limit);
            if (offset === 0) {
                setChatMessages(result.messages || []);
            } else {
                setChatMessages((prev) => [...prev, ...(result.messages || [])]);
            }
            setChatTotal(result.total || 0);
        } catch (err) {
            setError('加载群聊记录失败: ' + (err.message || '未知错误'));
        } finally {
            setChatLoading(false);
        }
    }, [taskId]);

    /**
     * 点击边 (关系) 时加载对应聊天记录
     * @param {Object} edge - 被点击的边
     */
    const handleEdgeClick = useCallback((edge) => {
        setSelectedEdge(edge);
        setSelectedNode(null);
        setChatMessages([]);
        setChatTotal(0);

        const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
        const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;

        // 群聊边: source 或 target 以 @chatroom 结尾
        if (sourceId.endsWith('@chatroom') || targetId.endsWith('@chatroom')) {
            const chatroom = sourceId.endsWith('@chatroom') ? sourceId : targetId;
            loadGroupChat(chatroom, 0, 50);
        } else {
            // 私聊边
            loadChatHistory(sourceId, targetId, 0, 50);
        }
    }, [loadChatHistory, loadGroupChat]);

    /**
     * 点击节点时选中节点
     * @param {Object} node - 被点击的节点
     */
    const handleNodeClick = useCallback((node) => {
        setSelectedNode(node);
        setSelectedEdge(null);
        setChatMessages([]);
        setChatTotal(0);
    }, []);

    /**
     * 点击背景时清除选择
     */
    const handleBackgroundClick = useCallback(() => {
        setSelectedNode(null);
        setSelectedEdge(null);
        setChatMessages([]);
        setChatTotal(0);
    }, []);

    /**
     * 刷新图谱: 使缓存失效后重新获取
     */
    const refreshGraph = useCallback(async () => {
        if (!taskId) return;
        setLoading(true);
        setError(null);
        try {
            await invalidateWeChatCache(taskId);
            await fetchGraph();
        } catch (err) {
            setError('刷新图谱失败: ' + (err.message || '未知错误'));
            setLoading(false);
        }
    }, [taskId, fetchGraph]);

    // 当 taskId 变化时自动获取图谱
    useEffect(() => {
        if (taskId) {
            fetchGraph();
        } else {
            setGraphData({ nodes: [], links: [] });
            setTimelineData([]);
            setSelectedNode(null);
            setSelectedEdge(null);
            setChatMessages([]);
            setChatTotal(0);
        }
    }, [taskId, fetchGraph]);

    /**
     * 过滤后的图谱数据: 按社区和搜索关键词过滤
     */
    const filteredGraphData = useMemo(() => {
        let { nodes, links } = graphData;

        // 按社区过滤
        if (selectedCommunity !== null) {
            const communityNodes = new Set(
                nodes
                    .filter((n) => n.community === selectedCommunity)
                    .map((n) => n.id)
            );
            nodes = nodes.filter((n) => n.community === selectedCommunity);
            links = links.filter((l) => {
                const src = typeof l.source === 'object' ? l.source.id : l.source;
                const tgt = typeof l.target === 'object' ? l.target.id : l.target;
                return communityNodes.has(src) && communityNodes.has(tgt);
            });
        }

        // 按搜索关键词过滤
        if (searchQuery.trim()) {
            const query = searchQuery.trim().toLowerCase();
            const matchedNodes = new Set(
                nodes
                    .filter((n) =>
                        (n.name && n.name.toLowerCase().includes(query)) ||
                        (n.label && n.label.toLowerCase().includes(query)) ||
                        (n.remark && n.remark.toLowerCase().includes(query))
                    )
                    .map((n) => n.id)
            );
            nodes = nodes.filter((n) => matchedNodes.has(n.id));
            links = links.filter((l) => {
                const src = typeof l.source === 'object' ? l.source.id : l.source;
                const tgt = typeof l.target === 'object' ? l.target.id : l.target;
                return matchedNodes.has(src) && matchedNodes.has(tgt);
            });
        }

        return { nodes, links };
    }, [graphData, selectedCommunity, searchQuery]);

    return {
        // Task
        taskId,

        // Graph
        graphData,
        filteredGraphData,
        timelineData,
        loading,
        error,
        setError,

        // Selection
        selectedNode,
        selectedEdge,

        // Chat
        chatMessages,
        chatTotal,
        chatLoading,
        loadChatHistory,
        loadGroupChat,

        // Filters
        timeRange,
        setTimeRange,
        selectedCommunity,
        setSelectedCommunity,
        searchQuery,
        setSearchQuery,

        // Actions
        fetchGraph,
        refreshGraph,
        handleEdgeClick,
        handleNodeClick,
        handleBackgroundClick,
    };
}
