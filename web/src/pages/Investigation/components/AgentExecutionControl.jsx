import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  HelpCircle,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
} from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import { useToast } from '../../../components/common/useToast';
import { fetchFeatures } from '../../../services/featuresService';
import {
  executeAgentCycle,
  getAgentState,
} from '../../../services/investigationService';

const FALLBACK_TOAST = {
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
};

export default function AgentExecutionControl({
  taskId,
  investigationId = null,
  onCycleCompleted,
  className = '',
}) {
  // Safe toast access with fallback
  let rawToast;
  try {
    rawToast = useToast();
  } catch {
    rawToast = FALLBACK_TOAST;
  }
  const toastRef = useRef(rawToast);
  toastRef.current = rawToast;

  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [checkingFeature, setCheckingFeature] = useState(true);

  const [agentState, setAgentState] = useState(null);
  const [loadingState, setLoadingState] = useState(false);
  const [stateError, setStateError] = useState(null);

  const [isExecuting, setIsExecuting] = useState(false);
  const [executionError, setExecutionError] = useState(null);
  const [executionOutcome, setExecutionOutcome] = useState(null);

  // Stable request ID for idempotent dispatch and retry recovery
  const [requestId, setRequestId] = useState(() => `req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`);

  const currentTaskRef = useRef(taskId);
  currentTaskRef.current = taskId;

  // Check feature gate on mount / task change
  useEffect(() => {
    let active = true;
    setCheckingFeature(true);
    fetchFeatures()
      .then((flags) => {
        if (active) {
          setFeatureEnabled(!!flags?.agent_execution_enabled);
        }
      })
      .catch(() => {
        if (active) {
          setFeatureEnabled(false);
        }
      })
      .finally(() => {
        if (active) {
          setCheckingFeature(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  // Fetch current working state for task
  const fetchState = useCallback(async (targetTaskId, targetInvId) => {
    if (!targetTaskId) {
      setAgentState(null);
      return;
    }
    setLoadingState(true);
    setStateError(null);
    try {
      const state = await getAgentState(targetTaskId, targetInvId);
      if (currentTaskRef.current === targetTaskId) {
        setAgentState(state);
      }
    } catch (err) {
      if (currentTaskRef.current === targetTaskId) {
        setStateError(err?.data?.detail || err?.message || '读取 Agent 状态失败');
      }
    } finally {
      if (currentTaskRef.current === targetTaskId) {
        setLoadingState(false);
      }
    }
  }, []);

  // Sync state on taskId change
  useEffect(() => {
    setAgentState(null);
    setStateError(null);
    setExecutionError(null);
    setExecutionOutcome(null);
    setRequestId(`req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`);
    if (taskId) {
      fetchState(taskId, investigationId);
    }
  }, [taskId, investigationId, fetchState]);

  // Execute Agent cycle
  const handleStartCycle = async () => {
    if (!taskId || isExecuting || !featureEnabled) return;

    setIsExecuting(true);
    setExecutionError(null);
    const stableReqId = requestId || `req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    setRequestId(stableReqId);

    try {
      const payload = {
        task_id: taskId,
        ...(investigationId ? { investigation_id: investigationId } : {}),
        request_id: stableReqId,
        expected_working_state_revision: agentState?.working_state_revision ?? null,
        max_steps: 5,
      };

      const outcome = await executeAgentCycle(payload, taskId);

      if (currentTaskRef.current === taskId) {
        setExecutionOutcome(outcome);
        // Generate new request ID for next cycle after successful completion
        setRequestId(`req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`);

        // Refresh state
        await fetchState(taskId, investigationId);

        toastRef.current.success(
          `Agent 循环执行成功 (Rev ${outcome.starting_revision} → Rev ${outcome.ending_revision})`
        );

        if (typeof onCycleCompleted === 'function') {
          onCycleCompleted(outcome);
        }
      }
    } catch (err) {
      if (currentTaskRef.current === taskId) {
        const errorDetail = err?.data?.detail || err?.message || 'Agent 循环执行失败';
        setExecutionError(errorDetail);
        toastRef.current.error(errorDetail);
        // Note: Retain stableReqId so analyst can retry with same request_id
      }
    } finally {
      if (currentTaskRef.current === taskId) {
        setIsExecuting(false);
      }
    }
  };

  const statusVariant = useMemo(() => {
    if (isExecuting) return 'yellow';
    const s = agentState?.agent_execution_status;
    if (s === 'running') return 'yellow';
    if (s === 'completed') return 'green';
    if (s === 'failed') return 'red';
    return 'gray';
  }, [isExecuting, agentState]);

  return (
    <div
      data-testid="agent-execution-control-container"
      className={`border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 p-3 flex flex-col gap-2.5 ${className}`}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-primary-500" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-200">
            Agent 调查执行 (Agent v0)
          </span>
          <Badge
            data-testid="agent-execution-status-badge"
            variant={statusVariant}
            size="xs"
            className="flex items-center gap-1"
          >
            {isExecuting && <Spinner size="xs" />}
            {isExecuting ? 'executing' : (agentState?.agent_execution_status || 'idle')}
          </Badge>
          <span
            data-testid="agent-state-revision"
            className="text-[11px] font-mono text-slate-500 dark:text-slate-400 bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 rounded"
          >
            Rev {agentState?.working_state_revision ?? 0}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            data-testid="btn-refresh-agent-state"
            size="xs"
            variant="ghost"
            onClick={() => fetchState(taskId, investigationId)}
            disabled={loadingState || isExecuting}
            title="刷新 Agent 状态"
            className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingState ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* State Metrics Bar */}
      {agentState && (
        <div
          data-testid="agent-state-metrics"
          className="grid grid-cols-4 gap-1.5 text-center bg-white dark:bg-slate-800/70 p-1.5 rounded border border-slate-200 dark:border-slate-700/60 text-xs"
        >
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-400">问题</span>
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              {agentState.questions_count ?? 0}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-400">结论</span>
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              {agentState.findings_count ?? 0}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-400">假说</span>
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              {agentState.hypotheses_count ?? 0}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-400">委派</span>
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              {agentState.active_delegations_count ?? 0}
            </span>
          </div>
        </div>
      )}

      {/* Feature Disabled Notice */}
      {!checkingFeature && !featureEnabled && (
        <div
          data-testid="agent-execution-disabled-notice"
          className="flex items-center gap-2 p-2 rounded bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/50 text-amber-800 dark:text-amber-300 text-xs"
        >
          <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span>Agent 自动执行未开启（配置参数 agent_execution_enabled: false）</span>
        </div>
      )}

      {/* Execution Error Banner with Retry */}
      {executionError && (
        <div
          data-testid="agent-execution-error-banner"
          className="flex flex-col gap-1.5 p-2 rounded bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800/50 text-red-800 dark:text-red-300 text-xs"
        >
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-red-600 dark:text-red-400 mt-0.5" />
            <div className="flex-1 min-w-0">
              <span className="font-semibold">执行失败: </span>
              <span className="break-words">{executionError}</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] text-red-600/80 dark:text-red-400/80 pl-6">
            <span className="font-mono truncate">Request ID: {requestId}</span>
            <button
              onClick={handleStartCycle}
              disabled={isExecuting || !featureEnabled}
              className="underline font-semibold hover:text-red-900 dark:hover:text-red-200 ml-2 shrink-0"
            >
              重试 (Retry)
            </button>
          </div>
        </div>
      )}

      {/* Actions and Controls */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button
            data-testid="btn-start-agent-cycle"
            size="sm"
            variant="primary"
            onClick={handleStartCycle}
            disabled={!featureEnabled || isExecuting || !taskId}
            title={!featureEnabled ? 'Agent execution is disabled by configuration' : '启动一个有界的调查循环'}
            className="flex items-center gap-1.5"
          >
            {isExecuting ? (
              <>
                <Spinner size="xs" />
                <span>执行中...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>启动调查循环</span>
              </>
            )}
          </Button>

          {isExecuting && (
            <span className="text-xs text-slate-500 animate-pulse">
              正在运行 Supervisor 规划与 Specialist 执行...
            </span>
          )}
        </div>

        <div className="text-[10px] text-slate-400 font-mono truncate max-w-[160px]" title={`Current request_id: ${requestId}`}>
          req: {requestId.slice(0, 14)}...
        </div>
      </div>
    </div>
  );
}
