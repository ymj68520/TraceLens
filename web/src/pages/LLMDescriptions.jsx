import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { getTaskResults } from '../services/taskService';
import { fetchTasks } from '../store/taskSlice';
import { reanalyzeFiles, getCaseAnalysisStatus } from '../services/caseAnalysisService';

const LLMDescriptions = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');

    const dispatch = useDispatch();
    const { tasks } = useSelector((state) => state.tasks);

    const [llmResults, setLlmResults] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [expandedItems, setExpandedItems] = useState({});

    // Selection state
    const [selectedItems, setSelectedItems] = useState(new Set());
    const [selectAll, setSelectAll] = useState(false);

    // Re-analysis state
    const [showReanalyzeModal, setShowReanalyzeModal] = useState(false);
    const [reanalyzeHint, setReanalyzeHint] = useState('');
    const [reanalyzeTargetFiles, setReanalyzeTargetFiles] = useState([]);
    const [reanalyzing, setReanalyzing] = useState(false);
    const [reanalyzeMessage, setReanalyzeMessage] = useState('');

    const currentTask = tasks.find((t) => t.id === taskId);

    // Fetch tasks on mount for the task selector
    useEffect(() => {
        dispatch(fetchTasks({ status: 'all', priority: 'all' }));
    }, [dispatch]);

    // Fetch LLM results when taskId changes
    const fetchResults = async () => {
        if (!taskId) {
            setLlmResults(null);
            setError(null);
            return;
        }

        setLoading(true);
        setError(null);

        try {
            const results = await getTaskResults(taskId);
            if (results.llm_results) {
                setLlmResults(results.llm_results);
            } else {
                setError('No LLM analysis results found for this task. Make sure LLM analysis was enabled when creating the task.');
            }
        } catch (err) {
            console.error('Failed to fetch LLM results:', err);
            setError(err.message || 'Failed to load LLM analysis results');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchResults();
    }, [taskId]);

    // Filter tasks with LLM analysis enabled and completed
    const llmEnabledTasks = tasks.filter(
        (t) => t.llm_analyze && t.status === 'completed'
    );

    // Toggle expanded state for a file
    const toggleExpanded = (index) => {
        setExpandedItems((prev) => ({
            ...prev,
            [index]: !prev[index],
        }));
    };

    // Handle task selection
    const handleTaskSelect = (selectedTaskId) => {
        setSearchParams({ task_id: selectedTaskId });
    };

    // Filter descriptions based on search query
    const filteredDescriptions = llmResults?.descriptions?.filter((item) => {
        if (!searchQuery) return true;
        const query = searchQuery.toLowerCase();
        return (
            (item.file_path && item.file_path.toLowerCase().includes(query)) ||
            (item.summary && item.summary.toLowerCase().includes(query)) ||
            (item.description && item.description.toLowerCase().includes(query)) ||
            (item.keywords && item.keywords.toLowerCase().includes(query))
        );
    }) || [];

    // Handle single item selection
    const handleItemSelect = (index) => {
        const newSelected = new Set(selectedItems);
        if (newSelected.has(index)) {
            newSelected.delete(index);
        } else {
            newSelected.add(index);
        }
        setSelectedItems(newSelected);
        setSelectAll(newSelected.size === filteredDescriptions.length && filteredDescriptions.length > 0);
    };

    // Handle select all
    const handleSelectAll = (checked) => {
        setSelectAll(checked);
        if (checked) {
            setSelectedItems(new Set(filteredDescriptions.map((_, idx) => idx)));
        } else {
            setSelectedItems(new Set());
        }
    };

    // Convert relative file path to absolute path
    const toAbsolutePath = (filePath) => {
        if (!filePath) return filePath;

        // If path is already absolute, return as is
        const isAbsolutePath = filePath.startsWith('/') || filePath.includes(':');
        if (isAbsolutePath) return filePath;

        // Try to use extraction directory from task
        if (currentTask?.extraction_directory) {
            return `${currentTask.extraction_directory}/${filePath}`;
        }

        // Fallback to default extraction directory
        return `../build/data/tasks/${taskId}/extracted_files/${filePath}`;
    };

    // Open re-analysis modal
    const openReanalyzeModal = (filePaths) => {
        // CRITICAL FIX: Convert paths to absolute before sending to backend
        const absolutePaths = filePaths.map(toAbsolutePath);
        console.log('Opening reanalyze modal with absolute paths:', absolutePaths);
        
        setReanalyzeTargetFiles(absolutePaths);
        setReanalyzeHint('');
        setReanalyzeMessage('');
        setShowReanalyzeModal(true);
    };

    // Handle re-analysis submission
    const handleReanalyze = async () => {
        if (!reanalyzeHint.trim() || reanalyzeTargetFiles.length === 0) return;

        setReanalyzing(true);
        setReanalyzeMessage(`正在分析 ${reanalyzeTargetFiles.length} 个文件...`);

        try {
            const filesDbPath = currentTask?.output_files_db || '';
            const result = await reanalyzeFiles(
                taskId,
                reanalyzeTargetFiles,
                reanalyzeHint.trim(),
                filesDbPath
            );

            if (result.job_id) {
                const poll = async () => {
                    try {
                        const status = await getCaseAnalysisStatus(result.job_id);
                        if (status.status === 'completed') {
                            setReanalyzeMessage(`✅ 重新分析完成`);
                            setReanalyzing(false);
                            // Refresh results
                            await fetchResults();
                            setSelectedItems(new Set());
                            setSelectAll(false);
                            setTimeout(() => setShowReanalyzeModal(false), 1500);
                        } else if (status.status === 'failed') {
                            setReanalyzeMessage(`❌ 分析失败: ${status.detail}`);
                            setReanalyzing(false);
                        } else {
                            setReanalyzeMessage(status.detail || '分析中...');
                            setTimeout(poll, 2000);
                        }
                    } catch (err) {
                        setReanalyzeMessage(`❌ 状态查询失败: ${err.message}`);
                        setReanalyzing(false);
                    }
                };
                poll();
            }
        } catch (err) {
            setReanalyzeMessage(`❌ 启动失败: ${err.message || '未知错误'}`);
            setReanalyzing(false);
        }
    };

    // Parse keywords string into array
    const parseKeywords = (keywords) => {
        if (!keywords) return [];
        try {
            const parsed = JSON.parse(keywords);
            return Array.isArray(parsed) ? parsed : [keywords];
        } catch {
            return keywords.split(',').map((k) => k.trim()).filter(Boolean);
        }
    };

    // Format date
    const formatDate = (dateStr) => {
        if (!dateStr) return '-';
        try {
            return new Date(dateStr).toLocaleString();
        } catch {
            return dateStr;
        }
    };

    // Task Selector Component
    const TaskSelector = () => (
        <Card title="📋 选择任务">
            {llmEnabledTasks.length === 0 ? (
                <div className="text-center py-8">
                    <div className="text-5xl mb-4">🔍</div>
                    <p className="text-slate-500 mb-4">
                        未找到已完成的包含 AI 分析的任务。
                    </p>
                    <p className="text-sm text-slate-400">
                        请先在{' '}
                        <a href="/tasks" className="text-primary-600 hover:text-blue-800 underline">
                            任务页面
                        </a>{' '}
                        创建一个启用 AI 分析的任务。
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    <p className="text-sm text-slate-600 mb-4">
                        选择一个已完成的任务以查看 AI 生成的文件描述：
                    </p>
                    <div className="space-y-2">
                        {llmEnabledTasks.map((task) => (
                            <button
                                key={task.id}
                                onClick={() => handleTaskSelect(task.id)}
                                className="w-full text-left p-4 border border-slate-200 rounded-xl hover:border-blue-400 hover:bg-blue-50 transition-all group"
                            >
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center space-x-3">
                                        <span className="text-xl">📊</span>
                                        <div>
                                            <p className="font-mono text-sm text-slate-700 group-hover:text-blue-700">
                                                {task.id.substring(0, 8)}...
                                            </p>
                                            <p className="text-sm text-slate-500 truncate max-w-md">
                                                {task.image_path}
                                            </p>
                                        </div>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <Badge variant="green">已完成</Badge>
                                        <Badge variant="purple">AI</Badge>
                                        <span className="text-blue-500 opacity-0 group-hover:opacity-100 transition-opacity">
                                            →
                                        </span>
                                    </div>
                                </div>
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </Card>
    );

    // No task selected - show task selector
    if (!taskId) {
        return (
            <div className="space-y-6">
                <div>
                    <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">🤖 AI 文件描述</motion.h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-300">查看 AI 为分析文件生成的详细描述和摘要</p>
                </div>
                <TaskSelector />
            </div>
        );
    }

    // Loading state
    if (loading) {
        return (
            <div className="space-y-6">
                <div>
                    <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">🤖 AI 文件描述</motion.h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
                </div>
                <Card>
                    <div className="flex items-center justify-center h-64">
                        <Spinner size="lg" />
                        <span className="ml-4 text-slate-600 dark:text-slate-300">正在加载 AI 分析结果...</span>
                    </div>
                </Card>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div className="space-y-6">
                <div>
                    <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">🤖 AI 文件描述</motion.h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
                </div>

                <Card title="错误">
                    <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
                        <p className="text-red-800 dark:text-red-200">{error}</p>
                    </div>
                </Card>

                <TaskSelector />
            </div>
        );
    }

    return (
        <div className="space-y-6 pb-20">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">🤖 AI 文件描述</motion.h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
                    {currentTask && (
                        <div className="mt-2 flex gap-2">
                            <Badge variant="blue">{currentTask.status}</Badge>
                            {currentTask.llm_analyze && (
                                <Badge variant="purple">AI 分析已启用</Badge>
                            )}
                        </div>
                    )}
                </div>
                <button
                    onClick={() => setSearchParams({})}
                    className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800 rounded-xl transition-colors"
                >
                    ← 返回任务列表
                </button>
            </div>

            {/* Statistics & Search Combined */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <Card title="📊 分析统计" className="lg:col-span-1">
                    <div className="space-y-4">
                        <div className="flex items-center justify-between p-3 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-100 dark:border-blue-800">
                            <span className="text-sm text-blue-700 dark:text-blue-300">分析总数</span>
                            <span className="text-xl font-bold text-blue-900 dark:text-white">
                                {llmResults?.stats?.total_analyzed || llmResults?.descriptions?.length || 0}
                            </span>
                        </div>
                        <div className="flex items-center justify-between p-3 bg-green-50 dark:bg-green-900/20 rounded-xl border border-green-100 dark:border-green-800">
                            <span className="text-sm text-green-700 dark:text-green-300">搜索匹配</span>
                            <span className="text-xl font-bold text-green-900 dark:text-white">
                                {filteredDescriptions.length}
                            </span>
                        </div>
                    </div>
                </Card>

                <Card className="lg:col-span-2 flex flex-col justify-center">
                    <div className="space-y-4">
                        <div className="relative">
                            <span className="absolute left-4 top-3 text-lg">🔍</span>
                            <input
                                type="text"
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                placeholder="搜索文件名、摘要或关键词..."
                                className="w-full pl-12 pr-10 py-3 border border-slate-300 dark:border-slate-600 rounded-2xl dark:bg-slate-700 dark:text-white focus:ring-2 focus:ring-primary-500 shadow-sm"
                            />
                            {searchQuery && (
                                <button
                                    onClick={() => setSearchQuery('')}
                                    className="absolute right-4 top-3.5 text-slate-400 hover:text-slate-600"
                                >
                                    ✕
                                </button>
                            )}
                        </div>
                        
                        {/* Action Bar */}
                        <div className="flex items-center justify-between px-2">
                            <div className="flex items-center gap-4">
                                <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={selectAll}
                                        onChange={(e) => handleSelectAll(e.target.checked)}
                                        className="h-4 w-4 text-purple-600 rounded"
                                    />
                                    全选匹配项
                                </label>
                                <span className="text-sm text-slate-500">
                                    已选: <span className="font-bold text-purple-600">{selectedItems.size}</span>
                                </span>
                            </div>
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={() => {
                                    const paths = [...selectedItems].map(idx => filteredDescriptions[idx].file_path).filter(Boolean);
                                    if (paths.length > 0) openReanalyzeModal(paths);
                                }}
                                disabled={selectedItems.size === 0}
                                className="bg-gradient-to-r from-amber-500 to-orange-500 border-none shadow-md hover:shadow-lg transition-all"
                            >
                                🔄 批量重新分析
                            </Button>
                        </div>
                    </div>
                </Card>
            </div>

            {/* File Descriptions List */}
            <div className="space-y-4">
                {filteredDescriptions.length === 0 ? (
                    <Card>
                        <div className="text-center py-12 text-slate-500">
                            {searchQuery ? '未找到匹配的描述。' : '暂无 AI 描述。'}
                        </div>
                    </Card>
                ) : (
                    filteredDescriptions.map((item, index) => {
                        const isSelected = selectedItems.has(index);
                        const isExpanded = expandedItems[index];
                        
                        return (
                            <div
                                key={index}
                                className={`group bg-white dark:bg-slate-800 border-2 rounded-2xl p-5 transition-all ${
                                    isSelected 
                                        ? 'border-purple-500 shadow-md ring-1 ring-purple-200' 
                                        : 'border-slate-100 dark:border-slate-700 hover:border-blue-300'
                                }`}
                            >
                                <div className="flex items-start gap-4">
                                    {/* Checkbox */}
                                    <div className="mt-1">
                                        <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onChange={() => handleItemSelect(index)}
                                            className="h-5 w-5 text-purple-600 rounded-lg cursor-pointer"
                                            aria-label={`选择 ${item.file_path}`}
                                        />
                                    </div>

                                    {/* Content */}
                                    <div className="flex-1 min-w-0 space-y-3">
                                        <div className="flex items-start justify-between">
                                            <div className="flex items-center space-x-2 flex-1 min-w-0">
                                                <span className="text-xl">📄</span>
                                                <p className="font-mono text-sm font-semibold text-slate-900 dark:text-white truncate" title={item.file_path}>
                                                    {item.file_path}
                                                </p>
                                            </div>
                                            <div className="flex items-center gap-3 ml-2">
                                                <span className="text-[10px] text-slate-400 bg-slate-50 dark:bg-slate-900 px-2 py-1 rounded-md font-mono">
                                                    {formatDate(item.created_at)}
                                                </span>
                                                <button
                                                    onClick={() => openReanalyzeModal([item.file_path])}
                                                    className="text-xs text-amber-600 hover:text-amber-800 dark:text-amber-400 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1"
                                                >
                                                    🔄 重新分析
                                                </button>
                                            </div>
                                        </div>

                                        {/* Summary */}
                                        {item.summary && (
                                            <div className="bg-slate-50 dark:bg-slate-900/50 p-3 rounded-xl">
                                                <p className="text-xs font-bold text-slate-400 uppercase mb-1 tracking-wider">AI 摘要</p>
                                                <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{item.summary}</p>
                                            </div>
                                        )}

                                        {/* Keywords */}
                                        {item.keywords && (
                                            <div className="flex flex-wrap gap-1.5">
                                                {parseKeywords(item.keywords).map((keyword, idx) => (
                                                    <span
                                                        key={idx}
                                                        className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800"
                                                    >
                                                        #{keyword}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {/* Full Description (Expandable) */}
                                        {item.description && (
                                            <div>
                                                <button
                                                    onClick={() => toggleExpanded(index)}
                                                    className="flex items-center text-xs font-bold text-purple-600 hover:text-purple-800 dark:text-purple-400"
                                                >
                                                    <span className="mr-1.5">{isExpanded ? '▼' : '▶'}</span>
                                                    {isExpanded ? '收起完整描述' : '显示完整描述'}
                                                </button>
                                                {isExpanded && (
                                                    <motion.div 
                                                        initial={{ opacity: 0, height: 0 }}
                                                        animate={{ opacity: 1, height: 'auto' }}
                                                        className="mt-3 p-4 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-100 dark:border-slate-700"
                                                    >
                                                        <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-relaxed">
                                                            {item.description}
                                                        </p>
                                                    </motion.div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        );
                    })
                )}
            </div>

            {/* Re-analysis Modal */}
            <ReanalyzeModal
                show={showReanalyzeModal}
                onClose={() => !reanalyzing && setShowReanalyzeModal(false)}
                targetFiles={reanalyzeTargetFiles}
                hint={reanalyzeHint}
                setHint={setReanalyzeHint}
                onSubmit={handleReanalyze}
                reanalyzing={reanalyzing}
                message={reanalyzeMessage}
            />
        </div>
    );
};

// Re-analysis Modal (Local component for consistency)
const ReanalyzeModal = ({ show, onClose, targetFiles, hint, setHint, onSubmit, reanalyzing, message }) => {
    if (!show) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
            <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="bg-white dark:bg-slate-800 rounded-3xl shadow-2xl max-w-xl w-full mx-4 overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="p-8">
                    <div className="flex items-center justify-between mb-6">
                        <h3 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
                            <span className="text-2xl">🔄</span> 重新分析选定文件
                        </h3>
                        <button
                            onClick={onClose}
                            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
                        >
                            <span className="text-xl">✕</span>
                        </button>
                    </div>

                    <div className="mb-6">
                        <p className="text-sm text-slate-600 dark:text-slate-300">
                            将对 <span className="font-bold text-purple-600">{targetFiles.length}</span> 个文件进行二次深度分析。
                        </p>
                        {targetFiles.length <= 2 && (
                            <div className="mt-2 space-y-1">
                                {targetFiles.map((f, i) => (
                                    <div key={i} className="text-xs font-mono text-slate-400 truncate bg-slate-50 dark:bg-slate-900 p-1.5 rounded">
                                        📄 {f}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="mb-6">
                        <label className="block text-sm font-bold text-slate-700 dark:text-slate-300 mb-2 uppercase tracking-wide">
                            分析指令 / 补充描述
                        </label>
                        <textarea
                            value={hint}
                            onChange={(e) => setHint(e.target.value)}
                            placeholder="请输入对此文件的具体分析方向，例如：关注其中的账户信息、加密货币关键词等..."
                            className="w-full h-36 px-4 py-3 border border-slate-300 dark:border-slate-600 rounded-2xl dark:bg-slate-700 dark:text-white text-sm resize-none focus:ring-4 focus:ring-purple-500/20 focus:border-purple-500 transition-all outline-none"
                            disabled={reanalyzing}
                        />
                    </div>

                    {message && (
                        <div className={`mb-6 p-4 rounded-2xl text-sm font-medium animate-pulse ${
                            message.startsWith('✅') ? 'bg-green-50 text-green-800 border border-green-100' :
                            message.startsWith('❌') ? 'bg-red-50 text-red-800 border border-red-100' :
                            'bg-blue-50 text-blue-800 border border-blue-100'
                        }`}>
                            {message}
                        </div>
                    )}

                    <div className="flex justify-end gap-3">
                        <button
                            onClick={onClose}
                            className="px-6 py-2.5 text-sm font-bold text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white transition-colors"
                            disabled={reanalyzing}
                        >
                            取消
                        </button>
                        <button
                            onClick={onSubmit}
                            disabled={reanalyzing || !hint.trim()}
                            className={`px-8 py-2.5 rounded-2xl text-sm font-bold transition-all shadow-lg ${
                                reanalyzing || !hint.trim()
                                    ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 hover:scale-[1.02] active:scale-95'
                            }`}
                        >
                            {reanalyzing ? (
                                <span className="flex items-center gap-2">
                                    <Spinner size="sm" />
                                    执行中...
                                </span>
                            ) : (
                                '🚀 开始重新分析'
                            )}
                        </button>
                    </div>
                </div>
            </motion.div>
        </div>
    );
};

export default LLMDescriptions;
