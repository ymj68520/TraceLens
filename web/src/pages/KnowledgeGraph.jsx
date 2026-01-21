import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../hooks/useTranslation';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import {
    ingestTaskData,
    searchGraph,
    listEntities,
    listRelationships,
    getGraphitiStatus,
} from '../services/graphitiService';
import { listTasks } from '../services/taskService';

/**
 * 知识图谱页面
 * 用于浏览和搜索 Graphiti 知识图谱中的实体和关系
 */
export default function KnowledgeGraph() {
    const { t } = useTranslation();

    // 状态管理
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

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
    const [tasks, setTasks] = useState([]);
    const [selectedTaskId, setSelectedTaskId] = useState('');
    const [ingesting, setIngesting] = useState(false);
    const [ingestResult, setIngestResult] = useState(null);

    // 当前视图
    const [activeTab, setActiveTab] = useState('search');

    // 页面大小
    const PAGE_SIZE = 20;

    // 获取 Graphiti 状态
    const fetchStatus = useCallback(async () => {
        try {
            const result = await getGraphitiStatus();
            setStatus(result);
            setError(null);
        } catch (err) {
            console.error('Failed to fetch Graphiti status:', err);
            setError('无法连接到知识图谱服务');
            setStatus({ status: 'error', neo4j_connected: false });
        } finally {
            setLoading(false);
        }
    }, []);

    // 获取任务列表
    const fetchTasks = useCallback(async () => {
        try {
            const result = await listTasks({ status: 'COMPLETED' });
            setTasks(result.tasks || []);
        } catch (err) {
            console.error('Failed to fetch tasks:', err);
        }
    }, []);

    // 初始化
    useEffect(() => {
        fetchStatus();
        fetchTasks();
    }, [fetchStatus, fetchTasks]);

    // 搜索知识图谱
    const handleSearch = async (e) => {
        e.preventDefault();
        if (!searchQuery.trim()) return;

        setSearching(true);
        try {
            const result = await searchGraph(searchQuery, { limit: 50 });
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
        setLoading(true);
        try {
            const result = await listEntities({ page, pageSize: PAGE_SIZE });
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
        setLoading(true);
        try {
            const result = await listRelationships({ page, pageSize: PAGE_SIZE });
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

    // 导入任务数据
    const handleIngest = async () => {
        if (!selectedTaskId) {
            setError('请选择要导入的任务');
            return;
        }

        setIngesting(true);
        setIngestResult(null);
        try {
            const result = await ingestTaskData(selectedTaskId, {
                includeLLMDescriptions: true,
            });
            setIngestResult(result);
            // 刷新状态
            await fetchStatus();
        } catch (err) {
            console.error('Ingestion failed:', err);
            setError('导入失败: ' + (err.message || '未知错误'));
        } finally {
            setIngesting(false);
        }
    };

    // 切换标签页时加载数据
    useEffect(() => {
        if (activeTab === 'entities') {
            fetchEntities(1);
        } else if (activeTab === 'relationships') {
            fetchRelationships(1);
        }
    }, [activeTab]);

    // 渲染连接状态
    const renderStatus = () => (
        <Card className="mb-6">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className={`w-3 h-3 rounded-full ${status?.neo4j_connected ? 'bg-green-500' : 'bg-red-500'
                        }`} />
                    <div>
                        <h3 className="font-medium text-gray-900 dark:text-white">
                            Neo4j 连接状态
                        </h3>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                            {status?.neo4j_connected ? '已连接' : '未连接'}
                        </p>
                    </div>
                </div>
                <div className="grid grid-cols-2 gap-8 text-center">
                    <div>
                        <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                            {status?.total_entities || 0}
                        </div>
                        <div className="text-sm text-gray-500 dark:text-gray-400">实体数量</div>
                    </div>
                    <div>
                        <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                            {status?.total_relationships || 0}
                        </div>
                        <div className="text-sm text-gray-500 dark:text-gray-400">关系数量</div>
                    </div>
                </div>
            </div>
        </Card>
    );

    // 渲染标签页导航
    const renderTabs = () => (
        <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
            {[
                { id: 'search', label: '搜索' },
                { id: 'entities', label: '实体' },
                { id: 'relationships', label: '关系' },
                { id: 'ingest', label: '导入数据' },
            ].map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === tab.id
                        ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                        : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
                        }`}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );

    // 渲染搜索视图
    const renderSearch = () => (
        <div>
            <form onSubmit={handleSearch} className="mb-6">
                <div className="flex gap-4">
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="搜索实体或关系..."
                        className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <Button type="submit" disabled={searching || !searchQuery.trim()}>
                        {searching ? '搜索中...' : '搜索'}
                    </Button>
                </div>
            </form>

            {searchResults.length > 0 ? (
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
                                        <p className="text-sm text-gray-500 dark:text-gray-400">
                                            类型: {result.entity_type}
                                        </p>
                                        {result.properties && Object.keys(result.properties).length > 0 && (
                                            <div className="mt-2 text-sm">
                                                {Object.entries(result.properties).slice(0, 3).map(([key, value]) => (
                                                    <div key={key} className="text-gray-600 dark:text-gray-300">
                                                        <span className="font-medium">{key}:</span> {String(value).substring(0, 100)}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <div className="text-sm text-gray-400">
                                        相关度: {(result.score * 100).toFixed(1)}%
                                    </div>
                                </div>
                            </Card>
                        ))}
                    </div>
                </div>
            ) : searchQuery && !searching ? (
                <p className="text-center text-gray-500 dark:text-gray-400 py-8">
                    没有找到相关结果
                </p>
            ) : null}
        </div>
    );

    // 渲染实体列表
    const renderEntities = () => (
        <div>
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-gray-900 dark:text-white">
                    实体列表 ({entitiesTotalCount})
                </h3>
                <div className="flex gap-2">
                    <Button
                        variant="outline"
                        onClick={() => fetchEntities(entitiesPage - 1)}
                        disabled={entitiesPage <= 1}
                    >
                        上一页
                    </Button>
                    <span className="px-4 py-2 text-gray-600 dark:text-gray-300">
                        {entitiesPage} / {Math.ceil(entitiesTotalCount / PAGE_SIZE) || 1}
                    </span>
                    <Button
                        variant="outline"
                        onClick={() => fetchEntities(entitiesPage + 1)}
                        disabled={entitiesPage >= Math.ceil(entitiesTotalCount / PAGE_SIZE)}
                    >
                        下一页
                    </Button>
                </div>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                    <thead className="text-xs uppercase bg-gray-50 dark:bg-gray-700">
                        <tr>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">ID</th>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">名称</th>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">类型</th>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">属性</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                        {entities.map((entity, index) => (
                            <tr key={entity.id || index} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                                <td className="px-4 py-3 font-mono text-xs text-gray-500 dark:text-gray-400">
                                    {entity.id?.substring(0, 8)}...
                                </td>
                                <td className="px-4 py-3 text-gray-900 dark:text-white">
                                    {entity.name || '-'}
                                </td>
                                <td className="px-4 py-3">
                                    <span className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                                        {entity.type || 'unknown'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                                    {entity.properties ? Object.keys(entity.properties).length : 0} 个属性
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {entities.length === 0 && (
                    <p className="text-center text-gray-500 dark:text-gray-400 py-8">
                        暂无实体数据
                    </p>
                )}
            </div>
        </div>
    );

    // 渲染关系列表
    const renderRelationships = () => (
        <div>
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-gray-900 dark:text-white">
                    关系列表 ({relationshipsTotalCount})
                </h3>
                <div className="flex gap-2">
                    <Button
                        variant="outline"
                        onClick={() => fetchRelationships(relationshipsPage - 1)}
                        disabled={relationshipsPage <= 1}
                    >
                        上一页
                    </Button>
                    <span className="px-4 py-2 text-gray-600 dark:text-gray-300">
                        {relationshipsPage} / {Math.ceil(relationshipsTotalCount / PAGE_SIZE) || 1}
                    </span>
                    <Button
                        variant="outline"
                        onClick={() => fetchRelationships(relationshipsPage + 1)}
                        disabled={relationshipsPage >= Math.ceil(relationshipsTotalCount / PAGE_SIZE)}
                    >
                        下一页
                    </Button>
                </div>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                    <thead className="text-xs uppercase bg-gray-50 dark:bg-gray-700">
                        <tr>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">源实体</th>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">关系类型</th>
                            <th className="px-4 py-3 text-gray-600 dark:text-gray-300">目标实体</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                        {relationships.map((rel, index) => (
                            <tr key={rel.id || index} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                                <td className="px-4 py-3 text-gray-900 dark:text-white">
                                    {rel.source_name || rel.source_id?.substring(0, 8)}
                                </td>
                                <td className="px-4 py-3">
                                    <span className="px-2 py-1 text-xs rounded bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200">
                                        {rel.type || 'RELATED_TO'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-gray-900 dark:text-white">
                                    {rel.target_name || rel.target_id?.substring(0, 8)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {relationships.length === 0 && (
                    <p className="text-center text-gray-500 dark:text-gray-400 py-8">
                        暂无关系数据
                    </p>
                )}
            </div>
        </div>
    );

    // 渲染导入视图
    const renderIngest = () => (
        <div className="max-w-xl">
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">
                导入任务数据到知识图谱
            </h3>
            <p className="text-gray-600 dark:text-gray-400 mb-6">
                选择一个已完成的分析任务，将其取证数据导入到 Graphiti 知识图谱中进行关联分析。
            </p>

            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                        选择任务
                    </label>
                    <select
                        value={selectedTaskId}
                        onChange={(e) => setSelectedTaskId(e.target.value)}
                        className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                        <option value="">请选择任务...</option>
                        {tasks.map((task) => (
                            <option key={task.id} value={task.id}>
                                {task.name || task.id} - {task.image_path?.split('/').pop()}
                            </option>
                        ))}
                    </select>
                </div>

                <Button
                    onClick={handleIngest}
                    disabled={!selectedTaskId || ingesting}
                    className="w-full"
                >
                    {ingesting ? '导入中...' : '开始导入'}
                </Button>

                {ingestResult && (
                    <Card className="mt-4 bg-green-50 dark:bg-green-900/20">
                        <div className="flex items-center gap-2 text-green-800 dark:text-green-200">
                            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                            </svg>
                            <span className="font-medium">{ingestResult.message}</span>
                        </div>
                        {ingestResult.job_id && (
                            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                                任务 ID: {ingestResult.job_id}
                            </p>
                        )}
                    </Card>
                )}
            </div>
        </div>
    );

    return (
        <div className="p-6">
            <div className="mb-6">
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                    知识图谱
                </h1>
                <p className="mt-1 text-gray-500 dark:text-gray-400">
                    使用 Graphiti 进行取证数据关联分析
                </p>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded-lg">
                    {error}
                    <button
                        onClick={() => setError(null)}
                        className="ml-4 text-sm underline"
                    >
                        关闭
                    </button>
                </div>
            )}

            {renderStatus()}
            {renderTabs()}

            <Card>
                {activeTab === 'search' && renderSearch()}
                {activeTab === 'entities' && renderEntities()}
                {activeTab === 'relationships' && renderRelationships()}
                {activeTab === 'ingest' && renderIngest()}
            </Card>
        </div>
    );
}
