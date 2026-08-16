// GenerateReportPanel.jsx
// R2d Generate 入口（唯一 generation UI，位于 Report 页面）。
// 请求体只允许 {task_id, requested_by}——evidence 集合、analysis 绑定、
// prompt 版本、模型、envelope 全部由服务端冻结；这里展示的 source
// summary 只是只读投影（R1 GET /api/reports/evidence），不参与提交。
import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { useReportGenerationPolling } from '../../hooks/useReportGenerationPolling';
import { listReportEvidence } from '../../services/investigationService';
import { generateReport, getReportGeneration } from '../../services/reportGenerationService';

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
    onAdmitted,
    onComplete,
    pollIntervalMs = 2000,
    evidenceLoader = listReportEvidence,
    generate = generateReport,
    fetchGeneration = getReportGeneration,
}) => {
    const [summary, setSummary] = useState(null);
    const [summaryError, setSummaryError] = useState(null);
    const [actor, setActor] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [admissionError, setAdmissionError] = useState(null);
    const [submission, setSubmission] = useState(null);
    const submittingRef = useRef(false);
    const completedNotifiedRef = useRef(null);
    const taskIdRef = useRef(taskId);

    // task 切换：丢弃旧 task 的 source summary 与 generation 状态（§23）。
    useEffect(() => {
        taskIdRef.current = taskId;
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

    const polling = useReportGenerationPolling(submission ? {
        taskId: submission.taskId,
        generationId: submission.generationId,
    } : null, { intervalMs: pollIntervalMs, fetchGeneration });

    // completed 只对每个 generation 通知一次；父级决定是否打开 exact 版本。
    useEffect(() => {
        const generation = polling.generation;
        if (
            generation?.status === 'completed'
            && generation.report_id
            && completedNotifiedRef.current !== generation.generation_id
        ) {
            completedNotifiedRef.current = generation.generation_id;
            onComplete?.(generation);
        }
    }, [polling.generation, onComplete]);

    const submit = useCallback(async () => {
        // 同步 ref 防抖：rapid double-click 只产生一个 admission（§5）。
        if (submittingRef.current || !taskId || !actor.trim()) return;
        submittingRef.current = true;
        setSubmitting(true);
        setAdmissionError(null);
        try {
            const admitted = await generate(taskId, { requestedBy: actor.trim() });
            if (taskIdRef.current !== taskId) return;
            // admission 成功即记录（父级用它判定 completed 时是否允许
            // 自动打开 exact 产物版本）；HTTP admission 失败不算。
            onAdmitted?.();
            setSubmission({ taskId, generationId: admitted.generation_id });
        } catch (error) {
            if (taskIdRef.current === taskId) setAdmissionError(error);
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    }, [actor, generate, onAdmitted, taskId]);

    const generation = polling.generation;
    const durableFailed = generation?.status === 'failed';
    // completed / failed 都是终态：允许 analyst 显式再发起（新的
    // generation_id）；绝不自动 retry（§9）。
    const terminal = Boolean(generation) && !polling.active;

    return (
        <section
            aria-label="Generate report"
            data-testid="generate-report-panel"
            className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 space-y-3"
        >
            <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                <Sparkles size={14} />
                生成叙事报告（Narrative Report）
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
                将基于当前显式 Report Evidence 集合生成报告；Evidence 集合与
                Analysis 绑定在生成时冻结，之后的变更不影响本次生成。
            </p>

            {summaryError && (
                <p className="text-xs text-amber-600 dark:text-amber-400" data-testid="generate-source-error">
                    无法读取当前 Report Evidence 绑定（HTTP {summaryError?.status || '错误'}）。
                </p>
            )}
            {summary && (
                <div className="text-xs text-slate-600 dark:text-slate-300 space-y-1" data-testid="generate-source-summary">
                    <div className="flex flex-wrap gap-3">
                        <span data-testid="summary-main">Main Evidence: {summary.main}</span>
                        <span data-testid="summary-appendix">Appendix Evidence: {summary.appendix}</span>
                        <span data-testid="summary-original">Original-only: {summary.originalOnly}</span>
                        <span data-testid="summary-bound">Bound accepted analyses: {summary.bound}</span>
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
                        disabled={submitting || !actor.trim()}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary-500/90 text-white hover:bg-primary-500 disabled:opacity-50"
                    >
                        {submitting && <Loader2 size={12} className="animate-spin" />}
                        {durableFailed ? 'Generate Again' : (submission ? '生成新版本' : 'Generate Report')}
                    </button>
                )}
            </div>

            {admissionError && (
                <div role="alert" className="text-xs text-rose-600 dark:text-rose-400" data-testid="generate-admission-error">
                    生成请求失败（HTTP admission failure，HTTP {admissionError?.status || '错误'}）：
                    {admissionError?.data?.detail || admissionError?.message || '请稍后重试'}
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
