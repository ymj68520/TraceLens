// CitationTracebackPanel.jsx
// R2d citation 溯源面板：persisted citation manifest entry 是唯一
// authoritative identity；当前 Investigation strict 读只是可选增强。
// 三层来源显式区分：Evidence = Evidence Source；Accepted Analysis =
// analyst-accepted derived finding；Claim = derived claim。绝不显示
// Graph Entity / Event / Timeline Cluster 作为来源（§24），也绝不因
// current 库变化而改写 frozen identity（§16）。
import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import {
    getInvestigationAnalysis,
    getInvestigationSnapshot,
    listInvestigationAnalysisClaims,
} from '../../services/investigationService';

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
            className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 space-y-3"
        >
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-slate-700 dark:text-slate-200">
                    引用溯源 · {citation.citation_id}
                </h4>
                <button
                    type="button"
                    onClick={onClose}
                    aria-label="关闭溯源面板"
                    className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                    <X size={14} />
                </button>
            </div>

            <p className="text-[10px] text-slate-400">
                以下 identity 来自报告发布时冻结的 citation manifest，不随后续调查变化。
            </p>

            <Layer
                title="Evidence · Evidence Source"
                tone="border-blue-200 dark:border-blue-900/60 bg-blue-50/60 dark:bg-blue-900/20"
                testId="traceback-evidence-layer"
            >
                <Field label="evidence_key" value={citation.evidence_key} />
                <Field label="captured_at" value={citation.evidence_captured_at ?? '—'} />
                {snapshot && (
                    <>
                        <Field label="evidence_type" value={snapshot.evidence_type || '—'} />
                        <Field
                            label="initial analysis"
                            value={snapshot.payload?.initial_summary || '—'}
                            mono={false}
                        />
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
                            <Field label="description" value={analysis.description || analysis.summary || '—'} mono={false} />
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
                            <Field label="claim text" value={claim.claim_text || '—'} mono={false} />
                            <Field label="grounding" value={claim.grounding_status || '—'} />
                            <Field
                                label="evidence_refs"
                                value={(claim.evidence_refs || []).join(', ') || '—'}
                            />
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
