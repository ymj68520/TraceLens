import { useEffect, useRef, useState } from 'react';
import { getReportGeneration } from '../services/reportGenerationService';

const POLL_INTERVAL_MS = 2000;

// R2c 冻结状态机：admitted 是排队态（R2b 命名），只有 admitted/running
// 继续轮询；completed / failed 都是停止条件。durable row 的
// status=failed 是业务终态，与轮询请求本身的瞬时 HTTP 错误分开暴露。
const POLLING_STATUSES = ['admitted', 'running'];

/**
 * 按 exact generation_id 轮询一个 Report Generation 直到离开
 * admitted/running。
 *
 * 身份绑定二元组 {taskId, generationId}（§6/§7）：
 *   - task 切换 / 新 admission 都会换 identity，旧 identity 晚返回的
 *     响应（成功或失败）绝不写入当前状态；
 *   - submission 为 null 时完全不发请求。
 *
 * 轮询 GET 的瞬时错误（503/网络）不终止轮询，只更新 error 供 UI 展示；
 * 下一次成功响应会清掉它。
 */
export function useReportGenerationPolling(submission, {
    intervalMs = POLL_INTERVAL_MS,
    fetchGeneration = getReportGeneration,
} = {}) {
    const [generation, setGeneration] = useState(null);
    const [error, setError] = useState(null);
    const identityRef = useRef(null);

    const identity = submission
        ? `${submission.taskId}|${submission.generationId}`
        : null;

    // identity 变化（含切换到 null）：丢弃旧 submission 的一切状态。
    useEffect(() => {
        identityRef.current = identity;
        setGeneration(null);
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
                const next = await fetchGeneration(current.taskId, current.generationId);
                if (cancelled || identityRef.current !== identity) return;
                if (next) {
                    setGeneration(next);
                    setError(null);
                }
                if (!next || !POLLING_STATUSES.includes(next.status)) {
                    // completed / failed：停止。
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
    }, [identity, intervalMs, fetchGeneration]);

    // active = 该 generation 仍在排队/执行（或尚未取到首个状态）。
    const active = identity !== null
        && (generation === null || POLLING_STATUSES.includes(generation?.status));
    return { generation, error, active, identity };
}
