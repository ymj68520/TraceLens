// GenerateReportPanel.jsx
// R2d Generate 入口（唯一 generation UI，位于 Report 页面）。
// 请求体仅含任务、操作人、阶段及二次研判的基线/案情——evidence 集合、analysis 绑定、
// prompt 版本、模型、envelope 全部由服务端冻结；这里展示的 source
// summary 只是只读投影（R1 GET /api/reports/evidence），不参与提交。
import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { useReportGenerationPolling } from '../../hooks/useReportGenerationPolling';
import { listReportEvidence } from '../../services/investigationService';
import { generateReport, getReportGeneration, getNarrativeReport } from '../../services/reportGenerationService';
import { fetchTaskById } from '../../services/taskService';

const ERROR_HINTS = {
    citation_invalid: '模型输出引用了报告证据边界之外的来源，生成已整体作废。',
    structured_output_invalid: '模型未按严格结构化契约返回报告，生成已作废。',
    input_integrity_error: '冻结输入完整性校验失败，生成已作废。',
    llm_timeout: '模型请求超时，可重新发起生成。',
    llm_connection_error: '模型服务暂时不可达，可重新发起生成。',
    llm_http_error: '模型请求失败，可重新发起生成。',
    llm_unavailable: '模型服务未初始化，可重新发起生成。',
    llm_empty_response: '模型返回了空响应，可重新发起生成。',
    service_restart: '服务重启中断了本次生成，可重新发起生成。',
    service_shutdown: '服务关闭中断了本次生成，可重新发起生成。',
    publication_error: '报告发布失败，未产生可见版本，可重新发起生成。',
    execution_schedule_failed: '生成任务调度失败，可重新发起生成。',
    execution_error: '生成执行失败，可重新发起生成。',
    neutral_sources_unavailable: '没有可用的中立材料。请检查已提取原文件或派生记录；不会回退使用历史 AI 摘要。',
    no_validated_neutral_analysis: '本轮研判未通过来源校验，未生成报告。原材料和历史报告保持不变。',
};

// admission 阶段的 HTTP 错误（409/404 等）没有 error_code，按 detail 映射成
// 可操作的指引；未命中的 detail 原样透出。
const ADMISSION_HINTS = {
    'task has no report evidence': '当前任务没有可生成的报告证据：请先在调查工作台打开某个证据，将其标记为"正文证据"或"附件证据"（事件簇证据不参与报告），再回到本页生成。',
    invalid_baseline: '请选择本任务已完成的“材料自主研判报告”作为基线；历史案情报告不能冒充中立基线。',
    baseline_required: '请先选择一份材料自主研判报告。',
    case_context_required: '请填写本次用于对照的案情描述，最多8000字。',
};

const STATUS_TEXT = {
    admitted: '排队中',
    running: '生成中',
    completed: '已完成',
    failed: '失败',
};

function summarize(rows) {
    const selected = (rows || []).filter((row) => row.report_status !== 'excluded');
    return {
        main: selected.filter((row) => row.report_status === 'main').length,
        appendix: selected.filter((row) => row.report_status === 'appendix').length,
        originalOnly: selected.filter((row) => !row.bound_analysis).length,
        bound: selected.filter((row) => row.bound_analysis).length,
        newer: selected.filter((row) => row.newer_accepted_available),
        total: selected.length,
    };
}

const GenerateReportPanel = ({
    taskId,
    onSubmitStart,
    onAdmitted,
    onComplete,
    pollIntervalMs = 2000,
    evidenceLoader = listReportEvidence,
    generate = generateReport,
    fetchGeneration = getReportGeneration,
    selectedReportId = null,
    narrativeLoader = getNarrativeReport,
    taskLoader = fetchTaskById,
}) => {
    const [summary, setSummary] = useState(null);
    const [summaryError, setSummaryError] = useState(null);
    const [actor, setActor] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [admissionError, setAdmissionError] = useState(null);
    const [submission, setSubmission] = useState(null);
    const submittingRef = useRef(false);
    const admissionRequestRef = useRef(null);
    const completedNotifiedRef = useRef(null);
    const taskIdRef = useRef(taskId);
    const [analysisMode, setAnalysisMode] = useState('narrative');
    const [caseDescription, setCaseDescription] = useState('');
    const [baseline, setBaseline] = useState(null);
    const [baselineLoading, setBaselineLoading] = useState(false);
    const contextEdited = useRef(false);

    useEffect(() => {
        let active = true;
        setAnalysisMode('narrative'); setCaseDescription(''); setBaseline(null);
        contextEdited.current = false;
        taskLoader(taskId).then(task => {
            if (active && !contextEdited.current) setCaseDescription(String(task?.case_description || ''));
        }).catch(() => {});
        return () => { active = false; };
    }, [taskId, taskLoader]);

    useEffect(() => {
        let active = true;
        setBaseline(null);
        setBaselineLoading(Boolean(selectedReportId));
        if (!selectedReportId) return () => { active = false; };
        narrativeLoader(taskId, selectedReportId).then(report => {
            if (!active) return;
            const stage = report.stage_analysis;
            if (stage) setBaseline({
                reportId: stage.analysis_mode === 'evidence_only' ? selectedReportId : stage.baseline_report_id,
                count: stage.materials?.length || 0,
            });
        }).catch(() => {}).finally(() => { if (active) setBaselineLoading(false); });
        return () => { active = false; };
    }, [taskId, selectedReportId, narrativeLoader]);

    // task 切换：丢弃旧 task 的 source summary 与 generation 状态（§23）。
    useEffect(() => {
        taskIdRef.current = taskId;
        admissionRequestRef.current = null;
        submittingRef.current = false;
        setSubmitting(false);
        setSummary(null);
        setSummaryError(null);
        setSubmission(null);
        setAdmissionError(null);
        let cancelled = false;
        evidenceLoader(taskId)
            .then((rows) => {
                if (!cancelled && taskIdRef.current === taskId) setSummary(summarize(rows));
            })
            .catch((error) => {
                if (!cancelled && taskIdRef.current === taskId) setSummaryError(error);
            });
        return () => { cancelled = true; };
    }, [taskId, evidenceLoader]);

    const polling = useReportGenerationPolling(submission?.taskId === taskId ? {
        taskId: submission.taskId,
        generationId: submission.generationId,
    } : null, { intervalMs: pollIntervalMs, fetchGeneration });

    // completed 只对每个 generation 通知一次；父级决定是否打开 exact 版本。
    useEffect(() => {
        const generation = polling.generation;
        if (
            submission?.taskId === taskId
            &&
            generation?.status === 'completed'
            && generation.report_id
            && completedNotifiedRef.current !== generation.generation_id
        ) {
            completedNotifiedRef.current = generation.generation_id;
            onComplete?.(generation);
        }
    }, [polling.generation, onComplete, submission, taskId]);

    const submit = useCallback(async () => {
        // 同步 ref 防抖：rapid double-click 只产生一个 admission（§5）。
        if (submittingRef.current || !taskId || !actor.trim()
            || (analysisMode === 'case_guided' && (!baseline?.reportId || !caseDescription.trim() || caseDescription.length > 8000))) return;
        submittingRef.current = true;
        const request = {};
        admissionRequestRef.current = request;
        // Capture navigation intent at the click, before an admission response
        // can arrive after the analyst has selected a different report.
        const submissionContext = onSubmitStart?.();
        setSubmitting(true);
        setAdmissionError(null);
        try {
            const admitted = await generate(taskId, {
                requestedBy: actor.trim(), analysisMode,
                ...(analysisMode === 'case_guided' ? {
                    baseReportId: baseline.reportId, caseDescription,
                } : {}),
            });
            if (admissionRequestRef.current !== request || taskIdRef.current !== taskId) return;
            // admission 成功即记录（父级用它判定 completed 时是否允许
            // 自动打开 exact 产物版本）；HTTP admission 失败不算。
            onAdmitted?.(submissionContext);
            setSubmission({ taskId, generationId: admitted.generation_id });
        } catch (error) {
            if (admissionRequestRef.current === request && taskIdRef.current === taskId) setAdmissionError(error);
        } finally {
            if (admissionRequestRef.current === request) {
                admissionRequestRef.current = null;
                submittingRef.current = false;
                setSubmitting(false);
            }
        }
    }, [actor, generate, onSubmitStart, onAdmitted, taskId, analysisMode, baseline, caseDescription]);

    const generation = polling.generation;
    const durableFailed = generation?.status === 'failed';
    // completed / failed 都是终态：允许 analyst 显式再发起（新的
    // generation_id）；绝不自动 retry（§9）。
    const terminal = Boolean(generation) && !polling.active;
    const busy = submitting || (Boolean(submission) && !terminal);
    const admissionDetail = admissionError?.data?.detail;
    const admissionText = typeof admissionDetail === 'object' && admissionDetail !== null
        ? (ADMISSION_HINTS[admissionDetail.code] || admissionDetail.message || '请检查分析阶段与案情输入。')
        : (ADMISSION_HINTS[admissionDetail] || admissionDetail || admissionError?.message || '请稍后重试');

    return (
        <section
            aria-label="生成报告"
            data-testid="generate-report-panel"
            className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 space-y-3"
        >
            <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                <Sparkles size={14} />
                报告生成与两阶段研判
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
                综合取证报告基于冻结入报材料生成，含逐份证据分类。
                首次研判在当前入报材料范围内独立阅读，不使用案情或历史 AI 摘要；
                二次研判复用首次报告的冻结材料，仅加入本次案情。三类报告分别保存版本，互不覆盖。
            </p>
            <div className="flex flex-wrap gap-4 text-sm text-slate-700 dark:text-slate-200" role="group" aria-label="报告分析阶段">
                <label><input type="radio" name={`analysis-mode-${taskId}`} value="narrative" checked={analysisMode === 'narrative'} disabled={busy}
                    onChange={() => setAnalysisMode('narrative')} /> 综合取证报告</label>
                <label><input type="radio" name={`analysis-mode-${taskId}`} value="evidence_only" checked={analysisMode === 'evidence_only'} disabled={busy}
                    onChange={() => setAnalysisMode('evidence_only')} /> 首次：材料自主研判</label>
                <label><input type="radio" name={`analysis-mode-${taskId}`} value="case_guided" checked={analysisMode === 'case_guided'} disabled={busy}
                    onChange={() => setAnalysisMode('case_guided')} /> 二次：案情对照研判</label>
            </div>
            {analysisMode === 'case_guided' && <div className="space-y-3 rounded-xl border border-blue-200 p-3 dark:border-blue-800">
                <p className="text-xs text-slate-600 dark:text-slate-300">{baselineLoading ? '正在核对基线报告…' : baseline?.reportId
                    ? `基于首次报告 ${baseline.reportId} · 沿用 ${baseline.count} 份冻结材料`
                    : '请在下方版本历史中选择一份材料自主研判报告。历史案情报告不能作为中立基线。'}</p>
                <label className="block text-xs text-slate-600 dark:text-slate-300">本次案情描述（调查语境，不作为已证实事实）
                    <textarea aria-label="本次案情描述" value={caseDescription} maxLength={8000} disabled={busy}
                        onChange={event => { contextEdited.current = true; setCaseDescription(event.target.value); }}
                        className="mt-2 min-h-32 w-full rounded-lg border border-slate-300 bg-white p-3 text-sm dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100" />
                </label>
                <p className="text-xs text-slate-500">{caseDescription.length}/8000 字 · 仅冻结到本次研判，不覆盖任务案情或首次报告。</p>
                {caseDescription.length > 8000 && <p role="alert" className="text-xs text-amber-700 dark:text-amber-300">已保存案情超过本轮8000字限制，请明确缩减后提交；不会自动截断。</p>}
            </div>}

            {summaryError && (
                <p className="text-xs text-amber-600 dark:text-amber-400" data-testid="generate-source-error">
                    无法读取当前 Report Evidence 绑定（HTTP {summaryError?.status || '错误'}）。
                </p>
            )}
            {summary && analysisMode !== 'case_guided' && (
                <div className="text-xs text-slate-600 dark:text-slate-300 space-y-1" data-testid="generate-source-summary">
                    <div className="flex flex-wrap gap-3">
                        <span data-testid="summary-main">主要证据： {summary.main}</span>
                        <span data-testid="summary-appendix">附录证据： {summary.appendix}</span>
                        <span data-testid="summary-original">仅原始材料： {summary.originalOnly}</span>
                        <span data-testid="summary-bound">已绑定的已接受分析： {summary.bound}</span>
                    </div>
                    {summary.newer.map((row) => (
                        <p
                            key={row.evidence_key}
                            className="text-amber-600 dark:text-amber-400"
                            data-testid="newer-accepted-hint"
                        >
                            存在更新的 accepted Analysis，但当前 Report Evidence 仍绑定历史版本（{row.evidence_key}）。
                        </p>
                    ))}
                    {summary.total === 0 && (
                        <p className="text-amber-600 dark:text-amber-400" data-testid="summary-empty">
                            当前任务没有加入报告的 Report Evidence，请先在调查工作台显式添加。
                        </p>
                    )}
                </div>
            )}

            <div className="flex flex-wrap items-end gap-2">
                <label className="block">
                    <span className="block text-[10px] font-medium text-slate-500 dark:text-slate-400">分析人（requested_by）</span>
                    <input
                        data-testid="generate-actor-input"
                        value={actor}
                        onChange={(event) => setActor(event.target.value)}
                        maxLength={256}
                        disabled={Boolean(submission) && !terminal}
                        className="mt-0.5 w-56 rounded-lg border border-slate-200/60 dark:border-slate-700/50 bg-white/70 dark:bg-slate-900/50 px-2 py-1 text-xs text-slate-700 dark:text-slate-200 disabled:opacity-50"
                    />
                </label>
                {(!submission || terminal) && (
                    <button
                        type="button"
                        data-testid="generate-submit"
                        onClick={() => { void submit(); }}
                        disabled={submitting || !actor.trim() || (analysisMode === 'case_guided' && (!baseline?.reportId || baselineLoading || !caseDescription.trim() || caseDescription.length > 8000))}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={12} className="animate-spin" />}
                        {durableFailed
                            ? (analysisMode === 'narrative' ? '重新发起生成' : '重新发起本阶段研判')
                            : analysisMode === 'narrative' ? '生成综合取证报告'
                                : analysisMode === 'evidence_only' ? '生成材料自主研判报告' : '生成案情对照研判报告'}
                    </button>
                )}
            </div>

            {admissionError && (
                <div role="alert" className="text-xs text-rose-600 dark:text-rose-400" data-testid="generate-admission-error">
                    生成请求失败（HTTP {admissionError?.status || '错误'}）：
                    {admissionText}
                </div>
            )}

            {generation && (
                <div className="text-xs space-y-1 border-t border-slate-100 dark:border-slate-700 pt-2" data-testid="generate-status">
                    <div className="flex flex-wrap items-center gap-2 text-slate-600 dark:text-slate-300">
                        <span data-testid="generate-status-text">
                            {STATUS_TEXT[generation.status] || generation.status}
                        </span>
                        <span className="font-mono text-[10px] text-slate-400" data-testid="generate-generation-id">
                            {generation.generation_id}
                        </span>
                        {polling.active && <Loader2 size={12} className="animate-spin text-slate-400" />}
                    </div>
                    {generation.status === 'completed' && (
                        <p className="text-emerald-600 dark:text-emerald-400" data-testid="generate-completed-identity">
                            已发布版本 {generation.report_id} · v{generation.produced_version}
                        </p>
                    )}
                    {durableFailed && (
                        <div className="text-rose-600 dark:text-rose-400" data-testid="generate-failed-detail">
                            <p className="font-mono">{generation.error_code}</p>
                            <p>{generation.error_message}</p>
                            <p className="text-slate-500 dark:text-slate-400">
                                {ERROR_HINTS[generation.error_code] || '生成失败；可重新发起（将创建新的 generation）。'}
                            </p>
                        </div>
                    )}
                </div>
            )}
            {!generation && polling.error && (
                <p className="text-xs text-amber-600 dark:text-amber-400" data-testid="generate-poll-error">
                    轮询状态暂时不可用（HTTP {polling.error?.status || '错误'}），自动重试中。
                </p>
            )}
        </section>
    );
};

export default GenerateReportPanel;
