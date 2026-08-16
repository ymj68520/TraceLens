// SubmitAnalysisForm.jsx
// Evidence 视图下的显式 "Run Secondary Analysis" 动作（C9b）。
//
// 边界：
//   - 只暴露后端 CreateAnalysisRequest 真实支持的 analyst context
//     （Analyst Note / Case Context / Related Evidence），不造参数；
//   - Related Evidence 只能从本任务已捕获的 canonical Evidence 里多选
//     （自动排除 primary、Set 去重），不允许自由输入 key；
//   - 提交只走 POST /api/investigation/analyses——不触碰 Snapshot、
//     Initial Analysis 或 reanalyze-files；
//   - submittingRef 保证 rapid double-click 只产生一次 POST；页面还会在
//     该 submission 处于 queued/running 期间保持按钮 disabled（busy）。
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, Play } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';

const SubmitAnalysisForm = ({ evidenceKey, evidenceOptions = [], busy = false, onSubmit }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [analystNote, setAnalystNote] = useState('');
    const [caseContext, setCaseContext] = useState('');
    const [related, setRelated] = useState(() => new Set());
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const submittingRef = useRef(false);

    // 切换 Evidence 时复位表单（旧 evidence 的草稿不得带过去）。
    useEffect(() => {
        setOpen(false);
        setAnalystNote('');
        setCaseContext('');
        setRelated(new Set());
        setSubmitError(null);
    }, [evidenceKey]);

    // picker 候选 = 本任务全部已捕获 Evidence，排除 primary key（§11）。
    const relatedOptions = evidenceOptions.filter((key) => key !== evidenceKey);

    const toggleRelated = (key) => {
        setRelated((previous) => {
            const next = new Set(previous);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const resetInputs = () => {
        setAnalystNote('');
        setCaseContext('');
        setRelated(new Set());
    };

    const handleSubmit = async () => {
        if (submittingRef.current) return;
        submittingRef.current = true;
        setSubmitting(true);
        setSubmitError(null);
        try {
            await onSubmit({
                evidence_key: evidenceKey,
                analyst_note: analystNote.trim() ? analystNote : null,
                case_context: caseContext.trim() ? caseContext : null,
                related_evidence: [...related],
            });
            setOpen(false);
            resetInputs();
        } catch (error) {
            // POST 提交失败（422/404/503…）与后续 status=failed 是两类错误，
            // 这里只展示前者。
            setSubmitError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    const disabled = submitting || busy;

    return (
        <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2" data-testid="submit-analysis-form">
            <button
                type="button"
                data-testid="run-analysis-toggle"
                onClick={() => setOpen((previous) => !previous)}
                disabled={disabled}
                className="w-full flex items-center justify-between gap-2 text-[11px] font-semibold text-slate-600 dark:text-slate-300 disabled:opacity-50"
            >
                <span className="flex items-center gap-1.5">
                    <Play size={11} />
                    {t('investigation_workbench.run_analysis')}
                </span>
                {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            {busy && !open && (
                <p className="mt-1 text-[10px] text-amber-600 dark:text-amber-400">
                    {t('investigation_workbench.analysis_in_progress')}
                </p>
            )}

            {open && (
                <div className="mt-2 space-y-2">
                    <p className="text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">
                        {t('investigation_workbench.context_disclaimer')}
                    </p>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.analyst_note')}
                        </span>
                        <textarea
                            data-testid="analyst-note-input"
                            value={analystNote}
                            onChange={(event) => setAnalystNote(event.target.value)}
                            rows={2}
                            maxLength={20000}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                        />
                    </label>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.case_context')}
                        </span>
                        <textarea
                            data-testid="case-context-input"
                            value={caseContext}
                            onChange={(event) => setCaseContext(event.target.value)}
                            rows={2}
                            maxLength={20000}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                        />
                    </label>

                    <div>
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.related_evidence')}
                        </span>
                        {relatedOptions.length === 0 ? (
                            <p className="mt-0.5 text-[10px] text-slate-400">
                                {t('investigation_workbench.no_related_evidence')}
                            </p>
                        ) : (
                            <div className="mt-0.5 max-h-28 overflow-y-auto rounded-lg border border-slate-200/60 dark:border-slate-700/50 divide-y divide-slate-200/40 dark:divide-slate-700/30" data-testid="related-evidence-options">
                                {relatedOptions.map((key) => (
                                    <label
                                        key={key}
                                        className="flex items-start gap-2 px-2 py-1 cursor-pointer hover:bg-slate-100/60 dark:hover:bg-slate-700/30"
                                    >
                                        <input
                                            type="checkbox"
                                            checked={related.has(key)}
                                            onChange={() => toggleRelated(key)}
                                            data-testid={`related-option-${key}`}
                                            className="mt-0.5 shrink-0"
                                        />
                                        <span className="text-[10px] font-mono break-all text-slate-600 dark:text-slate-300">
                                            {key}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    {submitError && (
                        <p className="text-[10px] text-rose-600 dark:text-rose-400" data-testid="submit-analysis-error">
                            {t('investigation_workbench.submit_failed')}
                            {submitError?.status ? ` (HTTP ${submitError.status})` : ''}
                        </p>
                    )}

                    <button
                        type="button"
                        data-testid="submit-analysis-button"
                        onClick={handleSubmit}
                        disabled={disabled}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={11} className="animate-spin" />}
                        {t('investigation_workbench.submit_analysis')}
                    </button>
                </div>
            )}
        </div>
    );
};

export default SubmitAnalysisForm;
