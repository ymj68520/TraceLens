// CitationTracebackPanel.jsx
// R2d citation 溯源面板：persisted citation manifest entry 是唯一
// authoritative identity；当前 Investigation strict 读只是可选增强。
// 三层来源显式区分：Evidence = Evidence Source；Accepted Analysis =
// analyst-accepted derived finding；Claim = derived claim。绝不显示
// Graph Entity / Event / Timeline Cluster 作为来源（§24），也绝不因
// current 库变化而改写 frozen identity（§16）。
import { useEffect, useRef, useState } from 'react';
import { ExternalLink, FileSearch, X } from 'lucide-react';
import {
    getInvestigationAnalysis,
    getInvestigationSnapshot,
    listInvestigationAnalysisClaims,
} from '../../services/investigationService';
import { investigationEvidenceUrl } from '../../utils/evidenceKey';
import { FIELD_AUTH_ENABLED } from '../../config/runtime';
import { Link } from 'react-router-dom';

const Layer = ({ title, tone, children, testId }) => (
    <div
        className={`rounded-xl border p-2.5 space-y-1 ${tone}`}
        data-testid={testId}
    >
        <p className="text-[10px] font-bold uppercase tracking-wide opacity-70">{title}</p>
        {children}
    </div>
);

const Field = ({ label, value, mono = true }) => (
    <p className="text-[11px] text-slate-600 dark:text-slate-300 break-all">
        <span className="text-slate-400">{label}: </span>
        <span className={mono ? 'font-mono' : ''}>{value}</span>
    </p>
);

const ExpandableDescription = ({ label, value }) => {
    const [expanded, setExpanded] = useState(false);
    const text = String(value || '—');
    const long = text.length > 300;
    return (
        <div className="rounded-lg border border-slate-200/70 bg-white/75 p-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">{label}</p>
            <p className={`mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-6 text-slate-700 dark:text-slate-200 ${long && !expanded ? 'line-clamp-5' : ''}`}>{text}</p>
            {long && <button type="button" className="mt-2 text-xs font-semibold text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-blue-300" onClick={() => setExpanded((value) => !value)}>{expanded ? '收起描述' : '展开完整描述'}</button>}
        </div>
    );
};

// file: 证据键 → 调查工作台深链（新标签页，时间线定位该文件）；
// cluster: 等其他命名空间没有文件时间线落点，保持纯文本。
const EvidenceKeyLink = ({ value, taskId, reportId, citationId, allowTimeline = true }) => {
    const href = allowTimeline ? investigationEvidenceUrl(taskId, value, { reportId, citationId }) : null;
    if (!href) return <span className="font-mono">{value}</span>;
    const linkClass = "font-mono text-primary-600 underline decoration-dotted underline-offset-2 transition-colors hover:text-primary-500 dark:text-primary-300 dark:hover:text-primary-200";
    if (FIELD_AUTH_ENABLED) return <Link to={href} data-testid="evidence-key-link"
        title="在当前登录会话中打开调查工作台，定位该冻结证据"
        className={linkClass}>{value}</Link>;
    return (
        <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="evidence-key-link"
            title="在新标签页打开调查工作台，定位该冻结证据"
            className="font-mono text-primary-600 underline decoration-dotted underline-offset-2 transition-colors hover:text-primary-500 dark:text-primary-300 dark:hover:text-primary-200"
        >
            {value}
            <ExternalLink size={10} className="ml-0.5 inline" aria-hidden />
        </a>
    );
};

const CitationTracebackPanel = ({
    taskId,
    reportId,
    citation,
    onClose,
    loaders = {
        snapshot: getInvestigationSnapshot,
        analysis: getInvestigationAnalysis,
        claims: listInvestigationAnalysisClaims,
    },
}) => {
    // identity 绑定 {taskId, reportId, citationId}：task 切换 / 报告切换 /
    // citation 切换后，旧的晚返回响应绝不写入当前面板（§23）。
    const identity = taskId && reportId && citation
        ? `${taskId}|${reportId}|${citation.citation_id}`
        : null;
    const [enrichment, setEnrichment] = useState(null);
    const [enrichmentError, setEnrichmentError] = useState(null);
    const identityRef = useRef(null);

    useEffect(() => {
        identityRef.current = identity;
        setEnrichment(null);
        setEnrichmentError(null);
        if (!identity || !citation) return undefined;

        let cancelled = false;
        const isCurrent = () => !cancelled && identityRef.current === identity;

        (async () => {
            try {
                const snapshot = await loaders.snapshot(taskId, citation.evidence_key);
                if (!isCurrent()) return;
                setEnrichment({ snapshot: snapshot || null, analysis: null, claim: null });

                // Original-only citation：绝不自动补 Analysis（§17）。
                if (!citation.analysis_id) return;

                const analysis = await loaders.analysis(taskId, citation.analysis_id);
                if (!isCurrent()) return;
                setEnrichment((prev) => ({ ...prev, analysis: analysis || null }));

                if (citation.claim_id) {
                    const claims = await loaders.claims(taskId, citation.analysis_id);
                    if (!isCurrent()) return;
                    // exact claim_id 过滤；同文不同 id 绝不合并（§18）。
                    const claim = (claims || []).find(
                        (item) => item.claim_id === citation.claim_id,
                    ) || null;
                    setEnrichment((prev) => ({ ...prev, claim }));
                }
            } catch (error) {
                if (isCurrent()) setEnrichmentError(error);
            }
        })();

        return () => { cancelled = true; };
        // loaders 真实实现是模块级函数（稳定引用）；identity 已含全部变化维度。
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [identity]);

    if (!citation) return null;

    const snapshot = enrichment?.snapshot || null;
    const analysis = enrichment?.analysis || null;
    const claim = enrichment?.claim || null;

    return (
        <aside
            aria-label="Citation provenance"
            data-testid="citation-traceback-panel"
            className="space-y-4 rounded-2xl border border-blue-200 bg-gradient-to-br from-white via-white to-blue-50/50 p-5 shadow-md ring-1 ring-blue-50 dark:border-blue-900/60 dark:from-slate-800 dark:via-slate-800 dark:to-blue-950/20 dark:ring-slate-700 md:p-6"
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                    <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"><FileSearch size={18} aria-hidden /></span>
                    <div>
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-300">证据溯源</p>
                        <h4 className="mt-0.5 text-base font-bold text-slate-900 dark:text-slate-100">引用溯源 · <span className="font-mono text-blue-700 dark:text-blue-300">{citation.citation_id}</span></h4>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={onClose}
                    aria-label="关闭溯源面板"
                    className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-blue-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-slate-700 dark:hover:text-slate-200"
                >
                    <X size={16} />
                </button>
            </div>

            <p className="border-b border-slate-100 pb-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                以下 identity 来自报告发布时冻结的 citation manifest，不随后续调查变化。
            </p>

            <Layer
                title="Evidence · Evidence Source"
                tone="border-blue-200 dark:border-blue-900/60 bg-blue-50/60 dark:bg-blue-900/20"
                testId="traceback-evidence-layer"
            >
                <p className="text-[11px] text-slate-600 dark:text-slate-300 break-all">
                    <span className="text-slate-400">evidence_key: </span>
                    <EvidenceKeyLink value={citation.evidence_key} taskId={taskId} reportId={reportId} citationId={citation.citation_id} />
                </p>
                <Field label="captured_at" value={citation.evidence_captured_at ?? '—'} />
                {snapshot && (
                    <>
                        <Field label="evidence_type" value={snapshot.evidence_type || '—'} />
                        {snapshot.evidence_type === 'android_artifact' && <>
                            <Field label="result_set_id" value={snapshot.payload?.result_set_id || '—'} />
                            <Field label="artifact/record" value={`${snapshot.payload?.artifact_kind || '—'} / ${snapshot.payload?.record_id ?? '—'}`} />
                            <p className="text-xs text-amber-800">AndroidAnalyzer 派生解析记录；原库主键、时间单位/时区和 WAL 定位以冻结来源字段为准，未知不代表已核实。</p>
                            <ExpandableDescription label="冻结来源精度与限制" value={JSON.stringify({
                                provenance: snapshot.payload?.provenance || {},
                                warnings: snapshot.payload?.warnings || [],
                                timestamp_unit: snapshot.payload?.timestamp_unit || null,
                                timestamp_timezone: snapshot.payload?.timestamp_timezone || null,
                            }, null, 2)} />
                        </>}
                        <ExpandableDescription label="证据简要分析" value={snapshot.payload?.initial_summary} />
                    </>
                )}
            </Layer>

            {citation.analysis_id ? (
                <Layer
                    title="Accepted Analysis · analyst-accepted derived finding"
                    tone="border-purple-200 dark:border-purple-900/60 bg-purple-50/60 dark:bg-purple-900/20"
                    testId="traceback-analysis-layer"
                >
                    <Field label="analysis_id" value={citation.analysis_id} />
                    <Field label="frozen version" value={citation.analysis_version ?? '—'} />
                    {analysis && (
                        <>
                            <Field label="status" value={analysis.status || '—'} />
                            <Field label="accepted by" value={analysis.decided_by || '—'} mono={false} />
                            <Field label="accepted at" value={analysis.decided_at || '—'} />
                            <Field label="grounding" value={analysis.grounding_status || '—'} />
                            <ExpandableDescription label="分析描述" value={analysis.description || analysis.summary} />
                        </>
                    )}
                </Layer>
            ) : (
                <p className="text-[11px] text-slate-500 dark:text-slate-400" data-testid="traceback-original-only">
                    Original Evidence only —— 本引用在报告发布时未绑定任何 Accepted Analysis。
                </p>
            )}

            {citation.claim_id && (
                <Layer
                    title="Claim · derived claim"
                    tone="border-amber-200 dark:border-amber-900/60 bg-amber-50/60 dark:bg-amber-900/20"
                    testId="traceback-claim-layer"
                >
                    <Field label="claim_id" value={citation.claim_id} />
                    <Field label="claim type" value={citation.claim_type ?? '—'} />
                    {claim && (
                        <>
                            <ExpandableDescription label="Claim 原文" value={claim.claim_text} />
                            <Field label="grounding" value={claim.grounding_status || '—'} />
                            <p className="text-[11px] text-slate-600 dark:text-slate-300 break-all">
                                <span className="text-slate-400">evidence_refs: </span>
                                {(claim.evidence_refs || []).length ? (
                                    claim.evidence_refs.map((ref, index) => (
                                        <span key={ref}>
                                            {index > 0 && <span className="text-slate-400">, </span>}
                                            <EvidenceKeyLink value={ref} taskId={taskId} reportId={reportId} citationId={citation.citation_id} allowTimeline={ref === citation.evidence_key} />
                                        </span>
                                    ))
                                ) : (
                                    <span>—</span>
                                )}
                            </p>
                        </>
                    )}
                </Layer>
            )}

            {enrichmentError && (
                <p className="text-[11px] text-amber-600 dark:text-amber-400" data-testid="traceback-enrichment-error">
                    当前调查库详细记录暂时不可读取（HTTP {enrichmentError?.status || '错误'}）；
                    上方 frozen identity 仍然有效，该引用不会被判定为不存在。
                </p>
            )}
        </aside>
    );
};

export default CitationTracebackPanel;
