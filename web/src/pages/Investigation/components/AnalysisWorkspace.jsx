import EvidenceAnalysisPanel from './EvidenceAnalysisPanel';
import EventAnalysisPanel from './EventAnalysisPanel';
import FileWorkbenchPanel from './FileWorkbenchPanel';

/**
 * 右栏工作台路由：
 * - 默认（rightPane='file'）→ 文件工作台（判定 + 分析评审 + 佐证事件）；
 * - 用户显式点选事件（佐证事件/关联事件/claim 追溯/深链）→ 事件面板；
 * - 事件面板内点选证据 → 证据分析面板。
 */
export default function AnalysisWorkspace({
  taskId,
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
}) {
  if (evidenceKey) {
    return <EvidenceAnalysisPanel taskId={taskId} eventId={eventId} evidenceKey={evidenceKey} onEvidenceChanged={onEvidenceChanged} />;
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
  return (
    <FileWorkbenchPanel
      taskId={taskId}
      file={file}
      events={events}
      onSelectEvent={onSelectEvent}
      onEvidenceChanged={onEvidenceChanged}
    />
  );
}
