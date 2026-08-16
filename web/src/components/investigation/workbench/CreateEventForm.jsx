// CreateEventForm.jsx
// Timeline 视图下的显式 "New Investigation Event" 动作（C9c §1/§2）。
//
// 边界：
//   - 只暴露后端 CreateInvestigationEventRequest 真实支持的字段
//     （title 必填 / summary 可选 / created_by 必填 analyst 标识）；
//   - Investigation Event 是调查员组织的高级语义事件，不是 Timeline
//     Cluster——不做任何 Cluster 自动转换，文案必须讲清这一点；
//   - 成功后由页面重新读取 Event list 并按 exact event_id 选中；
//     本组件从不插入临时 Event row；
//   - submittingRef 保证 rapid double-click 只产生一次 POST。
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, Plus } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';

const CreateEventForm = ({ onCreateEvent }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [title, setTitle] = useState('');
    const [summary, setSummary] = useState('');
    const [createdBy, setCreatedBy] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const submittingRef = useRef(false);

    useEffect(() => {
        setOpen(false);
        setTitle('');
        setSummary('');
        setCreatedBy('');
        setSubmitError(null);
    }, []);

    const handleSubmit = async () => {
        if (submittingRef.current) return;
        submittingRef.current = true;
        setSubmitting(true);
        setSubmitError(null);
        try {
            await onCreateEvent({
                title: title.trim(),
                summary: summary.trim() ? summary : null,
                created_by: createdBy.trim(),
            });
            setOpen(false);
            setTitle('');
            setSummary('');
            setCreatedBy('');
        } catch (error) {
            // POST 提交失败（422/404/503…）在这里展示，不与其他错误混同。
            setSubmitError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    return (
        <div className="px-2 py-1.5 border-b border-white/10 dark:border-slate-700/40" data-testid="create-event-form">
            <button
                type="button"
                data-testid="new-event-toggle"
                onClick={() => setOpen((previous) => !previous)}
                disabled={submitting}
                className="w-full flex items-center justify-between gap-2 px-2 py-1 text-[11px] font-semibold rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100/60 dark:hover:bg-slate-800/60 disabled:opacity-50"
            >
                <span className="flex items-center gap-1.5">
                    <Plus size={11} />
                    {t('investigation_workbench.new_event')}
                </span>
                {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            {open && (
                <div className="mt-1.5 px-1 space-y-2">
                    <p className="text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">
                        {t('investigation_workbench.event_form_disclaimer')}
                    </p>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.event_title_label')}
                        </span>
                        <input
                            data-testid="event-title-input"
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            maxLength={500}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                        />
                    </label>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.event_summary_label')}
                        </span>
                        <textarea
                            data-testid="event-summary-input"
                            value={summary}
                            onChange={(event) => setSummary(event.target.value)}
                            rows={2}
                            maxLength={20000}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                        />
                    </label>

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.created_by_label')}
                        </span>
                        <input
                            data-testid="event-created-by-input"
                            value={createdBy}
                            onChange={(event) => setCreatedBy(event.target.value)}
                            maxLength={256}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                        />
                    </label>

                    {submitError && (
                        <p className="text-[10px] text-rose-600 dark:text-rose-400" data-testid="create-event-error">
                            {t('investigation_workbench.create_event_failed')}
                            {submitError?.status ? ` (HTTP ${submitError.status})` : ''}
                        </p>
                    )}

                    <button
                        type="button"
                        data-testid="create-event-button"
                        onClick={handleSubmit}
                        disabled={submitting || !title.trim() || !createdBy.trim()}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={11} className="animate-spin" />}
                        {t('investigation_workbench.create_event')}
                    </button>
                </div>
            )}
        </div>
    );
};

export default CreateEventForm;
