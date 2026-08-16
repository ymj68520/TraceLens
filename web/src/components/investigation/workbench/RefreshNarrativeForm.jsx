// RefreshNarrativeForm.jsx
// Event 视图下的显式 "Refresh Event Narrative" admission（C9c §8-§10/§17/§18）。
//
// 边界：
//   - 请求体只有后端 CreateEventRefreshRequest 支持的 task_id /
//     requested_by——frozen envelope 完全由服务器 admission transaction
//     构造，前端不发送 title/summary/needs_refresh/evidence/prompt；
//   - needs_refresh=0（clean）时同样允许显式 refresh（C7c R8），只换
//     提示文案，不改权限；
//   - POST 是 admission：立即返回 queued refresh row，不等待 LLM；
//   - busy（本页发起的 refresh 仍在 queued/running）期间禁用，防止
//     与后端 409 already-in-progress 撞车；terminal 后按钮恢复，
//     analyst 可显式 Refresh Again（新 refresh_id）。
import { useEffect, useRef, useState } from 'react';
import { Loader2, RotateCw } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';

const RefreshNarrativeForm = ({ eventId, needsRefresh = false, busy = false, onStartRefresh }) => {
    const { t } = useTranslation();
    const [requestedBy, setRequestedBy] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const submittingRef = useRef(false);

    // 切换 Event 时复位（旧 event 的署名不得带过去）。
    useEffect(() => {
        setRequestedBy('');
        setSubmitError(null);
    }, [eventId]);

    const handleSubmit = async () => {
        if (submittingRef.current) return;
        submittingRef.current = true;
        setSubmitting(true);
        setSubmitError(null);
        try {
            await onStartRefresh(eventId, { requested_by: requestedBy.trim() });
        } catch (error) {
            // admission 失败（422/404/409/503…）与 refresh row 后来
            // status=failed 是两类错误，这里只展示前者。
            setSubmitError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    const disabled = submitting || busy || !requestedBy.trim();

    return (
        <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2" data-testid="refresh-narrative-form">
            <p className="text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">
                {needsRefresh
                    ? t('investigation_workbench.refresh_hint_dirty')
                    : t('investigation_workbench.refresh_hint_clean')}
            </p>

            <label className="block mt-1.5">
                <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                    {t('investigation_workbench.requested_by')}
                </span>
                <input
                    data-testid="requested-by-input"
                    value={requestedBy}
                    onChange={(event) => setRequestedBy(event.target.value)}
                    maxLength={256}
                    className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                />
            </label>

            {busy && (
                <p className="mt-1 text-[10px] text-amber-600 dark:text-amber-400" data-testid="refresh-in-progress">
                    {t('investigation_workbench.refresh_in_progress')}
                </p>
            )}

            {submitError && (
                <p className="mt-1 text-[10px] text-rose-600 dark:text-rose-400" data-testid="refresh-admission-error">
                    {t('investigation_workbench.refresh_admission_failed')}
                    {submitError?.status ? ` (HTTP ${submitError.status})` : ''}
                </p>
            )}

            <button
                type="button"
                data-testid="refresh-narrative-button"
                onClick={handleSubmit}
                disabled={disabled}
                className="mt-1.5 inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
            >
                {busy
                    ? <Loader2 size={11} className="animate-spin" />
                    : <RotateCw size={11} />}
                {t('investigation_workbench.refresh_narrative')}
            </button>
        </div>
    );
};

export default RefreshNarrativeForm;
