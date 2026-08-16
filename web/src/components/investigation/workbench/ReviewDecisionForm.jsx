// ReviewDecisionForm.jsx
// Analysis 视图（status == review_pending）的显式 Analyst Review 确认区（C9b §7/§8）。
//
//   - 决策三选一（accepted / rejected / invalid），全部 terminal；
//   - 请求体只有后端 ReviewAnalysisRequest 的 task_id / decision /
//     reviewer / reason——claims、grounding_status、description、summary、
//     status 一律不由前端提交；
//   - 持续提示决策不可更改；想改结论 = 提交新的 Secondary Analysis version。
import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';

const DECISIONS = ['accepted', 'rejected', 'invalid'];

const ReviewDecisionForm = ({ analysisId, onSubmitReview }) => {
    const { t } = useTranslation();
    const [decision, setDecision] = useState('accepted');
    const [reviewer, setReviewer] = useState('');
    const [reason, setReason] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [reviewError, setReviewError] = useState(null);
    const submittingRef = useRef(false);

    useEffect(() => {
        setDecision('accepted');
        setReviewer('');
        setReason('');
        setReviewError(null);
    }, [analysisId]);

    const handleSubmit = async () => {
        if (submittingRef.current || !reviewer.trim() || !decision) return;
        submittingRef.current = true;
        setSubmitting(true);
        setReviewError(null);
        try {
            await onSubmitReview(analysisId, decision, {
                reviewer: reviewer.trim(),
                reason: reason.trim() ? reason : null,
            });
            // 成功后表单由父级随 status 变化卸载；这里不复位输入。
        } catch (error) {
            setReviewError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    return (
        <div className="rounded-xl bg-amber-50/70 dark:bg-amber-900/20 px-3 py-2 ring-1 ring-amber-200/50 dark:ring-amber-800/30" data-testid="review-decision-form">
            <h3 className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                {t('investigation_workbench.analyst_review')}
            </h3>

            <div className="mt-1.5 space-y-1.5">
                <div>
                    <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                        {t('investigation_workbench.review_decision')}
                    </span>
                    <div className="mt-0.5 flex flex-wrap gap-2" role="radiogroup" data-testid="review-decision-options">
                        {DECISIONS.map((option) => (
                            <label
                                key={option}
                                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] cursor-pointer ring-1 transition-colors ${
                                    decision === option
                                        ? 'bg-amber-100/80 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 ring-amber-300/60 dark:ring-amber-700/50'
                                        : 'text-slate-500 dark:text-slate-400 ring-slate-200/60 dark:ring-slate-700/50'
                                }`}
                            >
                                <input
                                    type="radio"
                                    name={`review-decision-${analysisId}`}
                                    checked={decision === option}
                                    onChange={() => setDecision(option)}
                                    data-testid={`review-decision-${option}`}
                                    className="hidden"
                                />
                                {t(`investigation_workbench.review_decision_${option}`)}
                            </label>
                        ))}
                    </div>
                </div>

                <label className="block">
                    <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                        {t('investigation_workbench.reviewer')}
                    </span>
                    <input
                        type="text"
                        data-testid="reviewer-input"
                        value={reviewer}
                        onChange={(event) => setReviewer(event.target.value)}
                        maxLength={256}
                        className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                    />
                </label>

                <label className="block">
                    <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                        {t('investigation_workbench.review_reason')}
                    </span>
                    <textarea
                        data-testid="review-reason-input"
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        rows={2}
                        maxLength={4000}
                        className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                    />
                </label>

                <p className="text-[10px] text-amber-700 dark:text-amber-400">
                    {t('investigation_workbench.review_terminal_warning')}
                </p>

                {reviewError && (
                    <p className="text-[10px] text-rose-600 dark:text-rose-400" data-testid="review-error">
                        {t('investigation_workbench.review_failed')}
                        {reviewError?.status ? ` (HTTP ${reviewError.status})` : ''}
                    </p>
                )}

                <button
                    type="button"
                    data-testid="submit-review-button"
                    onClick={handleSubmit}
                    disabled={submitting || !reviewer.trim()}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-amber-500/90 text-white hover:bg-amber-500 disabled:opacity-50"
                >
                    {submitting && <Loader2 size={11} className="animate-spin" />}
                    {t('investigation_workbench.submit_review')}
                </button>
            </div>
        </div>
    );
};

export default ReviewDecisionForm;
