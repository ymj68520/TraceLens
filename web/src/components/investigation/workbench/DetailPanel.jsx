// DetailPanel.jsx
// Workbench 右栏：Analysis Workspace。按当前 primary selection 渲染：
//   event    → 当前 narrative / 版本历史 / refresh 状态 + C9c 的
//              Add Evidence / Refresh Event Narrative 动作
//   evidence → Snapshot Initial Analysis（唯一来源，不回读 files.db）+ Analysis 版本
//              + C9b 的 Run Secondary Analysis 动作
//   analysis → exact analysis 的 description/summary/Claims + 分区展示的
//              Grounding 与 Analyst Review（C9b：grounding ≠ accepted，
//              review 表单只在 review_pending 出现）
//   claim    → exact 持久化 Claim 的 provenance（含 evidence refs）
// 数据由页面加载；本组件只渲染、转发 selection 与提交动作。
import { ArrowUpRight, CircleAlert } from 'lucide-react';
import Badge from '../../common/Badge';
import Spinner from '../../common/Spinner';
import SubmitAnalysisForm from './SubmitAnalysisForm';
import ReviewDecisionForm from './ReviewDecisionForm';
import LinkEvidenceForm from './LinkEvidenceForm';
import RefreshNarrativeForm from './RefreshNarrativeForm';
import { useTranslation } from '../../../hooks/useTranslation';

const Row = ({ label, value, mono = false, breakAll = false }) => (
    <div className="flex items-baseline justify-between gap-3 py-1">
        <span className="text-[11px] text-slate-500 dark:text-slate-400 shrink-0">{label}</span>
        <span className={`text-[11px] text-right text-slate-700 dark:text-slate-200 ${mono ? 'font-mono' : ''} ${breakAll ? 'break-all' : ''}`}>
            {value === undefined || value === null || value === '' ? '-' : String(value)}
        </span>
    </div>
);

const Section = ({ title, children, action }) => (
    <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2">
        <div className="flex items-center justify-between gap-2 pb-1">
            <h3 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">{title}</h3>
            {action}
        </div>
        {children}
    </div>
);

const statusVariant = (status) => {
    if (status === 'accepted' || status === 'completed') return 'green';
    if (status === 'review_pending' || status === 'queued') return 'yellow';
    if (status === 'running') return 'blue';
    if (status === 'rejected' || status === 'invalid' || status === 'failed') return 'red';
    return 'gray';
};

// grounding 徽章一律中性灰（§6）：grounded ≠ analyst accepted，不能用绿色
// 让用户误读为人工确认。绿色只属于 status=accepted。
const groundingVariant = () => 'gray';

// 解析冻结的 AnalysisInputEnvelope（v1 related_evidence 是 string[]，
// v2 是 {evidence_key, snapshot}[]——只展示 key，不渲染快照本体）。
const parseSubmittedContext = (analysis) => {
    if (!analysis?.input_envelope_json) return null;
    try {
        const envelope = JSON.parse(analysis.input_envelope_json);
        const related = Array.isArray(envelope.related_evidence)
            ? envelope.related_evidence
                .map((entry) => (typeof entry === 'string' ? entry : entry?.evidence_key))
                .filter(Boolean)
            : [];
        return {
            analystNote: envelope.analyst_note ?? null,
            caseContext: envelope.case_context ?? null,
            relatedEvidence: related,
        };
    } catch {
        return null;
    }
};

const formatTime = (iso) => {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
};

const EventDetail = ({
    bundle,
    onSelectEvidence,
    evidenceOptions = [],
    onLinkEvidence,
    refreshBusy = false,
    onStartRefresh,
}) => {
    const { t } = useTranslation();
    const { event, versions = [], links = [], refreshes = [] } = bundle || {};
    if (!event) return null;
    return (
        <div className="space-y-3" data-testid="event-detail">
            <div className="flex items-start justify-between gap-2 flex-wrap">
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100 break-all">{event.title}</h2>
                <span className="flex items-center gap-1 shrink-0">
                    <Badge variant="gray" size="sm">v{event.current_version}</Badge>
                    {event.needs_refresh && (
                        <Badge variant="yellow" size="sm">{t('investigation_workbench.needs_refresh')}</Badge>
                    )}
                </span>
            </div>
            {event.summary && (
                <p className="text-xs leading-relaxed whitespace-pre-wrap break-words text-slate-600 dark:text-slate-300">
                    {event.summary}
                </p>
            )}

            <Section title={t('investigation_workbench.event_versions')}>
                {versions.length === 0 ? (
                    <p className="text-[11px] text-slate-400">-</p>
                ) : versions.map((version) => (
                    <div key={version.version} className="flex items-baseline justify-between gap-2 py-1 border-t border-slate-200/40 dark:border-slate-700/30 first:border-0">
                        <span className="text-[11px] font-mono text-slate-600 dark:text-slate-300">
                            v{version.version} {formatTime(version.created_at)}
                        </span>
                        <span className="text-[10px] text-slate-400 truncate max-w-[50%]">
                            {version.created_by || '-'}
                        </span>
                    </div>
                ))}
            </Section>

            {/* §8：clean / dirty 都允许显式 refresh（C7c R8），只换提示文案。 */}
            <RefreshNarrativeForm
                eventId={event.event_id}
                needsRefresh={Boolean(event.needs_refresh)}
                busy={refreshBusy}
                onStartRefresh={onStartRefresh}
            />

            {/* §15：轻量 refresh 历史——不展示 envelope/snapshot/prompt 全文。 */}
            <Section title={t('investigation_workbench.event_refreshes')}>
                {refreshes.length === 0 ? (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.no_refreshes')}</p>
                ) : refreshes.map((refresh) => (
                    <div
                        key={refresh.refresh_id}
                        data-testid={`refresh-item-${refresh.refresh_id}`}
                        className="py-1 border-t border-slate-200/40 dark:border-slate-700/30 first:border-0"
                    >
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-[11px] font-mono text-slate-600 dark:text-slate-300 truncate">
                                {refresh.refresh_id}
                            </span>
                            <Badge variant={statusVariant(refresh.status)} size="sm">{refresh.status}</Badge>
                        </div>
                        <Row label={t('investigation_workbench.requested_by')} value={refresh.requested_by} />
                        <Row label={t('investigation_workbench.base_version_label')} value={`v${refresh.base_version}`} />
                        {refresh.produced_version !== null && refresh.produced_version !== undefined && (
                            <Row label={t('investigation_workbench.produced_version')} value={`v${refresh.produced_version}`} />
                        )}
                        {refresh.model && <Row label={t('investigation_workbench.model_label')} value={refresh.model} mono />}
                        <Row label={t('investigation_workbench.event_created_at')} value={formatTime(refresh.created_at)} />
                        <Row label={t('investigation_workbench.started_at_label')} value={formatTime(refresh.started_at)} />
                        {(refresh.status === 'completed' || refresh.completed_at) && (
                            <Row label={t('investigation_workbench.completed_at_label')} value={formatTime(refresh.completed_at)} />
                        )}
                        {(refresh.status === 'failed' || refresh.failed_at) && (
                            <Row label={t('investigation_workbench.failed_at_label')} value={formatTime(refresh.failed_at)} />
                        )}
                        {refresh.status === 'failed' && (
                            <>
                                <Row label="error_code" value={refresh.error_code} mono />
                                <Row label="error_message" value={refresh.error_message} breakAll />
                                {refresh.error_code === 'base_version_changed' ? (
                                    // §18：fail-closed 并发保护，不是系统故障。
                                    <p className="mt-1 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
                                        {t('investigation_workbench.base_version_changed_note')}
                                    </p>
                                ) : (
                                    <p className="mt-1 text-[10px] text-slate-400">
                                        {t('investigation_workbench.failure_no_retry')}
                                    </p>
                                )}
                            </>
                        )}
                    </div>
                ))}
            </Section>

            <Section title={t('investigation_workbench.event_evidence')}>
                {links.length === 0 ? (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.no_event_evidence')}</p>
                ) : links.map((link) => (
                    <button
                        key={`${link.event_id}:${link.evidence_key}`}
                        type="button"
                        data-testid={`event-evidence-${link.evidence_key}`}
                        onClick={() => onSelectEvidence(link.evidence_key)}
                        className="w-full text-left py-1 border-t border-slate-200/40 dark:border-slate-700/30 first:border-0 hover:bg-slate-100/60 dark:hover:bg-slate-700/30 rounded"
                    >
                        <span className="text-[11px] font-mono break-all text-slate-600 dark:text-slate-300">
                            {link.evidence_key}
                        </span>
                        <span className="block text-[10px] text-slate-400">
                            {formatTime(link.linked_at)} · {link.linked_by || '-'}
                        </span>
                    </button>
                ))}
            </Section>

            {/* §3/§4/§5：append-only 显式 link；候选排除已链接 key，无自由输入。 */}
            <LinkEvidenceForm
                eventId={event.event_id}
                linkedKeys={links.map((link) => link.evidence_key)}
                evidenceOptions={evidenceOptions}
                onLinkEvidence={onLinkEvidence}
            />
        </div>
    );
};

const EvidenceDetail = ({
    bundle,
    evidenceKey,
    onSelectAnalysis,
    selectedAnalysisId,
    evidenceOptions,
    submitBusy,
    onSubmitAnalysis,
}) => {
    const { t } = useTranslation();
    const { snapshot, analyses = [] } = bundle || {};
    const payload = snapshot?.payload || null;
    return (
        <div className="space-y-3" data-testid="evidence-detail">
            <h2 className="text-sm font-semibold font-mono break-all text-slate-900 dark:text-slate-100">
                {evidenceKey}
            </h2>

            <Section title={t('investigation_workbench.initial_analysis')}>
                {snapshot ? (
                    <>
                        <Row label={t('investigation_workbench.captured_at')} value={snapshot.captured_at ? new Date(snapshot.captured_at * 1000).toLocaleString() : '-'} />
                        <Row label="summary" value={payload?.initial_summary} breakAll />
                        <Row label="model" value={payload?.initial_model} mono />
                        {payload?.initial_description && (
                            <p className="mt-1 text-[11px] leading-relaxed whitespace-pre-wrap break-words text-slate-600 dark:text-slate-300">
                                {payload.initial_description}
                            </p>
                        )}
                    </>
                ) : (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.no_snapshot')}</p>
                )}
            </Section>

            <Section title={t('investigation_workbench.secondary_analyses')}>
                {analyses.length === 0 ? (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.no_analyses')}</p>
                ) : analyses.map((analysis) => (
                    <button
                        key={analysis.analysis_id}
                        type="button"
                        data-testid={`analysis-item-${analysis.analysis_id}`}
                        onClick={() => onSelectAnalysis(analysis.analysis_id)}
                        className={`w-full text-left py-1.5 px-1 -mx-1 rounded-lg border-t border-slate-200/40 dark:border-slate-700/30 first:border-0 transition-colors ${
                            analysis.analysis_id === selectedAnalysisId
                                ? 'bg-blue-500/10 ring-1 ring-blue-500/30'
                                : 'hover:bg-slate-100/60 dark:hover:bg-slate-700/30'
                        }`}
                    >
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-[11px] font-mono text-slate-600 dark:text-slate-300 truncate">
                                v{analysis.version} · {analysis.analysis_id}
                            </span>
                            <Badge variant={statusVariant(analysis.status)} size="sm">{analysis.status}</Badge>
                        </div>
                        {analysis.summary && (
                            <span className="block mt-0.5 text-[10px] text-slate-400 line-clamp-1">{analysis.summary}</span>
                        )}
                    </button>
                ))}
            </Section>

            <SubmitAnalysisForm
                evidenceKey={evidenceKey}
                evidenceOptions={evidenceOptions}
                busy={submitBusy}
                onSubmit={onSubmitAnalysis}
            />
        </div>
    );
};

const AnalysisDetail = ({
    bundle,
    onSelectClaim,
    selectedClaimId,
    onSelectEvidence,
    onSubmitReview,
}) => {
    const { t } = useTranslation();
    const { analysis, claims = [] } = bundle || {};
    if (!analysis) return null;

    const submittedContext = parseSubmittedContext(analysis);
    const hasSubmittedContext = Boolean(
        submittedContext
        && (submittedContext.analystNote || submittedContext.caseContext || submittedContext.relatedEvidence.length > 0),
    );

    return (
        <div className="space-y-3" data-testid="analysis-detail">
            <div className="flex items-start justify-between gap-2 flex-wrap">
                <h2 className="text-sm font-semibold font-mono break-all text-slate-900 dark:text-slate-100">
                    {analysis.analysis_id}
                </h2>
                <span className="flex items-center gap-1 shrink-0">
                    <Badge variant="gray" size="sm">v{analysis.version}</Badge>
                    <Badge variant={statusVariant(analysis.status)} size="sm">{analysis.status}</Badge>
                    {analysis.status === 'review_pending' && (
                        <Badge variant="yellow" size="sm">{t('investigation_workbench.awaiting_review')}</Badge>
                    )}
                </span>
            </div>

            <Section title={t('investigation_workbench.analysis_meta')}>
                <Row label="evidence_key" value={analysis.evidence_key} mono breakAll />
                <Row label="created_at" value={formatTime(analysis.created_at)} />
                {analysis.model && <Row label="model" value={analysis.model} mono />}
                <button
                    type="button"
                    onClick={() => onSelectEvidence(analysis.evidence_key)}
                    className="mt-1 inline-flex items-center gap-1 text-[11px] text-primary-600 dark:text-primary-400 hover:underline"
                >
                    <ArrowUpRight size={11} />
                    {t('investigation_workbench.goto_evidence')}
                </button>
            </Section>

            {analysis.status === 'failed' && (
                <Section title={t('investigation_workbench.execution_failure')}>
                    <Row label="error_code" value={analysis.error_code} mono />
                    <Row label="error_message" value={analysis.error_message} breakAll />
                    <p className="mt-1 text-[10px] text-slate-400">
                        {t('investigation_workbench.failure_no_retry')}
                    </p>
                </Section>
            )}

            {analysis.description && (
                <Section title="description">
                    <p className="text-[11px] leading-relaxed whitespace-pre-wrap break-words text-slate-600 dark:text-slate-300">
                        {analysis.description}
                    </p>
                </Section>
            )}
            {analysis.summary && (
                <Section title="summary">
                    <p className="text-[11px] leading-relaxed whitespace-pre-wrap break-words text-slate-600 dark:text-slate-300">
                        {analysis.summary}
                    </p>
                </Section>
            )}

            {/* §6：Grounding 与 Analyst Review 是两个独立区域。
                grounding=valid 只表示引用校验通过，绝不是人工 accepted。 */}
            <Section title={t('investigation_workbench.grounding')}>
                {analysis.grounding_status ? (
                    <div className="flex items-center justify-between gap-2 py-1">
                        <span className="text-[11px] text-slate-500 dark:text-slate-400">
                            {t('investigation_workbench.grounding_note')}
                        </span>
                        <Badge variant={groundingVariant()} size="sm">{analysis.grounding_status}</Badge>
                    </div>
                ) : (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.grounding_not_run')}</p>
                )}
            </Section>

            <Section title={t('investigation_workbench.claims')}>
                {claims.length === 0 ? (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.no_claims')}</p>
                ) : claims.map((claim) => (
                    <button
                        key={claim.claim_id}
                        type="button"
                        data-testid={`claim-item-${claim.claim_id}`}
                        onClick={() => onSelectClaim(claim.claim_id, claim.analysis_id)}
                        className={`w-full text-left py-1.5 px-1 -mx-1 rounded-lg border-t border-slate-200/40 dark:border-slate-700/30 first:border-0 transition-colors ${
                            claim.claim_id === selectedClaimId
                                ? 'bg-fuchsia-500/10 ring-1 ring-fuchsia-500/30'
                                : 'hover:bg-slate-100/60 dark:hover:bg-slate-700/30'
                        }`}
                    >
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-[11px] font-mono text-slate-500">{claim.claim_type}</span>
                            <Badge variant={groundingVariant()} size="sm">
                                {claim.grounding_status}
                            </Badge>
                        </div>
                        <span className="block mt-0.5 text-[11px] text-slate-600 dark:text-slate-300 line-clamp-2">
                            {claim.claim_text}
                        </span>
                        {(claim.evidence_refs || []).length > 0 && (
                            <span className="block text-[10px] text-slate-400">
                                {(claim.evidence_refs || []).length} refs
                            </span>
                        )}
                    </button>
                ))}
            </Section>

            {/* §12：提交后 envelope 已冻结；这里展示的是冻结时的 analyst
                context（从 exact read 的 input_envelope_json 解析），绝不
                回显表单当前内容冒充该 Analysis 的输入。 */}
            {hasSubmittedContext && (
                <Section title={t('investigation_workbench.submitted_context')}>
                    <Row label={t('investigation_workbench.analyst_note')} value={submittedContext.analystNote} breakAll />
                    <Row label={t('investigation_workbench.case_context')} value={submittedContext.caseContext} breakAll />
                    {submittedContext.relatedEvidence.map((key) => (
                        <Row key={key} label={t('investigation_workbench.related_evidence')} value={key} mono breakAll />
                    ))}
                </Section>
            )}

            {/* §7/§8：review 表单只在 review_pending 出现；决策信息独立分区。 */}
            {analysis.status === 'review_pending' ? (
                <ReviewDecisionForm analysisId={analysis.analysis_id} onSubmitReview={onSubmitReview} />
            ) : analysis.decided_by ? (
                <Section title={t('investigation_workbench.analyst_review')}>
                    <Row label="decision" value={analysis.status} />
                    <Row label="decided_by" value={analysis.decided_by} />
                    <Row label="decided_at" value={formatTime(analysis.decided_at)} />
                    <Row label="reason" value={analysis.decision_reason} breakAll />
                </Section>
            ) : null}
        </div>
    );
};

const ClaimDetail = ({ claim, onSelectAnalysis, onSelectEvidence }) => {
    const { t } = useTranslation();
    if (!claim) return null;
    return (
        <div className="space-y-3" data-testid="claim-detail">
            <div className="flex items-start justify-between gap-2 flex-wrap">
                <h2 className="text-sm font-semibold font-mono break-all text-slate-900 dark:text-slate-100">
                    {claim.claim_id}
                </h2>
                <span className="flex items-center gap-1 shrink-0">
                    <Badge variant="gray" size="sm">{claim.claim_type}</Badge>
                    <Badge variant={groundingVariant()} size="sm">
                        {claim.grounding_status}
                    </Badge>
                </span>
            </div>

            <Section title={t('investigation_workbench.claim_text')}>
                <p className="text-xs leading-relaxed whitespace-pre-wrap break-words text-slate-700 dark:text-slate-200">
                    {claim.claim_text}
                </p>
            </Section>

            <Section title={t('investigation_workbench.claim_provenance')}>
                <Row label="analysis_id" value={claim.analysis_id} mono breakAll />
                <Row label="claim_index" value={claim.claim_index} />
                <Row label="created_at" value={formatTime(claim.created_at)} />
                <button
                    type="button"
                    onClick={() => onSelectAnalysis(claim.analysis_id)}
                    className="mt-1 inline-flex items-center gap-1 text-[11px] text-primary-600 dark:text-primary-400 hover:underline"
                >
                    <ArrowUpRight size={11} />
                    {t('investigation_workbench.goto_analysis')}
                </button>
            </Section>

            <Section title={t('investigation_workbench.claim_evidence_refs')}>
                {(claim.evidence_refs || []).length === 0 ? (
                    <p className="text-[11px] text-slate-400">{t('investigation_workbench.no_claim_refs')}</p>
                ) : claim.evidence_refs.map((ref) => (
                    <button
                        key={ref}
                        type="button"
                        data-testid={`claim-ref-${ref}`}
                        onClick={() => onSelectEvidence(ref)}
                        className="w-full text-left py-1 border-t border-slate-200/40 dark:border-slate-700/30 first:border-0 hover:bg-slate-100/60 dark:hover:bg-slate-700/30 rounded"
                    >
                        <span className="text-[11px] font-mono break-all text-slate-600 dark:text-slate-300">{ref}</span>
                    </button>
                ))}
            </Section>

            {claim.warnings && Object.keys(claim.warnings).length > 0 && (
                <Section title="warnings">
                    <pre className="text-[10px] whitespace-pre-wrap break-all text-amber-700 dark:text-amber-400">
                        {JSON.stringify(claim.warnings, null, 2)}
                    </pre>
                </Section>
            )}
        </div>
    );
};

const DetailPanel = ({
    selection,
    loading = false,
    error = null,
    eventBundle,
    evidenceBundle,
    analysisBundle,
    claim,
    onSelectEvidence,
    onSelectAnalysis,
    onSelectClaim,
    selectedAnalysisId,
    selectedClaimId,
    evidenceOptions = [],
    submitBusy = false,
    onSubmitAnalysis,
    onSubmitReview,
    onLinkEvidence,
    refreshBusy = false,
    onStartRefresh,
}) => {
    const { t } = useTranslation();

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-4">
                <CircleAlert size={20} className="text-rose-500" />
                <p className="text-xs text-rose-600 dark:text-rose-400">
                    {t('investigation_workbench.load_failed')}
                    {error?.status ? ` (HTTP ${error.status})` : ''}
                </p>
            </div>
        );
    }

    if (!selection) {
        return (
            <div className="flex items-center justify-center h-full text-xs text-slate-400 dark:text-slate-500 px-6 text-center"
                data-testid="detail-empty">
                {t('investigation_workbench.select_hint')}
            </div>
        );
    }

    let content = null;
    if (loading) {
        content = (
            <div className="flex items-center justify-center py-12">
                <Spinner size="md" />
            </div>
        );
    } else if (selection.type === 'event') {
        content = (
            <EventDetail
                bundle={eventBundle}
                onSelectEvidence={onSelectEvidence}
                evidenceOptions={evidenceOptions}
                onLinkEvidence={onLinkEvidence}
                refreshBusy={refreshBusy}
                onStartRefresh={onStartRefresh}
            />
        );
    } else if (selection.type === 'evidence') {
        content = (
            <EvidenceDetail
                bundle={evidenceBundle}
                evidenceKey={selection.id}
                onSelectAnalysis={onSelectAnalysis}
                selectedAnalysisId={selectedAnalysisId}
                evidenceOptions={evidenceOptions}
                submitBusy={submitBusy}
                onSubmitAnalysis={onSubmitAnalysis}
            />
        );
    } else if (selection.type === 'analysis') {
        content = (
            <AnalysisDetail
                bundle={analysisBundle}
                onSelectClaim={onSelectClaim}
                selectedClaimId={selectedClaimId}
                onSelectEvidence={onSelectEvidence}
                onSubmitReview={onSubmitReview}
            />
        );
    } else if (selection.type === 'claim') {
        content = <ClaimDetail claim={claim} onSelectAnalysis={onSelectAnalysis} onSelectEvidence={onSelectEvidence} />;
    }

    return (
        <div className="overflow-y-auto h-full px-3 py-3" data-testid="analysis-workspace">
            {content}
        </div>
    );
};

export default DetailPanel;
