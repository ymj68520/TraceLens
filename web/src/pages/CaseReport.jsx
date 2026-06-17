import { motion } from 'framer-motion';
import { useEffect, useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { fetchTasks } from '../store/taskSlice';
import { useToast } from '../components/common/ToastContext';
import {
    getCaseReport,
    getFilteredFiles,
    startCaseAnalysis,
    pollCaseAnalysis,
    saveCaseDescription,
} from '../services/caseAnalysisService';

const CaseReport = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('taskId');
    const navigate = useNavigate();
    const dispatch = useDispatch();
    const toast = useToast();
    const { tasks } = useSelector((state) => state.tasks);

    const [report, setReport] = useState(null);
    const [filteredFiles, setFilteredFiles] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Analysis form state
    const [caseDescription, setCaseDescription] = useState('');
    const [maxFilterFiles, setMaxFilterFiles] = useState(200);
    const [analyzing, setAnalyzing] = useState(false);
    const [analysisProgress, setAnalysisProgress] = useState(null);

    // Expanded sections
    const [expandedFiles, setExpandedFiles] = useState({});
    const [showReport, setShowReport] = useState(true);

    const currentTask = tasks.find((t) => t.id === taskId);

    // Fetch tasks on mount
    useEffect(() => {
        dispatch(fetchTasks({ status: 'all', priority: 'all' }));
    }, [dispatch]);

    // Fetch existing report when taskId changes
    useEffect(() => {
        if (!taskId) {
            setReport(null);
            setFilteredFiles([]);
            setError(null);
            return;
        }

        const fetchData = async () => {
            setLoading(true);
            setError(null);

            try {
                // Try to fetch existing report
                const reportData = await getCaseReport(taskId);
                if (reportData && reportData.report) {
                    setReport(reportData);
                    setCaseDescription(reportData.case_description || '');
                }
            } catch (err) {
                // 404 is fine — no report yet
                if (err.status !== 404) {
                    console.error('Failed to fetch case report:', err);
                }
            }

            try {
                const filesData = await getFilteredFiles(taskId);
                if (filesData && filesData.filtered_files) {
                    setFilteredFiles(filesData.filtered_files);
                }
            } catch (err) {
                // Ignore — no filtered files yet
            }

            setLoading(false);
        };

        fetchData();
    }, [taskId]);

    // Start case analysis
    const handleStartAnalysis = useCallback(async () => {
        if (!taskId || !caseDescription.trim()) return;

        setAnalyzing(true);
        setAnalysisProgress({ step: '初始化', detail: '正在准备案情分析...' });
        setError(null);
        // DO NOT reset report and filteredFiles here to keep the UI from flashing empty

        try {
            // Save description first
            await saveCaseDescription(taskId, caseDescription);

            // Get the correct files_db_path
            let filesDbPath = currentTask?.output_files_db || currentTask?.output_files_db_path || '';
            
            console.log('Starting case analysis with:', {
                taskId,
                filesDbPath,
                caseDescription: caseDescription.trim(),
                maxFilterFiles
            });

            if (!filesDbPath) {
                throw new Error('无法找到_files.db路径，请确保任务已完成分析');
            }

            // Start analysis
            const result = await startCaseAnalysis({
                taskId,
                filesDbPath: filesDbPath,
                caseDescription: caseDescription.trim(),
                maxFilterFiles,
            });

            if (!result.job_id) {
                throw new Error('未获取到分析任务 ID');
            }

            // Poll for completion
            await pollCaseAnalysis(
                result.job_id,
                (status) => {
                    setAnalysisProgress({
                        step: status.current_step || '分析中',
                        detail: status.detail || '正在处理...',
                    });
                },
                3000
            );

            // Fetch the generated report and filtered files ONLY AFTER SUCCESS
            const [reportData, filesData] = await Promise.all([
                getCaseReport(taskId).catch(err => {
                    console.error("Failed to fetch report after job completion:", err);
                    return null;
                }),
                getFilteredFiles(taskId).catch(() => null)
            ]);

            if (reportData && reportData.report) {
                setReport(reportData);
            }
            
            if (filesData && filesData.filtered_files) {
                setFilteredFiles(filesData.filtered_files);
            }

            setAnalysisProgress(null);
            toast.success('案情分析生成成功！');
        } catch (err) {
            console.error('Case analysis failed:', err);
            setError(typeof err === 'string' ? err : err.message || '案情分析失败');
            setAnalysisProgress(null);
        } finally {
            setAnalyzing(false);
        }
    }, [taskId, caseDescription, currentTask, maxFilterFiles, toast]);

    // Filter tasks that have completed + have a files DB
    const completedTasks = tasks.filter(
        (t) => t.status === 'completed' && t.output_files_db
    );

    const handleTaskSelect = (selectedTaskId) => {
        setSearchParams({ taskId: selectedTaskId });
    };

    const toggleFileExpanded = (index) => {
        setExpandedFiles((prev) => ({ ...prev, [index]: !prev[index] }));
    };

    // ---- Render: Simple Markdown-like renderer ----
    const renderMarkdown = (text) => {
        if (!text) return null;
        const lines = text.split('\n');
        const elements = [];
        let key = 0;

        for (const line of lines) {
            key++;
            if (line.startsWith('# ')) {
                elements.push(
                    <h1 key={key} className="text-2xl font-bold text-slate-900 mt-6 mb-3">
                        {line.slice(2)}
                    </h1>
                );
            } else if (line.startsWith('## ')) {
                elements.push(
                    <h2 key={key} className="text-xl font-semibold text-slate-800 mt-5 mb-2">
                        {line.slice(3)}
                    </h2>
                );
            } else if (line.startsWith('### ')) {
                elements.push(
                    <h3 key={key} className="text-lg font-semibold text-slate-700 mt-4 mb-2">
                        {line.slice(4)}
                    </h3>
                );
            } else if (line.startsWith('- ') || line.startsWith('* ')) {
                elements.push(
                    <li key={key} className="text-sm text-slate-700 ml-4 mb-1 list-disc">
                        {renderInlineStyles(line.slice(2))}
                    </li>
                );
            } else if (line.match(/^\d+\. /)) {
                elements.push(
                    <li key={key} className="text-sm text-slate-700 ml-4 mb-1 list-decimal">
                        {renderInlineStyles(line.replace(/^\d+\. /, ''))}
                    </li>
                );
            } else if (line.trim() === '') {
                elements.push(<div key={key} className="h-2" />);
            } else {
                elements.push(
                    <p key={key} className="text-sm text-slate-700 mb-2 leading-relaxed">
                        {renderInlineStyles(line)}
                    </p>
                );
            }
        }

        return <div className="prose prose-slate max-w-none">{elements}</div>;
    };

    const renderInlineStyles = (text) => {
        // Handle both [[file:path]] and [[event:...]] references
        const refParts = text.split(/(\[\[(?:file|event):[^\]]+\]\])/g);
        const processed = refParts.map((part, i) => {
            // [[file:path]] reference
            const fileMatch = part.match(/^\[\[file:(.+)\]\]$/);
            if (fileMatch) {
                const filePath = fileMatch[1];
                const fileName = filePath.split('/').pop();
                return (
                    <a
                        key={`file-${i}`}
                        href={`/files?task_id=${taskId}&highlight=${encodeURIComponent(filePath)}`}
                        onClick={(e) => {
                            e.preventDefault();
                            navigate(`/files?task_id=${taskId}&highlight=${encodeURIComponent(filePath)}`);
                        }}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-md text-xs font-mono hover:bg-blue-100 dark:hover:bg-blue-800/40 transition-colors cursor-pointer border border-blue-200 dark:border-blue-700"
                        title={filePath}
                    >
                        📄 {fileName}
                    </a>
                );
            }
            // [[event:type@window/dir]] reference
            const eventMatch = part.match(/^\[\[event:(.+)\]\]$/);
            if (eventMatch) {
                const eventRef = eventMatch[1];
                const shortLabel = eventRef.length > 30 ? eventRef.slice(0, 30) + '…' : eventRef;
                return (
                    <a
                        key={`event-${i}`}
                        href={`/timeline?task_id=${taskId}&cluster=true`}
                        onClick={(e) => {
                            e.preventDefault();
                            navigate(`/timeline?task_id=${taskId}&cluster=true`);
                        }}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-md text-xs font-mono hover:bg-purple-100 dark:hover:bg-purple-800/40 transition-colors cursor-pointer border border-purple-200 dark:border-purple-700"
                        title={`事件簇: ${eventRef}`}
                    >
                        ⏱ {shortLabel}
                    </a>
                );
            }
            // Then handle bold: **text**
            const boldParts = part.split(/(\*\*[^*]+\*\*)/g);
            return boldParts.map((bp, j) => {
                if (bp.startsWith('**') && bp.endsWith('**')) {
                    return (
                        <strong key={`b-${i}-${j}`} className="font-semibold text-slate-900">
                            {bp.slice(2, -2)}
                        </strong>
                    );
                }
                return bp;
            });
        });
        return processed;
    };

    // ---- Render: Task Selector ----
    const TaskSelector = () => (
        <Card title="📋 选择任务">
            {completedTasks.length === 0 ? (
                <div className="text-center py-8">
                    <div className="text-5xl mb-4">🔍</div>
                    <p className="text-slate-500 mb-4">
                        没有已完成的分析任务。
                    </p>
                    <p className="text-sm text-slate-400">
                        请先在{' '}
                        <a href="/tasks" className="text-primary-600 hover:text-blue-800 underline">
                            任务页面
                        </a>{' '}
                        创建并完成一个取证分析任务。
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    <p className="text-sm text-slate-600 mb-4">
                        选择一个已完成的分析任务，开始 AI 案情分析：
                    </p>
                    <div className="space-y-2">
                        {completedTasks.map((task) => (
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

    // ---- No task selected ----
    if (!taskId) {
        return (
            <div className="space-y-6">
                <div>
                    <motion.h1
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.4 }}
                        className="text-3xl font-bold text-slate-900"
                    >
                        📋 案情分析报告
                    </motion.h1>
                    <p className="mt-2 text-slate-600">基于 AI 的数字取证案情综合分析</p>
                </div>
                <TaskSelector />
            </div>
        );
    }

    // ---- Loading ----
    if (loading) {
        return (
            <div className="space-y-6">
                <div>
                    <motion.h1
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.4 }}
                        className="text-3xl font-bold text-slate-900"
                    >
                        📋 案情分析报告
                    </motion.h1>
                </div>
                <Card>
                    <div className="flex items-center justify-center h-64">
                        <Spinner size="lg" />
                        <span className="ml-4 text-slate-600">加载中...</span>
                    </div>
                </Card>
            </div>
        );
    }

    // ---- Main Content ----
    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <motion.h1
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.4 }}
                        className="text-3xl font-bold text-slate-900"
                    >
                        📋 案情分析报告
                    </motion.h1>
                    <p className="mt-2 text-slate-600">
                        任务: {currentTask?.image_path || taskId}
                    </p>
                    {currentTask && (
                        <div className="mt-2">
                            <Badge variant="blue">{currentTask.status}</Badge>
                        </div>
                    )}
                </div>
                <button
                    onClick={() => {
                        const newParams = Object.fromEntries(searchParams);
                        delete newParams.taskId;
                        delete newParams.task_id;
                        setSearchParams(newParams);
                    }}
                    className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors"
                >
                    ← 返回任务列表
                </button>
            </div>

            {/* Case Description Input */}
            <Card title="📝 案情描述">
                <div className="space-y-4">
                    <textarea
                        id="case-description-input"
                        value={caseDescription}
                        onChange={(e) => setCaseDescription(e.target.value)}
                        placeholder="请输入案情描述，例如：一起涉嫌网络诈骗案件，嫌疑人使用手机进行频繁转账操作..."
                        className="w-full h-32 px-4 py-3 border border-slate-300 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm resize-none"
                        disabled={analyzing}
                    />
                    <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-4">
                            <label className="text-sm text-slate-600">
                                最大筛选文件数：
                                <input
                                    type="number"
                                    value={maxFilterFiles}
                                    onChange={(e) =>
                                        setMaxFilterFiles(
                                            Math.max(1, Math.min(2000, parseInt(e.target.value) || 200))
                                        )
                                    }
                                    className="ml-2 w-20 px-2 py-1 border border-slate-300 rounded-lg text-sm"
                                    disabled={analyzing}
                                    min={1}
                                    max={2000}
                                />
                            </label>
                        </div>
                        <button
                            id="start-analysis-btn"
                            onClick={handleStartAnalysis}
                            disabled={analyzing || !caseDescription.trim()}
                            className={`px-6 py-2.5 rounded-xl text-sm font-medium transition-all ${analyzing || !caseDescription.trim()
                                ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                : 'bg-gradient-to-r from-primary-500 to-purple-500 text-white hover:from-primary-600 hover:to-purple-600 shadow-lg hover:shadow-xl'
                                }`}
                        >
                            {analyzing ? (
                                <span className="flex items-center">
                                    <Spinner size="sm" />
                                    <span className="ml-2">分析中...</span>
                                </span>
                            ) : (
                                '🧠 开始 AI 案情分析'
                            )}
                        </button>
                    </div>
                </div>
            </Card>

            {/* Analysis Progress */}
            {analysisProgress && (
                <Card>
                    <div className="flex items-center space-x-4 py-4">
                        <Spinner size="md" />
                        <div>
                            <p className="text-sm font-medium text-slate-700">
                                {analysisProgress.step}
                            </p>
                            <p className="text-xs text-slate-500 mt-1">
                                {analysisProgress.detail}
                            </p>
                        </div>
                    </div>
                </Card>
            )}

            {/* Error */}
            {error && (
                <Card>
                    <div className="p-4 bg-red-50 border border-red-200 rounded-xl">
                        <p className="text-red-800 text-sm">{error}</p>
                    </div>
                </Card>
            )}

            {/* Statistics */}
            {(report || filteredFiles.length > 0) && (
                <Card title="📊 分析统计">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="bg-blue-50 rounded-xl p-4">
                            <p className="text-sm text-primary-600 font-medium">证据文件数</p>
                            <p className="text-2xl font-bold text-blue-900">
                                {filteredFiles.length || report?.filtered_files?.length || 0}
                            </p>
                        </div>
                        <div className="bg-green-50 rounded-xl p-4">
                            <p className="text-sm text-green-600 font-medium">成功分析</p>
                            <p className="text-2xl font-bold text-green-900">
                                {report?.files_analyzed || 0}
                            </p>
                        </div>
                        <div className="bg-purple-50 rounded-xl p-4">
                            <p className="text-sm text-purple-600 font-medium">报告状态</p>
                            <p className="text-2xl font-bold text-purple-900">
                                {report?.report ? '✅ 已生成' : '⏳ 待生成'}
                            </p>
                        </div>
                    </div>
                </Card>
            )}

            {/* Filtered Files */}
            {filteredFiles.length > 0 && (
                <Card title={`🗂️ 案情相关证据文件 (${filteredFiles.length})`}>
                    <div className="max-h-64 overflow-y-auto space-y-1 text-sm text-slate-600 mb-3 px-3 italic">
                        包含初始 AI 筛选及后续深度研判的所有关键文件
                    </div>
                    <div className="max-h-64 overflow-y-auto space-y-1">
                        {filteredFiles.map((filePath, index) => (
                            <div
                                key={index}
                                className="flex items-center space-x-2 px-3 py-2 hover:bg-slate-50 rounded-lg transition-colors"
                            >
                                <span className="text-sm">📄</span>
                                <span className="font-mono text-xs text-slate-700 truncate">
                                    {filePath}
                                </span>
                            </div>
                        ))}
                    </div>
                </Card>
            )}

            {/* Case Report */}
            {report?.report && (
                <Card
                    title={
                        <div className="flex items-center justify-between w-full">
                            <span>📝 综合案情分析报告</span>
                            <div className="flex items-center space-x-2">
                                <button
                                    onClick={() => setShowReport(!showReport)}
                                    className="text-sm text-primary-600 hover:text-blue-800"
                                >
                                    {showReport ? '收起' : '展开'}
                                </button>
                                <button
                                    onClick={handleStartAnalysis}
                                    disabled={analyzing || !caseDescription.trim()}
                                    className="px-3 py-1 text-xs bg-amber-100 hover:bg-amber-200 text-amber-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {analyzing ? '生成中...' : '🔄 重新生成'}
                                </button>
                                <button
                                    onClick={() => {
                                        const blob = new Blob([report.report], { type: 'text/markdown' });
                                        const url = URL.createObjectURL(blob);
                                        const a = document.createElement('a');
                                        a.href = url;
                                        a.download = `case_report_${taskId}.md`;
                                        a.click();
                                        URL.revokeObjectURL(url);
                                    }}
                                    className="px-3 py-1 text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg transition-colors"
                                >
                                    📥 下载报告
                                </button>
                            </div>
                        </div>
                    }
                >
                    {showReport && (
                        <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            transition={{ duration: 0.3 }}
                        >
                            <div className="bg-white rounded-xl p-6 border border-slate-100">
                                {renderMarkdown(report.report)}
                            </div>
                            {report.generated_at && (
                                <p className="text-xs text-slate-400 mt-4 text-right">
                                    生成时间: {report.generated_at} | 模型: {report.model_used || 'N/A'}
                                </p>
                            )}
                        </motion.div>
                    )}
                </Card>
            )}
        </div>
    );
};

export default CaseReport;
