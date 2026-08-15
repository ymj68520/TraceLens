import { FileText, FolderClock, Star } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import { ANALYSIS_STATUS, REPORT_LABELS, ROLE_LABELS, formatTimestamp } from '../utils/investigationConstants';

export default function EvidenceCard({ evidence, selected, onClick }) {
  const analysis = ANALYSIS_STATUS[evidence.analysis_status];
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-xl border p-3 text-left transition-all ${selected
        ? 'border-primary-500 bg-primary-50/70 dark:bg-primary-950/30'
        : 'border-slate-200/70 dark:border-slate-700/60 bg-white/50 dark:bg-slate-900/30 hover:border-primary-300'}`}
      data-testid={`evidence-${evidence.evidence_key}`}
    >
      <div className="flex items-start gap-2">
        <div className="mt-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 p-1.5">{evidence.evidence_type === 'event_cluster' ? <FolderClock size={16} /> : <FileText size={16} />}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {evidence.report_usage && <Star size={14} className="fill-amber-400 text-amber-500" />}
            <span className="font-medium text-sm text-slate-900 dark:text-slate-100 truncate">{evidence.title}</span>
          </div>
          <div className="mt-1 text-[11px] text-slate-500">{evidence.evidence_type === 'event_cluster' ? 'Event Cluster' : 'File'} · {formatTimestamp(evidence.timestamp)}</div>
          <div className="mt-2 flex flex-wrap gap-1">
            <Badge size="sm" variant={evidence.role === 'contradicting' ? 'red' : 'blue'}>{ROLE_LABELS[evidence.role] || evidence.role}</Badge>
            {analysis && <Badge size="sm" variant={analysis.variant}>{analysis.label}</Badge>}
            {evidence.report_usage && <Badge size="sm" variant="yellow">{REPORT_LABELS[evidence.report_usage]}</Badge>}
          </div>
          {evidence.initial_summary && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400 line-clamp-2">{evidence.initial_summary}</p>}
        </div>
      </div>
    </button>
  );
}
