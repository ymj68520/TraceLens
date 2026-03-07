import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { fetchTasks } from '../store/taskSlice';
import { useToast } from '../components/common/ToastContext';
import { getTaskResults } from '../services/taskService';
import { toggleFileRelevance } from '../services/llmService';
import {
    getCaseReport,
    getFilteredFiles,
    startCaseAnalysis,
    pollCaseAnalysis,
    saveCaseDescription,
    reanalyzeFiles,
    getCaseAnalysisStatus
} from '../services/caseAnalysisService';

const CaseIntelligence = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('taskId') || searchParams.get('task_id');
    const navigate = useNavigate();
    const dispatch = useDispatch();
    const toast = useToast();
    const { tasks } = useSelector((state) => state.tasks);

    // --- State: Case Context ---
    const [report, setReport] = useState(null);
    const [caseDescription, setCaseDescription] = useState('');
    const [analyzing, setAnalyzing] = useState(false);
    const [analysisProgress, setAnalysisProgress] = useState(null);
    const [showReport, setShowReport] = useState(true);

    // --- State: Evidence (LLM Descriptions) ---
    const [llmResults, setLlmResults] = useState(null);
    const [loadingEvidence, setLoadingEvidence] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [expandedItems, setExpandedItems] = useState({});
    const [selectedItems, setSelectedItems] = useState(new Set());
    const [selectAll, setSelectAll] = useState(false);

    // --- State: Re-analysis ---
    const [showReanalyzeModal, setShowReanalyzeModal] = useState(false);
    const [reanalyzeHint, setReanalyzeHint] = useState('');
    const [reanalyzeTargetFiles, setReanalyzeTargetFiles] = useState([]);
    const [reanalyzing, setReanalyzing] = useState(false);
    const [reanalyzeMessage, setReanalyzeMessage] = useState('');

    const currentTask = tasks.find((t) => t.id === taskId);

    // Initial load
    useEffect(() => {
        dispatch(fetchTasks({ status: 'all', priority: 'all' }));
    }, [dispatch]);

    const fetchData = useCallback(async () => {
        if (!taskId) return;
        setLoadingEvidence(true);
        try {
            const results = await getTaskResults(taskId);
            if (results.llm_results) {
                setLlmResults(results.llm_results);
            }
            
            const reportData = await getCaseReport(taskId);
            if (reportData && reportData.report) {
                setReport(reportData);
                setCaseDescription(reportData.case_description || '');
            }
        } catch (err) {
            console.error('Failed to fetch intelligence data:', err);
        } finally {
            setLoadingEvidence(false);
        }
    }, [taskId]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    // --- Logic: Filtering & Search ---
    const filteredDescriptions = useMemo(() => {
        const items = llmResults?.descriptions || [];
        if (!searchQuery) return items;
        const query = searchQuery.toLowerCase();
        return items.filter(item => 
            (item.file_path && item.file_path.toLowerCase().includes(query)) ||
            (item.summary && item.summary.toLowerCase().includes(query)) ||
            (item.description && item.description.toLowerCase().includes(query))
        );
    }, [llmResults, searchQuery]);

    // --- Actions: Relevance Management ---
    const handleToggleRelevance = async (filePath, currentStatus) => {
        try {
            const newStatus = !currentStatus;
            await toggleFileRelevance(taskId, filePath, newStatus);
            
            // Update local state immediately for snappy UI
            setLlmResults(prev => {
                if (!prev) return prev;
                return {
                    ...prev,
                    descriptions: prev.descriptions.map(d => 
                        d.file_path === filePath ? { ...d, is_relevant: newStatus ? 1 : 0 } : d
                    )
                };
            });
            toast.success(newStatus ? '已标记为案情证据' : '已剔除出报告');
        } catch (err) {
            toast.error('操作失败: ' + err.message);
        }
    };

    // --- Actions: Case Analysis (Report Generation) ---
    const handleStartAnalysis = async () => {
        if (!taskId || !caseDescription.trim()) return;
        setAnalyzing(true);
        setAnalysisProgress({ step: '汇总证据', detail: '正在根据当前标记的证据生成报告...' });
        try {
            await saveCaseDescription(taskId, caseDescription);
            const result = await startCaseAnalysis({
                taskId,
                filesDbPath: currentTask?.output_files_db || '',
                caseDescription: caseDescription.trim(),
                maxFilterFiles: 200,
            });

            await pollCaseAnalysis(result.job_id, (status) => {
                setAnalysisProgress({
                    step: status.current_step || '分析中',
                    detail: status.detail || '正在处理...',
                });
            }, 3000);

            const reportData = await getCaseReport(taskId);
            if (reportData && reportData.report) setReport(reportData);
            setAnalysisProgress(null);
            toast.success('报告生成成功！');
        } catch (err) {
            toast.error('生成失败: ' + err.message);
            setAnalysisProgress(null);
        } finally {
            setAnalyzing(false);
        }
    };

    // --- Actions: Path Resolution ---
    const toAbsolutePath = (filePath) => {
        if (!filePath) return filePath;
        const isAbsolutePath = filePath.startsWith('/') || filePath.includes(':');
        if (isAbsolutePath) return filePath;
        if (currentTask?.extraction_directory) return `${currentTask.extraction_directory}/${filePath}`;
        return `../build/data/tasks/${taskId}/extracted_files/${filePath}`;
    };

    // --- Actions: Re-analysis ---
    const handleReanalyzeSubmission = async () => {
        if (!reanalyzeHint.trim() || reanalyzeTargetFiles.length === 0) return;
        setReanalyzing(true);
        setReanalyzeMessage(`正在深度研判 ${reanalyzeTargetFiles.length} 个文件...`);
        try {
            const filesDbPath = currentTask?.output_files_db || '';
            const result = await reanalyzeFiles(taskId, reanalyzeTargetFiles, reanalyzeHint.trim(), filesDbPath, caseDescription);
            if (result.job_id) {
                const poll = async () => {
                    const status = await getCaseAnalysisStatus(result.job_id);
                    if (status.status === 'completed') {
                        setReanalyzeMessage(`✅ 研判完成`);
                        setReanalyzing(false);
                        await fetchData();
                        setSelectedItems(new Set());
                        setTimeout(() => setShowReanalyzeModal(false), 1500);
                    } else if (status.status === 'failed') {
                        setReanalyzeMessage(`❌ 失败: ${status.detail}`);
                        setReanalyzing(false);
                    } else {
                        setReanalyzeMessage(status.detail || '研判中...');
                        setTimeout(poll, 2000);
                    }
                };
                poll();
            }
        } catch (err) {
            setReanalyzeMessage(`❌ 启动失败: ${err.message}`);
            setReanalyzing(false);
        }
    };

    // --- Rendering: Markdown ---
    const renderMarkdown = (text) => {
        if (!text) return null;
        return <div className="prose prose-slate max-w-none dark:prose-invert">
            {text.split('\n').map((line, i) => {
                if (line.startsWith('# ')) return <h1 key={i} className="text-2xl font-bold mt-6 mb-3">{line.slice(2)}</h1>;
                if (line.startsWith('## ')) return <h2 key={i} className="text-xl font-semibold mt-5 mb-2">{line.slice(3)}</h2>;
                if (line.startsWith('### ')) return <h3 key={i} className="text-lg font-semibold mt-4 mb-2">{line.slice(4)}</h3>;
                if (line.trim() === '') return <div key={i} className="h-2" />;
                return <p key={i} className="text-sm mb-2 leading-relaxed">{line}</p>;
            })}
        </div>;
    };

    // --- Task Selector if no taskId ---
    if (!taskId) {
        return (
            <div className="max-w-4xl mx-auto py-12 px-4">
                <Card title="🔍 选择一个任务进入指挥中心">
                    <div className="space-y-3">
                        {tasks.filter(t => t.status === 'completed').map(task => (
                            <button key={task.id} onClick={() => setSearchParams({ taskId: task.id })} className="w-full text-left p-4 border border-slate-200 rounded-2xl hover:border-purple-400 hover:bg-purple-50 transition-all flex justify-between items-center group">
                                <div>
                                    <p className="font-mono text-sm font-bold text-slate-700">TASK-{task.id.substring(0, 8)}</p>
                                    <p className="text-xs text-slate-500 truncate max-w-md">{task.image_path}</p>
                                </div>
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
            {/* Top Bar: Case Context */}
            <div className="flex flex-col lg:flex-row gap-6">
                <Card className="flex-1 border-l-4 border-purple-500">
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
                                📝 案情背景
                            </h2>
                            <Button variant="primary" size="sm" onClick={handleStartAnalysis} disabled={analyzing || !caseDescription.trim()}>
                                {analyzing ? <Spinner size="sm" /> : '🚀 生成/更新报告'}
                            </Button>
                        </div>
                        <textarea
                            value={caseDescription}
                            onChange={(e) => setCaseDescription(e.target.value)}
                            placeholder="描述案情关键词或背景，AI 将基于此进行研判..."
                            className="w-full h-24 p-3 text-sm border border-slate-200 dark:border-slate-700 rounded-xl dark:bg-slate-900 resize-none focus:ring-2 focus:ring-purple-500"
                        />
                    </div>
                </Card>

                <Card className="lg:w-80 flex flex-col justify-center bg-slate-50 dark:bg-slate-900/50">
                    <div className="grid grid-cols-2 gap-4 text-center">
                        <div>
                            <p className="text-[10px] font-bold text-slate-400 uppercase">总分析文件</p>
                            <p className="text-2xl font-bold text-slate-700 dark:text-white">{llmResults?.descriptions?.length || 0}</p>
                        </div>
                        <div>
                            <p className="text-[10px] font-bold text-purple-400 uppercase">入报证据</p>
                            <p className="text-2xl font-bold text-purple-600">{llmResults?.descriptions?.filter(d => d.is_relevant).length || 0}</p>
                        </div>
                    </div>
                </Card>
            </div>

            {/* Main Area: Two Columns */}
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
                
                {/* Column 1: Evidence Workbench (7/12) */}
                <div className="xl:col-span-7 space-y-4">
                    <div className="flex items-center justify-between px-2">
                        <div className="flex items-center gap-4 flex-1">
                            <div className="relative flex-1 max-w-md">
                                <span className="absolute left-3 top-2 text-slate-400 text-sm">🔍</span>
                                <input
                                    type="text"
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    placeholder="搜索证据内容..."
                                    className="w-full pl-9 pr-3 py-1.5 text-xs border border-slate-200 dark:border-slate-700 rounded-full dark:bg-slate-800"
                                />
                            </div>
                            <Button variant="outline" size="sm" disabled={selectedItems.size === 0} onClick={() => {
                                const paths = [...selectedItems].map(idx => filteredDescriptions[idx].file_path).map(toAbsolutePath);
                                openReanalyzeModal(paths);
                            }}>
                                🔄 批量研判 ({selectedItems.size})
                            </Button>
                        </div>
                    </div>

                    <div className="space-y-3 h-[calc(100vh-320px)] overflow-y-auto pr-2 custom-scrollbar">
                        <AnimatePresence>
                            {filteredDescriptions.map((item, index) => {
                                const isRelevant = item.is_relevant !== 0;
                                return (
                                    <motion.div
                                        key={item.file_path}
                                        layout
                                        initial={{ opacity: 0, x: -20 }}
                                        animate={{ opacity: 1, x: 0 }}
                                        className={`p-4 rounded-2xl border-2 transition-all ${
                                            isRelevant 
                                                ? 'bg-white dark:bg-slate-800 border-purple-100 dark:border-purple-900/30 shadow-sm' 
                                                : 'bg-slate-50/50 dark:bg-slate-900/20 border-transparent opacity-60 grayscale'
                                        }`}
                                    >
                                        <div className="flex gap-4">
                                            <input
                                                type="checkbox"
                                                checked={selectedItems.has(index)}
                                                onChange={() => {
                                                    const next = new Set(selectedItems);
                                                    next.has(index) ? next.delete(index) : next.add(index);
                                                    setSelectedItems(next);
                                                }}
                                                className="mt-1 h-4 w-4 text-purple-600 rounded"
                                            />
                                            <div className="flex-1 space-y-2">
                                                <div className="flex items-start justify-between gap-2">
                                                    <p className="font-mono text-[11px] font-bold text-slate-500 break-all truncate max-w-[80%]" title={item.file_path}>
                                                        {item.file_path}
                                                    </p>
                                                    <button 
                                                        onClick={() => handleToggleRelevance(item.file_path, isRelevant)}
                                                        className={`text-[10px] font-bold px-2 py-1 rounded-lg transition-colors ${
                                                            isRelevant 
                                                                ? 'bg-green-100 text-green-700 hover:bg-red-100 hover:text-red-700' 
                                                                : 'bg-slate-200 text-slate-500 hover:bg-purple-100 hover:text-purple-700'
                                                        }`}
                                                    >
                                                        {isRelevant ? '✅ 设为证据' : '🚫 标记无关'}
                                                    </button>
                                                </div>
                                                
                                                <div className="space-y-1">
                                                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 leading-snug">
                                                        {item.summary}
                                                    </p>
                                                    <button
                                                        onClick={() => setExpandedItems(p => ({ ...p, [index]: !p[index] }))}
                                                        className="text-[10px] font-bold text-purple-500 hover:underline"
                                                    >
                                                        {expandedItems[index] ? '收起详情 ▲' : '查看分析全文 ▼'}
                                                    </button>
                                                </div>

                                                <AnimatePresence>
                                                    {expandedItems[index] && (
                                                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                                            <div className="mt-2 p-3 bg-slate-50 dark:bg-slate-900 rounded-xl text-xs text-slate-600 dark:text-slate-400 border border-slate-100 dark:border-slate-700 whitespace-pre-wrap leading-relaxed">
                                                                {item.description}
                                                            </div>
                                                        </motion.div>
                                                    )}
                                                </AnimatePresence>
                                            </div>
                                        </div>
                                    </motion.div>
                                );
                            })}
                        </AnimatePresence>
                    </div>
                </div>

                {/* Column 2: Live Report Preview (5/12) */}
                <div className="xl:col-span-5 sticky top-6">
                    <div className="glass rounded-2xl overflow-hidden shadow-glass-lg flex flex-col h-[calc(100vh-180px)]">
                        {/* Header Fixed */}
                        <div className="px-6 py-4 border-b border-white/10 dark:border-slate-700/40 bg-white/50 dark:bg-slate-800/50 backdrop-blur-sm flex items-center justify-between">
                            <h3 className="font-bold text-slate-900 dark:text-white flex items-center gap-2">
                                <span className="text-xl">📃</span> 案情报告预览
                            </h3>
                            <div className="flex gap-2">
                                <button 
                                    onClick={() => fetchData()} 
                                    className="p-1.5 text-slate-400 hover:text-purple-500 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-all" 
                                    title="同步数据"
                                >
                                    <span className="text-sm">🔄</span>
                                </button>
                                <Button variant="outline" size="sm" onClick={() => {
                                    const blob = new Blob([report?.report || ''], { type: 'text/markdown' });
                                    const url = URL.createObjectURL(blob);
                                    const a = document.createElement('a'); a.href = url; a.download = `case_report.md`; a.click();
                                }}>📥 导出</Button>
                            </div>
                        </div>

                        {/* Scrollable Content Area */}
                        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-white/30 dark:bg-slate-900/30">
                            {analysisProgress ? (
                                <div className="h-full flex flex-col items-center justify-center space-y-4">
                                    <Spinner size="lg" className="text-purple-500" />
                                    <div className="text-center">
                                        <p className="font-bold text-slate-700 dark:text-slate-300">{analysisProgress.step}</p>
                                        <p className="text-xs text-slate-500">{analysisProgress.detail}</p>
                                    </div>
                                </div>
                            ) : report?.report ? (
                                <div className="p-1 animate-in fade-in duration-500">
                                    {renderMarkdown(report.report)}
                                </div>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2 opacity-50 grayscale">
                                    <span className="text-6xl mb-2">📄</span>
                                    <p className="text-sm font-medium">暂无报告内容</p>
                                    <p className="text-xs">请先确认左侧证据并点击“生成报告”</p>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Re-analysis Modal */}
            {showReanalyzeModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="bg-white dark:bg-slate-800 rounded-3xl shadow-2xl max-w-xl w-full p-8 overflow-hidden">
                        <div className="flex items-center justify-between mb-6">
                            <h3 className="text-xl font-bold flex items-center gap-2">🔄 深度研判说明</h3>
                            <button onClick={() => !reanalyzing && setShowReanalyzeModal(false)} className="text-slate-400">✕</button>
                        </div>
                        <textarea
                            value={reanalyzeHint}
                            onChange={(e) => setHint(e.target.value)}
                            placeholder="输入研判方向，如：'查找与毒品交易相关的代码'..."
                            className="w-full h-32 p-4 border border-slate-200 dark:border-slate-700 rounded-2xl dark:bg-slate-900 text-sm mb-6 outline-none focus:ring-2 focus:ring-purple-500"
                        />
                        {reanalyzeMessage && <div className="mb-6 p-3 bg-purple-50 text-purple-700 text-xs rounded-xl font-bold animate-pulse">{reanalyzeMessage}</div>}
                        <div className="flex justify-end gap-3">
                            <Button variant="outline" onClick={() => setShowReanalyzeModal(false)}>取消</Button>
                            <Button variant="primary" onClick={handleReanalyzeSubmission} disabled={reanalyzing || !reanalyzeHint.trim()}>
                                {reanalyzing ? '执行中...' : '🚀 开始研判'}
                            </Button>
                        </div>
                    </motion.div>
                </div>
            )}
        </div>
    );
};

export default CaseIntelligence;
