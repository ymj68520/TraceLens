import { useState, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import IntelligenceReportReader from '../components/case-intelligence/report-reader/IntelligenceReportReader';
import ForensicReportPage from './ForensicReportPage';

/**
 * 证据研判 (Case Intelligence)
 *
 * 报告阅读器页面。提供两种报告视图的切换：
 *  - 情报研判报告：IntelligenceReportReader（基于 LLM 生成的研判报告）
 *  - 取证快照报告：ForensicReportPage（基于取证快照的版本化报告）
 *
 * 真正的研判工作区（案情背景、证据卡片、事件簇、报告预览）已迁移到
 * 研判中心页面（/analysis-center），通过点击 "研判工具" 按钮跳转进入。
 */
const CaseIntelligence = () => {
    const [searchParams] = useSearchParams();
    const caseId = searchParams.get('case_id');
    const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
    const activeContextId = caseId || urlTaskId;

    // Tab 切换：'intelligence' 情报研判报告 | 'forensic' 取证快照/叙事报告。
    // R2d：Workbench 的 "生成叙事报告" 入口通过 ?tab=forensic 直达报告页。
    const [reportTab, setReportTab] = useState(
        () => (searchParams.get('tab') === 'forensic' ? 'forensic' : 'intelligence'),
    );

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

    return (
        <div className="max-w-[1600px] mx-auto space-y-6">
            {/* 报告视图切换 Tab */}
            <div className="flex flex-wrap items-center gap-2 p-1.5 bg-slate-100 dark:bg-slate-800/50 rounded-xl">
                <button
                    onClick={() => setReportTab('intelligence')}
                    className={`px-4 py-2 text-sm font-bold rounded-lg transition-all flex items-center gap-2 whitespace-nowrap ${
                        reportTab === 'intelligence'
                        ? 'bg-white dark:bg-slate-700 text-purple-600 dark:text-purple-400 shadow-sm'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                    }`}
                >
                    📑 情报研判报告
                </button>
                <button
                    onClick={() => setReportTab('forensic')}
                    className={`px-4 py-2 text-sm font-bold rounded-lg transition-all flex items-center gap-2 whitespace-nowrap ${
                        reportTab === 'forensic'
                        ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                    }`}
                >
                    📋 取证快照 / 叙事报告
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

            {reportTab === 'intelligence' ? (
                <IntelligenceReportReader taskId={activeContextId} />
            ) : (
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
