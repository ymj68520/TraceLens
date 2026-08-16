import { useEffect, useRef, useState } from 'react';
import { listInvestigationEventRefreshes } from '../services/investigationService';

const POLL_INTERVAL_MS = 2000;

// C7c 冻结状态机：只在 queued/running 继续轮询；completed / failed 都是
// 停止条件。refresh row 自身 status=failed 是业务终态，不是 HTTP 请求
// 失败——两类错误在该 hook 里分开暴露。
const POLLING_STATUSES = ['queued', 'running'];

/**
 * 按 exact refresh_id 轮询一个 Event Refresh 直到离开 queued/running。
 *
 * 后端没有 exact GET /refreshes/{refresh_id}（C9c §0 已核实），但
 * GET /events/{event_id}/refreshes 返回完整 read model 且确定性排序，
 * 因此这里轮询 history 并按 exact refresh_id 过滤——绝不轮询 "latest"。
 *
 * 身份绑定三元组 {taskId, eventId, refreshId}（§12）：
 *   - task 切换 / event 切换 / 新 submission 都会换 identity，
 *     旧 identity 晚返回的响应（成功或失败）绝不写入当前状态；
 *   - submission 为 null 时完全不发请求。
 *
 * 轮询 GET 的瞬时错误（503/网络）不终止轮询，只更新 error 供 UI 展示；
 * 下一次成功响应会清掉它。history 中找不到 exact row 时同样按瞬时异常
 * 处理：不写状态、停止调度（admission 已提交该行，缺失属于服务端异常，
 * fail-closed 好过无限轮询）。
 */
export function useEventRefreshPolling(submission, {
    intervalMs = POLL_INTERVAL_MS,
    fetchRefreshes = listInvestigationEventRefreshes,
} = {}) {
    const [refresh, setRefresh] = useState(null);
    const [error, setError] = useState(null);
    const identityRef = useRef(null);

    const identity = submission
        ? `${submission.taskId}|${submission.eventId}|${submission.refreshId}`
        : null;

    // identity 变化（含切换到 null）：丢弃旧 submission 的一切状态。
    useEffect(() => {
        identityRef.current = identity;
        setRefresh(null);
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
                const rows = await fetchRefreshes(current.taskId, current.eventId);
                if (cancelled || identityRef.current !== identity) return;
                // exact refresh_id 过滤：绝不允许 latest 行冒充本次轮询对象。
                const next = Array.isArray(rows)
                    ? rows.find((row) => row?.refresh_id === current.refreshId)
                    : undefined;
                if (next) {
                    setRefresh(next);
                    setError(null);
                }
                if (!next || !POLLING_STATUSES.includes(next.status)) {
                    // completed / failed / 行缺失：停止。
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
    }, [identity, intervalMs, fetchRefreshes]);

    // active = 该 refresh 仍在排队/执行（或尚未取到首个状态）。
    const active = identity !== null
        && (refresh === null || POLLING_STATUSES.includes(refresh?.status));
    return { refresh, error, active, identity };
}
