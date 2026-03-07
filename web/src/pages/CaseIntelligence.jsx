import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { fetchTasks } from '../store/taskSlice';
import { 
    setAnalysisJob, 
    updateAnalysisProgress, 
    clearAnalysisJob 
} from '../store/intelligenceSlice';
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
    const { activeAnalysisJobs } = useSelector((state) => state.intelligence);

    // Get current job state from Redux
    const activeJob = activeAnalysisJobs[taskId];

    // --- State: Case Context ---
    const [report, setReport] = useState(null);
    const [caseDescription, setCaseDescription] = useState('');
    const [showReport, setShowReport] = useState(true);
    const [runFiltering, setRunFiltering] = useState(false);

    // --- State: Evidence (LLM Descriptions) ---
    const [llmResults, setLlmResults] = useState(null);
    const [loadingEvidence, setLoadingEvidence] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [expandedItems, setExpandedItems] = useState({});
    const [selectedItems, setSelectedItems] = useState(new Set());

    // --- State: Re-analysis Modal ---
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

    // Fetch basic case data
    const fetchData = useCallback(async () => {
        if (!taskId) return;
        setLoadingEvidence(true);
        try {
            const results = await getTaskResults(taskId);
            if (results.llm_results) setLlmResults(results.llm_results);
            
            const reportData = await getCaseReport(taskId);
            if (reportData && (reportData.report || reportData.case_report)) {
                setReport({
                    ...reportData,
                    report: reportData.report || reportData.case_report
                });
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

    // --- Actions: Case Analysis (Report Generation) ---
    const startPolling = useCallback(async (jobId) => {
        try {
            await pollCaseAnalysis(jobId, (status) => {
                dispatch(updateAnalysisProgress({
                    taskId,
                    currentStep: status.current_step || '分析中',
                    detail: status.detail || '正在处理...',
                    progress: status.progress || 0
                }));
            }, 3000);

            // Success
            dispatch(updateAnalysisProgress({ taskId, status: 'completed', progress: 100 }));
            const reportData = await getCaseReport(taskId);
            if (reportData && (reportData.report || reportData.case_report)) {
                setReport({
                    ...reportData,
                    report: reportData.report || reportData.case_report
                });
            }
            toast.success('报告生成成功！');
            setTimeout(() => dispatch(clearAnalysisJob({ taskId })), 10000);
        } catch (err) {
            console.error('Polling failed:', err);
            dispatch(updateAnalysisProgress({ taskId, status: 'failed', detail: err.message }));
            toast.error('生成失败: ' + err.message);
        }
    }, [taskId, dispatch, toast]);

    // AUTO-RESUME: Detect active job on mount and start polling
    useEffect(() => {
        if (activeJob && activeJob.status === 'running' && activeJob.jobId) {
            console.log(`[Intelligence] Auto-resuming polling for job: ${activeJob.jobId}`);
            startPolling(activeJob.jobId);
        }
    }, [taskId, activeJob?.status, activeJob?.jobId, startPolling]);

    const handleStartAnalysis = async () => {
        if (!taskId || !caseDescription.trim()) return;
        try {
            await saveCaseDescription(taskId, caseDescription);
            const result = await startCaseAnalysis({
                taskId,
                filesDbPath: currentTask?.output_files_db || '',
                case_description: caseDescription.trim(),
                max_filter_files: 200,
                run_filtering: runFiltering,
            });

            if (result.job_id) {
                dispatch(setAnalysisJob({ taskId, jobId: result.job_id }));
                startPolling(result.job_id);
            }
        } catch (err) {
            toast.error('启动失败: ' + err.message);
        }
    };

    // --- Other Logic ---
    const filteredDescriptions = useMemo(() => {
        const items = llmResults?.descriptions || [];
        if (!searchQuery) return items;
        const query = searchQuery.toLowerCase();
        return items.filter(item => 
            (item.file_path && item.file_path.toLowerCase().includes(query)) ||
            (item.summary && item.summary.toLowerCase().includes(query))
        );
    }, [llmResults, searchQuery]);

    const handleToggleRelevance = async (filePath, currentStatus) => {
        try {
            const newStatus = !currentStatus;
            await toggleFileRelevance(taskId, filePath, newStatus);
            setLlmResults(prev => ({
                ...prev,
                descriptions: prev.descriptions.map(d => d.file_path === filePath ? { ...d, is_relevant: newStatus ? 1 : 0 } : d)
            }));
            toast.success(newStatus ? '已标记为案情证据' : '已剔除出报告');
        } catch (err) { toast.error('操作失败: ' + err.message); }
    };

    const toAbsolutePath = (filePath) => {
        if (!filePath) return filePath;
        if (filePath.startsWith('/') || filePath.includes(':')) return filePath;
        if (currentTask?.extraction_directory) return `${currentTask.extraction_directory}/${filePath}`;
        return `../build/data/tasks/${taskId}/extracted_files/${filePath}`;
    };

    const handleReanalyzeSubmission = async () => {
        if (!reanalyzeHint.trim() || reanalyzeTargetFiles.length === 0) return;
        setReanalyzing(true);
        try {
            const filesDbPath = currentTask?.output_files_db || '';
            const result = await reanalyzeFiles(taskId, reanalyzeTargetFiles, reanalyzeHint.trim(), filesDbPath, caseDescription);
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

    const scrollToFile = (targetPath) => {
        if (!targetPath) return;
        setSearchQuery('');
        
        const normalize = (p) => p.trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '').toLowerCase();
        const normalizedTarget = normalize(targetPath);

        setTimeout(() => {
            const allItems = llmResults?.descriptions || [];
            const foundItem = allItems.find(d => d.file_path === targetPath) || 
                              allItems.find(d => normalize(d.file_path) === normalizedTarget);
            
            if (foundItem) {
                const elementId = pathToId(foundItem.file_path);
                const element = document.getElementById(elementId);
                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    element.classList.add('ring-4', 'ring-purple-500', 'ring-opacity-60', 'scale-[1.02]');
                    setTimeout(() => element.classList.remove('ring-4', 'ring-purple-500', 'ring-opacity-60', 'scale-[1.02]'), 3000);
                    setExpandedItems(p => ({ ...p, [foundItem.file_path]: true }));
                } else { toast.error('定位失败，请尝试刷新列表。'); }
            } else { toast.error('未在研判列表中找到匹配的证据路径'); }
        }, 300);
    };

    const renderMarkdown = (text) => {
        if (!text) return null;
        return <div className="prose prose-slate max-w-none dark:prose-invert">
            {text.split('\n').map((line, i) => {
                const renderInline = (t) => {
                    const parts = t.split(/(\[\[file:[^\]]+\]\])/g);
                    return parts.map((part, j) => {
                        const fileMatch = part.match(/^\[\[file:(.+)\]\]$/);
                        if (fileMatch) {
                            const fPath = fileMatch[1];
                            return <button key={j} onClick={() => scrollToFile(fPath)} className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-md text-[13px] font-mono hover:bg-purple-100 border border-purple-200 font-bold">📄 {fPath.split('/').pop()}</button>;
                        }
                        return part;
                    });
                };
                if (line.startsWith('# ')) return <h1 key={i} className="text-2xl font-bold mt-6 mb-3">{renderInline(line.slice(2))}</h1>;
                if (line.startsWith('## ')) return <h2 key={i} className="text-xl font-semibold mt-5 mb-2">{renderInline(line.slice(3))}</h2>;
                if (line.startsWith('### ')) return <h3 key={i} className="text-lg font-semibold mt-4 mb-2">{renderInline(line.slice(4))}</h3>;
                return <p key={i} className="text-sm mb-2 leading-relaxed text-slate-700 dark:text-slate-300">{renderInline(line)}</p>;
            })}
        </div>;
    };

    if (!taskId) {
        return (
            <div className="max-w-4xl mx-auto py-12 px-4">
                <Card title="🔍 选择一个任务进入指挥中心">
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
            {/* Top Bar */}
            <div className="flex flex-col lg:flex-row gap-6">
                <Card className="flex-1 border-l-4 border-purple-500">
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">📝 案情背景</h2>
                            <div className="flex items-center gap-4">
                                <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 cursor-help">
                                    <input type="checkbox" checked={runFiltering} onChange={(e) => setRunFiltering(e.target.checked)} className="h-3.5 w-3.5 text-purple-600 rounded" />
                                    执行 AI 自动筛选
                                </label>
                                <Button variant="primary" size="sm" onClick={handleStartAnalysis} disabled={activeJob?.status === 'running' || !caseDescription.trim()}>
                                    {activeJob?.status === 'running' ? <Spinner size="sm" /> : '🚀 生成/更新报告'}
                                </Button>
                            </div>
                        </div>
                        <textarea value={caseDescription} onChange={(e) => setCaseDescription(e.target.value)} className="w-full h-24 p-3 text-sm border border-slate-200 dark:border-slate-700 rounded-xl dark:bg-slate-900 resize-none focus:ring-2 focus:ring-purple-500" placeholder="描述案情关键词..." />
                    </div>
                </Card>
                <Card className="lg:w-80 flex flex-col justify-center bg-slate-50 dark:bg-slate-900/50">
                    <div className="grid grid-cols-2 gap-4 text-center">
                        <div><p className="text-[10px] font-bold text-slate-400">总分析文件</p><p className="text-2xl font-bold text-slate-700 dark:text-white">{llmResults?.descriptions?.length || 0}</p></div>
                        <div><p className="text-[10px] font-bold text-purple-400">入报证据</p><p className="text-2xl font-bold text-purple-600">{llmResults?.descriptions?.filter(d => d.is_relevant !== 0).length || 0}</p></div>
                    </div>
                </Card>
            </div>

            {/* Content Area */}
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
                <div className="xl:col-span-7 space-y-4">
                    <div className="flex items-center gap-4 px-2">
                        <div className="relative flex-1 max-w-md">
                            <span className="absolute left-3 top-2 text-slate-400 text-sm">🔍</span>
                            <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索证据..." className="w-full pl-9 pr-3 py-1.5 text-xs border border-slate-200 rounded-full dark:bg-slate-800" />
                        </div>
                        <Button variant="outline" size="sm" disabled={selectedItems.size === 0} onClick={() => openReanalyzeModal([...selectedItems].map(idx => filteredDescriptions[idx].file_path).map(toAbsolutePath))}>🔄 批量研判 ({selectedItems.size})</Button>
                    </div>

                    <div className="space-y-3 h-[calc(100vh-320px)] overflow-y-auto pr-2 custom-scrollbar">
                        <AnimatePresence>
                            {filteredDescriptions.map((item, index) => {
                                const isRelevant = item.is_relevant !== 0;
                                return (
                                    <motion.div key={item.file_path} id={pathToId(item.file_path)} layout initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className={`p-4 rounded-2xl border-2 transition-all duration-500 ${isRelevant ? 'bg-white dark:bg-slate-800 border-purple-100 dark:border-purple-900/30 shadow-sm' : 'bg-slate-50/50 opacity-60 grayscale'}`}>
                                        <div className="flex gap-4">
                                            <input type="checkbox" checked={selectedItems.has(index)} onChange={() => { const next = new Set(selectedItems); next.has(index) ? next.delete(index) : next.add(index); setSelectedItems(next); }} className="mt-1 h-4 w-4 text-purple-600 rounded" />
                                            <div className="flex-1 space-y-2">
                                                <div className="flex items-start justify-between gap-2">
                                                    <p className="font-mono text-[11px] font-bold text-slate-500 truncate max-w-[80%]">{item.file_path}</p>
                                                    <button onClick={() => handleToggleRelevance(item.file_path, isRelevant)} className={`text-[10px] font-bold px-2 py-1 rounded-lg ${isRelevant ? 'bg-green-100 text-green-700 hover:bg-red-100 hover:text-red-700' : 'bg-slate-200 text-slate-500 hover:bg-purple-100 hover:text-purple-700'}`}>{isRelevant ? '✅ 设为证据' : '🚫 标记无关'}</button>
                                                </div>
                                                <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{item.summary}</p>
                                                <button onClick={() => setExpandedItems(p => ({ ...p, [item.file_path]: !p[item.file_path] }))} className="text-[10px] font-bold text-purple-500 hover:underline">{expandedItems[item.file_path] ? '收起详情 ▲' : '查看分析全文 ▼'}</button>
                                                {expandedItems[item.file_path] && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} className="mt-2 p-3 bg-slate-50 dark:bg-slate-900 rounded-xl text-xs text-slate-600 border whitespace-pre-wrap">{item.description}</motion.div>}
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
                                <Button variant="outline" size="sm" onClick={() => { const blob = new Blob([report?.report || ''], { type: 'text/markdown' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `report.md`; a.click(); }}>📥 导出</Button>
                            </div>
                        </div>
                        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-white/30 dark:bg-slate-900/30">
                            {activeJob?.status === 'running' ? (
                                <div className="h-full flex flex-col items-center justify-center space-y-4">
                                    <Spinner size="lg" className="text-purple-500" />
                                    <div className="text-center"><p className="font-bold text-slate-700">{activeJob.currentStep}</p><p className="text-xs text-slate-500">{activeJob.detail}</p>{activeJob.progress !== undefined && <div className="mt-4 w-48 bg-slate-200 rounded-full h-1.5 overflow-hidden"><div className="bg-purple-500 h-full" style={{ width: `${activeJob.progress}%` }} /></div>}</div>
                                </div>
                            ) : activeJob?.status === 'failed' ? (
                                <div className="h-full flex flex-col items-center justify-center text-center p-4"><span className="text-red-500 text-4xl mb-2">⚠️</span><p className="text-sm font-bold text-red-600">生成失败</p><p className="text-xs text-slate-500">{activeJob.detail}</p><Button variant="outline" size="sm" className="mt-4" onClick={() => dispatch(clearAnalysisJob({ taskId }))}>清除状态</Button></div>
                            ) : report?.report ? (
                                <div className="p-1 animate-in fade-in duration-500">{renderMarkdown(report.report)}</div>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2 opacity-50"><span className="text-6xl mb-2">📄</span><p className="text-sm font-medium">暂无报告内容</p></div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

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
    );
};

export default CaseIntelligence;
