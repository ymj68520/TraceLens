import { motion } from 'framer-motion';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import ForceGraph2D from 'react-force-graph-2d';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import {
    ingestTaskData,
    searchGraph,
    listEntities,
    listRelationships,
    getGraphitiStatus,
    listTaskGraphs,
    deleteTaskGraph,
    getGraphData,
    getRelationshipTrace,
    getJobStatus,
    listIngestionJobs,
    reingestAnalyzedData,
} from '../services/graphitiService';

// Shared graph constants (node colors) extracted to a reusable module
import { NODE_COLORS, getNodeColor } from '../components/knowledge-graph/graphConstants';
// Knowledge graph subcomponents (split for maintainability)
import SearchTab from '../components/knowledge-graph/SearchTab';
import EntitiesTab from '../components/knowledge-graph/EntitiesTab';
import RelationshipsTab from '../components/knowledge-graph/RelationshipsTab';
import RelationshipTracePanel from '../components/knowledge-graph/RelationshipTracePanel';
import PeopleGraphPanel from '../components/knowledge-graph/PeopleGraphPanel';

const escapeGraphTooltip = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));

/**
 * 知识图谱页面 - 任务特定
 */
export default function KnowledgeGraph() {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');
    const requestedRelationshipId = searchParams.get('relationship_id');
    const { tasks } = useSelector((state) => state.tasks);

    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [taskGraphs, setTaskGraphs] = useState([]);

    // Search
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [searching, setSearching] = useState(false);

    // Entities
    const [entities, setEntities] = useState([]);
    const [entitiesPage, setEntitiesPage] = useState(1);
    const [entitiesTotalCount, setEntitiesTotalCount] = useState(0);

    // Relationships
    const [relationships, setRelationships] = useState([]);
    const [relationshipsPage, setRelationshipsPage] = useState(1);
    const [relationshipsTotalCount, setRelationshipsTotalCount] = useState(0);

    // Ingest
    const [ingesting, setIngesting] = useState(false);
    const [ingestResult, setIngestResult] = useState(null);
    const [ingestProgress, setIngestProgress] = useState(0);
    const [ingestMessage, setIngestMessage] = useState('');

    // Re-ingestion state (separate from regular ingestion)
    const [reingesting, setReingesting] = useState(false);
    const [reingestJobId, setReingestJobId] = useState(null);
    const [reingestProgress, setReingestProgress] = useState(0);
    const [reingestMessage, setReingestMessage] = useState('');
    const [reingestError, setReingestError] = useState(null);

    // Graph visualization
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [graphLoading, setGraphLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState(null);
    const [selectedRelationship, setSelectedRelationship] = useState(null);
    const [relationshipTrace, setRelationshipTrace] = useState(null);
    const [traceLoading, setTraceLoading] = useState(false);
    const [traceError, setTraceError] = useState(null);
    const traceRequestRef = useRef(0);
    const [highlightNodes, setHighlightNodes] = useState(new Set());
    const [highlightLinks, setHighlightLinks] = useState(new Set());
    const [maxNodes, setMaxNodes] = useState(200);
    const graphRef = useRef(null);
    const graphContainerRef = useRef(null);
    const [graphWidth, setGraphWidth] = useState(900);

    const [activeTab, setActiveTab] = useState('graph');
    const [peopleSelection, setPeopleSelection] = useState({ taskId: null, runId: '' });
    const selectPeopleRun = useCallback((runId) => setPeopleSelection(previous =>
        previous.taskId === taskId && previous.runId === runId ? previous : { taskId, runId }), [taskId]);
    const selectedPeopleRun = peopleSelection.taskId === taskId ? peopleSelection.runId : '';
    const PAGE_SIZE = 20;
    const currentTask = tasks.find((t) => t.id === taskId);
    const graphConnected = Boolean(taskId) && status?.task_id === taskId && status?.neo4j_connected === true;
    const hasSelectedRelationship = Boolean(selectedRelationship);

    useEffect(() => {
        const container = graphContainerRef.current;
        if (!container) return undefined;
        const measure = () => setGraphWidth(Math.max(320, Math.floor(container.clientWidth)));
        measure();
        if (typeof ResizeObserver === 'undefined') return undefined;
        const observer = new ResizeObserver(measure);
        observer.observe(container);
        return () => observer.disconnect();
    }, [graphData.nodes.length, hasSelectedRelationship]);

    useEffect(() => {
        if (!graphData.nodes.length) return undefined;
        const timer = setTimeout(() => graphRef.current?.zoomToFit(300, 36), 250);
        return () => clearTimeout(timer);
    }, [graphWidth, graphData.nodes.length]);

    // ── Fetch status ────────────────────────────────────────────────────────────
    const fetchStatus = useCallback(async () => {
        try {
            const result = await getGraphitiStatus(taskId);
            setStatus(result);
            setError(null);
        } catch (err) {
            setStatus({ status: 'error', neo4j_connected: false });
        } finally {
            setLoading(false);
        }
    }, [taskId]);

    const fetchTaskGraphs = useCallback(async () => {
        try {
            const result = await listTaskGraphs();
            setTaskGraphs(result.task_ids || []);
        } catch { /* Preserve the existing graph list when the status lookup is unavailable. */ }
    }, []);

    useEffect(() => {
        fetchStatus();
        fetchTaskGraphs();
    }, [fetchStatus, fetchTaskGraphs]);

    // Reset when task changes
    useEffect(() => {
        setSearchResults([]);
        setEntities([]);
        setRelationships([]);
        setEntitiesPage(1);
        setRelationshipsPage(1);
        setGraphData({ nodes: [], links: [] });
        setSelectedNode(null);
        traceRequestRef.current += 1;
        setSelectedRelationship(null);
        setRelationshipTrace(null);
        setTraceError(null);
        setReingestError(null);
        if (taskId) fetchStatus();
    }, [taskId, fetchStatus]);

    // Poll re-ingestion job status
    useEffect(() => {
        if (!reingestJobId) return;

        let isMounted = true;

        const pollStatus = async () => {
            try {
                const status = await getJobStatus(reingestJobId);
                if (!isMounted) return;

                setReingestProgress(status.progress || 0);
                setReingestMessage(status.current_phase || 'Processing...');

                if (status.status === 'COMPLETED') {
                    if (!isMounted) return;
                    setReingesting(false);
                    setReingestMessage('重新摄入完成！');
                    await fetchStatus();
                    await fetchTaskGraphs();
                    setGraphData({ nodes: [], links: [] }); // trigger reload
                } else if (status.status === 'FAILED') {
                    if (!isMounted) return;
                    setReingesting(false);
                    setReingestProgress(0);
                    setReingestMessage('');
                    setReingestError(`重新摄入失败: ${status.error || '未知错误'}`);
                } else if (status.status === 'CANCELLED') {
                    if (!isMounted) return;
                    setReingesting(false);
                    setReingestMessage('操作已取消');
                }
            } catch (err) {
                if (!isMounted) return;
                setReingesting(false);
                setReingestProgress(0);
                setReingestMessage('');
                setReingestError('获取任务状态失败: ' + (err.message || '未知错误'));
            }
        };

        // Poll every 2 seconds
        const interval = setInterval(pollStatus, 2000);
        pollStatus(); // Initial call

        return () => {
            isMounted = false;
            clearInterval(interval);
        };
    }, [reingestJobId, fetchStatus, fetchTaskGraphs]);

    // ── Background KG ingestion job (pipeline-dispatched kg_sync job) ────────
    // The analysis pipeline queues KG ingestion as a background job; surface
    // its progress here instead of an empty spinner (SPEC §B3).
    const [kgJob, setKgJob] = useState(null);
    const hadKgJobRef = useRef(false);

    const fetchKgJob = useCallback(async () => {
        if (!taskId || status?.read_only) { setKgJob(null); return; }
        try {
            const res = await listIngestionJobs(taskId, 5);
            const jobs = res.jobs || [];
            const active = jobs.find((j) =>
                ['PENDING', 'RUNNING'].includes(String(j.status || '').toUpperCase())
            );
            setKgJob(active || null);
        } catch { /* jobs endpoint unavailable — banner simply stays hidden */ }
    }, [taskId, status?.read_only]);

    useEffect(() => {
        fetchKgJob();
        const iv = setInterval(fetchKgJob, 3000);
        return () => clearInterval(iv);
    }, [fetchKgJob]);

    // Refresh counts while the job runs; reload data once it finishes
    // (the active job disappears from the poll result).
    useEffect(() => {
        if (kgJob) {
            hadKgJobRef.current = true;
            fetchStatus();
        } else if (hadKgJobRef.current) {
            hadKgJobRef.current = false;
            fetchStatus();
            fetchTaskGraphs();
            setGraphData({ nodes: [], links: [] }); // trigger graph reload
        }
    }, [kgJob, fetchStatus, fetchTaskGraphs]);

    // ── Graph visualization ──────────────────────────────────────────────────────
    const fetchGraphData = useCallback(async () => {
        if (!taskId || !graphConnected) return;
        setGraphLoading(true);
        try {
            const result = await getGraphData(taskId, maxNodes);
            setGraphData({ nodes: result.nodes || [], links: result.links || [] });
        } catch (err) {
            setError('加载图谱数据失败: ' + (err.message || '未知错误'));
        } finally {
            setGraphLoading(false);
        }
    }, [taskId, maxNodes, graphConnected]);

    // Auto-load graph when tab switches to graph
    const graphLoaderRef = useRef(null);
    graphLoaderRef.current = { fetchGraphData, nodeCount: graphData.nodes.length, loading: graphLoading };
    useEffect(() => {
        const current = graphLoaderRef.current;
        if (activeTab === 'graph' && graphConnected && current.nodeCount === 0 && !current.loading) {
            current.fetchGraphData();
        }
    }, [activeTab, taskId, graphConnected]);

    const handleNodeClick = useCallback((node) => {
        traceRequestRef.current += 1;
        setSelectedRelationship(null);
        setRelationshipTrace(null);
        if (searchParams.has('relationship_id')) {
            const next = new URLSearchParams(searchParams);
            next.delete('relationship_id');
            setSearchParams(next, { replace: true });
        }
        setSelectedNode(node);
        // Highlight node and neighbors
        const neighbors = new Set();
        const neighborLinks = new Set();
        graphData.links.forEach((link) => {
            const src = typeof link.source === 'object' ? link.source.id : link.source;
            const tgt = typeof link.target === 'object' ? link.target.id : link.target;
            if (src === node.id) { neighbors.add(tgt); neighborLinks.add(link); }
            if (tgt === node.id) { neighbors.add(src); neighborLinks.add(link); }
        });
        neighbors.add(node.id);
        setHighlightNodes(neighbors);
        setHighlightLinks(neighborLinks);
    }, [graphData, searchParams, setSearchParams]);

    const handleRelationshipClick = useCallback(async (link) => {
        const relationshipId = link?.id;
        const requestId = ++traceRequestRef.current;
        setSelectedNode(null);
        setSelectedRelationship(link || null);
        setRelationshipTrace(null);
        setTraceError(null);
        if (!taskId || !relationshipId) {
            setTraceError('该关系没有可追溯的 ID，请刷新图谱后重试。');
            return;
        }
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;
        setHighlightNodes(new Set([sourceId, targetId].filter(Boolean)));
        setHighlightLinks(new Set([link]));
        setTraceLoading(true);
        try {
            const result = await getRelationshipTrace(taskId, relationshipId);
            if (requestId === traceRequestRef.current) setRelationshipTrace(result);
        } catch (err) {
            if (requestId === traceRequestRef.current) setTraceError(err?.data?.detail || err?.message || '未知错误');
        } finally {
            if (requestId === traceRequestRef.current) setTraceLoading(false);
        }
    }, [taskId]);

    useEffect(() => {
        if (!taskId || !requestedRelationshipId || selectedRelationship?.id === requestedRelationshipId) return;
        handleRelationshipClick({ id: requestedRelationshipId });
    }, [taskId, requestedRelationshipId, selectedRelationship?.id, handleRelationshipClick]);

    const openRelationship = (link) => {
        handleRelationshipClick(link);
        if (link?.id && requestedRelationshipId !== link.id) {
            const next = new URLSearchParams(searchParams);
            next.set('relationship_id', link.id);
            setSearchParams(next);
        }
    };

    const closeRelationship = () => {
        traceRequestRef.current += 1;
        setSelectedRelationship(null);
        setRelationshipTrace(null);
        setTraceError(null);
        setHighlightNodes(new Set());
        setHighlightLinks(new Set());
        if (searchParams.has('relationship_id')) {
            const next = new URLSearchParams(searchParams);
            next.delete('relationship_id');
            setSearchParams(next, { replace: true });
        }
    };

    const handleNodeHover = useCallback((node) => {
        if (!node) {
            setHighlightNodes(new Set());
            setHighlightLinks(new Set());
            return;
        }
        const neighbors = new Set();
        const neighborLinks = new Set();
        graphData.links.forEach((link) => {
            const src = typeof link.source === 'object' ? link.source.id : link.source;
            const tgt = typeof link.target === 'object' ? link.target.id : link.target;
            if (src === node.id) { neighbors.add(tgt); neighborLinks.add(link); }
            if (tgt === node.id) { neighbors.add(src); neighborLinks.add(link); }
        });
        neighbors.add(node.id);
        setHighlightNodes(neighbors);
        setHighlightLinks(neighborLinks);
    }, [graphData]);

    // ── Search ───────────────────────────────────────────────────────────────────
    const handleSearch = async (e) => {
        e.preventDefault();
        if (!searchQuery.trim() || !taskId) return;
        setSearching(true);
        try {
            const result = await searchGraph(searchQuery, taskId, { limit: 50 });
            setSearchResults(result.results || []);
        } catch (err) {
            setError('搜索失败: ' + (err.message || '未知错误'));
        } finally {
            setSearching(false);
        }
    };

    // ── Entities ─────────────────────────────────────────────────────────────────
    const fetchEntities = async (page = 1) => {
        if (!taskId) return;
        setLoading(true);
        try {
            const result = await listEntities(taskId, { page, pageSize: PAGE_SIZE });
            setEntities(result.entities || []);
            setEntitiesTotalCount(result.total_count || 0);
            setEntitiesPage(page);
        } catch { setError('获取实体列表失败'); }
        finally { setLoading(false); }
    };

    const fetchRelationships = async (page = 1) => {
        if (!taskId) return;
        setLoading(true);
        try {
            const result = await listRelationships(taskId, { page, pageSize: PAGE_SIZE });
            setRelationships(result.relationships || []);
            setRelationshipsTotalCount(result.total_count || 0);
            setRelationshipsPage(page);
        } catch { setError('获取关系列表失败'); }
        finally { setLoading(false); }
    };

    // ── Ingest ───────────────────────────────────────────────────────────────────
    const handleIngest = async () => {
        if (!taskId) { setError('请先选择一个任务'); return; }
        setIngesting(true);
        setIngestResult(null);
        setIngestProgress(0);
        setIngestMessage('正在准备导入数据...');
        try {
            const result = await ingestTaskData(taskId, { includeLLMDescriptions: true });
            if (result.job_id) {
                setIngestMessage('导入进行中...');
                let progress = 10;
                const iv = setInterval(() => {
                    progress = Math.min(progress + 15, 90);
                    setIngestProgress(progress);
                    setIngestMessage(`已处理 ${progress}%...`);
                }, 2000);
                setTimeout(async () => {
                    clearInterval(iv);
                    setIngestProgress(100);
                    setIngestMessage('导入完成！');
                    setIngestResult(result);
                    await fetchStatus();
                    await fetchTaskGraphs();
                    setGraphData({ nodes: [], links: [] }); // trigger reload
                }, 10000);
            } else {
                setIngestProgress(100);
                setIngestMessage('导入完成！');
                setIngestResult(result);
                await fetchStatus();
                await fetchTaskGraphs();
                setGraphData({ nodes: [], links: [] });
            }
        } catch (err) {
            setError('导入失败: ' + (err.message || '未知错误'));
            setIngestProgress(0);
            setIngestMessage('');
        } finally {
            setIngesting(false);
        }
    };

    const handleDeleteGraph = async () => {
        if (!taskId) return;
        if (!confirm('确定要删除此任务的知识图谱数据吗？')) return;
        try {
            await deleteTaskGraph(taskId);
            await fetchStatus();
            await fetchTaskGraphs();
            setGraphData({ nodes: [], links: [] });
            setIngestResult({ message: '图谱已删除' });
        } catch (err) {
            setError('删除失败: ' + (err.message || '未知错误'));
        }
    };

    const handleReingestAnalyzed = async () => {
        if (!taskId) {
            setError('请先选择一个任务');
            return;
        }

        setReingesting(true);
        setReingestJobId(null);
        setReingestProgress(0);
        setReingestMessage('正在准备重新摄入...');

        try {
            const result = await reingestAnalyzedData(taskId);
            if (result.job_id) {
                setReingestJobId(result.job_id);
                setReingestMessage('已提交重新摄入任务');
            } else {
                setReingesting(false);
                setError('未能提交重新摄入任务');
            }
        } catch (err) {
            setReingestError('提交重新摄入任务失败: ' + (err.message || '未知错误'));
            setReingesting(false);
            setReingestProgress(0);
            setReingestMessage('');
        }
    };

    const handleTaskChange = (newId) => setSearchParams({ task_id: newId });

    const tabReadersRef = useRef(null);
    tabReadersRef.current = { fetchEntities, fetchRelationships };
    useEffect(() => {
        if (!taskId) return;
        if (activeTab === 'entities') tabReadersRef.current.fetchEntities(1);
        else if (activeTab === 'relationships') tabReadersRef.current.fetchRelationships(1);
    }, [activeTab, taskId]);

    // ── Render helpers ────────────────────────────────────────────────────────────
    const renderTaskSelector = () => (
        <Card className="mb-6">
            <div className="flex items-center gap-4">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-300">选择镜像任务:</label>
                <select
                    value={taskId || ''}
                    onChange={(e) => handleTaskChange(e.target.value)}
                    className="flex-1 max-w-md px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                >
                    <option value="">请选择任务...</option>
                    {tasks.filter(t => t.status === 'completed').map((task) => (
                        <option key={task.id} value={task.id}>
                            {task.image_path?.split('/').pop() || task.id}
                            {taskGraphs.includes(task.id) && ' ✓ (有图谱)'}
                        </option>
                    ))}
                </select>
                {taskId && taskGraphs.includes(taskId) && <Badge variant="green">有图谱数据</Badge>}
            </div>
        </Card>
    );

    const renderManagementToolbar = () => (
        <Card className="mb-4">
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="font-medium text-slate-900 dark:text-white">
                        🔧 图谱管理工具栏
                    </h3>
                    <p className="text-sm text-slate-500">
                        仅重新摄入包含AI分析结果的文件和事件簇
                    </p>
                </div>
                <Button onClick={handleReingestAnalyzed} disabled={status?.read_only || !taskId || reingesting || ingesting}>
                    {reingesting ? <Spinner size="sm" /> : '📥 重新摄入已分析数据'}
                </Button>
            </div>
            {/* Error display for re-ingestion */}
            {reingestError && (
                <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded flex items-start justify-between">
                    <div className="flex items-start gap-2">
                        <span className="text-lg">❌</span>
                        <span className="text-sm">{reingestError}</span>
                    </div>
                    <button
                        onClick={() => setReingestError(null)}
                        className="text-red-600 dark:text-red-400 hover:underline text-sm"
                    >
                        关闭
                    </button>
                </div>
            )}
            {/* Progress indicator for re-ingestion */}
            {reingesting && reingestProgress > 0 && reingestProgress < 100 && (
                <div className="mt-4">
                    <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-600 dark:text-slate-300">{reingestMessage}</span>
                        <span className="text-purple-600">{reingestProgress}%</span>
                    </div>
                    <div className="w-full bg-slate-200 dark:bg-gray-600 rounded-full h-2">
                        <div className="bg-purple-600 h-2 rounded-full transition-all"
                             style={{ width: `${reingestProgress}%` }} />
                    </div>
                </div>
            )}
            {reingesting && reingestProgress === 100 && reingestMessage && (
                <div className="mt-4 p-3 bg-purple-50 dark:bg-purple-900/20 text-purple-800 dark:text-purple-200 rounded">
                    ✅ {reingestMessage}
                </div>
            )}
        </Card>
    );

    const renderStatus = () => (
        <Card className="mb-6">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className={`w-3 h-3 rounded-full ${status?.neo4j_connected ? 'bg-green-500' : 'bg-red-500'}`} />
                    <div>
                        <h3 className="font-medium text-slate-900 dark:text-white">
                            {currentTask?.image_path?.split('/').pop() || '未选择任务'}
                        </h3>
                        <p className="text-sm text-slate-500 dark:text-slate-400">
                            Neo4j: {status?.neo4j_connected ? '已连接' : '未连接'}
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-8">
                    <div className="text-center">
                        <div className="text-2xl font-bold text-primary-600 dark:text-primary-400">{status?.total_entities || 0}</div>
                        <div className="text-sm text-slate-500">实体</div>
                    </div>
                    <div className="text-center">
                        <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">{status?.total_relationships || 0}</div>
                        <div className="text-sm text-slate-500">关系</div>
                    </div>
                    <div className="flex gap-2">
                        <Button size="sm" onClick={handleIngest} disabled={status?.read_only || !taskId || ingesting || reingesting}>
                            {ingesting ? <Spinner size="sm" /> : '导入数据'}
                        </Button>
                        {taskGraphs.includes(taskId) && (
                            <Button size="sm" variant="outline" onClick={handleDeleteGraph}>删除图谱</Button>
                        )}
                    </div>
                </div>
            </div>
            {(ingesting || ingestProgress > 0) && ingestProgress < 100 && (
                <div className="mt-4">
                    <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-600 dark:text-slate-300">{ingestMessage}</span>
                        <span className="text-primary-600">{ingestProgress}%</span>
                    </div>
                    <div className="w-full bg-slate-200 dark:bg-gray-600 rounded-full h-2">
                        <div className="bg-primary-600 h-2 rounded-full transition-all" style={{ width: `${ingestProgress}%` }} />
                    </div>
                </div>
            )}
            {kgJob && (
                <div className="mt-4">
                    <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-600 dark:text-slate-300">
                            🔄 知识图谱摄取进行中（分析已完成，后台建图，可先浏览其他页面）…
                        </span>
                        <span className="text-purple-600">{parseInt(kgJob.progress, 10) || 0}%</span>
                    </div>
                    <div className="w-full bg-slate-200 dark:bg-gray-600 rounded-full h-2">
                        <div className="bg-purple-600 h-2 rounded-full transition-all"
                             style={{ width: `${parseInt(kgJob.progress, 10) || 2}%` }} />
                    </div>
                </div>
            )}
            {ingestResult && (
                <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-200 rounded">
                    ✅ {ingestResult.message}
                </div>
            )}
        </Card>
    );

    const tabs = [
        { id: 'graph', label: '🕸️ 图谱可视化' },
        { id: 'people', label: '人员关系图' },
        { id: 'priorities', label: '优先级关系网' },
        { id: 'search', label: '🔍 搜索' },
        { id: 'entities', label: '📦 实体' },
        { id: 'relationships', label: '🔗 关系' },
    ];

    const renderTabs = () => (
        <div className="flex flex-wrap border-b border-slate-200 dark:border-slate-700 mb-6 gap-1">
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === tab.id
                        ? 'border-blue-500 text-primary-600 dark:text-primary-400'
                        : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400'
                        }`}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );

    // ── Graph Visualization Tab ──────────────────────────────────────────────────
    const renderGraph = () => {
        const hasData = graphData.nodes.length > 0;

        return (
            <div>
                {/* Toolbar */}
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-slate-500 dark:text-slate-400">
                            {hasData
                                ? `${graphData.nodes.length} 节点 · ${graphData.links.length} 关系`
                                : graphConnected ? '点击"加载图谱"查看知识图谱' : 'Neo4j 未连接，无法加载图谱'}
                        </span>
                        {hasData && <span className="text-xs text-amber-700 dark:text-amber-300">连线为机器提取的待核验关系；点击连线查看来源</span>}
                        {hasData && (
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-slate-400">最多节点:</span>
                                <select
                                    value={maxNodes}
                                    onChange={(e) => setMaxNodes(Number(e.target.value))}
                                    className="text-xs px-2 py-1 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                                >
                                    {[100, 200, 300, 500].map(v => <option key={v} value={v}>{v}</option>)}
                                </select>
                            </div>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <Button
                            size="sm"
                            onClick={fetchGraphData}
                            disabled={!graphConnected || graphLoading}
                        >
                            {graphLoading ? <><Spinner size="sm" />&nbsp;加载中...</> : '加载图谱'}
                        </Button>
                        {hasData && (
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => { setSelectedNode(null); closeRelationship(); graphRef.current?.zoomToFit(400); }}
                            >
                                重置视图
                            </Button>
                        )}
                    </div>
                </div>

                {!taskId ? (
                    <div className="flex flex-col items-center justify-center h-80 text-slate-400">
                        <span className="text-5xl mb-3">🕸️</span>
                        <p>请先选择一个任务</p>
                    </div>
                ) : graphLoading ? (
                    <div className="flex flex-col items-center justify-center h-80 gap-4 text-slate-500">
                        <Spinner size="lg" />
                        <p>正在加载图谱数据...</p>
                    </div>
                ) : !hasData ? (
                    <div className="flex flex-col items-center justify-center h-80 text-slate-400">
                        <span className="text-5xl mb-3">📭</span>
                        <p className="mb-2">暂无图谱数据</p>
                        <p className="text-sm">请先点击“导入数据”，再点击“加载图谱”</p>
                    </div>
                ) : (
                    <div className="flex gap-4">
                        {/* Graph Canvas */}
                        <div
                            ref={graphContainerRef}
                            className="min-w-0 flex-1 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700"
                            style={{ background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)', minHeight: 560 }}
                        >
                            <ForceGraph2D
                                ref={graphRef}
                                graphData={graphData}
                                width={graphWidth}
                                height={560}
                                backgroundColor="transparent"
                                nodeLabel={(n) => `${escapeGraphTooltip(n.name)}<br>${n.summary ? escapeGraphTooltip(n.summary.substring(0, 80)) + '…' : ''}`}
                                nodeColor={(n) => {
                                    if (highlightNodes.size === 0) return getNodeColor(n.label);
                                    return highlightNodes.has(n.id) ? getNodeColor(n.label) : 'rgba(148,163,184,0.2)';
                                }}
                                nodeRelSize={5}
                                nodeVal={(n) => highlightNodes.has(n.id) ? 2 : 1}
                                linkColor={(l) => {
                                    if (highlightLinks.size === 0) return 'rgba(148,163,184,0.3)';
                                    return highlightLinks.has(l) ? 'rgba(99,102,241,0.8)' : 'rgba(148,163,184,0.08)';
                                }}
                                linkWidth={(l) => highlightLinks.has(l) ? 2 : 0.8}
                                linkDirectionalArrowLength={4}
                                linkDirectionalArrowRelPos={1}
                                linkDirectionalParticles={(l) => highlightLinks.has(l) ? 3 : 0}
                                linkDirectionalParticleSpeed={0.005}
                                linkDirectionalParticleColor={() => '#a5b4fc'}
                                linkLabel={(l) => `${escapeGraphTooltip(l.label)} · 机器提取，点击查看来源`}
                                onNodeClick={handleNodeClick}
                                onLinkClick={openRelationship}
                                onNodeHover={handleNodeHover}
                                onBackgroundClick={() => {
                                    setSelectedNode(null);
                                    closeRelationship();
                                }}
                                nodeCanvasObject={(node, ctx, globalScale) => {
                                    const r = highlightNodes.size === 0 || highlightNodes.has(node.id) ? 5 : 3;
                                    const color = highlightNodes.size === 0 || highlightNodes.has(node.id)
                                        ? getNodeColor(node.label)
                                        : 'rgba(148,163,184,0.2)';

                                    // Glow for highlighted
                                    if (highlightNodes.has(node.id) && highlightNodes.size > 0) {
                                        ctx.beginPath();
                                        ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI);
                                        ctx.fillStyle = color + '33';
                                        ctx.fill();
                                    }

                                    // Circle
                                    ctx.beginPath();
                                    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
                                    ctx.fillStyle = color;
                                    ctx.fill();

                                    // Selected ring
                                    if (selectedNode?.id === node.id) {
                                        ctx.beginPath();
                                        ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
                                        ctx.strokeStyle = '#ffffff';
                                        ctx.lineWidth = 1.5;
                                        ctx.stroke();
                                    }

                                    // Label when zoomed in enough
                                    if (globalScale >= 1.5) {
                                        const label = node.name?.length > 18 ? node.name.substring(0, 18) + '…' : node.name;
                                        ctx.font = `${Math.max(10 / globalScale, 3)}px Inter, sans-serif`;
                                        ctx.fillStyle = 'rgba(255,255,255,0.9)';
                                        ctx.textAlign = 'center';
                                        ctx.fillText(label, node.x, node.y + r + 6 / globalScale);
                                    }
                                }}
                                cooldownTicks={80}
                                onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
                            />
                        </div>

                        {/* Node detail panel */}
                        <div className={selectedRelationship ? 'w-[420px] max-w-[44vw] shrink-0' : 'w-72 shrink-0'}>
                            {selectedRelationship ? (
                                <RelationshipTracePanel
                                    taskId={taskId}
                                    trace={relationshipTrace}
                                    loading={traceLoading}
                                    error={traceError}
                                    onClose={closeRelationship}
                                />
                            ) : selectedNode ? (
                                <motion.div
                                    initial={{ opacity: 0, x: 20 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 h-full"
                                >
                                    <div className="flex items-start justify-between mb-3">
                                        <div className="flex items-center gap-2">
                                            <div className="w-3 h-3 rounded-full" style={{ background: getNodeColor(selectedNode.label) }} />
                                            <Badge variant="blue">{selectedNode.label}</Badge>
                                        </div>
                                        <button
                                            onClick={() => { setSelectedNode(null); setHighlightNodes(new Set()); setHighlightLinks(new Set()); }}
                                            className="text-slate-400 hover:text-slate-600 text-lg leading-none"
                                        >×</button>
                                    </div>
                                    <h4 className="font-semibold text-slate-900 dark:text-white text-sm mb-2 break-all">
                                        {selectedNode.name}
                                    </h4>
                                    <p className="text-xs text-slate-500 dark:text-slate-400 font-mono mb-3">
                                        {selectedNode.id?.substring(0, 12)}...
                                    </p>
                                    {selectedNode.summary && (
                                        <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded-xl text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                                            {selectedNode.summary}
                                        </div>
                                    )}
                                    <div className="mt-3 text-xs text-slate-400">
                                        <span className="font-medium">邻居节点:</span>&nbsp;
                                        {highlightNodes.size - 1} 个
                                    </div>
                                </motion.div>
                            ) : (
                                <div className="rounded-2xl border border-dashed border-slate-200 dark:border-slate-700 h-full flex flex-col items-center justify-center text-slate-400 text-sm gap-2 p-6" style={{ minHeight: 200 }}>
                                    <span className="text-3xl">👆</span>
                                    <p className="text-center">点击节点<br />查看详情</p>
                                    <div className="mt-4 w-full space-y-1.5">
                                        {Object.entries(NODE_COLORS).filter(([k]) => k !== 'default').map(([label, color]) => (
                                            <div key={label} className="flex items-center gap-2">
                                                <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                                                <span className="text-xs text-slate-500">{label}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    // ── Search Tab ───────────────────────────────────────────────────────────────
    const renderSearch = () => (
        <SearchTab
            taskId={taskId}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            handleSearch={handleSearch}
            searching={searching}
            searchResults={searchResults}
        />
    );

    // ── Entities Tab ─────────────────────────────────────────────────────────────
    const renderEntities = () => (
        <EntitiesTab
            taskId={taskId}
            entities={entities}
            entitiesTotalCount={entitiesTotalCount}
            entitiesPage={entitiesPage}
            fetchEntities={fetchEntities}
            PAGE_SIZE={PAGE_SIZE}
        />
    );

    // ── Relationships Tab ─────────────────────────────────────────────────────────
    const renderRelationships = () => (
        <RelationshipsTab
            taskId={taskId}
            relationships={relationships}
            relationshipsTotalCount={relationshipsTotalCount}
            relationshipsPage={relationshipsPage}
            fetchRelationships={fetchRelationships}
            onTrace={(item) => {
                setActiveTab('graph');
                openRelationship({ id: item.id, source: item.source_id, target: item.target_id, label: item.type });
            }}
            PAGE_SIZE={PAGE_SIZE}
        />
    );

    return (
        <div className="p-6" aria-busy={loading}>
            <div className="mb-6">
                <motion.h1
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4 }}
                    className="text-2xl font-bold text-slate-900 dark:text-white"
                >
                    知识图谱
                </motion.h1>
                <p className="mt-1 text-slate-500 dark:text-slate-400">
                    每个镜像任务有独立的知识图谱 &mdash; 选择任务查看或导入图谱数据
                </p>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded-xl">
                    {error}
                    <button onClick={() => setError(null)} className="ml-4 text-sm underline">关闭</button>
                </div>
            )}

            {renderTaskSelector()}
            {taskId && renderManagementToolbar()}
            {taskId && renderStatus()}
            {taskId && renderTabs()}

            <Card>
                {activeTab === 'graph' && renderGraph()}
                {activeTab === 'people' && <PeopleGraphPanel key={`${taskId}:people`} taskId={taskId} view="people" initialRunId={selectedPeopleRun} onRunChange={selectPeopleRun} />}
                {activeTab === 'priorities' && <PeopleGraphPanel key={`${taskId}:relations`} taskId={taskId} view="relations" initialRunId={selectedPeopleRun} onRunChange={selectPeopleRun} />}
                {activeTab === 'search' && renderSearch()}
                {activeTab === 'entities' && renderEntities()}
                {activeTab === 'relationships' && renderRelationships()}
            </Card>
        </div>
    );
}
