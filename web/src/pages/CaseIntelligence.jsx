import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { ArrowLeft } from 'lucide-react';
import IntelligenceReportReader from '../components/case-intelligence/report-reader/IntelligenceReportReader';
import ForensicReportPage from './ForensicReportPage';
import { getCase } from '../services/caseGroupService';

/**
 * 证据研判 (Case Intelligence)
 *
 * 报告阅读器页面。提供两种报告视图的切换：
 *  - 情报研判报告：IntelligenceReportReader（基于 LLM 生成的研判报告）
 *  - 取证快照报告：ForensicReportPage（基于取证快照的版本化报告）
 *
 * 真正的研判工作区（案情背景、证据卡片、事件簇、报告预览）已迁移到
 * 研判中心页面（/analysis-center），通过点击 "研判工具" 按钮跳转进入。
 *
 * 上下文两种：task_id（单任务）或 case_id（案件）。历史研判报告按任务读取，
 * case 上下文下先解析案件的 task_ids 并让用户在案件任务间切换。
 */
const CaseIntelligence = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const caseId = searchParams.get('case_id');
    const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
    const activeContextId = caseId || urlTaskId;
    const { tasks: allTasks } = useSelector((state) => state.tasks);

    // Tab 切换：'intelligence' 历史兼容报告 | 'forensic' 当前取证/叙事报告。
    // 当前报告工作流默认使用 R2；历史 Chain B 内容必须通过显式 query 查看。
    const [reportTab, setReportTab] = useState(
        () => (searchParams.get('tab') === 'intelligence' ? 'intelligence' : 'forensic'),
    );

    // case 上下文：案件记录 + 当前选中的案件任务（历史研判报告按任务读取）。
    const [caseInfo, setCaseInfo] = useState(null);
    const [caseError, setCaseError] = useState(null);
    const [selectedCaseTask, setSelectedCaseTask] = useState('');

    useEffect(() => {
        if (!caseId) {
            setCaseInfo(null);
            setCaseError(null);
            return undefined;
        }
        let cancelled = false;
        setCaseError(null);
        getCase(caseId)
            .then((data) => { if (!cancelled) setCaseInfo(data); })
            .catch((err) => { if (!cancelled) setCaseError(err); });
        return () => { cancelled = true; };
    }, [caseId]);

    const caseTaskOptions = useMemo(() => {
        const ids = caseInfo?.task_ids || [];
        return ids.map((id) => {
            const t = allTasks.find((x) => x.id === id);
            const name = t?.name || t?.image_path?.split('/').pop() || id.slice(0, 8);
            return { id, label: `${name} (${id.slice(0, 8)})${t?.status ? ` - ${t.status}` : ''}`, status: t?.status || '' };
        });
    }, [caseInfo, allTasks]);

    // 默认选第一个 completed 的案件任务；等案件/任务列表到位后再兜底一次。
    useEffect(() => {
        if (!caseId || selectedCaseTask || caseTaskOptions.length === 0) return;
        const done = caseTaskOptions.find((t) => t.status === 'completed');
        setSelectedCaseTask((done || caseTaskOptions[0]).id);
    }, [caseId, selectedCaseTask, caseTaskOptions]);

    // 历史研判报告阅读器的任务上下文：case 下用选中的案件任务。
    const readerTaskId = caseId ? selectedCaseTask : urlTaskId;

    const switchTab = (tab) => {
        setReportTab(tab);
        // tab 写回 URL：深链/刷新/回退都停留在当前视图。
        const next = new URLSearchParams(searchParams);
        next.set('tab', tab);
        setSearchParams(next, { replace: true });
    };

    // 取证快照报告的 scope：case 上下文用 case_id，否则用 task_id
    const forensicScopeType = caseId ? 'case' : 'task';
    const forensicScopeId = caseId || urlTaskId;

    const noContextPlaceholder = useMemo(() => {
        if (activeContextId) return null;
        return (
            <div className="max-w-4xl mx-auto py-12 px-4">
                <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-8 text-center">
                    <h2 className="text-lg font-bold text-slate-700 dark:text-white mb-2">🔍 选择一个任务进入证据研判</h2>
                    <p className="text-sm text-slate-500">请在顶部任务选择器中选择一个镜像任务。</p>
                </div>
            </div>
        );
    }, [activeContextId]);

    if (!activeContextId) {
        return noContextPlaceholder;
    }

    const renderIntelligence = () => {
        if (!caseId) return <IntelligenceReportReader taskId={readerTaskId} />;
        if (caseError) {
            return (
                <div role="alert" className="p-4 rounded-xl bg-red-50 text-red-700 text-sm">
                    加载案件失败：{caseError?.data?.detail || caseError?.message || String(caseError)}
                </div>
            );
        }
        if (!caseInfo) {
            return <div className="p-8 text-sm text-slate-500">正在加载案件信息…</div>;
        }
        if (caseTaskOptions.length === 0) {
            return (
                <div className="p-8 text-sm text-slate-500 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
                    该案件还没有关联任务，请先在案件页添加镜像任务。
                </div>
            );
        }
        return (
            <>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-slate-500 dark:text-slate-400">案件任务：</span>
                    <select
                        value={selectedCaseTask}
                        onChange={(e) => setSelectedCaseTask(e.target.value)}
                        data-testid="case-task-select"
                        className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-xs"
                    >
                        {caseTaskOptions.map((t) => (
                            <option key={t.id} value={t.id}>{t.label}</option>
                        ))}
                    </select>
                </div>
                {readerTaskId ? (
                    <IntelligenceReportReader key={readerTaskId} taskId={readerTaskId} />
                ) : (
                    <div className="p-8 text-sm text-slate-500">正在解析案件任务…</div>
                )}
            </>
        );
    };

    return (
        <div className="max-w-[1600px] mx-auto space-y-6">
            {/* 报告视图切换 Tab */}
            <div className="flex flex-wrap items-center gap-2 p-1.5 bg-slate-100 dark:bg-slate-800/50 rounded-xl">
                <button
                    onClick={() => switchTab('intelligence')}
                    className={`px-4 py-2 text-sm font-bold rounded-lg transition-all flex items-center gap-2 whitespace-nowrap ${
                        reportTab === 'intelligence'
                        ? 'bg-white dark:bg-slate-700 text-purple-600 dark:text-purple-400 shadow-sm'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                    }`}
                >
                    📑 历史研判报告
                </button>
                <button
                    onClick={() => switchTab('forensic')}
                    className={`px-4 py-2 text-sm font-bold rounded-lg transition-all flex items-center gap-2 whitespace-nowrap ${
                        reportTab === 'forensic'
                        ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                    }`}
                >
                    📋 取证报告
                </button>
                {/* R2d：task 上下文时返回调查工作台（同一全局 TaskSelector task）。 */}
                {urlTaskId && (
                    <Link
                        to={`/investigation?taskId=${encodeURIComponent(urlTaskId)}`}
                        data-testid="back-to-investigation"
                        className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                    >
                        <ArrowLeft size={12} />
                        返回调查工作台
                    </Link>
                )}
            </div>

            {reportTab === 'intelligence' ? renderIntelligence() : (
                <ForensicReportPage
                    key={`${forensicScopeType}-${forensicScopeId}`}
                    scopeType={forensicScopeType}
                    scopeId={forensicScopeId}
                />
            )}
        </div>
    );
};

export default CaseIntelligence;
