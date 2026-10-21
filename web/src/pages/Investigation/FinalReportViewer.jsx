import { forensicLabel } from '../../utils/forensicLabels';
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
import FileTimestampTimeline from './components/FileTimestampTimeline';
import { checkFinalReportIntegrity } from './finalReportIntegrity';

function shortHash(value) {
  if (!value || value.length <= 18) return value || '—';
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function formatCreatedAt(value) {
  if (!value) return '—';
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN');
}

function reportLabel(report) {
  return `报告版本 v${report?.report_version ?? '—'}`;
}

function PublicationState({ publication, loading, ready, error, publishLoading, publishError, publishSuccess, onPublish }) {
  if (!ready || loading) return <span className="text-xs text-slate-500">正在读取发布记录…</span>;
  if (error) return <span role="alert" className="text-xs text-rose-700 dark:text-rose-300">{error}</span>;
  if (publication) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-emerald-700 dark:text-emerald-300">
        <span>已发布</span>
        <span>发布时间 {formatCreatedAt(publication.published_at)}</span>
        {publication.publication_id && <span className="font-mono">发布记录 {shortHash(publication.publication_id)}</span>}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
      <span>此报告版本尚无发布记录。</span>
      <Button
        size="sm"
        variant="secondary"
        loading={publishLoading}
        disabled={publishLoading}
        onClick={onPublish}
      >
        发布此报告版本
      </Button>
      {publishSuccess && <span className="text-emerald-700 dark:text-emerald-300">已保存发布记录。</span>}
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
              <Badge variant="blue" size="sm">断言 {claimId}</Badge>
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
    <aside className="rounded-2xl glass p-5" aria-label="报告溯源">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-mono text-slate-400">只读来源链</div>
          <h2 className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{trace.type === 'citation' ? '报告引用' : '历史断言'}</h2>
        </div>
        <button type="button" aria-label="关闭溯源" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={onClose}><X size={18} /></button>
      </div>
      {trace.type === 'citation' && (
        citation ? (
          <div className="mt-4 space-y-4 text-sm">
            <dl className="grid gap-3 sm:grid-cols-2">
              <div><dt className="text-xs text-slate-500">引用编号</dt><dd className="mt-1 font-mono text-slate-800 dark:text-slate-200">{citation.citation_id}</dd></div>
              <div><dt className="text-xs text-slate-500">证据标识</dt><dd className="mt-1 break-all font-mono text-slate-800 dark:text-slate-200">({taskId}, {citation.evidence_key})</dd></div>
              <div><dt className="text-xs text-slate-500">证据类型</dt><dd className="mt-1 text-slate-800 dark:text-slate-200">{forensicLabel(citation.evidence_type)}</dd></div>
              <div><dt className="text-xs text-slate-500">报告状态</dt><dd className="mt-1 text-slate-800 dark:text-slate-200">{forensicLabel(citation.report_status)}</dd></div>
            </dl>
            <div><div className="text-xs font-semibold text-slate-500">引用此证据的报告断言</div><div className="mt-2 flex flex-wrap gap-2">{claimIdsForCitation.length ? claimIdsForCitation.map((claimId) => <Badge key={claimId} variant="blue" size="sm">{claimId}</Badge>) : <span className="text-sm text-slate-500">没有断言引用此项。</span>}</div></div>
            <TraceValue label="报告绑定的证据快照" value={citation.snapshot} empty="未保存报告绑定的快照。" />
            <TraceValue label="绑定的分析版本" value={citation.pinned_analysis} empty="此报告证据未绑定已接受的分析版本。" />
          </div>
        ) : <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">引用来源暂不可用。</p>
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
          ['断言编号', claim.claim_id],
          ['断言类型', claim.claim_type],
          ['状态', claim.status],
          ['证据引用校验状态', claim.grounding_status],
          ['事件编号', claim.event_id],
          ['事件版本编号', claim.event_version_id],
        ].map(([label, value]) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-all text-slate-800 dark:text-slate-200">{value || '—'}</dd></div>)}
      </dl>
      <div><div className="text-xs font-semibold text-slate-500">断言内容</div><p className="mt-2 rounded-xl border border-slate-200/60 bg-white/50 p-3 leading-6 text-slate-800 dark:border-slate-700/50 dark:bg-slate-900/30 dark:text-slate-200">{claim.claim_text || '—'}</p></div>
      <div><div className="text-xs font-semibold text-slate-500">历史断言当前状态</div><p className="mt-1 text-sm text-slate-700 dark:text-slate-300">{forensicLabel(claim.status)}</p></div>
      {!!claim.grounding_warnings?.length && <div><div className="text-xs font-semibold text-amber-700">证据引用校验提醒</div><ul className="mt-2 list-disc pl-5 text-xs text-amber-700">{claim.grounding_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      <div><div className="text-xs font-semibold text-slate-500">断言的证据来源</div><div className="mt-2 space-y-2">{links.length ? links.map((link) => { const citationId = citationByEvidence.get(link.evidence_key); return <div key={`${link.evidence_key}-${link.relation}`} className="rounded-xl border border-slate-200/60 p-3 dark:border-slate-700/50"><div className="flex flex-wrap items-center gap-2"><Badge variant={link.relation === 'contradicts' ? 'red' : 'green'} size="sm">{forensicLabel(link.relation)}</Badge><span className="break-all font-mono text-xs text-slate-700 dark:text-slate-300">{link.evidence_key}</span><span className="text-xs text-slate-500">{citationId ? `${citationId} · 已在本报告引用` : '断言来源，未被本报告引用'}</span></div>{link.rationale && <p className="mt-2 text-xs text-slate-500">{link.rationale}</p>}</div>; }) : <p className="text-sm text-slate-500">未保存固定的断言证据关联。</p>}</div></div>
    </div>
  );
}

function ReportProvenance({ report }) {
  return (
    <details className="rounded-xl border border-slate-200/70 bg-white/40 p-4 dark:border-slate-700/60 dark:bg-slate-900/20">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
        <Hash size={16} /> 来源链
      </summary>
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        {[
          ['报告编号', report.report_id],
          ['最终报告哈希', report.final_report_hash],
          ['数据集哈希', report.report_dataset_hash],
          ['Citation Graph Hash', report.citation_graph_hash],
          ['Section Plan Hash', report.section_plan_hash],
          ['Schema Version', report.report_schema_version],
          ['Assembly Rule', report.assembly_rule_version],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
            <dd className="mt-1 break-all font-mono text-slate-700 dark:text-slate-200" title={value || ''}>{label.endsWith('哈希') ? shortHash(value) : value || '—'}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function ReportVersionList({ reports, selectedReportId, onSelect }) {
  return (
    <fieldset aria-label="最终报告版本" className="space-y-2">
      <legend className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">报告版本</legend>
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
            <Badge variant="green" size="sm">已编制</Badge>
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
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle size={17} /> 报告完整性提醒</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{integrityWarnings.map((warning) => <li key={warning.code}>{warning.message}</li>)}</ul>
        </div>
      )}
      <div className="flex flex-wrap gap-2" aria-label="报告章节">
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
              )) : <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">本节暂无内容。</p>}
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
    return <div className="flex min-h-[calc(100vh-9rem)] items-center justify-center"><div className="max-w-md text-center"><FileCheck2 className="mx-auto h-14 w-14 text-primary-500" /><h1 className="mt-4 text-2xl font-bold text-slate-900 dark:text-white">最终报告查看</h1><p className="mt-2 text-sm text-slate-500 dark:text-slate-400">请选择任务，查看已编制的报告版本。</p></div></div>;
  }

  return (
    <div className="space-y-5">
      <header className="rounded-2xl glass px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><div className="text-xs font-mono text-slate-400">只读报告</div><h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">最终报告查看</h1><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">查看此任务已冻结的报告版本。</p></div>
          <Link to={`/investigation?task_id=${encodeURIComponent(taskId)}`} className="text-sm font-semibold text-primary-600 hover:text-primary-500 dark:text-primary-300">返回调查研判</Link>
        </div>
      </header>
      {/* MVP (mvp-phase1-acceptance §6.1): file timeline over the filtered
          files' four forensic timestamps — events are not part of the report. */}
      <FileTimestampTimeline taskId={taskId} />
      {viewer.listLoading && <div className="flex justify-center py-10"><Spinner size="lg" /></div>}
      {viewer.listError && !viewer.listLoading && <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/20 dark:text-rose-200"><div>{viewer.listError}</div><Button className="mt-3" size="sm" variant="secondary" icon={RefreshCw} onClick={viewer.retryList}>重试</Button></div>}
      {!viewer.listLoading && !viewer.listError && viewer.reports.length === 0 && <div className="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">此任务尚未编制最终报告。</div>}
      {!viewer.listLoading && !viewer.listError && viewer.reports.length > 0 && (
        <div className="grid min-w-0 gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
          <aside className="space-y-4 rounded-2xl glass p-4 lg:sticky lg:top-20 lg:h-fit"><div className="text-xs font-mono text-slate-400">选中的报告版本</div><ReportVersionList reports={viewer.reports} selectedReportId={viewer.selectedReportId} onSelect={viewer.selectReport} /></aside>
          <main className="min-w-0 space-y-5" aria-label="选中的最终报告">
            {viewer.detailLoading && <div className="flex justify-center rounded-2xl glass py-12"><Spinner size="lg" /></div>}
            {viewer.detailError && !viewer.detailLoading && <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/20 dark:text-rose-200"><div>{viewer.detailError}</div><Button className="mt-3" size="sm" variant="secondary" icon={RefreshCw} onClick={viewer.retryDetail}>重试</Button></div>}
            {viewer.selectedReport && !viewer.detailLoading && !viewer.detailError && <><header className="rounded-2xl glass px-5 py-4"><div className="flex flex-wrap items-center gap-2"><h2 className="mr-auto text-xl font-bold text-slate-900 dark:text-white">选中的报告版本：v{viewer.selectedReport.report_version}</h2><Badge variant="green">已编制</Badge></div><div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500 dark:text-slate-400"><span>创建于 {formatCreatedAt(viewer.selectedReport.created_at)}</span><span>哈希 {shortHash(viewer.selectedReport.final_report_hash)}</span><span>引用断言数 {viewer.selectedReport.claim_manifest?.length || 0}</span><span>引用证据数 {viewer.selectedReport.citation_manifest?.length || 0}</span></div><div className="mt-3"><PublicationState {...publication} onPublish={publication.publish} /></div><div className="mt-3 flex flex-wrap items-center gap-2" aria-label="报告导出操作"><Button size="sm" variant="secondary" icon={Download} loading={presentation.loading === 'markdown'} disabled={!presentation.canPresent || Boolean(presentation.loading)} onClick={presentation.downloadMarkdown}>下载 Markdown</Button><Button size="sm" variant="secondary" icon={ExternalLink} loading={presentation.loading === 'html'} disabled={!presentation.canPresent || Boolean(presentation.loading)} onClick={presentation.openHtml}>打开 HTML</Button><Button size="sm" variant="secondary" icon={Printer} loading={presentation.loading === 'print'} disabled={!presentation.canPresent || Boolean(presentation.loading)} onClick={presentation.printReport}>打印 / 保存 PDF</Button>{presentation.error && <span role="alert" className="text-xs text-rose-700 dark:text-rose-300">{presentation.error}</span>}</div><div className="mt-4"><ReportProvenance report={viewer.selectedReport} /></div></header><ReportTracePanel taskId={taskId} report={viewer.selectedReport} trace={traceback.selectedTrace} citation={traceback.citationTrace} claim={traceback.claimDetail} claimLoading={traceback.claimLoading} claimError={traceback.claimError} onClose={traceback.closeTrace} /><ReportContent report={viewer.selectedReport} onClaim={traceback.openClaim} onCitation={traceback.openCitation} /></>}
          </main>
        </div>
      )}
    </div>
  );
}

export { ReportParagraph };
