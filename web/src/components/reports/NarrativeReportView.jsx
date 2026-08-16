// NarrativeReportView.jsx
// R2d narrative 报告阅读视图：只消费 persisted narrative version 的
// strict 读响应（sections + persisted citation manifest + audit 元数据）。
// 历史 V1 的内容与其 citation identity 完全来自发布时冻结的 manifest，
// 之后 Investigation 里的 rebind/新 accepted/claim 变化都不会改变这里
// 显示的内容（§12/§16）。citation 点击 = exact citation_id → manifest
// entry 查表，绝不在正文里做 regex/Markdown token 推导（§13）。
import { useEffect, useRef, useState } from 'react';
import { FileText } from 'lucide-react';
import CitationTracebackPanel from './CitationTracebackPanel';

const NarrativeReportView = ({
    taskId,
    reportId,
    fetchNarrative,
    TracebackPanel = CitationTracebackPanel,
}) => {
    // identity 绑定 {taskId, reportId}：切换版本/任务后旧响应不写入。
    const identity = taskId && reportId ? `${taskId}|${reportId}` : null;
    const [report, setReport] = useState(null);
    const [error, setError] = useState(null);
    const [openCitationId, setOpenCitationId] = useState(null);
    const identityRef = useRef(null);

    useEffect(() => {
        identityRef.current = identity;
        setReport(null);
        setError(null);
        setOpenCitationId(null);
        if (!identity) return undefined;
        let cancelled = false;

        fetchNarrative(taskId, reportId)
            .then((body) => {
                if (cancelled || identityRef.current !== identity) return;
                setReport(body);
            })
            .catch((nextError) => {
                if (cancelled || identityRef.current !== identity) return;
                setError(nextError);
            });

        return () => { cancelled = true; };
    }, [identity, taskId, reportId, fetchNarrative]);

    const citationsById = new Map((report?.citations || []).map((entry) => [entry.citation_id, entry]));
    const openEntry = openCitationId ? citationsById.get(openCitationId) || null : null;

    return (
        <div className="space-y-4" data-testid="narrative-report-view">
            {error && (
                <div role="alert" className="rounded-2xl border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-900/20 p-4 text-sm text-rose-600 dark:text-rose-400" data-testid="narrative-report-error">
                    叙事报告暂时不可读取（HTTP {error?.status || '错误'}）：
                    {error?.data?.detail || error?.message || '请稍后重试'}
                </div>
            )}
            {!report && !error && (
                <p className="text-sm text-slate-400" data-testid="narrative-report-loading">正在读取叙事报告…</p>
            )}
            {report && (
                <>
                    <header className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 space-y-2">
                        <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
                            <FileText size={16} />
                            {report.title}
                        </h2>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                            叙事报告版本 v{report.version} · 生成时间 {report.created_at}
                        </p>
                        {/* audit 元数据：可展示，但冻结 prompt/envelope 不是正文 */}
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-slate-400" data-testid="narrative-audit-metadata">
                            <span>generation {report.generation_id}</span>
                            <span>prompt {report.prompt_version}</span>
                            <span>model {report.model}</span>
                            <span>input_hash {report.input_hash?.slice(0, 16)}…</span>
                        </div>
                    </header>

                    <article className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 space-y-5" data-testid="narrative-sections">
                        {(report.sections || []).map((section, index) => (
                            <section key={`${section.heading}-${index}`} className="space-y-2" data-testid="narrative-section">
                                <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200">{section.heading}</h3>
                                <p className="whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                                    {section.content}
                                </p>
                                {section.citation_ids?.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5 pt-1">
                                        {section.citation_ids.map((citationId) => (
                                            <button
                                                key={citationId}
                                                type="button"
                                                data-testid={`citation-chip-${citationId}`}
                                                onClick={() => setOpenCitationId(
                                                    (previous) => (previous === citationId ? null : citationId),
                                                )}
                                                className="rounded-full border border-blue-200 dark:border-blue-900/60 bg-blue-50/70 dark:bg-blue-900/30 px-2 py-0.5 text-[10px] font-mono text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/50"
                                            >
                                                {citationId}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </section>
                        ))}
                    </article>

                    {openCitationId && !openEntry && (
                        <p className="text-xs text-amber-600 dark:text-amber-400" data-testid="citation-unknown-warning">
                            未知引用 ID：{openCitationId}。manifest 中不存在该引用，不做任何推测。
                        </p>
                    )}
                    {openEntry && (
                        <TracebackPanel
                            taskId={taskId}
                            reportId={reportId}
                            citation={openEntry}
                            onClose={() => setOpenCitationId(null)}
                        />
                    )}
                </>
            )}
        </div>
    );
};

export default NarrativeReportView;
