import { useEffect, useRef, useState } from 'react';
import { getInvestigationAnalysis } from '../services/investigationService';

const POLL_INTERVAL_MS = 2000;

// C4b-2 冻结状态机：只在 queued/running 继续轮询；review_pending 与四种
// terminal 状态都是停止条件。Analysis 自身的 status=failed 是业务终态，
// 不是 HTTP 请求失败——两类错误在该 hook 里分开暴露。
const POLLING_STATUSES = ['queued', 'running'];

/**
 * 按 exact analysis_id 轮询一个 Secondary Analysis 直到离开 queued/running。
 *
 * 身份绑定三元组 {taskId, evidenceKey, analysisId}（§4）：
 *   - task 切换 / evidence 切换 / 新 submission 都会换 identity，
 *     旧 identity 晚返回的响应（成功或失败）绝不写入当前状态；
 *   - submission 为 null 时完全不发请求。
 *
 * 轮询 GET 的瞬时错误（503/网络）不终止轮询，只更新 error 供 UI 展示；
 * 下一次成功响应会清掉它。
 */
export function useSecondaryAnalysisPolling(submission, {
    intervalMs = POLL_INTERVAL_MS,
    fetchAnalysis = getInvestigationAnalysis,
} = {}) {
    const [analysis, setAnalysis] = useState(null);
    const [error, setError] = useState(null);
    const identityRef = useRef(null);

    const identity = submission
        ? `${submission.taskId}|${submission.evidenceKey}|${submission.analysisId}`
        : null;

    // identity 变化（含切换到 null）：丢弃旧 submission 的一切状态。
    useEffect(() => {
        identityRef.current = identity;
        setAnalysis(null);
        setError(null);
    }, [identity]);

    const submissionRef = useRef(submission);
    submissionRef.current = submission;

    useEffect(() => {
        if (!identity) return undefined;
        let cancelled = false;
        let timer = null;

        const poll = async () => {
            const current = submissionRef.current;
            let scheduleNext = true;
            try {
                // submissionRef 的字段与 identity 一致（identity 是它的派生）。
                const next = await fetchAnalysis(current.taskId, current.analysisId);
                if (cancelled || identityRef.current !== identity) return;
                if (next) {
                    setAnalysis(next);
                    setError(null);
                }
                if (!next || !POLLING_STATUSES.includes(next.status)) {
                    // review_pending / accepted / rejected / invalid / failed：停止。
                    scheduleNext = false;
                }
            } catch (nextError) {
                if (cancelled || identityRef.current !== identity) return;
                setError(nextError);
            }
            if (scheduleNext && !cancelled && identityRef.current === identity) {
                timer = setTimeout(poll, intervalMs);
            }
        };

        poll();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, [identity, intervalMs, fetchAnalysis]);

    // active = 该 submission 仍在排队/执行（或尚未取到首个状态）。
    const active = identity !== null
        && (analysis === null || POLLING_STATUSES.includes(analysis?.status));
    return { analysis, error, active, identity };
}
