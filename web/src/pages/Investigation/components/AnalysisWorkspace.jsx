import { useCallback, useState } from 'react';
import EvidenceAnalysisPanel from './EvidenceAnalysisPanel';
import EventAnalysisPanel from './EventAnalysisPanel';
import AgentReviewPanel from './AgentReviewPanel';
import AgentExecutionControl from './AgentExecutionControl';

/**
 * 右栏工作台路由：
 * - 默认（rightPane='file' 且选中文件）→ 文件上下文的证据分析工作台
 *   （身份 + 判定 + 元数据 + 分析评审 + 笔记 + Claims + 图谱 + 历史 + 佐证事件），
 *   与左栏"关联证据"入口共用同一个 EvidenceAnalysisPanel；
 * - 用户显式点选事件（佐证事件/关联事件/claim 追溯/深链）→ 事件面板；
 * - 事件面板内点选证据 → 证据分析面板（证据维度，无文件上下文头）；
 * - 底部集成 Agent 调查执行控制与 Analyst Review 面板，保持工作台三栏布局不变。
 */
export default function AnalysisWorkspace({
  taskId,
  investigationId = null,
  file,
  events,
  event,
  eventId,
  evidenceKey,
  rightPane = 'file',
  onRefreshEvents,
  onEvidenceChanged,
  onTraceClaim,
  onTraceEvidence,
  onSelectEvent,
  onBackToFile,
  readOnly = false,
}) {
  const [reviewRefreshSignal, setReviewRefreshSignal] = useState(0);

  const handleCycleCompleted = useCallback(() => {
    setReviewRefreshSignal((s) => s + 1);
  }, []);

  const renderPrimaryPanel = () => {
    if (evidenceKey) {
      return (
        <EvidenceAnalysisPanel
          key={`${taskId}:${evidenceKey}`}
          taskId={taskId}
          eventId={eventId}
          evidenceKey={evidenceKey}
          onEvidenceChanged={onEvidenceChanged}
          readOnly={readOnly}
        />
      );
    }
    if (rightPane === 'event' && event) {
      return (
        <EventAnalysisPanel
          taskId={taskId}
          event={event}
          onRefresh={onRefreshEvents}
          onTraceClaim={onTraceClaim}
          onTraceEvidence={onTraceEvidence}
          onBackToFile={onBackToFile}
        />
      );
    }
    if (file) {
      return (
        <EvidenceAnalysisPanel
          key={`${taskId}:file:${file.path}`}
          taskId={taskId}
          evidenceKey={`file:${file.path}`}
          onEvidenceChanged={onEvidenceChanged}
          fileContext={{ file, events, onSelectEvent }}
          readOnly={readOnly}
        />
      );
    }
    return (
      <div className="p-8 text-center text-sm text-slate-500">
        在中间时间线选择一个文件节点进行证据判定与分析。
      </div>
    );
  };

  const resolvedEvidenceKey = evidenceKey || (file ? `file:${file.path}` : null);

  return (
    <div className="h-full flex flex-col min-h-0" data-testid="analysis-workspace-container">
      <div className="flex-1 min-h-0 overflow-y-auto">
        {renderPrimaryPanel()}
      </div>
      <div className="shrink-0 max-h-[50%] flex flex-col min-h-0">
        <AgentExecutionControl
          taskId={taskId}
          investigationId={investigationId}
          onCycleCompleted={handleCycleCompleted}
        />
        <AgentReviewPanel
          taskId={taskId}
          investigationId={investigationId}
          evidenceKey={resolvedEvidenceKey}
          eventId={eventId}
          onTraceEvidence={onTraceEvidence}
          refreshSignal={reviewRefreshSignal}
        />
      </div>
    </div>
  );
}
