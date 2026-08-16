// LinkEvidenceForm.jsx
// Event 视图下的显式 "Add Evidence" 动作（C9c §3/§4/§5）。
//
// 边界：
//   - 候选只能来自当前 task 已捕获的 canonical Evidence（页面传入），
//     自动排除已链接 key——正常 UI 不主动制造 409；保留 409 处理，
//     因为存在并发窗口；
//   - 不提供自由文本输入 evidence key；resolve + capture_if_absent +
//     composite FK 的完整性边界完全由后端 transaction 保证；
//   - append-only：不提供 unlink/delete（C7a 冻结审计模型）；
//   - submittingRef 保证 rapid double-click 只产生一次 POST。
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, LinkIcon } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';

const LinkEvidenceForm = ({ eventId, linkedKeys = [], evidenceOptions = [], onLinkEvidence }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [selected, setSelected] = useState(null);
    const [linkedBy, setLinkedBy] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const submittingRef = useRef(false);

    // 切换 Event 时复位表单（旧 event 的选择不得带过去）。
    useEffect(() => {
        setOpen(false);
        setSelected(null);
        setLinkedBy('');
        setSubmitError(null);
    }, [eventId]);

    // 候选 = 本任务全部已捕获 Evidence，排除已链接 key（§4）。
    const candidates = evidenceOptions.filter((key) => !linkedKeys.includes(key));

    const handleSubmit = async () => {
        if (submittingRef.current || !selected) return;
        submittingRef.current = true;
        setSubmitting(true);
        setSubmitError(null);
        try {
            await onLinkEvidence(eventId, selected, { linked_by: linkedBy.trim() });
            setOpen(false);
            setSelected(null);
            setLinkedBy('');
        } catch (error) {
            // 409 = 并发窗口下的重复 link；其余按普通提交失败展示。
            setSubmitError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    return (
        <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2" data-testid="link-evidence-form">
            <button
                type="button"
                data-testid="add-evidence-toggle"
                onClick={() => setOpen((previous) => !previous)}
                disabled={submitting}
                className="w-full flex items-center justify-between gap-2 text-[11px] font-semibold text-slate-600 dark:text-slate-300 disabled:opacity-50"
            >
                <span className="flex items-center gap-1.5">
                    <LinkIcon size={11} />
                    {t('investigation_workbench.add_evidence')}
                </span>
                {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            {open && (
                <div className="mt-2 space-y-2">
                    <p className="text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">
                        {t('investigation_workbench.link_evidence_hint')}
                    </p>

                    {candidates.length === 0 ? (
                        <p className="text-[10px] text-slate-400" data-testid="no-link-candidates">
                            {t('investigation_workbench.no_link_candidates')}
                        </p>
                    ) : (
                        <div className="max-h-28 overflow-y-auto rounded-lg border border-slate-200/60 dark:border-slate-700/50 divide-y divide-slate-200/40 dark:divide-slate-700/30" data-testid="link-evidence-options">
                            {candidates.map((key) => (
                                <label
                                    key={key}
                                    className="flex items-start gap-2 px-2 py-1 cursor-pointer hover:bg-slate-100/60 dark:hover:bg-slate-700/30"
                                >
                                    <input
                                        type="radio"
                                        name={`link-evidence-${eventId}`}
                                        checked={selected === key}
                                        onChange={() => setSelected(key)}
                                        data-testid={`link-option-${key}`}
                                        className="mt-0.5 shrink-0"
                                    />
                                    <span className="text-[10px] font-mono break-all text-slate-600 dark:text-slate-300">
                                        {key}
                                    </span>
                                </label>
                            ))}
                        </div>
                    )}

                    <label className="block">
                        <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.linked_by')}
                        </span>
                        <input
                            data-testid="linked-by-input"
                            value={linkedBy}
                            onChange={(event) => setLinkedBy(event.target.value)}
                            maxLength={256}
                            className="mt-0.5 w-full rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-400"
                        />
                    </label>

                    {submitError && (
                        <p className="text-[10px] text-rose-600 dark:text-rose-400" data-testid="link-evidence-error">
                            {submitError?.status === 409
                                ? t('investigation_workbench.link_conflict')
                                : t('investigation_workbench.link_failed') + (submitError?.status ? ` (HTTP ${submitError.status})` : '')}
                        </p>
                    )}

                    <button
                        type="button"
                        data-testid="link-evidence-button"
                        onClick={handleSubmit}
                        disabled={submitting || !selected || !linkedBy.trim()}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={11} className="animate-spin" />}
                        {t('investigation_workbench.link_evidence')}
                    </button>
                </div>
            )}
        </div>
    );
};

export default LinkEvidenceForm;
