import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { Search as SearchIcon, FileText, Save } from 'lucide-react';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import ReportEvidenceJudgment from '../components/investigation/ReportEvidenceJudgment';
import { fetchTasks } from '../store/taskSlice';
import { fetchCases } from '../store/caseSlice';
import { useToast } from '../components/common/useToast';
import { fetchTaskById } from '../services/taskService';
import { saveCaseDescription } from '../services/caseAnalysisService';
import { listReportEvidenceFileCandidates } from '../services/investigationService';

/**
 * 证据判定 (Evidence Review) — /analysis-center
 *
 * 以文件为核心：逐个判定任务内的文件是否作为版本化取证报告的证据
 * （正文证据 / 附件证据 / 移出报告）。判定直接写入 R1 报告证据真相源
 * （/api/reports/evidence），取证报告页按只读投影消费。
 * 事件/事件簇不参与判定——当前报告链只吃文件证据。
 */

const PAGE_SIZE = 50;

const STATUS_TABS = [
    { key: 'all', label: '全部' },
    { key: 'main', label: '正文证据' },
    { key: 'appendix', label: '附件证据' },
    { key: 'unjudged', label: '未判定' },
    { key: 'excluded', label: '已排除' },
];

const formatSize = (bytes) => {
    if (bytes == null) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

const formatTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : '—');

const EvidenceReviewPage = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const caseId = searchParams.get('case_id');
    const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
    const [activeContextId, setActiveContextId] = useState(caseId || urlTaskId);

    const navigate = useNavigate();
    const dispatch = useDispatch();
    const toast = useToast();
    const { tasks } = useSelector((state) => state.tasks);
    const { cases } = useSelector((state) => state.cases);

    const activeCase = caseId ? cases.find(c => c.id === caseId) : null;

    // --- 案情背景（保留的描述编辑能力） ---
    const [caseDescription, setCaseDescription] = useState('');
    const [savingDescription, setSavingDescription] = useState(false);

    // --- 证据判定列表 ---
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [statusCounts, setStatusCounts] = useState({ main: 0, appendix: 0, excluded: 0, unjudged: 0 });
    const [page, setPage] = useState(1);
    const [statusFilter, setStatusFilter] = useState('all');
    const [searchInput, setSearchInput] = useState('');
    const [search, setSearch] = useState('');
    const [loading, setLoading] = useState(false);
    const searchTimer = useRef(null);

    useEffect(() => {
        dispatch(fetchTasks({ status: 'all', priority: 'all' }));
        if (caseId) dispatch(fetchCases());
    }, [dispatch, caseId]);

    useEffect(() => {
        if (!activeContextId && (caseId || urlTaskId)) {
            setActiveContextId(caseId || urlTaskId);
        }
    }, [caseId, urlTaskId, activeContextId]);

    // 回显已保存的案情描述
    useEffect(() => {
        if (!activeContextId || activeContextId === caseId) return undefined;
        let alive = true;
        fetchTaskById(activeContextId)
            .then((task) => {
                if (alive && task?.case_description) setCaseDescription(task.case_description);
            })
            .catch(() => {});
        return () => { alive = false; };
    }, [activeContextId, caseId]);

    const loadCandidates = useCallback(async () => {
        if (!activeContextId || activeContextId === caseId) return;
        setLoading(true);
        try {
            const data = await listReportEvidenceFileCandidates(activeContextId, {
                search,
                status: statusFilter,
                page,
                page_size: PAGE_SIZE,
            });
            setItems(data?.items || []);
            setTotal(data?.total || 0);
            setStatusCounts(data?.status_counts || { main: 0, appendix: 0, excluded: 0, unjudged: 0 });
        } catch (err) {
            console.error('Failed to load evidence candidates:', err);
            toast.error('加载证据清单失败: ' + (err?.response?.data?.detail || err?.message || err));
            setItems([]);
            setTotal(0);
        } finally {
            setLoading(false);
        }
    }, [activeContextId, caseId, search, statusFilter, page, toast]);

    useEffect(() => {
        loadCandidates();
    }, [loadCandidates]);

    // 搜索防抖：输入后 400ms 才真正触发查询并回到第一页
    const handleSearchInput = (value) => {
        setSearchInput(value);
        if (searchTimer.current) clearTimeout(searchTimer.current);
        searchTimer.current = setTimeout(() => {
            setSearch(value.trim());
            setPage(1);
        }, 400);
    };

    const handleSaveDescription = async () => {
        if (!activeContextId || activeContextId === caseId || !caseDescription.trim()) return;
        setSavingDescription(true);
        try {
            await saveCaseDescription(activeContextId, caseDescription.trim());
            toast.success('案情描述已保存');
        } catch (err) {
            toast.error('保存案情描述失败: ' + (err?.message || err));
        } finally {
            setSavingDescription(false);
        }
    };

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const totalFiles = useMemo(
        () => Object.values(statusCounts).reduce((a, b) => a + (b || 0), 0),
        [statusCounts],
    );

    const reportQuery = (tid) => `taskId=${encodeURIComponent(tid)}`;

    if (!activeContextId) {
        return (
            <div className="max-w-4xl mx-auto py-12 px-4">
                <Card title="🛡 选择一个任务进行证据判定">
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
            {/* Case 层级：仅用于在子任务之间切换；判定本身永远 task 级 */}
            {activeCase && (
                <div className="flex gap-2 p-1.5 bg-slate-100 dark:bg-slate-800/50 rounded-xl overflow-x-auto custom-scrollbar">
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

            {activeContextId === caseId ? (
                <Card title="🛡 证据判定按任务进行">
                    <p className="text-sm text-slate-500">请从上方选择一个具体子任务，再对其文件进行报告证据判定。</p>
                </Card>
            ) : (
                <div className="space-y-4">
                    {/* 案情背景（保留） */}
                    <Card className="border-l-4 border-purple-500">
                        <div className="space-y-4">
                            <div className="flex items-center justify-between flex-wrap gap-3">
                                <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">📝 案情背景</h2>
                                <div className="flex items-center gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={handleSaveDescription}
                                        disabled={savingDescription || !caseDescription.trim()}
                                    >
                                        <Save size={14} className="mr-1" />
                                        {savingDescription ? '保存中...' : '保存案情描述'}
                                    </Button>
                                    <Button
                                        variant="primary"
                                        size="sm"
                                        onClick={() => navigate(`/case-intelligence?${reportQuery(activeContextId)}&tab=forensic`)}
                                    >
                                        📋 打开取证报告
                                    </Button>
                                </div>
                            </div>
                            <p className="text-sm text-slate-500 dark:text-slate-400">
                                逐个判定文件是否进入版本化取证报告：正文证据 / 附件证据 / 移出。判定结果即时生效于下一次报告生成。
                            </p>
                            <textarea value={caseDescription} onChange={(e) => setCaseDescription(e.target.value)} className="w-full h-24 p-3 text-sm border border-slate-200 dark:border-slate-700 rounded-xl dark:bg-slate-900 resize-none focus:ring-2 focus:ring-purple-500" placeholder="描述案情关键词..." />
                        </div>
                    </Card>

                    {/* 统计 + 过滤 + 搜索 */}
                    <div className="flex flex-col lg:flex-row gap-4 lg:items-center">
                        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 flex-1">
                            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700 px-4 py-2.5">
                                <p className="text-[10px] font-bold text-slate-400">文件总数</p>
                                <p className="text-xl font-bold text-slate-700 dark:text-white">{totalFiles.toLocaleString()}</p>
                            </div>
                            <div className="bg-white dark:bg-slate-800 rounded-xl border border-purple-100 dark:border-purple-900/40 px-4 py-2.5">
                                <p className="text-[10px] font-bold text-purple-400">正文证据</p>
                                <p className="text-xl font-bold text-purple-600">{statusCounts.main}</p>
                            </div>
                            <div className="bg-white dark:bg-slate-800 rounded-xl border border-blue-100 dark:border-blue-900/40 px-4 py-2.5">
                                <p className="text-[10px] font-bold text-blue-400">附件证据</p>
                                <p className="text-xl font-bold text-blue-600">{statusCounts.appendix}</p>
                            </div>
                            <div className="bg-white dark:bg-slate-800 rounded-xl border border-amber-100 dark:border-amber-900/40 px-4 py-2.5">
                                <p className="text-[10px] font-bold text-amber-400">未判定</p>
                                <p className="text-xl font-bold text-amber-500">{statusCounts.unjudged.toLocaleString()}</p>
                            </div>
                            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700 px-4 py-2.5">
                                <p className="text-[10px] font-bold text-slate-400">已排除</p>
                                <p className="text-xl font-bold text-slate-500">{statusCounts.excluded}</p>
                            </div>
                        </div>
                        <div className="relative lg:w-80">
                            <span className="absolute left-3 top-2.5 text-slate-400"><SearchIcon size={15} /></span>
                            <input
                                type="text"
                                value={searchInput}
                                onChange={(e) => handleSearchInput(e.target.value)}
                                placeholder="按路径搜索文件..."
                                className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-xl dark:bg-slate-800 focus:ring-2 focus:ring-purple-500"
                            />
                        </div>
                    </div>

                    <div className="flex items-center gap-2 bg-slate-100 dark:bg-slate-800 rounded-full p-1 w-fit">
                        {STATUS_TABS.map(tab => (
                            <button
                                key={tab.key}
                                onClick={() => { setStatusFilter(tab.key); setPage(1); }}
                                className={`px-3.5 py-1.5 text-xs font-bold rounded-full transition-all ${
                                    statusFilter === tab.key
                                        ? 'bg-white dark:bg-slate-700 text-purple-600 shadow-sm'
                                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                                }`}
                            >
                                {tab.label}
                                {tab.key !== 'all' && (
                                    <span className="ml-1 text-[10px] text-slate-400">
                                        {tab.key === 'unjudged' ? statusCounts.unjudged : statusCounts[tab.key]}
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>

                    {/* 判定列表 */}
                    <div className="space-y-2">
                        {loading ? (
                            <div className="flex items-center gap-3 p-6 text-sm text-slate-500 dark:text-slate-400 bg-white/70 dark:bg-slate-800/70 rounded-2xl border border-slate-100 dark:border-slate-700">
                                <span className="animate-spin inline-block h-4 w-4 border-2 border-purple-500 border-t-transparent rounded-full"></span>
                                正在加载文件证据…
                            </div>
                        ) : items.length === 0 ? (
                            <div className="p-8 text-center text-sm text-slate-400 bg-white/60 dark:bg-slate-800/60 rounded-2xl border border-slate-100 dark:border-slate-700">
                                没有匹配的文件。换个关键词或切换判定状态试试。
                            </div>
                        ) : (
                            items.map((item) => {
                                const statusKey = item.report_status || 'unjudged';
                                const analyzed = !!item.llm_analyzed_at;
                                return (
                                    <div
                                        key={item.evidence_key}
                                        className={`p-3.5 rounded-2xl border transition-all ${
                                            item.report_status === 'main'
                                                ? 'bg-purple-50/60 dark:bg-slate-800 border-purple-200 dark:border-purple-900/40'
                                                : item.report_status === 'appendix'
                                                    ? 'bg-blue-50/60 dark:bg-slate-800 border-blue-200 dark:border-blue-900/40'
                                                    : 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700'
                                        }`}
                                    >
                                        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <FileText size={14} className="text-slate-400 shrink-0" />
                                                    <p className="font-mono text-xs font-bold text-slate-700 dark:text-slate-200 truncate" title={item.path}>
                                                        {item.path}
                                                    </p>
                                                    {item.is_deleted ? (
                                                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-600">已删除</span>
                                                    ) : null}
                                                    {analyzed && (
                                                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-green-100 text-green-700">AI 已分析</span>
                                                    )}
                                                    {item.scene_relevant ? (
                                                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-600">场景相关</span>
                                                    ) : null}
                                                </div>
                                                <div className="mt-1 flex items-center gap-3 text-[10px] text-slate-400 font-medium">
                                                    <span>{formatSize(item.size)}</span>
                                                    <span>修改: {formatTime(item.mtime)}</span>
                                                    {item.category && <span>{item.category}</span>}
                                                    {item.llm_summary && (
                                                        <span className="truncate max-w-md text-slate-400" title={item.llm_summary}>{item.llm_summary}</span>
                                                    )}
                                                </div>
                                            </div>
                                            {/* 判定动作：与调查工作台共用同一组件（单一真相源 R1） */}
                                            <div className="shrink-0">
                                                <ReportEvidenceJudgment
                                                    taskId={activeContextId}
                                                    evidenceKey={item.evidence_key}
                                                    status={item.report_status}
                                                    onChanged={() => loadCandidates()}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    {/* 分页 */}
                    {total > PAGE_SIZE && (
                        <div className="flex items-center justify-between text-sm text-slate-500">
                            <span>共 {total.toLocaleString()} 个文件 · 第 {page} / {totalPages} 页</span>
                            <div className="flex gap-2">
                                <Button variant="outline" size="sm" disabled={page <= 1 || loading} onClick={() => setPage(p => Math.max(1, p - 1))}>上一页</Button>
                                <Button variant="outline" size="sm" disabled={page >= totalPages || loading} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>下一页</Button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default EvidenceReviewPage;
