import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { Virtuoso } from 'react-virtuoso';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { fetchTasks } from '../store/taskSlice';
import { fetchCases } from '../store/caseSlice';
import {
    setAnalysisJob,
    updateAnalysisProgress,
    clearAnalysisJob,
    clearRefreshFlag
} from '../store/intelligenceSlice';
import { useToast } from '../components/common/ToastContext';
import { toggleFileRelevance } from '../services/llmService';
import {
    getCaseReport,
    startCaseAnalysis,
    pollCaseAnalysis,
    saveCaseDescription,
    reanalyzeFiles,
    getCaseAnalysisStatus
} from '../services/caseAnalysisService';
import {
    getClusterRelatedFiles,
    getFileRelatedClusters,
    formatAnomalyType,
    getAnomalySeverity,
    getAnomalyColorClass
} from '../services/associationService';
import { X, AlertTriangle, Clock, FileText, Layers } from 'lucide-react';

const CaseIntelligence = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const caseId = searchParams.get('case_id');
    const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
    const [activeContextId, setActiveContextId] = useState(caseId || urlTaskId);

    const navigate = useNavigate();
    const dispatch = useDispatch();
    const toast = useToast();
    const { tasks } = useSelector((state) => state.tasks);
    const { cases } = useSelector((state) => state.cases);
    const { activeAnalysisJobs, refreshFlags } = useSelector((state) => state.intelligence);

    const activeCase = caseId ? cases.find(c => c.id === caseId) : null;
    // Get current job state from Redux
    const activeJob = activeAnalysisJobs[activeContextId];

    // --- State: Case Context ---
    const [report, setReport] = useState(null);
    const [caseDescription, setCaseDescription] = useState('');
    const [runFiltering, setRunFiltering] = useState(false);

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

            // 尝试从多个来源获取LLM结果
            let llmResultsData = null;

            // 1. 首先尝试从任务结果获取
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

            // 2. 如果没有，尝试直接从LLM API获取
            if (!llmResultsData) {
                try {
                    const { pythonApi } = await import('../services/api');
                    const llmData = await pythonApi.get(`/api/llm/results/${activeContextId}`);
                    if (llmData.descriptions) {
                        console.log('Direct LLM results from Python API:', llmData);
                        llmResultsData = llmData;
                    }
                } catch (err) {
                    console.error('Failed to fetch direct LLM results:', err);
                }
            }

            // 3. 如果仍然没有，尝试从Python API获取分析文件列表
            if (!llmResultsData) {
                try {
                    const { pythonApi } = await import('../services/api');
                    const analyzedFiles = await pythonApi.get(`/api/db/query`, {
                        params: {
                            task_id: activeContextId,
                            query_type: 'analyzed_files'
                        }
                    });
                    if (analyzedFiles && analyzedFiles.length > 0) {
                        console.log('Analyzed files from Python API:', analyzedFiles);
                        llmResultsData = {
                            descriptions: analyzedFiles.map(file => ({
                                file_path: file.file_path,
                                summary: file.llm_summary || file.summary,
                                description: file.llm_description || file.description,
                                keywords: file.llm_keywords || file.keywords,
                                is_relevant: file.llm_is_relevant || file.is_relevant
                            }))
                        };
                    }
                } catch (err) {
                    console.error('Failed to fetch analyzed files:', err);
                }
            }

            if (llmResultsData) {
                setLlmResults(llmResultsData);
            } else {
                console.log('No LLM results found from any source');
                // 设置空的结果，确保UI正常显示
                setLlmResults({ descriptions: [] });
            }

            // 获取案例报告
            try {
                const reportData = await getCaseReport(activeContextId);
                if (reportData && (reportData.report || reportData.case_report)) {
                    setReport({
                        ...reportData,
                        report: reportData.report || reportData.case_report
                    });
                    setCaseDescription(reportData.case_description || '');
                }
            } catch (err) {
                console.error('Failed to fetch case report:', err);
            }

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

    // --- Actions: Case Analysis (Report Generation) ---
    const startPolling = useCallback(async (jobId) => {
        try {
            await pollCaseAnalysis(jobId, (status) => {
                dispatch(updateAnalysisProgress({
                    activeContextId,
                    currentStep: status.current_step || '分析中',
                    detail: status.detail || '正在处理...',
                    progress: status.progress || 0
                }));
            }, 3000);

            // Job completed successfully — now fetch the report
            dispatch(updateAnalysisProgress({ activeContextId, status: 'completed', progress: 100 }));
            try {
                const reportData = await getCaseReport(activeContextId);
                if (reportData && (reportData.report || reportData.case_report)) {
                    setReport({
                        ...reportData,
                        report: reportData.report || reportData.case_report
                    });
                }
            } catch (reportErr) {
                console.error('Report fetch after job completion failed:', reportErr);
                // Report will be loaded on next fetchData via page refresh
            }
            toast.success('报告生成成功！');
            setTimeout(() => dispatch(clearAnalysisJob({ activeContextId })), 10000);
        } catch (err) {
            console.error('Polling failed:', err);
            dispatch(updateAnalysisProgress({ activeContextId, status: 'failed', detail: err.message }));
            toast.error('生成失败: ' + err.message);
        }
    }, [activeContextId, dispatch, toast]);

    // AUTO-RESUME: Detect active job on mount and start polling
    useEffect(() => {
        if (activeJob && activeJob.status === 'running' && activeJob.jobId) {
            console.log(`[Intelligence] Auto-resuming polling for job: ${activeJob.jobId}`);
            startPolling(activeJob.jobId);
        }
    }, [activeContextId, activeJob?.status, activeJob?.jobId, startPolling]);

    const handleStartAnalysis = async () => {
        if (!activeContextId || !caseDescription.trim()) return;
        try {
            await saveCaseDescription(activeContextId, caseDescription);
            const result = await startCaseAnalysis({
                taskId: activeContextId,
                filesDbPath: currentTask?.output_files_db || '',
                caseDescription: caseDescription.trim(),
                maxFilterFiles: 200,
                run_filtering: runFiltering,
                report_only: !runFiltering,
            });

            if (result.job_id) {
                dispatch(setAnalysisJob({ activeContextId, jobId: result.job_id }));
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

    const scrollToFile = (targetPath) => {
        if (!targetPath) return;
        
        // 1. Clear search to ensure DOM elements exist
        setSearchQuery('');
        
        /**
         * Ultra-robust path normalization for forensic contexts
         */
        const superNormalize = (p) => {
            if (!p) return '';
            return p.trim()
                .replace(/\\/g, '/')           // Backslashes to forward
                .replace(/^\.\/+/g, '')        // Remove leading ./
                .replace(/\/+/g, '/')          // Dedup slashes
                .replace(/^\/+|\/+$/g, '')     // Remove start/end slashes
                .toLowerCase();
        };

        const normalizedTarget = superNormalize(targetPath);
        console.log(`[Indexing] Target: "${targetPath}" -> Normalized: "${normalizedTarget}"`);

        setTimeout(() => {
            const allItems = llmResults?.descriptions || [];
            
            // TIER 1: Exact Match
            let foundItem = allItems.find(d => d.file_path === targetPath);
            
            // TIER 2: Normalized Match
            if (!foundItem) {
                foundItem = allItems.find(d => superNormalize(d.file_path) === normalizedTarget);
            }
            
            // TIER 3: Tail Match (for cases where LLM uses short path)
            if (!foundItem && normalizedTarget.length > 3) {
                foundItem = allItems.find(d => {
                    const normDb = superNormalize(d.file_path);
                    return normDb.endsWith(normalizedTarget) || normalizedTarget.endsWith(normDb);
                });
            }
            
            if (foundItem) {
                const elementId = pathToId(foundItem.file_path);
                const element = document.getElementById(elementId);
                
                console.log(`[Indexing] Match found: "${foundItem.file_path}". Element ID: ${elementId}`);

                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    element.classList.add('ring-4', 'ring-purple-500', 'ring-opacity-60', 'scale-[1.02]');
                    setTimeout(() => element.classList.remove('ring-4', 'ring-purple-500', 'ring-opacity-60', 'scale-[1.02]'), 3000);
                    
                    setExpandedItems(p => ({ ...p, [foundItem.file_path]: true }));
                } else {
                    console.error('[Indexing] Element not found in DOM:', elementId);
                    toast.error('渲染延迟，请再点一次');
                }
            } else {
                console.warn('[Indexing] No evidence match for:', targetPath);
                toast.error(`未在证据库中找到: ${targetPath.split('/').pop()}`);
            }
        }, 350);
    };

    const renderMarkdown = (text) => {
        if (!text) return null;

        // Render a single reference token into an interactive badge, or null.
        const renderRef = (token, keyPrefix) => {
            const fileMatch = token.match(/^\[\[file:(.+)\]\]$/);
            if (fileMatch) {
                const fPath = fileMatch[1];
                return <button key={`${keyPrefix}-f`} onClick={() => scrollToFile(fPath)} className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-md text-[13px] font-mono hover:bg-purple-100 border border-purple-200 font-bold">📄 {fPath.split('/').pop()}</button>;
            }
            const eventMatch = token.match(/^\[\[event:([A-Za-z_]+)@(\d+)\/([^\]]*)\]\]$/);
            if (eventMatch) {
                const eType = eventMatch[1];
                const eWindow = eventMatch[2];
                const eDir = eventMatch[3];
                const label = `${eType}@${eWindow}/${eDir.split('/').filter(Boolean).pop() || eDir}`;
                const shortLabel = label.length > 32 ? label.slice(0, 32) + '…' : label;
                const params = new URLSearchParams({
                    task_id: activeContextId || '',
                    cluster: 'true',
                    type: eType,
                });
                return (
                    <button
                        key={`${keyPrefix}-e`}
                        onClick={() => navigate(`/timeline?${params.toString()}`)}
                        title={`事件簇: ${eType}@${eWindow}/${eDir}`}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-md text-[13px] font-mono hover:bg-blue-100 dark:hover:bg-blue-800/40 border border-blue-200 dark:border-blue-700 font-bold"
                    >
                        ⏱ {shortLabel}
                    </button>
                );
            }
            return null;
        };

        // Split a chunk on reference tokens; refs become badges, rest is text.
        const renderRefParts = (chunk, keyPrefix) => {
            const parts = chunk.split(/(\[\[(?:file|event):[^\]]+\]\])/g);
            return parts.map((part, j) => {
                const ref = renderRef(part, `${keyPrefix}-${j}`);
                if (ref) return ref;
                return <span key={`${keyPrefix}-${j}-t`}>{part}</span>;
            });
        };

        // IMPORTANT: split bold first, then resolve refs inside each chunk.
        // The LLM often wraps a whole reference in bold, so the reference token
        // is surrounded by double-asterisks. If we split references first and
        // match with start/end anchors, the surrounding asterisks break the
        // match and the whole reference renders as bold literal text instead of
        // a badge. Splitting bold first lets refs render even inside bold spans.
        const renderInline = (t, lineKey) => {
            const boldParts = t.split(/(\*\*[^*]+\*\*)/g);
            return boldParts.flatMap((bp, bi) => {
                const boldMatch = bp.match(/^\*\*(.+)\*\*$/);
                if (boldMatch) {
                    return [<strong key={`${lineKey}-b-${bi}`} className="font-bold text-slate-900 dark:text-slate-100">{renderRefParts(boldMatch[1], `${lineKey}-b-${bi}`)}</strong>];
                }
                return renderRefParts(bp, `${lineKey}-${bi}`);
            });
        };

        return <div className="prose prose-slate max-w-none dark:prose-invert">
            {text.split('\n').map((line, i) => {
                if (line.startsWith('# ')) return <h1 key={i} className="text-2xl font-bold mt-6 mb-3">{renderInline(line.slice(2), `l${i}`)}</h1>;
                if (line.startsWith('## ')) return <h2 key={i} className="text-xl font-semibold mt-5 mb-2">{renderInline(line.slice(3), `l${i}`)}</h2>;
                if (line.startsWith('### ')) return <h3 key={i} className="text-lg font-semibold mt-4 mb-2">{renderInline(line.slice(4), `l${i}`)}</h3>;
                if (line.startsWith('- ') || line.startsWith('* ')) return <li key={i} className="text-sm mb-1 ml-4 list-disc text-slate-700 dark:text-slate-300">{renderInline(line.slice(2), `l${i}`)}</li>;
                if (line.match(/^\d+\.\s/)) return <li key={i} className="text-sm mb-1 ml-4 list-decimal text-slate-700 dark:text-slate-300">{renderInline(line.replace(/^\d+\.\s/, ''), `l${i}`)}</li>;
                if (line.trim() === '') return null;
                return <p key={i} className="text-sm mb-2 leading-relaxed text-slate-700 dark:text-slate-300">{renderInline(line, `l${i}`)}</p>;
            })}
        </div>;
    };

    if (!activeContextId) {
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
                                <div className="h-full flex flex-col items-center justify-center text-center p-4"><span className="text-red-500 text-4xl mb-2">⚠️</span><p className="text-sm font-bold text-red-600">生成失败</p><p className="text-xs text-slate-500">{activeJob.detail}</p><Button variant="outline" size="sm" className="mt-4" onClick={() => dispatch(clearAnalysisJob({ activeContextId }))}>清除状态</Button></div>
                            ) : report?.report ? (
                                <div className="p-1 animate-in fade-in duration-500">{renderMarkdown(report.report)}</div>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2 opacity-50"><span className="text-6xl mb-2">📄</span><p className="text-sm font-medium">暂无报告内容</p></div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Cluster-Files Association Drawer */}
            <AnimatePresence>
                {selectedClusterForFiles && (
                    <>
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="fixed inset-0 bg-slate-900/20 backdrop-blur-sm z-40"
                            onClick={() => setSelectedClusterForFiles(null)}
                        />
                        <motion.div
                            initial={{ x: '100%' }}
                            animate={{ x: 0 }}
                            exit={{ x: '100%' }}
                            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                            className="fixed top-0 right-0 bottom-0 w-full lg:w-[600px] bg-white shadow-2xl z-50 border-l border-slate-200 flex flex-col"
                        >
                            {/* Header */}
                            <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                                <div>
                                    <h3 className="text-sm font-bold text-slate-900">📎 关联文件</h3>
                                    <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                                        {selectedClusterForFiles.event_type} @ {new Date(selectedClusterForFiles.timestamp * 1000).toLocaleTimeString()}
                                    </p>
                                </div>
                                <button
                                    onClick={() => setSelectedClusterForFiles(null)}
                                    className="p-2 hover:bg-slate-100 rounded-full transition-colors"
                                >
                                    <X size={18} />
                                </button>
                            </div>

                            {/* Content */}
                            <div className="flex-1 overflow-hidden">
                                {loadingClusterFiles ? (
                                    <div className="h-full flex flex-col items-center justify-center">
                                        <Spinner size="lg" />
                                        <span className="text-[10px] mt-4 text-slate-400">加载关联文件...</span>
                                    </div>
                                ) : clusterRelatedFiles.length === 0 ? (
                                    <div className="h-full flex flex-col items-center justify-center text-slate-400">
                                        <FileText size={32} strokeWidth={1} />
                                        <p className="text-sm mt-2">暂无关联文件</p>
                                    </div>
                                ) : (
                                    <Virtuoso
                                        data={clusterRelatedFiles}
                                        style={{ height: '100%' }}
                                        itemContent={(index, file) => {
                                            const fileAnomalies = file.anomalies || [];
                                            return (
                                                <div className={`px-4 py-3 border-b border-slate-50 ${fileAnomalies.length > 0 ? 'bg-red-50/30' : ''}`}>
                                                    {/* File Path */}
                                                    <div className="flex items-start gap-2 mb-2">
                                                        <span className="text-lg">📄</span>
                                                        <p className="text-[11px] text-slate-700 font-medium break-all flex-1">{file.file_path}</p>
                                                    </div>

                                                    {/* Time Differences */}
                                                    <div className="grid grid-cols-2 gap-2 mb-2">
                                                        {file.time_diffs && (
                                                            <>
                                                                {file.time_diffs.mtime_diff !== null && (
                                                                    <div className="text-[9px] bg-slate-50 px-2 py-1 rounded">
                                                                        <span className="text-slate-500">mtime: </span>
                                                                        <span className="font-mono text-slate-700">{file.time_diffs_formatted?.mtime_diff}</span>
                                                                    </div>
                                                                )}
                                                                {file.time_diffs.ctime_diff !== null && (
                                                                    <div className="text-[9px] bg-slate-50 px-2 py-1 rounded">
                                                                        <span className="text-slate-500">ctime: </span>
                                                                        <span className="font-mono text-slate-700">{file.time_diffs_formatted?.ctime_diff}</span>
                                                                    </div>
                                                                )}
                                                            </>
                                                        )}
                                                    </div>

                                                    {/* Anomalies */}
                                                    {fileAnomalies.length > 0 && (
                                                        <div className="flex flex-wrap gap-1 mt-2">
                                                            {fileAnomalies.map((anomaly, idx) => (
                                                                <span
                                                                    key={idx}
                                                                    className={`text-[9px] px-2 py-0.5 rounded-full border font-medium ${getAnomalyColorClass(getAnomalySeverity(anomaly))}`}
                                                                >
                                                                    <AlertTriangle size={10} className="inline mr-1" />
                                                                    {formatAnomalyType(anomaly)}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    )}

                                                    {/* File Summary if available */}
                                                    {file.llm_summary && (
                                                        <p className="text-[10px] text-slate-500 mt-2 line-clamp-2">{file.llm_summary}</p>
                                                    )}
                                                </div>
                                            );
                                        }}
                                    />
                                )}
                            </div>

                            {/* Footer */}
                            <div className="p-3 border-t border-slate-100 bg-slate-50/80 text-[10px] text-slate-500 flex justify-between">
                                <span>共 {clusterRelatedFiles.length} 个关联文件</span>
                                <span className="text-purple-500 font-medium">时间关联分析</span>
                            </div>
                        </motion.div>
                    </>
                )}
            </AnimatePresence>

            {/* File-Clusters Association Drawer */}
            <AnimatePresence>
                {selectedFileForClusters && (
                    <>
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="fixed inset-0 bg-slate-900/20 backdrop-blur-sm z-40"
                            onClick={() => setSelectedFileForClusters(null)}
                        />
                        <motion.div
                            initial={{ x: '100%' }}
                            animate={{ x: 0 }}
                            exit={{ x: '100%' }}
                            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                            className="fixed top-0 right-0 bottom-0 w-full lg:w-[500px] bg-white shadow-2xl z-50 border-l border-slate-200 flex flex-col"
                        >
                            {/* Header */}
                            <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                                <div>
                                    <h3 className="text-sm font-bold text-slate-900">🔗 关联事件簇</h3>
                                    <p className="text-[10px] text-slate-500 font-mono mt-0.5 max-w-[300px] truncate">
                                        {selectedFileForClusters.file_path}
                                    </p>
                                </div>
                                <button
                                    onClick={() => setSelectedFileForClusters(null)}
                                    className="p-2 hover:bg-slate-100 rounded-full transition-colors"
                                >
                                    <X size={18} />
                                </button>
                            </div>

                            {/* Content */}
                            <div className="flex-1 overflow-hidden">
                                {loadingFileClusters ? (
                                    <div className="h-full flex flex-col items-center justify-center">
                                        <Spinner size="lg" />
                                        <span className="text-[10px] mt-4 text-slate-400">加载关联事件簇...</span>
                                    </div>
                                ) : fileRelatedClusters.length === 0 ? (
                                    <div className="h-full flex flex-col items-center justify-center text-slate-400">
                                        <Clock size={32} strokeWidth={1} />
                                        <p className="text-sm mt-2">暂无关联事件簇</p>
                                    </div>
                                ) : (
                                    <Virtuoso
                                        data={fileRelatedClusters}
                                        style={{ height: '100%' }}
                                        itemContent={(index, cluster) => (
                                            <div className="px-4 py-3 border-b border-slate-50 hover:bg-slate-50 transition-colors">
                                                {/* Event Type Badge */}
                                                <div className="flex items-center gap-2 mb-2">
                                                    <Badge variant={
                                                        cluster.event_type === 'CREATED' ? 'green' :
                                                        cluster.event_type === 'MODIFIED' ? 'blue' :
                                                        cluster.event_type === 'DELETED' ? 'red' : 'gray'
                                                    } className="text-[9px] px-2 py-0.5 font-bold">
                                                        {cluster.event_type}
                                                    </Badge>
                                                    <span className="text-[10px] text-slate-500">
                                                        {new Date(cluster.representative_timestamp * 1000).toLocaleString()}
                                                    </span>
                                                </div>

                                                {/* Directory */}
                                                <p className="text-[10px] text-slate-600 font-mono mb-1 truncate">
                                                    📁 {cluster.parent_directory || '/'}
                                                </p>

                                                {/* Match Info */}
                                                {cluster.matched_time && (
                                                    <div className="text-[9px] bg-purple-50 px-2 py-1 rounded mb-1">
                                                        <span className="text-purple-700">匹配时间: {cluster.matched_time} </span>
                                                        <span className="text-purple-500 font-mono">({cluster.time_diff_formatted})</span>
                                                    </div>
                                                )}

                                                {/* Event Count */}
                                                <div className="text-[9px] text-slate-500">
                                                    包含 {cluster.cluster_count || cluster.event_count} 个事件
                                                </div>

                                                {/* AI Summary */}
                                                {cluster.llm_summary && (
                                                    <p className="text-[10px] text-slate-600 mt-2 line-clamp-2">{cluster.llm_summary}</p>
                                                )}

                                                {/* Action Button */}
                                                <button
                                                    onClick={() => {
                                                        setSelectedFileForClusters(null);
                                                        navigate(`/timeline?task_id=${activeContextId}&type=${cluster.event_type}&cluster=true`);
                                                    }}
                                                    className="mt-2 text-[9px] text-blue-500 hover:text-blue-700 font-medium"
                                                >
                                                    在时间线中查看 →
                                                </button>
                                            </div>
                                        )}
                                    />
                                )}
                            </div>

                            {/* Footer */}
                            <div className="p-3 border-t border-slate-100 bg-slate-50/80 text-[10px] text-slate-500 flex justify-between">
                                <span>共 {fileRelatedClusters.length} 个关联事件簇</span>
                                <span className="text-blue-500 font-medium">时间关联分析</span>
                            </div>
                        </motion.div>
                    </>
                )}
            </AnimatePresence>

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
