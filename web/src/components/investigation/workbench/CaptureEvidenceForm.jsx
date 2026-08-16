// CaptureEvidenceForm.jsx
// Evidence Workspace 的显式 "Capture Evidence" 动作（C10 §20：Phase C 用户链
// 的第一步——POST /snapshots 此前没有 UI consumer，新任务上 Workbench 无法
// 起链）。
//
// 边界：
//   - 候选 key 只来自任务真实文件列表（页面从服务端 files API 取得），
//     不提供自由文本输入 evidence_key；resolve + capture_if_absent 的
//     完整校验都在后端（key 不属于本任务 source 时 404）；
//   - 已捕获的 key 从候选中排除（capture_if_absent 幂等，但 UI 不重复
//     展示已存在项）；
//   - 捕获成功后只刷新 Evidence 列表 + Graph，不改变任何 selection。
import { useEffect, useRef, useState } from 'react';
import { Camera, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import { useTranslation } from '../../../hooks/useTranslation';

const CaptureEvidenceForm = ({ capturedKeys = [], fileOptions = [], onCapture }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [selected, setSelected] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const submittingRef = useRef(false);

    useEffect(() => {
        setSelected(null);
        setSubmitError(null);
    }, [fileOptions]);

    const candidates = fileOptions.filter((key) => !capturedKeys.includes(key));

    const handleSubmit = async () => {
        if (submittingRef.current || !selected) return;
        submittingRef.current = true;
        setSubmitting(true);
        setSubmitError(null);
        try {
            await onCapture(selected);
            setSelected(null);
            setOpen(false);
        } catch (error) {
            setSubmitError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    return (
        <div className="px-3 py-2 border-b border-white/10 dark:border-slate-700/40" data-testid="capture-evidence-form">
            <button
                type="button"
                data-testid="capture-evidence-toggle"
                onClick={() => setOpen((previous) => !previous)}
                className="w-full flex items-center justify-between gap-2 text-[11px] font-semibold text-slate-600 dark:text-slate-300"
            >
                <span className="flex items-center gap-1.5">
                    <Camera size={11} />
                    {t('investigation_workbench.capture_evidence')}
                </span>
                {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            {open && (
                <div className="mt-2 space-y-2">
                    <p className="text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">
                        {t('investigation_workbench.capture_evidence_hint')}
                    </p>
                    {candidates.length === 0 ? (
                        <p className="text-[10px] text-slate-400" data-testid="no-capture-candidates">
                            {t('investigation_workbench.no_capture_candidates')}
                        </p>
                    ) : (
                        <div className="max-h-36 overflow-y-auto rounded-lg border border-slate-200/60 dark:border-slate-700/50 divide-y divide-slate-200/40 dark:divide-slate-700/30" data-testid="capture-evidence-options">
                            {candidates.map((key) => (
                                <label
                                    key={key}
                                    className="flex items-start gap-2 px-2 py-1 cursor-pointer hover:bg-slate-100/60 dark:hover:bg-slate-700/30"
                                >
                                    <input
                                        type="radio"
                                        name="capture-evidence-key"
                                        checked={selected === key}
                                        onChange={() => setSelected(key)}
                                        data-testid={`capture-option-${key}`}
                                        className="mt-0.5 shrink-0"
                                    />
                                    <span className="text-[10px] font-mono break-all text-slate-600 dark:text-slate-300">
                                        {key}
                                    </span>
                                </label>
                            ))}
                        </div>
                    )}
                    {submitError && (
                        <p className="text-[10px] text-rose-600 dark:text-rose-400" data-testid="capture-evidence-error">
                            {t('investigation_workbench.capture_failed')}
                            {submitError?.status ? ` (HTTP ${submitError.status})` : ''}
                        </p>
                    )}
                    <button
                        type="button"
                        data-testid="capture-evidence-button"
                        onClick={handleSubmit}
                        disabled={submitting || !selected}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={11} className="animate-spin" />}
                        {t('investigation_workbench.capture')}
                    </button>
                </div>
            )}
        </div>
    );
};

export default CaptureEvidenceForm;
