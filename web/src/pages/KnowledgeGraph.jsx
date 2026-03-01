import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
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
} from '../services/graphitiService';

/**
 * 知识图谱页面 - 任务特定
 * 每个任务/镜像有独立的知识图谱，切换任务时显示对应图谱
 */
export default function KnowledgeGraph() {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');
    const { tasks } = useSelector((state) => state.tasks);

    // 状态管理
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // 任务图谱列表
    const [taskGraphs, setTaskGraphs] = useState([]);

    // 搜索状态
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [searching, setSearching] = useState(false);

    // 实体列表状态
    const [entities, setEntities] = useState([]);
    const [entitiesPage, setEntitiesPage] = useState(1);
    const [entitiesTotalCount, setEntitiesTotalCount] = useState(0);

    // 关系列表状态
    const [relationships, setRelationships] = useState([]);
    const [relationshipsPage, setRelationshipsPage] = useState(1);
    const [relationshipsTotalCount, setRelationshipsTotalCount] = useState(0);

    // 导入状态
    const [ingesting, setIngesting] = useState(false);
    const [ingestResult, setIngestResult] = useState(null);
    const [ingestProgress, setIngestProgress] = useState(0);
    const [ingestMessage, setIngestMessage] = useState('');

    // 当前视图
    const [activeTab, setActiveTab] = useState('search');

    const PAGE_SIZE = 20;
    const currentTask = tasks.find((t) => t.id === taskId);

    // 获取任务特定的 Graphiti 状态
    const fetchStatus = useCallback(async () => {
        try {
            const result = await getGraphitiStatus(taskId);
            setStatus(result);
            setError(null);
        } catch (err) {
            console.error('Failed to fetch Graphiti status:', err);
            setError('无法连接到知识图谱服务');
            setStatus({ status: 'error', neo4j_connected: false });
        } finally {
            setLoading(false);
        }
    }, [taskId]);

    // 获取有图谱数据的任务列表
    const fetchTaskGraphs = useCallback(async () => {
        try {
            const result = await listTaskGraphs();
            setTaskGraphs(result.task_ids || []);
        } catch (err) {
            console.error('Failed to fetch task graphs:', err);
        }
    }, []);

    // 初始化
    useEffect(() => {
        fetchStatus();
        fetchTaskGraphs();
    }, [fetchStatus, fetchTaskGraphs]);

    // 任务改变时重置数据
    useEffect(() => {
        setSearchResults([]);
        setEntities([]);
        setRelationships([]);
        setEntitiesPage(1);
        setRelationshipsPage(1);
        if (taskId) {
            fetchStatus();
        }
    }, [taskId, fetchStatus]);

    // 搜索知识图谱
    const handleSearch = async (e) => {
        e.preventDefault();
        if (!searchQuery.trim() || !taskId) return;

        setSearching(true);
        try {
            const result = await searchGraph(searchQuery, taskId, { limit: 50 });
            setSearchResults(result.results || []);
        } catch (err) {
            console.error('Search failed:', err);
            setError('搜索失败: ' + (err.message || '未知错误'));
        } finally {
            setSearching(false);
        }
    };

    // 获取实体列表
    const fetchEntities = async (page = 1) => {
        if (!taskId) return;
        setLoading(true);
        try {
            const result = await listEntities(taskId, { page, pageSize: PAGE_SIZE });
            setEntities(result.entities || []);
            setEntitiesTotalCount(result.total_count || 0);
            setEntitiesPage(page);
        } catch (err) {
            console.error('Failed to fetch entities:', err);
            setError('获取实体列表失败');
        } finally {
            setLoading(false);
        }
    };

    // 获取关系列表
    const fetchRelationships = async (page = 1) => {
        if (!taskId) return;
        setLoading(true);
        try {
            const result = await listRelationships(taskId, { page, pageSize: PAGE_SIZE });
            setRelationships(result.relationships || []);
            setRelationshipsTotalCount(result.total_count || 0);
            setRelationshipsPage(page);
        } catch (err) {
            console.error('Failed to fetch relationships:', err);
            setError('获取关系列表失败');
        } finally {
            setLoading(false);
        }
    };

    // 导入当前任务数据
    const handleIngest = async () => {
        if (!taskId) {
            setError('请先选择一个任务');
            return;
        }

        setIngesting(true);
        setIngestResult(null);
        setIngestProgress(0);
        setIngestMessage('正在准备导入数据...');
        try {
            const result = await ingestTaskData(taskId, {
                includeLLMDescriptions: true,
            });
            // If there's a job_id, we could poll — for now just show progress
            if (result.job_id) {
                setIngestMessage('导入进行中...');
                // Simulate progress tracking
                let progress = 10;
                const progressInterval = setInterval(async () => {
                    progress = Math.min(progress + 15, 90);
                    setIngestProgress(progress);
                    setIngestMessage(`已处理 ${progress}%...`);
                }, 2000);

                // Wait a bit then fetch final status
                setTimeout(async () => {
                    clearInterval(progressInterval);
                    setIngestProgress(100);
                    setIngestMessage('导入完成！');
                    setIngestResult(result);
                    await fetchStatus();
                    await fetchTaskGraphs();
                }, 10000);
            } else {
                setIngestProgress(100);
                setIngestMessage('导入完成！');
                setIngestResult(result);
                await fetchStatus();
                await fetchTaskGraphs();
            }
        } catch (err) {
            console.error('Ingestion failed:', err);
            setError('导入失败: ' + (err.message || '未知错误'));
            setIngestProgress(0);
            setIngestMessage('');
        } finally {
            setIngesting(false);
        }
    };

    // 删除图谱
    const handleDeleteGraph = async () => {
        if (!taskId) return;
        if (!confirm('确定要删除此任务的知识图谱数据吗？')) return;

        try {
            await deleteTaskGraph(taskId);
            await fetchStatus();
            await fetchTaskGraphs();
            setIngestResult({ message: '图谱已删除' });
        } catch (err) {
            setError('删除失败: ' + (err.message || '未知错误'));
        }
    };

    // 切换任务
    const handleTaskChange = (newTaskId) => {
        setSearchParams({ task_id: newTaskId });
    };

    // 切换标签页时加载数据
    useEffect(() => {
        if (!taskId) return;
        if (activeTab === 'entities') {
            fetchEntities(1);
        } else if (activeTab === 'relationships') {
            fetchRelationships(1);
        }
    }, [activeTab, taskId]);

    // 任务选择器
    const renderTaskSelector = () => (
        <Card className="mb-6">
            <div className="flex items-center gap-4">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    选择镜像任务:
                </label>
                <select
                    value={taskId || ''}
                    onChange={(e) => handleTaskChange(e.target.value)}
                    className="flex-1 max-w-md px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                >
                    <option value="">请选择任务...</option>
                    {tasks.filter(t => t.status === 'completed').map((task) => (
                        <option key={task.id} value={task.id}>
                            {task.image_path?.split('/').pop() || task.id}
                            {taskGraphs.includes(task.id) && ' ✓ (有图谱)'}
                        </option>
                    ))}
                </select>
                {taskId && taskGraphs.includes(taskId) && (
                    <Badge variant="green">有图谱数据</Badge>
                )}
            </div>
        </Card>
    );

    // 渲染连接状态
    const renderStatus = () => (
        <Card className="mb-6">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className={`w-3 h-3 rounded-full ${status?.neo4j_connected ? 'bg-green-500' : 'bg-red-500'}`} />
                    <div>
                        <h3 className="font-medium text-gray-900 dark:text-white">
                            {currentTask?.image_path?.split('/').pop() || '未选择任务'}
                        </h3>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                            Neo4j: {status?.neo4j_connected ? '已连接' : '未连接'}
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-8">
                    <div className="text-center">
                        <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                            {status?.total_entities || 0}
                        </div>
                        <div className="text-sm text-gray-500">实体</div>
                    </div>
                    <div className="text-center">
                        <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                            {status?.total_relationships || 0}
                        </div>
                        <div className="text-sm text-gray-500">关系</div>
                    </div>
                    <div className="flex gap-2">
                        <Button size="sm" onClick={handleIngest} disabled={!taskId || ingesting}>
                            {ingesting ? <Spinner size="sm" /> : '导入数据'}
                        </Button>
                        {taskGraphs.includes(taskId) && (
                            <Button size="sm" variant="outline" onClick={handleDeleteGraph}>
                                删除图谱
                            </Button>
                        )}
                    </div>
                </div>
            </div>
            {/* Ingest Progress Bar */}
            {(ingesting || ingestProgress > 0) && ingestProgress < 100 && (
                <div className="mt-4">
                    <div className="flex justify-between text-sm mb-1">
                        <span className="text-gray-600 dark:text-gray-300">{ingestMessage}</span>
                        <span className="text-blue-600">{ingestProgress}%</span>
                    </div>
                    <div className="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-2">
                        <div className="bg-blue-600 h-2 rounded-full transition-all" style={{ width: `${ingestProgress}%` }} />
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

    // 渲染标签页
    const renderTabs = () => (
        <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
            {[
                { id: 'search', label: '搜索' },
                { id: 'entities', label: '实体' },
                { id: 'relationships', label: '关系' },
            ].map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === tab.id
                        ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                        : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
                        }`}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );

    // 搜索视图
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
                        className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white disabled:opacity-50"
                    />
                    <Button type="submit" disabled={searching || !searchQuery.trim() || !taskId}>
                        {searching ? '搜索中...' : '搜索'}
                    </Button>
                </div>
            </form>

            {!taskId ? (
                <p className="text-center text-gray-500 py-8">请先选择一个任务</p>
            ) : searchResults.length > 0 ? (
                <div className="space-y-4">
                    <h3 className="text-lg font-medium text-gray-900 dark:text-white">
                        搜索结果 ({searchResults.length})
                    </h3>
                    <div className="grid gap-4">
                        {searchResults.map((result, index) => (
                            <Card key={result.entity_id || index}>
                                <div className="flex justify-between items-start">
                                    <div>
                                        <h4 className="font-medium text-gray-900 dark:text-white">
                                            {result.name || '未命名实体'}
                                        </h4>
                                        <Badge variant="blue">{result.entity_type}</Badge>
                                    </div>
                                    <span className="text-sm text-gray-400">
                                        相关度: {(result.score * 100).toFixed(1)}%
                                    </span>
                                </div>
                            </Card>
                        ))}
                    </div>
                </div>
            ) : null}
        </div>
    );

    // 实体列表
    const renderEntities = () => (
        <div>
            {!taskId ? (
                <p className="text-center text-gray-500 py-8">请先选择一个任务</p>
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
                        <thead className="bg-gray-50 dark:bg-gray-700">
                            <tr>
                                <th className="px-4 py-3 text-left">ID</th>
                                <th className="px-4 py-3 text-left">名称</th>
                                <th className="px-4 py-3 text-left">类型</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {entities.map((e, i) => (
                                <tr key={e.id || i} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                                    <td className="px-4 py-3 font-mono text-xs">{e.id?.substring(0, 8)}...</td>
                                    <td className="px-4 py-3">{e.name || '-'}</td>
                                    <td className="px-4 py-3"><Badge variant="blue">{e.type}</Badge></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {entities.length === 0 && <p className="text-center text-gray-500 py-8">暂无实体数据</p>}
                </>
            )}
        </div>
    );

    // 关系列表
    const renderRelationships = () => (
        <div>
            {!taskId ? (
                <p className="text-center text-gray-500 py-8">请先选择一个任务</p>
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
                        <thead className="bg-gray-50 dark:bg-gray-700">
                            <tr>
                                <th className="px-4 py-3 text-left">源实体</th>
                                <th className="px-4 py-3 text-left">关系</th>
                                <th className="px-4 py-3 text-left">目标实体</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {relationships.map((r, i) => (
                                <tr key={r.id || i} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                                    <td className="px-4 py-3">{r.source_name || r.source_id?.substring(0, 8)}</td>
                                    <td className="px-4 py-3"><Badge variant="purple">{r.type}</Badge></td>
                                    <td className="px-4 py-3">{r.target_name || r.target_id?.substring(0, 8)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {relationships.length === 0 && <p className="text-center text-gray-500 py-8">暂无关系数据</p>}
                </>
            )}
        </div>
    );

    return (
        <div className="p-6">
            <div className="mb-6">
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">知识图谱</h1>
                <p className="mt-1 text-gray-500 dark:text-gray-400">
                    每个镜像任务有独立的知识图谱 - 选择任务查看或导入图谱数据
                </p>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded-lg">
                    {error}
                    <button onClick={() => setError(null)} className="ml-4 text-sm underline">关闭</button>
                </div>
            )}

            {renderTaskSelector()}
            {taskId && renderStatus()}
            {taskId && renderTabs()}

            <Card>
                {activeTab === 'search' && renderSearch()}
                {activeTab === 'entities' && renderEntities()}
                {activeTab === 'relationships' && renderRelationships()}
            </Card>
        </div>
    );
}
