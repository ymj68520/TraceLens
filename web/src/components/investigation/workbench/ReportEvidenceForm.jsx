// ReportEvidenceForm.jsx
// Evidence detail 的显式 Report Evidence binding 面板（R1）。
// Report source 永远是当前 canonical evidence_key；analysis_id 只是可选的
// frozen accepted 版本。没有自动加入、latest fallback 或 review_pending binding。
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, FilePlus2, Loader2, RefreshCw } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';
import Badge from '../../common/Badge';

const ReportEvidenceForm = ({
    evidenceKey,
    analyses = [],
    reportEvidence = null,
    onAdd,
    onUpdate,
}) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [status, setStatus] = useState('main');
    const [analysisChoice, setAnalysisChoice] = useState('original');
    const [actor, setActor] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const submittingRef = useRef(false);

    const acceptedAnalyses = useMemo(
        () => analyses.filter((analysis) => analysis.status === 'accepted'),
        [analyses],
    );

    useEffect(() => {
        setOpen(false);
        setStatus(reportEvidence?.report_status || 'main');
        setAnalysisChoice(reportEvidence?.analysis_id || 'original');
        setActor('');
        setError(null);
    }, [evidenceKey, reportEvidence?.analysis_id, reportEvidence?.report_status]);

    const submit = async () => {
        if (submittingRef.current || !actor.trim()) return;
        submittingRef.current = true;
        setSubmitting(true);
        setError(null);
        try {
            if (reportEvidence) {
                const bindingChanged = analysisChoice !== (reportEvidence.analysis_id || 'original');
                await onUpdate({
                    evidenceKey,
                    reportStatus: status,
                    analysisId: bindingChanged && analysisChoice !== 'original'
                        ? analysisChoice
                        : undefined,
                    updatedBy: actor.trim(),
                });
            } else {
                await onAdd({
                    evidenceKey,
                    reportStatus: status,
                    analysisId: analysisChoice === 'original' ? null : analysisChoice,
                    addedBy: actor.trim(),
                });
            }
            setOpen(false);
            setActor('');
        } catch (submitError) {
            setError(submitError);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    const bound = reportEvidence?.bound_analysis;
    const canRebind = acceptedAnalyses.length > 0;

    return (
        <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2" data-testid="report-evidence-form">
            {reportEvidence ? (
                <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                            <RefreshCw size={11} />
                            {t('investigation_workbench.report_evidence')}
                        </span>
                        <Badge variant={reportEvidence.report_status === 'excluded' ? 'gray' : 'green'} size="sm">
                            {reportEvidence.report_status}
                        </Badge>
                    </div>
                    <div className="text-[10px] text-slate-500 dark:text-slate-400" data-testid="report-binding-summary">
                        <span>{t('investigation_workbench.bound_analysis')}: </span>
                        <span className="font-mono break-all">
                            {bound ? `v${bound.version} · ${bound.analysis_id}` : t('investigation_workbench.original_evidence')}
                        </span>
                    </div>
                    {bound?.decided_by && (
                        <div className="text-[10px] text-slate-400">
                            {t('investigation_workbench.accepted_by')}: {bound.decided_by}
                        </div>
                    )}
                    {reportEvidence.newer_accepted_available && (
                        <p className="text-[10px] text-amber-600 dark:text-amber-400" data-testid="newer-accepted-hint">
                            {t('investigation_workbench.newer_accepted_available')}
                        </p>
                    )}
                </div>
            ) : null}

            <button
                type="button"
                data-testid="report-evidence-toggle"
                onClick={() => setOpen((previous) => !previous)}
                disabled={submitting}
                className="mt-1.5 w-full flex items-center justify-between gap-2 text-[11px] font-semibold text-slate-600 dark:text-slate-300 disabled:opacity-50"
            >
                <span className="flex items-center gap-1.5">
                    <FilePlus2 size={11} />
                    {reportEvidence ? t('investigation_workbench.edit_report_evidence') : t('investigation_workbench.add_to_report')}
                </span>
                {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            {open && (
                <div className="mt-2 space-y-2">
                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.report_status')}
                        </span>
                        <select
                            data-testid="report-status-select"
                            value={status}
                            onChange={(event) => setStatus(event.target.value)}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200"
                        >
                            {reportEvidence && <option value="excluded">{t('investigation_workbench.report_status_excluded')}</option>}
                            <option value="main">{t('investigation_workbench.report_status_main')}</option>
                            <option value="appendix">{t('investigation_workbench.report_status_appendix')}</option>
                        </select>
                    </label>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.bind_analysis')}
                        </span>
                        <select
                            data-testid="report-analysis-select"
                            value={analysisChoice}
                            onChange={(event) => setAnalysisChoice(event.target.value)}
                            disabled={!canRebind && !reportEvidence?.analysis_id}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 disabled:opacity-50"
                        >
                            <option value="original" disabled={Boolean(reportEvidence?.analysis_id)}>
                                {t('investigation_workbench.original_evidence')}
                            </option>
                            {acceptedAnalyses.map((analysis) => (
                                <option key={analysis.analysis_id} value={analysis.analysis_id}>
                                    v{analysis.version} · {analysis.analysis_id}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.report_actor')}
                        </span>
                        <input
                            data-testid="report-actor-input"
                            value={actor}
                            onChange={(event) => setActor(event.target.value)}
                            maxLength={256}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200"
                        />
                    </label>

                    {error && (
                        <p className="text-[10px] text-rose-600 dark:text-rose-400" data-testid="report-evidence-error">
                            {t('investigation_workbench.report_evidence_failed')}
                            {error?.status ? ` (HTTP ${error.status})` : ''}
                        </p>
                    )}
                    <button
                        type="button"
                        data-testid="report-evidence-submit"
                        onClick={submit}
                        disabled={submitting || !actor.trim()}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={11} className="animate-spin" />}
                        {reportEvidence ? t('investigation_workbench.save_report_evidence') : t('investigation_workbench.add_to_report')}
                    </button>
                </div>
            )}
        </div>
    );
};

export default ReportEvidenceForm;
