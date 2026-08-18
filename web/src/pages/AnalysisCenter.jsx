import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Button from '../components/common/Button';
import { fetchTasks } from '../store/taskSlice';
import { fetchCases } from '../store/caseSlice';
import {
    clearRefreshFlag
} from '../store/intelligenceSlice';
import { useToast } from '../components/common/useToast';
import { toggleFileRelevance } from '../services/llmService';
import { reanalyzeFiles, getCaseAnalysisStatus, saveCaseDescription } from '../services/caseAnalysisService';
import {
    getClusterRelatedFiles,
    getFileRelatedClusters,
    formatAnomalyType,
    getAnomalySeverity,
    getAnomalyColorClass
} from '../services/associationService';
import { Layers } from 'lucide-react';

// Case-intelligence subcomponents (split for maintainability)
import ClusterFilesDrawer from '../components/case-intelligence/ClusterFilesDrawer';
import FileClustersDrawer from '../components/case-intelligence/FileClustersDrawer';

/**
 * 研判中心 (Analysis Center)
 *
 * 承载实际的研判工作区：案情背景、证据文件卡片、事件簇、报告预览，
 * 以及关联抽屉与重新研判弹窗。从 URL 读取 task_id / case_id 确定当前镜像。
 */
const AnalysisCenter = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const caseId = searchParams.get('case_id');
    const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
    const [activeContextId, setActiveContextId] = useState(caseId || urlTaskId);

    const navigate = useNavigate();
    const dispatch = useDispatch();
    const toast = useToast();
    const { tasks } = useSelector((state) => state.tasks);
    const { cases } = useSelector((state) => state.cases);
    const { refreshFlags } = useSelector((state) => state.intelligence);

    const activeCase = caseId ? cases.find(c => c.id === caseId) : null;

    const [caseDescription, setCaseDescription] = useState('');


    // --- State: Evidence (LLM Descriptions & Event Clusters) ---
    const [llmResults, setLlmResults] = useState(null);
    const [eventClusters, setEventClusters] = useState([]);
    const [searchQuery, setSearchQuery] = useState('');
    const [expandedItems, setExpandedItems] = useState({});
    const [selectedItems, setSelectedItems] = useState(new Set());
    const [viewMode, setViewMode] = useState('all'); // 'all', 'files', 'clusters'

    // --- State: Re-analysis Modal ---
    const [showReanalyzeModal, setShowReanalyzeModal] = useState(false);
    const [reanalyzeHint, setReanalyzeHint] = useState('');
    const [reanalyzeTargetFiles, setReanalyzeTargetFiles] = useState([]);
    const [reanalyzing, setReanalyzing] = useState(false);
    const [reanalyzeMessage, setReanalyzeMessage] = useState('');

    // --- State: Association Drawers (Cluster ↔ File) ---
    const [selectedClusterForFiles, setSelectedClusterForFiles] = useState(null);
    const [clusterRelatedFiles, setClusterRelatedFiles] = useState([]);
    const [loadingClusterFiles, setLoadingClusterFiles] = useState(false);
    const [selectedFileForClusters, setSelectedFileForClusters] = useState(null);
    const [fileRelatedClusters, setFileRelatedClusters] = useState([]);
    const [loadingFileClusters, setLoadingFileClusters] = useState(false);

    const currentTask = tasks.find((t) => t.id === activeContextId);

    // Initial load
    useEffect(() => {
        dispatch(fetchTasks({ status: 'all', priority: 'all' }));
        if (caseId) dispatch(fetchCases());
    }, [dispatch, caseId]);

    useEffect(() => {
        if (!activeContextId && (caseId || urlTaskId)) {
            setActiveContextId(caseId || urlTaskId);
        }
    }, [caseId, urlTaskId, activeContextId]);

    // Fetch basic case data
    const fetchData = useCallback(async () => {
        if (!activeContextId) return;
        try {
            console.log('Fetching task results for taskId:', activeContextId);

            // LLM 证据列表来自 C++ 后端的 /api/tasks/{id}/results 响应中的
            // llm_results.descriptions。后端会探测 _files.db（file_descriptions
            // 表，回退到 files.llm_* 列），因此无需依赖其它来源。
            let llmResultsData = null;
            try {
                const { getTaskResults } = await import('../services/taskService');
                const results = await getTaskResults(activeContextId);
                console.log('Task results:', results);
                if (results.llm_results) {
                    console.log('LLM results found in task results:', results.llm_results);
                    llmResultsData = results.llm_results;
                }
            } catch (err) {
                console.error('Failed to fetch task results:', err);
            }

            if (llmResultsData) {
                setLlmResults(llmResultsData);
            } else {
                console.log('No LLM results found');
                // 设置空的结果，确保UI正常显示
                setLlmResults({ descriptions: [] });
            }

            // Report generation is retired from this evidence workspace. Current
            // reports are generated explicitly from the R2 forensic report page.

            // 获取事件簇分析结果
            try {
                const { getAnalyzedEventClusters } = await import('../services/forensicsService');
                const clusterData = await getAnalyzedEventClusters(activeContextId);
                if (clusterData && clusterData.clusters && clusterData.clusters.length > 0) {
                    console.log('Event cluster analysis results:', clusterData.clusters);
                    setEventClusters(clusterData.clusters);
                } else {
                    setEventClusters([]);
                }
            } catch (err) {
                console.error('Failed to fetch cluster analysis results:', err);
                setEventClusters([]);
            }
        } catch (err) {
            console.error('Failed to fetch intelligence data:', err);
            // 确保即使出错也设置空的结果
            setLlmResults({ descriptions: [] });
        }
    }, [activeContextId]);

    // 初始加载数据
    useEffect(() => {
        fetchData();
    }, [fetchData]);

    // 监听刷新标志，当文件描述变化时刷新数据
    useEffect(() => {
        if (refreshFlags.files || refreshFlags.clusters) {
            console.log('Refresh flag detected, fetching data...');
            fetchData();
            // 清除刷新标志
            if (refreshFlags.files) {
                dispatch(clearRefreshFlag({ type: 'files' }));
            }
            if (refreshFlags.clusters) {
                dispatch(clearRefreshFlag({ type: 'clusters' }));
            }
        }
    }, [refreshFlags, fetchData, dispatch]);

    // --- Actions: Evidence workspace ---
    const saveDescription = async () => {
        if (!activeContextId || !caseDescription.trim()) return;
        try {
            await saveCaseDescription(activeContextId, caseDescription.trim());
            toast.success('案情描述已保存');
        } catch (err) {
            toast.error('保存案情描述失败: ' + (err?.message || err));
        }
    };

    const filteredDescriptions = useMemo(() => {
        const items = llmResults?.descriptions || [];
        if (!searchQuery) return items;
        const query = searchQuery.toLowerCase();
        return items.filter(item =>
            (item.file_path && item.file_path.toLowerCase().includes(query)) ||
            (item.summary && item.summary.toLowerCase().includes(query))
        );
    }, [llmResults, searchQuery]);

    const filteredClusters = useMemo(() => {
        if (!searchQuery) return eventClusters;
        const query = searchQuery.toLowerCase();
        return eventClusters.filter(cluster =>
            (cluster.event_type && cluster.event_type.toLowerCase().includes(query)) ||
            (cluster.parent_directory && cluster.parent_directory.toLowerCase().includes(query)) ||
            (cluster.llm_summary && cluster.llm_summary.toLowerCase().includes(query)) ||
            (cluster.file_path && cluster.file_path.toLowerCase().includes(query))
        );
    }, [eventClusters, searchQuery]);

    // 根据视图模式过滤显示内容
    const displayFiles = viewMode === 'clusters' ? [] : filteredDescriptions;
    const displayClusters = viewMode === 'files' ? [] : filteredClusters;

    const handleToggleRelevance = async (item, itemType, currentStatus) => {
        try {
            const newStatus = !currentStatus;

            if (itemType === 'file') {
                await toggleFileRelevance(activeContextId, item.file_path, newStatus);
                setLlmResults(prev => ({
                    ...prev,
                    descriptions: prev.descriptions.map(d => d.file_path === item.file_path ? { ...d, is_relevant: newStatus ? 1 : 0 } : d)
                }));
                toast.success(newStatus ? '已标记为案情证据' : '已剔除出报告');
            } else if (itemType === 'cluster') {
                // 切换事件簇的相关性
                const { pythonApi } = await import('../services/api');
                await pythonApi.post('/api/llm/toggle-cluster-relevance', {
                    task_id: activeContextId,
                    time_window: Math.floor(item.timestamp / 60),
                    event_type: item.event_type,
                    is_relevant: newStatus
                });
                setEventClusters(prev =>
                    prev.map(c =>
                        (c.timestamp === item.timestamp && c.event_type === item.event_type)
                            ? { ...c, llm_is_relevant: newStatus ? 1 : 0 }
                            : c
                    )
                );
                toast.success(newStatus ? '已标记事件簇为相关' : '已标记事件簇为无关');
            }
        } catch (err) {
            console.error('Toggle relevance error:', err);
            toast.error('操作失败: ' + err.message);
        }
    };

    const toAbsolutePath = (filePath) => {
        if (!filePath) return filePath;
        if (filePath.startsWith('/') || filePath.includes(':')) return filePath;
        if (currentTask?.extraction_directory) return `${currentTask.extraction_directory}/${filePath}`;
        return `../build/data/tasks/${activeContextId}/extracted_files/${filePath}`;
    };

    const openReanalyzeModal = (filePaths) => {
        const absolutePaths = filePaths.map(toAbsolutePath);
        setReanalyzeTargetFiles(absolutePaths);
        setReanalyzeHint('');
        setReanalyzeMessage('');
        setShowReanalyzeModal(true);
    };

    const handleReanalyzeSubmission = async () => {
        if (!reanalyzeHint.trim() || reanalyzeTargetFiles.length === 0) return;
        setReanalyzing(true);
        try {
            const filesDbPath = currentTask?.output_files_db || '';
            const result = await reanalyzeFiles(activeContextId, reanalyzeTargetFiles, reanalyzeHint.trim(), filesDbPath, caseDescription);
            if (result.job_id) {
                const poll = async () => {
                    const status = await getCaseAnalysisStatus(result.job_id);
                    if (status.status === 'completed') {
                        setReanalyzeMessage(`✅ 研判完成`); setReanalyzing(false);
                        await fetchData(); setSelectedItems(new Set());
                        setTimeout(() => setShowReanalyzeModal(false), 1500);
                    } else if (status.status === 'failed') {
                        setReanalyzeMessage(`❌ 失败: ${status.detail}`); setReanalyzing(false);
                    } else {
                        setReanalyzeMessage(status.detail || '研判中...'); setTimeout(poll, 2000);
                    }
                };
                poll();
            }
        } catch (err) { setReanalyzeMessage(`❌ 启动失败: ${err.message}`); setReanalyzing(false); }
    };

    // --- Actions: Association Drawers ---
    const handleOpenClusterFiles = async (cluster) => {
        console.log('[Association] cluster object keys:', Object.keys(cluster));
        console.log('[Association] cluster.time_window:', cluster.time_window);
        console.log('[Association] cluster.event_type:', cluster.event_type);

        setSelectedClusterForFiles(cluster);
        setClusterRelatedFiles([]);
        setLoadingClusterFiles(true);
        try {
            const result = await getClusterRelatedFiles(activeContextId, cluster, 500);
            console.log('[Association] Cluster files result:', result);
            setClusterRelatedFiles(result?.files || []);
        } catch (err) {
            console.error('[Association] Failed to load cluster files:', err);
            console.error('[Association] Error response:', err.response);
            const errorMsg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || '未知错误';
            toast.error('加载关联文件失败: ' + errorMsg);
        } finally {
            setLoadingClusterFiles(false);
        }
    };

    const handleOpenFileClusters = async (file) => {
        console.log('[Association] file object:', file);

        setSelectedFileForClusters(file);
        setFileRelatedClusters([]);
        setLoadingFileClusters(true);
        try {
            const result = await getFileRelatedClusters(activeContextId, file, 100);
            console.log('[Association] File clusters result:', result);
            setFileRelatedClusters(result?.clusters || []);
        } catch (err) {
            console.error('[Association] Failed to load file clusters:', err);
            console.error('[Association] Error response:', err.response);
            const errorMsg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || '未知错误';
            toast.error('加载关联事件簇失败: ' + errorMsg);
        } finally {
            setLoadingFileClusters(false);
        }
    };

    // --- Actions: Scrolling & Highlighting ---
    const pathToId = (path) => {
        if (!path) return '';
        let hash = 0;
        for (let i = 0; i < path.length; i++) {
            hash = ((hash << 5) - hash) + path.charCodeAt(i);
            hash |= 0;
        }
        return `file-id-${Math.abs(hash)}-${path.length}`;
    };


    if (!activeContextId) {
        return (
            <div className="max-w-4xl mx-auto py-12 px-4">
                <Card title="🔍 选择一个任务进入研判中心">
                    <div className="space-y-3">
                        {tasks.filter(t => t.status === 'completed').map(task => (
                            <button key={task.id} onClick={() => setSearchParams({ taskId: task.id })} className="w-full text-left p-4 border border-slate-200 rounded-2xl hover:border-purple-400 hover:bg-purple-50 transition-all flex justify-between items-center group">
                                <div><p className="font-mono text-sm font-bold text-slate-700">TASK-{task.id.substring(0, 8)}</p><p className="text-xs text-slate-500 truncate max-w-md">{task.image_path}</p></div>
                                <span className="text-purple-500 opacity-0 group-hover:opacity-100 transition-opacity">进入 →</span>
                            </button>
                        ))}
                    </div>
                </Card>
            </div>
        );
    }

    return (
        <div className="max-w-[1600px] mx-auto space-y-6">
            {/* If it's a Case, show hierarchical tabs */}
            {activeCase && (
                <div className="flex gap-2 p-1.5 bg-slate-100 dark:bg-slate-800/50 rounded-xl overflow-x-auto custom-scrollbar">
                    <button
                        onClick={() => setActiveContextId(caseId)}
                        className={`px-4 py-2 text-sm font-bold rounded-lg transition-all flex items-center gap-2 whitespace-nowrap ${
                            activeContextId === caseId
                            ? 'bg-white dark:bg-slate-700 text-purple-600 dark:text-purple-400 shadow-sm'
                            : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                        }`}
                    >
                        <Layers size={16} /> 综合分析报告
                    </button>
                    <div className="w-px h-6 bg-slate-300 dark:bg-slate-600 my-auto mx-2" />
                    {activeCase.task_ids?.map((tid, idx) => {
                        const t = tasks.find(t => t.id === tid);
                        const label = t ? t.image_path.split('/').pop() : `子任务 ${idx + 1}`;
                        return (
                            <button
                                key={tid}
                                onClick={() => setActiveContextId(tid)}
                                className={`px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2 whitespace-nowrap ${
                                    activeContextId === tid
                                    ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                                }`}
                            >
                                📄 {label}
                            </button>
                        );
                    })}
                </div>
            )}

            <div className="space-y-4">
                {/* Top Bar */}
                <div className="flex flex-col lg:flex-row gap-6">
                    <Card className="flex-1 border-l-4 border-purple-500">
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">📝 案情背景</h2>
                                <div className="flex items-center gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={saveDescription}
                                        disabled={!caseDescription.trim()}
                                    >
                                        保存案情描述
                                    </Button>
                                    <Button
                                        variant="primary"
                                        size="sm"
                                        onClick={() => {
                                        const query = caseId && activeContextId === caseId
                                            ? `case_id=${encodeURIComponent(activeContextId)}`
                                            : `taskId=${encodeURIComponent(activeContextId)}`;
                                        navigate(`/case-intelligence?${query}&tab=forensic`);
                                    }}
                                >
                                    📋 打开取证报告
                                </Button>
                                </div>
                            </div>
                            <p className="text-sm text-slate-500 dark:text-slate-400">
                                当前报告工作流使用版本化取证报告；历史 Chain B 报告请从“历史研判报告”标签只读查看。
                            </p>
                            <textarea value={caseDescription} onChange={(e) => setCaseDescription(e.target.value)} className="w-full h-24 p-3 text-sm border border-slate-200 dark:border-slate-700 rounded-xl dark:bg-slate-900 resize-none focus:ring-2 focus:ring-purple-500" placeholder="描述案情关键词..." />
                        </div>
                    </Card>
                    <Card className="lg:w-80 flex flex-col justify-center bg-slate-50 dark:bg-slate-900/50">
                        <div className="grid grid-cols-2 gap-4 text-center">
                            <div><p className="text-[10px] font-bold text-slate-400">文件证据</p><p className="text-2xl font-bold text-slate-700 dark:text-white">{llmResults?.descriptions?.length || 0}</p></div>
                            <div><p className="text-[10px] font-bold text-blue-400">事件簇</p><p className="text-2xl font-bold text-blue-600">{eventClusters.length || 0}</p></div>
                            <div><p className="text-[10px] font-bold text-purple-400">入报证据</p><p className="text-2xl font-bold text-purple-600">{llmResults?.descriptions?.filter(d => d.is_relevant !== 0).length || 0}</p></div>
                            <div><p className="text-[10px] font-bold text-green-400">相关簇</p><p className="text-2xl font-bold text-green-600">{eventClusters.filter(c => c.llm_is_relevant !== 0).length || 0}</p></div>
                        </div>
                    </Card>
                </div>

                {/* Content Area */}
                <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
                    <div className="xl:col-span-7 space-y-4">
                        <div className="flex items-center gap-4 px-2 flex-wrap">
                            <div className="relative flex-1 max-w-md min-w-[200px]">
                                <span className="absolute left-3 top-2 text-slate-400 text-sm">🔍</span>
                                <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索证据或事件簇..." className="w-full pl-9 pr-3 py-1.5 text-xs border border-slate-200 rounded-full dark:bg-slate-800" />
                            </div>
                            <div className="flex items-center gap-2 bg-slate-100 dark:bg-slate-800 rounded-full p-1">
                                <button onClick={() => setViewMode('all')} className={`px-3 py-1 text-xs font-bold rounded-full transition-all ${viewMode === 'all' ? 'bg-white text-purple-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>全部</button>
                                <button onClick={() => setViewMode('files')} className={`px-3 py-1 text-xs font-bold rounded-full transition-all ${viewMode === 'files' ? 'bg-white text-purple-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>文件</button>
                                <button onClick={() => setViewMode('clusters')} className={`px-3 py-1 text-xs font-bold rounded-full transition-all ${viewMode === 'clusters' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>事件簇</button>
                            </div>
                            <Button variant="outline" size="sm" disabled={selectedItems.size === 0} onClick={() => openReanalyzeModal([...selectedItems].map(idx => displayFiles[idx].file_path).map(toAbsolutePath))}>🔄 批量研判 ({selectedItems.size})</Button>
                        </div>

                        <div className="space-y-3 h-[calc(100vh-320px)] overflow-y-auto pr-2 custom-scrollbar">
                            <AnimatePresence>
                                {/* 文件卡片 */}
                                {displayFiles.map((item, index) => {
                                    const isRelevant = item.is_relevant !== 0;
                                    return (
                                        <motion.div key={`file-${item.file_path}`} id={pathToId(item.file_path)} layout initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className={`p-4 rounded-2xl border-2 transition-all duration-500 ${isRelevant ? 'bg-white dark:bg-slate-800 border-purple-100 dark:border-purple-900/30 shadow-sm' : 'bg-slate-50/50 opacity-60 grayscale'}`}>
                                            <div className="flex gap-4">
                                                <input type="checkbox" checked={selectedItems.has(`file-${index}`)} onChange={() => { const next = new Set(selectedItems); next.has(`file-${index}`) ? next.delete(`file-${index}`) : next.add(`file-${index}`); setSelectedItems(next); }} className="mt-1 h-4 w-4 text-purple-600 rounded" />
                                                <div className="flex-1 space-y-2">
                                                    <div className="flex items-start justify-between gap-2">
                                                        <p className="font-mono text-[11px] font-bold text-slate-500 truncate max-w-[70%]" title={item.file_path}>
                                                            📄 {item.file_path}
                                                        </p>
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                onClick={() => openReanalyzeModal([item.file_path])}
                                                                className="text-[10px] font-bold text-amber-600 hover:text-amber-700 px-2 py-1 bg-amber-50 hover:bg-amber-100 rounded-lg transition-colors flex items-center gap-1"
                                                                title="为此文件提供补充指令并重新分析"
                                                            >
                                                                <span>🔄</span>
                                                                <span className="hidden sm:inline">重新研判</span>
                                                            </button>
                                                            <button
                                                                onClick={() => handleToggleRelevance(item, 'file', isRelevant)}
                                                                className={`text-[10px] font-bold px-2 py-1 rounded-lg transition-colors ${
                                                                    isRelevant
                                                                        ? 'bg-green-100 text-green-700 hover:bg-red-100 hover:text-red-700'
                                                                        : 'bg-slate-200 text-slate-500 hover:bg-purple-100 hover:text-purple-700'
                                                                }`}
                                                            >
                                                                {isRelevant ? '✅ 设为证据' : '🚫 标记无关'}
                                                            </button>
                                                            <button
                                                                onClick={() => handleOpenFileClusters(item)}
                                                                className="text-[10px] font-bold text-blue-600 hover:text-blue-700 px-2 py-1 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
                                                                title="查看相关事件簇"
                                                            >
                                                                <span>🔗</span>
                                                                <span className="hidden sm:inline">事件簇</span>
                                                            </button>
                                                        </div>
                                                    </div>
                                                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{item.summary}</p>
                                                    <button onClick={() => setExpandedItems(p => ({ ...p, [item.file_path]: !p[item.file_path] }))} className="text-[10px] font-bold text-purple-500 hover:underline">{expandedItems[item.file_path] ? '收起详情 ▲' : '查看分析全文 ▼'}</button>
                                                    {expandedItems[item.file_path] && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} className="mt-2 p-3 bg-slate-50 dark:bg-slate-900 rounded-xl text-xs text-slate-600 border whitespace-pre-wrap">{item.description}</motion.div>}
                                                </div>
                                            </div>
                                        </motion.div>
                                    );
                                })}

                                {/* 事件簇卡片 */}
                                {displayClusters.map((cluster) => {
                                    const isRelevant = cluster.llm_is_relevant !== 0;
                                    const timestamp = new Date(cluster.timestamp * 1000).toLocaleString();
                                    return (
                                        <motion.div key={`cluster-${cluster.timestamp}-${cluster.event_type}`} layout initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className={`p-4 rounded-2xl border-2 transition-all duration-500 ${isRelevant ? 'bg-blue-50 dark:bg-slate-800 border-blue-100 dark:border-blue-900/30 shadow-sm' : 'bg-slate-50/50 opacity-60 grayscale'}`}>
                                            <div className="space-y-3">
                                                <div className="flex items-start justify-between gap-2">
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2 mb-2">
                                                            <span className="text-lg">🔗</span>
                                                            <Badge variant={
                                                                cluster.event_type === 'CREATED' ? 'green' :
                                                                cluster.event_type === 'MODIFIED' ? 'blue' :
                                                                cluster.event_type === 'DELETED' ? 'red' : 'gray'
                                                            } className="text-[9px] px-2 py-0.5 font-bold">
                                                                {cluster.event_type}
                                                            </Badge>
                                                            <Badge variant="blue" className="text-[9px] px-2 py-0.5 font-bold">
                                                                {cluster.cluster_count || 0} 个事件
                                                            </Badge>
                                                            {isRelevant && (
                                                                <Badge variant="green" className="text-[9px] px-2 py-0.5 font-bold">
                                                                    ✓ 相关
                                                                </Badge>
                                                            )}
                                                        </div>
                                                        <p className="font-mono text-[10px] text-slate-500 mb-1">
                                                            ⏰ {timestamp}
                                                        </p>
                                                        <p className="font-mono text-[10px] text-slate-500 mb-1">
                                                            📁 {cluster.parent_directory || '/'}
                                                        </p>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <button
                                                            onClick={() => {
                                                                // 导航到 Timeline 页面并定位到此事件簇
                                                                navigate(`/timeline?task_id=${activeContextId}&type=${cluster.event_type}&cluster=true`);
                                                            }}
                                                            className="text-[10px] font-bold text-blue-600 hover:text-blue-700 px-2 py-1 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors flex items-center gap-1"
                                                            title="在 Timeline 中查看"
                                                        >
                                                            <span>📍</span>
                                                            <span className="hidden sm:inline">查看时间线</span>
                                                        </button>
                                                        <button
                                                            onClick={() => handleToggleRelevance(cluster, 'cluster', isRelevant)}
                                                            className={`text-[10px] font-bold px-2 py-1 rounded-lg transition-colors ${
                                                                isRelevant
                                                                    ? 'bg-green-100 text-green-700 hover:bg-red-100 hover:text-red-700'
                                                                    : 'bg-slate-200 text-slate-500 hover:bg-blue-100 hover:text-blue-700'
                                                            }`}
                                                            title={isRelevant ? '标记为无关' : '标记为相关'}
                                                        >
                                                            {isRelevant ? '✓' : '○'}
                                                        </button>
                                                    </div>
                                                </div>

                                                {cluster.llm_summary && (
                                                    <div className="bg-white dark:bg-slate-900 rounded-xl p-3 border border-blue-200 dark:border-blue-800">
                                                        <div className="flex items-start gap-2 mb-2">
                                                            <span className="text-sm">🤖</span>
                                                            <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300">AI 分析</h4>
                                                        </div>
                                                        <p className="text-xs text-slate-600 dark:text-slate-400 mb-2">{cluster.llm_summary}</p>
                                                        {cluster.llm_keywords && (
                                                            <div className="flex flex-wrap gap-1 mt-2">
                                                                {cluster.llm_keywords.split(',').map((keyword, kwIdx) => (
                                                                    <span key={kwIdx} className="text-[9px] bg-blue-100 dark:bg-blue-900 px-2 py-0.5 rounded-full border border-blue-200 dark:border-blue-700 text-blue-700 dark:text-blue-300 font-medium">
                                                                        {keyword.trim()}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Related Files Preview */}
                                                <div className="border-t border-blue-100 dark:border-blue-800/30 pt-2">
                                                    <div className="flex items-center justify-between mb-1">
                                                        <span className="text-[10px] text-slate-500 font-medium">📎 相关文件</span>
                                                        <button
                                                            onClick={() => handleOpenClusterFiles(cluster)}
                                                            className="text-[9px] text-blue-500 hover:text-blue-700 font-medium"
                                                        >
                                                            查看 →
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        </motion.div>
                                    );
                                })}
                            </AnimatePresence>
                        </div>
                    </div>

                    {/* Right Column: Preview */}
                    <div className="xl:col-span-5 sticky top-6">
                        <div className="glass rounded-2xl overflow-hidden shadow-glass-lg flex flex-col h-[calc(100vh-180px)]">
                            <div className="px-6 py-4 border-b bg-white/50 dark:bg-slate-800/50 backdrop-blur-sm flex items-center justify-between">
                                <h3 className="font-bold text-slate-900 dark:text-white flex items-center gap-2"><span className="text-xl">📃</span> 案情报告预览</h3>
                                <div className="flex gap-2">
                                    <button onClick={fetchData} className="p-1.5 text-slate-400 hover:text-purple-500 transition-all">🔄</button>
                                </div>
                            </div>
                            <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-white/30 dark:bg-slate-900/30">
                                <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2 opacity-50">
                                    <span className="text-6xl mb-2">📋</span>
                                    <p className="text-sm font-medium">请从取证报告页面生成或查看当前报告</p>
                                    <p className="text-xs">历史研判报告仅在 Case Intelligence 的历史标签中只读显示</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Cluster-Files Association Drawer */}
                <ClusterFilesDrawer
                    selectedClusterForFiles={selectedClusterForFiles}
                    onClose={() => setSelectedClusterForFiles(null)}
                    loadingClusterFiles={loadingClusterFiles}
                    clusterRelatedFiles={clusterRelatedFiles}
                    getAnomalyColorClass={getAnomalyColorClass}
                    getAnomalySeverity={getAnomalySeverity}
                    formatAnomalyType={formatAnomalyType}
                />

                {/* File-Clusters Association Drawer */}
                <FileClustersDrawer
                    selectedFileForClusters={selectedFileForClusters}
                    onClose={() => setSelectedFileForClusters(null)}
                    loadingFileClusters={loadingFileClusters}
                    fileRelatedClusters={fileRelatedClusters}
                    activeContextId={activeContextId}
                    navigate={navigate}
                />

                {/* Modal */}
                {showReanalyzeModal && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                        <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="bg-white dark:bg-slate-800 rounded-3xl shadow-2xl max-w-xl w-full p-8">
                            <h3 className="text-xl font-bold mb-6">🔄 深度研判说明</h3>
                            <textarea value={reanalyzeHint} onChange={(e) => setReanalyzeHint(e.target.value)} placeholder="输入研判方向..." className="w-full h-32 p-4 border rounded-2xl dark:bg-slate-900 text-sm mb-6 focus:ring-2 focus:ring-purple-500 outline-none" />
                            {reanalyzeMessage && <div className="mb-6 p-3 bg-purple-50 text-purple-700 text-xs rounded-xl font-bold">{reanalyzeMessage}</div>}
                            <div className="flex justify-end gap-3"><Button variant="outline" onClick={() => setShowReanalyzeModal(false)}>取消</Button><Button variant="primary" onClick={handleReanalyzeSubmission} disabled={reanalyzing || !reanalyzeHint.trim()}>{reanalyzing ? '执行中...' : '🚀 开始研判'}</Button></div>
                        </motion.div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default AnalysisCenter;
