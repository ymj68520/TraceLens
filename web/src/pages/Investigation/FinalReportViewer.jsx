import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileCheck2,
  Hash,
  Download,
  ExternalLink,
  Printer,
  RefreshCw,
  X,
} from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import Spinner from '../../components/common/Spinner';
import useFinalReportViewer from './hooks/useFinalReportViewer';
import useReportTraceback from './hooks/useReportTraceback';
import useFinalReportPublication from './hooks/useFinalReportPublication';
import useFinalReportPresentation from './hooks/useFinalReportPresentation';
import { checkFinalReportIntegrity } from './finalReportIntegrity';

function shortHash(value) {
  if (!value || value.length <= 18) return value || '—';
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function formatCreatedAt(value) {
  if (!value) return '—';
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function reportLabel(report) {
  return `Report v${report?.report_version ?? '—'}`;
}

function PublicationState({ publication, loading, ready, error, publishLoading, publishError, publishSuccess, onPublish }) {
  if (!ready || loading) return <span className="text-xs text-slate-500">Reading publication fact…</span>;
  if (error) return <span role="alert" className="text-xs text-rose-700 dark:text-rose-300">{error}</span>;
  if (publication) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-emerald-700 dark:text-emerald-300">
        <span>Published</span>
        <span>Published at {formatCreatedAt(publication.published_at)}</span>
        {publication.publication_id && <span className="font-mono">Publication {shortHash(publication.publication_id)}</span>}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
      <span>No publication fact for this report version.</span>
      <Button
        size="sm"
        variant="secondary"
        loading={publishLoading}
        disabled={publishLoading}
        onClick={onPublish}
      >
        Publish this report version
      </Button>
      {publishSuccess && <span className="text-emerald-700 dark:text-emerald-300">Publication recorded.</span>}
      {publishError && <span role="alert" className="text-rose-700 dark:text-rose-300">{publishError}</span>}
    </div>
  );
}

function ReportParagraph({ text, claimIds = [], citationIds = [], onClaim, onCitation }) {
  return (
    <article className="rounded-xl border border-slate-200/70 bg-white/60 p-4 dark:border-slate-700/60 dark:bg-slate-900/30">
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800 dark:text-slate-200">{text}</p>
      {(claimIds.length > 0 || citationIds.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-200/60 pt-3 dark:border-slate-700/50">
          {claimIds.map((claimId) => (
            <button key={claimId} type="button" onClick={() => onClaim?.(claimId)} className="focus:outline-none focus:ring-2 focus:ring-primary-500/60 rounded-lg">
              <Badge variant="blue" size="sm">Claim {claimId}</Badge>
            </button>
          ))}
          {citationIds.map((citationId) => (
            <button key={citationId} type="button" onClick={() => onCitation?.(citationId)} className="focus:outline-none focus:ring-2 focus:ring-purple-500/60 rounded-lg">
              <Badge variant="purple" size="sm">{citationId}</Badge>
            </button>
          ))}
        </div>
      )}
    </article>
  );
}

function ReportTracePanel({ taskId, report, trace, citation, claim, claimLoading, claimError, onClose }) {
  if (!trace) return null;

  const citations = Array.isArray(report?.citation_manifest) ? report.citation_manifest : [];
  const claimIdsForCitation = citations.length
    ? (Array.isArray(report?.claim_manifest) ? report.claim_manifest : [])
      .filter((entry) => entry?.citation_ids?.includes(trace.id))
      .map((entry) => entry.claim_id)
    : [];

  return (
    <aside className="rounded-2xl glass p-5" aria-label="Report trace-back">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-mono text-slate-400">Read-only provenance</div>
          <h2 className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{trace.type === 'citation' ? 'Report Citation' : 'Historical Claim'}</h2>
        </div>
        <button type="button" aria-label="Close trace-back" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={onClose}><X size={18} /></button>
      </div>
      {trace.type === 'citation' && (
        citation ? (
          <div className="mt-4 space-y-4 text-sm">
            <dl className="grid gap-3 sm:grid-cols-2">
              <div><dt className="text-xs text-slate-500">Citation ID</dt><dd className="mt-1 font-mono text-slate-800 dark:text-slate-200">{citation.citation_id}</dd></div>
              <div><dt className="text-xs text-slate-500">Evidence Identity</dt><dd className="mt-1 break-all font-mono text-slate-800 dark:text-slate-200">({taskId}, {citation.evidence_key})</dd></div>
              <div><dt className="text-xs text-slate-500">Evidence Type</dt><dd className="mt-1 text-slate-800 dark:text-slate-200">{citation.evidence_type || '—'}</dd></div>
              <div><dt className="text-xs text-slate-500">Report Status</dt><dd className="mt-1 text-slate-800 dark:text-slate-200">{citation.report_status || '—'}</dd></div>
            </dl>
            <div><div className="text-xs font-semibold text-slate-500">Used by Report Claims</div><div className="mt-2 flex flex-wrap gap-2">{claimIdsForCitation.length ? claimIdsForCitation.map((claimId) => <Badge key={claimId} variant="blue" size="sm">{claimId}</Badge>) : <span className="text-sm text-slate-500">No Claim manifest entry references this Citation.</span>}</div></div>
            <TraceValue label="Report-bound Evidence Snapshot" value={citation.snapshot} empty="No report-bound snapshot was persisted." />
            <TraceValue label="Pinned Analysis" value={citation.pinned_analysis} empty="No pinned accepted analysis was bound to this report evidence." />
          </div>
        ) : <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">Citation provenance unavailable.</p>
      )}
      {trace.type === 'claim' && (
        <div className="mt-4">
          {claimLoading && <div className="flex justify-center py-8"><Spinner /></div>}
          {!claimLoading && claimError && <div role="alert" className="text-sm text-rose-700 dark:text-rose-300">{claimError}</div>}
          {!claimLoading && !claimError && claim && <ClaimTraceDetail report={report} claim={claim} />}
        </div>
      )}
    </aside>
  );
}

function TraceValue({ label, value, empty }) {
  return (
    <div>
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      {value ? <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200/60 bg-slate-50/70 p-3 text-xs text-slate-700 dark:border-slate-700/50 dark:bg-slate-950/30 dark:text-slate-300">{JSON.stringify(value, null, 2)}</pre> : <p className="mt-2 text-sm text-slate-500">{empty}</p>}
    </div>
  );
}

function ClaimTraceDetail({ report, claim }) {
  const citations = Array.isArray(report?.citation_manifest) ? report.citation_manifest : [];
  const citationByEvidence = new Map(citations.map((citation) => [citation.evidence_key, citation.citation_id]));
  const links = Array.isArray(claim.evidence_links) ? claim.evidence_links : [];
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid gap-3 sm:grid-cols-2">
        {[
          ['Claim ID', claim.claim_id],
          ['Claim Type', claim.claim_type],
          ['Status', claim.status],
          ['Grounding Status', claim.grounding_status],
          ['Event ID', claim.event_id],
          ['Event Version ID', claim.event_version_id],
        ].map(([label, value]) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-all text-slate-800 dark:text-slate-200">{value || '—'}</dd></div>)}
      </dl>
      <div><div className="text-xs font-semibold text-slate-500">Claim Text</div><p className="mt-2 rounded-xl border border-slate-200/60 bg-white/50 p-3 leading-6 text-slate-800 dark:border-slate-700/50 dark:bg-slate-900/30 dark:text-slate-200">{claim.claim_text || '—'}</p></div>
      <div><div className="text-xs font-semibold text-slate-500">Current historical Claim row status</div><p className="mt-1 text-sm text-slate-700 dark:text-slate-300">{claim.status || '—'}</p></div>
      {!!claim.grounding_warnings?.length && <div><div className="text-xs font-semibold text-amber-700">Grounding Warnings</div><ul className="mt-2 list-disc pl-5 text-xs text-amber-700">{claim.grounding_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      <div><div className="text-xs font-semibold text-slate-500">Claim Evidence Provenance</div><div className="mt-2 space-y-2">{links.length ? links.map((link) => { const citationId = citationByEvidence.get(link.evidence_key); return <div key={`${link.evidence_key}-${link.relation}`} className="rounded-xl border border-slate-200/60 p-3 dark:border-slate-700/50"><div className="flex flex-wrap items-center gap-2"><Badge variant={link.relation === 'contradicts' ? 'red' : 'green'} size="sm">{link.relation || 'unknown'}</Badge><span className="break-all font-mono text-xs text-slate-700 dark:text-slate-300">{link.evidence_key}</span><span className="text-xs text-slate-500">{citationId ? `${citationId} · Used in this report` : 'Claim provenance, not cited in this report'}</span></div>{link.rationale && <p className="mt-2 text-xs text-slate-500">{link.rationale}</p>}</div>; }) : <p className="text-sm text-slate-500">No immutable Claim Evidence links were persisted.</p>}</div></div>
    </div>
  );
}

function ReportProvenance({ report }) {
  return (
    <details className="rounded-xl border border-slate-200/70 bg-white/40 p-4 dark:border-slate-700/60 dark:bg-slate-900/20">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
        <Hash size={16} /> Provenance
      </summary>
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        {[
          ['Report ID', report.report_id],
          ['Final Report Hash', report.final_report_hash],
          ['Dataset Hash', report.report_dataset_hash],
          ['Citation Graph Hash', report.citation_graph_hash],
          ['Section Plan Hash', report.section_plan_hash],
          ['Schema Version', report.report_schema_version],
          ['Assembly Rule', report.assembly_rule_version],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
            <dd className="mt-1 break-all font-mono text-slate-700 dark:text-slate-200" title={value || ''}>{label.endsWith('Hash') ? shortHash(value) : value || '—'}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function ReportVersionList({ reports, selectedReportId, onSelect }) {
  return (
    <fieldset aria-label="Final Report Versions" className="space-y-2">
      <legend className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">Report Versions</legend>
      {reports.map((report) => (
        <label key={report.report_id} className={`block cursor-pointer rounded-xl border p-3 transition-colors ${selectedReportId === report.report_id ? 'border-primary-400 bg-primary-50/70 dark:border-primary-500 dark:bg-primary-950/30' : 'border-slate-200/70 hover:border-primary-300 dark:border-slate-700/60'}`}>
          <input
            className="sr-only"
            type="radio"
            name="final-report-version"
            checked={selectedReportId === report.report_id}
            onChange={() => onSelect(report.report_id)}
          />
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-slate-800 dark:text-slate-100">{reportLabel(report)}</span>
            <Badge variant="green" size="sm">Assembled</Badge>
          </div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">{formatCreatedAt(report.created_at)}</div>
          <div className="mt-1 font-mono text-[11px] text-slate-400">{shortHash(report.final_report_hash)}</div>
        </label>
      ))}
    </fieldset>
  );
}

function ReportContent({ report, onClaim, onCitation }) {
  const [openSection, setOpenSection] = useState(report?.sections?.[0]?.section_id || null);
  const sections = Array.isArray(report?.sections) ? report.sections : [];
  const integrityWarnings = useMemo(() => checkFinalReportIntegrity(report), [report]);

  return (
    <div className="space-y-5">
      {integrityWarnings.length > 0 && (
        <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-200">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle size={17} /> Report Integrity Warning</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{integrityWarnings.map((warning) => <li key={warning.code}>{warning.message}</li>)}</ul>
        </div>
      )}
      <div className="flex flex-wrap gap-2" aria-label="Report sections">
        {sections.map((section) => (
          <button
            key={section.section_id}
            type="button"
            className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${openSection === section.section_id ? 'bg-primary-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-primary-100 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'}`}
            onClick={() => setOpenSection(section.section_id)}
          >
            {String(section.order).padStart(2, '0')} {section.title}
          </button>
        ))}
      </div>
      {sections.map((section) => (
        <section key={section.section_id} className="overflow-hidden rounded-2xl glass">
          <button type="button" className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left" onClick={() => setOpenSection((value) => value === section.section_id ? null : section.section_id)}>
            <div><div className="text-xs font-mono text-slate-400">{section.section_id}</div><h2 className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{section.title}</h2></div>
            {openSection === section.section_id ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          </button>
          {openSection === section.section_id && (
            <div className="space-y-3 border-t border-slate-200/60 px-5 py-5 dark:border-slate-700/50">
              {section.paragraphs?.length ? section.paragraphs.map((paragraph, index) => (
                <ReportParagraph
                  key={`${section.section_id}-${index}`}
                  text={paragraph.text}
                  claimIds={paragraph.claim_ids}
                  citationIds={paragraph.citation_ids}
                  onClaim={onClaim}
                  onCitation={onCitation}
                />
              )) : <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">This section is empty.</p>}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}

export default function FinalReportViewer() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  const viewer = useFinalReportViewer(taskId);
  const traceback = useReportTraceback(
    taskId,
    viewer.selectedReportId,
    viewer.selectedReport,
  );
  const publication = useFinalReportPublication(
    taskId,
    viewer.selectedReportId,
    Boolean(viewer.selectedReport && !viewer.detailLoading && !viewer.detailError),
  );
  const presentation = useFinalReportPresentation(
    taskId,
    viewer.selectedReportId,
    viewer.selectedReport?.report_version,
    Boolean(
      viewer.selectedReport
      && !viewer.detailLoading
      && !viewer.detailError
      && checkFinalReportIntegrity(viewer.selectedReport).length === 0
    ),
  );
  if (!taskId) {
    return <div className="flex min-h-[calc(100vh-9rem)] items-center justify-center"><div className="max-w-md text-center"><FileCheck2 className="mx-auto h-14 w-14 text-primary-500" /><h1 className="mt-4 text-2xl font-bold text-slate-900 dark:text-white">Final Report Viewer</h1><p className="mt-2 text-sm text-slate-500 dark:text-slate-400">Select a task to view its assembled Final Report Versions.</p></div></div>;
  }

  return (
    <div className="space-y-5">
      <header className="rounded-2xl glass px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><div className="text-xs font-mono text-slate-400">Phase 5A · Read-only</div><h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">Final Report Viewer</h1><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">View selected immutable report versions for this task.</p></div>
          <Link to={`/investigation?task_id=${encodeURIComponent(taskId)}`} className="text-sm font-semibold text-primary-600 hover:text-primary-500 dark:text-primary-300">Back to Investigation</Link>
        </div>
      </header>
      {viewer.listLoading && <div className="flex justify-center py-10"><Spinner size="lg" /></div>}
      {viewer.listError && !viewer.listLoading && <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/20 dark:text-rose-200"><div>{viewer.listError}</div><Button className="mt-3" size="sm" variant="secondary" icon={RefreshCw} onClick={viewer.retryList}>Retry</Button></div>}
      {!viewer.listLoading && !viewer.listError && viewer.reports.length === 0 && <div className="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">No final report versions have been assembled for this task.</div>}
      {!viewer.listLoading && !viewer.listError && viewer.reports.length > 0 && (
        <div className="grid min-w-0 gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
          <aside className="space-y-4 rounded-2xl glass p-4 lg:sticky lg:top-20 lg:h-fit"><div className="text-xs font-mono text-slate-400">Selected Report Version</div><ReportVersionList reports={viewer.reports} selectedReportId={viewer.selectedReportId} onSelect={viewer.selectReport} /></aside>
          <main className="min-w-0 space-y-5" aria-label="Selected Final Report">
            {viewer.detailLoading && <div className="flex justify-center rounded-2xl glass py-12"><Spinner size="lg" /></div>}
            {viewer.detailError && !viewer.detailLoading && <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/20 dark:text-rose-200"><div>{viewer.detailError}</div><Button className="mt-3" size="sm" variant="secondary" icon={RefreshCw} onClick={viewer.retryDetail}>Retry</Button></div>}
            {viewer.selectedReport && !viewer.detailLoading && !viewer.detailError && <><header className="rounded-2xl glass px-5 py-4"><div className="flex flex-wrap items-center gap-2"><h2 className="mr-auto text-xl font-bold text-slate-900 dark:text-white">Selected Report Version: v{viewer.selectedReport.report_version}</h2><Badge variant="green">Assembled</Badge></div><div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500 dark:text-slate-400"><span>Created {formatCreatedAt(viewer.selectedReport.created_at)}</span><span>Hash {shortHash(viewer.selectedReport.final_report_hash)}</span><span>Claims Used {viewer.selectedReport.claim_manifest?.length || 0}</span><span>Citations Used {viewer.selectedReport.citation_manifest?.length || 0}</span></div><div className="mt-3"><PublicationState {...publication} onPublish={publication.publish} /></div><div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Report presentation actions"><Button size="sm" variant="secondary" icon={Download} loading={presentation.loading === 'markdown'} disabled={!presentation.canPresent || Boolean(presentation.loading)} onClick={presentation.downloadMarkdown}>Download Markdown</Button><Button size="sm" variant="secondary" icon={ExternalLink} loading={presentation.loading === 'html'} disabled={!presentation.canPresent || Boolean(presentation.loading)} onClick={presentation.openHtml}>Open HTML</Button><Button size="sm" variant="secondary" icon={Printer} loading={presentation.loading === 'print'} disabled={!presentation.canPresent || Boolean(presentation.loading)} onClick={presentation.printReport}>Print / Save PDF</Button>{presentation.error && <span role="alert" className="text-xs text-rose-700 dark:text-rose-300">{presentation.error}</span>}</div><div className="mt-4"><ReportProvenance report={viewer.selectedReport} /></div></header><ReportTracePanel taskId={taskId} report={viewer.selectedReport} trace={traceback.selectedTrace} citation={traceback.citationTrace} claim={traceback.claimDetail} claimLoading={traceback.claimLoading} claimError={traceback.claimError} onClose={traceback.closeTrace} /><ReportContent report={viewer.selectedReport} onClaim={traceback.openClaim} onCitation={traceback.openCitation} /></>}
          </main>
        </div>
      )}
    </div>
  );
}

export { ReportParagraph };
