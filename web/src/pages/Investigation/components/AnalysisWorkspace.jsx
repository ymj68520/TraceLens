import EvidenceAnalysisPanel from './EvidenceAnalysisPanel';
import EventAnalysisPanel from './EventAnalysisPanel';

export default function AnalysisWorkspace({ taskId, event, eventId, evidenceKey, onRefreshEvents, onEvidenceChanged, onTraceClaim, onTraceEvidence }) {
  return evidenceKey ? (
    <EvidenceAnalysisPanel taskId={taskId} eventId={eventId} evidenceKey={evidenceKey} onEvidenceChanged={onEvidenceChanged} />
  ) : (
    <EventAnalysisPanel taskId={taskId} event={event} onRefresh={onRefreshEvents} onTraceClaim={onTraceClaim} onTraceEvidence={onTraceEvidence} />
  );
}
