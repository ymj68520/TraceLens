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
} from '../services/graphitiService';

// Node color palette by label
const NODE_COLORS = {
    Entity: '#6366f1',
    File: '#06b6d4',
    Process: '#f59e0b',
    User: '#10b981',
    Network: '#ec4899',
    Registry: '#8b5cf6',
    Event: '#ef4444',
    Directory: '#14b8a6',
    default: '#94a3b8',
};

const getNodeColor = (label) => NODE_COLORS[label] || NODE_COLORS.default;

/**
 * 知识图谱页面 - 任务特定
 */
export default function KnowledgeGraph() {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');
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

    // Graph visualization
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [graphLoading, setGraphLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState(null);
    const [highlightNodes, setHighlightNodes] = useState(new Set());
    const [highlightLinks, setHighlightLinks] = useState(new Set());
    const [maxNodes, setMaxNodes] = useState(200);
    const graphRef = useRef(null);

    const [activeTab, setActiveTab] = useState('graph');
    const PAGE_SIZE = 20;
    const currentTask = tasks.find((t) => t.id === taskId);

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
        } catch { }
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
        if (taskId) fetchStatus();
    }, [taskId, fetchStatus]);

    // ── Graph visualization ──────────────────────────────────────────────────────
    const fetchGraphData = useCallback(async () => {
        if (!taskId) return;
        setGraphLoading(true);
        try {
            const result = await getGraphData(taskId, maxNodes);
            setGraphData({ nodes: result.nodes || [], links: result.links || [] });
        } catch (err) {
            setError('加载图谱数据失败: ' + (err.message || '未知错误'));
        } finally {
            setGraphLoading(false);
        }
    }, [taskId, maxNodes]);

    // Auto-load graph when tab switches to graph
    useEffect(() => {
        if (activeTab === 'graph' && taskId && graphData.nodes.length === 0 && !graphLoading) {
            fetchGraphData();
        }
    }, [activeTab, taskId]);

    const handleNodeClick = useCallback((node) => {
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
    }, [graphData]);

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

    const handleTaskChange = (newId) => setSearchParams({ task_id: newId });

    useEffect(() => {
        if (!taskId) return;
        if (activeTab === 'entities') fetchEntities(1);
        else if (activeTab === 'relationships') fetchRelationships(1);
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
                        <Button size="sm" onClick={handleIngest} disabled={!taskId || ingesting}>
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
            {ingestResult && (
                <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-200 rounded">
                    ✅ {ingestResult.message}
                </div>
            )}
        </Card>
    );

    const tabs = [
        { id: 'graph', label: '🕸️ 图谱可视化' },
        { id: 'search', label: '🔍 搜索' },
        { id: 'entities', label: '📦 实体' },
        { id: 'relationships', label: '🔗 关系' },
    ];

    const renderTabs = () => (
        <div className="flex border-b border-slate-200 dark:border-slate-700 mb-6 gap-1">
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
                                : '点击"加载图谱"查看知识图谱'}
                        </span>
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
                            disabled={!taskId || graphLoading}
                        >
                            {graphLoading ? <><Spinner size="sm" />&nbsp;加载中...</> : '加载图谱'}
                        </Button>
                        {hasData && (
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => { setSelectedNode(null); setHighlightNodes(new Set()); setHighlightLinks(new Set()); graphRef.current?.zoomToFit(400); }}
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
                        <p className="text-sm">请先点击"导入数据"，再点击"加载图谱"</p>
                    </div>
                ) : (
                    <div className="flex gap-4">
                        {/* Graph Canvas */}
                        <div
                            className="flex-1 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700"
                            style={{ background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)', minHeight: 560 }}
                        >
                            <ForceGraph2D
                                ref={graphRef}
                                graphData={graphData}
                                width={undefined}
                                height={560}
                                backgroundColor="transparent"
                                nodeLabel={(n) => `${n.name}\n${n.summary ? n.summary.substring(0, 80) + '...' : ''}`}
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
                                linkLabel={(l) => l.label}
                                onNodeClick={handleNodeClick}
                                onNodeHover={handleNodeHover}
                                onBackgroundClick={() => {
                                    setSelectedNode(null);
                                    setHighlightNodes(new Set());
                                    setHighlightLinks(new Set());
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
                        <div className="w-72 shrink-0">
                            {selectedNode ? (
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
        <div>
            <form onSubmit={handleSearch} className="mb-6">
                <div className="flex gap-4">
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="搜索实体或关系..."
                        disabled={!taskId}
                        className="flex-1 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-white disabled:opacity-50"
                    />
                    <Button type="submit" disabled={searching || !searchQuery.trim() || !taskId}>
                        {searching ? '搜索中...' : '搜索'}
                    </Button>
                </div>
            </form>
            {!taskId ? (
                <p className="text-center text-slate-500 py-8">请先选择一个任务</p>
            ) : searchResults.length > 0 ? (
                <div className="space-y-4">
                    <h3 className="text-lg font-medium text-slate-900 dark:text-white">搜索结果 ({searchResults.length})</h3>
                    <div className="grid gap-4">
                        {searchResults.map((result, index) => (
                            <Card key={result.entity_id || index}>
                                <div className="flex justify-between items-start">
                                    <div>
                                        <h4 className="font-medium text-slate-900 dark:text-white">{result.name || '未命名实体'}</h4>
                                        <Badge variant="blue">{result.entity_type}</Badge>
                                    </div>
                                    <span className="text-sm text-slate-400">相关度: {(result.score * 100).toFixed(1)}%</span>
                                </div>
                            </Card>
                        ))}
                    </div>
                </div>
            ) : searchResults.length === 0 && searchQuery && !searching ? (
                <p className="text-center text-slate-500 py-8">未找到相关实体</p>
            ) : null}
        </div>
    );

    // ── Entities Tab ─────────────────────────────────────────────────────────────
    const renderEntities = () => (
        <div>
            {!taskId ? (
                <p className="text-center text-slate-500 py-8">请先选择一个任务</p>
            ) : (
                <>
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-medium">实体 ({entitiesTotalCount})</h3>
                        <div className="flex gap-2">
                            <Button variant="outline" size="sm" onClick={() => fetchEntities(entitiesPage - 1)} disabled={entitiesPage <= 1}>上一页</Button>
                            <span className="px-3 py-1">{entitiesPage} / {Math.ceil(entitiesTotalCount / PAGE_SIZE) || 1}</span>
                            <Button variant="outline" size="sm" onClick={() => fetchEntities(entitiesPage + 1)} disabled={entitiesPage >= Math.ceil(entitiesTotalCount / PAGE_SIZE)}>下一页</Button>
                        </div>
                    </div>
                    <table className="w-full text-sm">
                        <thead className="bg-slate-50 dark:bg-slate-700">
                            <tr>
                                <th className="px-4 py-3 text-left">ID</th>
                                <th className="px-4 py-3 text-left">名称</th>
                                <th className="px-4 py-3 text-left">类型</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {entities.map((e, i) => (
                                <tr key={e.id || i} className="hover:bg-slate-50 dark:hover:bg-slate-800">
                                    <td className="px-4 py-3 font-mono text-xs">{e.id?.substring(0, 8)}...</td>
                                    <td className="px-4 py-3">{e.name || '-'}</td>
                                    <td className="px-4 py-3">
                                        <Badge variant="blue">
                                            {Array.isArray(e.type) ? (e.type[0] || 'Entity') : (e.type || 'Entity')}
                                        </Badge>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {entities.length === 0 && <p className="text-center text-slate-500 py-8">暂无实体数据</p>}
                </>
            )}
        </div>
    );

    // ── Relationships Tab ─────────────────────────────────────────────────────────
    const renderRelationships = () => (
        <div>
            {!taskId ? (
                <p className="text-center text-slate-500 py-8">请先选择一个任务</p>
            ) : (
                <>
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-medium">关系 ({relationshipsTotalCount})</h3>
                        <div className="flex gap-2">
                            <Button variant="outline" size="sm" onClick={() => fetchRelationships(relationshipsPage - 1)} disabled={relationshipsPage <= 1}>上一页</Button>
                            <span className="px-3 py-1">{relationshipsPage} / {Math.ceil(relationshipsTotalCount / PAGE_SIZE) || 1}</span>
                            <Button variant="outline" size="sm" onClick={() => fetchRelationships(relationshipsPage + 1)} disabled={relationshipsPage >= Math.ceil(relationshipsTotalCount / PAGE_SIZE)}>下一页</Button>
                        </div>
                    </div>
                    <table className="w-full text-sm">
                        <thead className="bg-slate-50 dark:bg-slate-700">
                            <tr>
                                <th className="px-4 py-3 text-left">源实体</th>
                                <th className="px-4 py-3 text-left">关系</th>
                                <th className="px-4 py-3 text-left">目标实体</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {relationships.map((r, i) => (
                                <tr key={r.id || i} className="hover:bg-slate-50 dark:hover:bg-slate-800">
                                    <td className="px-4 py-3">{r.source_name || r.source_id?.substring(0, 8)}</td>
                                    <td className="px-4 py-3"><Badge variant="purple">{r.type || 'RELATES_TO'}</Badge></td>
                                    <td className="px-4 py-3">{r.target_name || r.target_id?.substring(0, 8)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {relationships.length === 0 && <p className="text-center text-slate-500 py-8">暂无关系数据</p>}
                </>
            )}
        </div>
    );

    return (
        <div className="p-6">
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
            {taskId && renderStatus()}
            {taskId && renderTabs()}

            <Card>
                {activeTab === 'graph' && renderGraph()}
                {activeTab === 'search' && renderSearch()}
                {activeTab === 'entities' && renderEntities()}
                {activeTab === 'relationships' && renderRelationships()}
            </Card>
        </div>
    );
}
