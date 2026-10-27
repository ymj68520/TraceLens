import { stripFileKeyPrefix } from '../../utils/evidenceKey';
// NarrativeReportView.jsx
// R2d narrative 报告阅读视图：只消费 persisted narrative version 的
// strict 读响应（sections + persisted citation manifest + audit 元数据）。
// 历史 V1 的内容与其 citation identity 完全来自发布时冻结的 manifest，
// 之后 Investigation 里的 rebind/新 accepted/claim 变化都不会改变这里
// 显示的内容（§12/§16）。citation 点击 = exact citation_id → manifest
// entry 查表，绝不在正文里做 regex/Markdown token 推导（§13）。
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, FileSearch, FileText } from 'lucide-react';
import CitationTracebackPanel from './CitationTracebackPanel';
import { getInvestigationSnapshot } from '../../services/investigationService';
import { investigationEvidenceUrl } from '../../utils/evidenceKey';
import { FIELD_AUTH_ENABLED } from '../../config/runtime';
import { Link } from 'react-router-dom';
import { placeNarrativeCitations } from './narrativeCitationPlacement';
import EvidenceClassification, { ClassificationBadges, ClassificationDetails } from './EvidenceClassification';
import { priorityStyle } from './evidenceClassificationStyles';
import StageAnalysisPanel, { StageSourcePanel } from './StageAnalysisPanel';
import ReportOrganizationPanel from './ReportOrganizationPanel';
import DeliveryQualityPanel from './DeliveryQualityPanel';
import { forensicError } from '../../utils/forensicLabels';
import { explicitNarrativeParts } from './narrativeCitationPlacement';

function previewText(value, limit) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function CitationMarker({ taskId, reportId, citationId, citation, classification, inline, focused = false, preview, onOpen, onPreview }) {
    const [hovered, setHovered] = useState(false);
    const [popupPlacement, setPopupPlacement] = useState({ left: 0, below: false });
    const markerRef = useRef(null);
    const isAndroid = (citation?.evidence_key?.startsWith('android_artifact:') || citation?.evidence_key?.startsWith('windows_artifact:'));
    const filename = isAndroid ? `${citation?.evidence_key?.startsWith('windows_artifact:') ? 'Windows记录' : 'Android 工件'} ${citation?.evidence_key?.split(':').slice(-2).join(' #')}`
        : stripFileKeyPrefix(citation?.evidence_key)?.split(/[\\/]/).pop() || citationId;
    const evidenceUrl = investigationEvidenceUrl(taskId, citation?.evidence_key, { reportId, citationId });
    const showPreview = () => {
        const bounds = markerRef.current?.getBoundingClientRect();
        if (bounds) {
            const width = Math.min(320, window.innerWidth * 0.8);
            const left = Math.max(12, Math.min(bounds.left, window.innerWidth - width - 12));
            const below = window.innerWidth < 640
                ? bounds.top < 470 && window.innerHeight - bounds.bottom > 340
                : bounds.top < 220;
            setPopupPlacement({ left: left - bounds.left, below });
        }
        setHovered(true);
        onPreview(citationId);
    };
    return (
        <span
            ref={markerRef}
            className={`relative inline-block ${inline ? 'ml-1 align-super' : ''}`}
            onMouseEnter={showPreview}
            onMouseLeave={() => setHovered(false)}
            onFocus={showPreview}
            onBlur={() => setHovered(false)}
        >
            <button
                type="button"
                id={`report-citation-${citationId}`}
                data-testid={`citation-chip-${citationId}`}
                onClick={() => onOpen(citationId)}
                data-priority={classification?.priority || 'unassessed'}
                title={classification ? priorityStyle(classification.priority).label : '历史未分类'}
                className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono font-semibold transition-all hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${priorityStyle(classification?.priority).tone} ${focused ? 'ring-2 ring-amber-400 ring-offset-2 dark:ring-offset-slate-900' : ''} ${inline ? 'text-[10px] leading-none' : 'text-[11px]'}`}
                aria-label={`查看引用 ${citationId} 的证据`}
            >
                {citationId}{classification && <span>{priorityStyle(classification.priority).label}</span>}
            </button>
            {hovered && (
                <span role="tooltip" data-testid={`citation-tooltip-${citationId}`} style={{ left: popupPlacement.left }} className={`absolute z-40 block w-80 max-w-[80vw] overflow-hidden rounded-2xl border border-slate-200 bg-white text-left text-xs normal-case shadow-[0_16px_40px_rgba(15,23,42,0.18)] ring-1 ring-white/70 dark:border-slate-600 dark:bg-slate-800 dark:ring-slate-700 ${popupPlacement.below ? 'top-full mt-2' : 'bottom-full mb-2'}`}>
                    <span className="flex items-start gap-2.5 border-b border-slate-100 bg-gradient-to-r from-blue-50 to-indigo-50/40 px-3.5 py-3 dark:border-slate-700 dark:from-blue-950/50 dark:to-slate-800">
                        <span className="inline-flex shrink-0 items-center rounded-md bg-blue-600 px-1.5 py-0.5 font-mono font-bold text-white">{citationId}</span>
                        <span className="min-w-0 break-all font-semibold leading-5 text-slate-800 dark:text-slate-100">{preview?.title || filename}</span>
                    </span>
                    {classification && <span className="block px-3.5 pt-3"><ClassificationBadges classification={classification} compact /></span>}
                    {preview?.loading ? <span className="block px-3.5 py-3 text-slate-500">正在读取证据简介…</span> : preview?.error ? <span className="block px-3.5 py-3 text-amber-700 dark:text-amber-300">证据简介暂不可用，点击仍可查看引用溯源。</span> : (
                        <>
                            <span className="block px-3.5 pt-3 font-semibold text-slate-500 dark:text-slate-400">证据简述</span>
                            <span className="block px-3.5 pt-1 leading-5 text-slate-700 dark:text-slate-200">{preview?.summary || '暂无摘要'}</span>
                            {preview?.description && <><span className="block px-3.5 pt-3 font-semibold text-slate-500 dark:text-slate-400">更多描述</span><span className="block px-3.5 pt-1 leading-5 text-slate-600 dark:text-slate-300">{preview.description}</span></>}
                        </>
                    )}
                    <span className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-3.5 py-2.5 font-medium text-blue-700 dark:border-slate-700 dark:text-blue-300">
                        <span className="inline-flex items-center gap-1">点击查看完整证据溯源 <ArrowUpRight size={13} aria-hidden /></span>
                        {evidenceUrl && (FIELD_AUTH_ENABLED
                            ? <Link to={evidenceUrl} data-testid={`citation-timeline-link-${citationId}`} className="rounded-md border border-blue-200 px-1.5 py-0.5 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-blue-800 dark:hover:bg-blue-900/40">{isAndroid ? '查看冻结工件 ↗' : '定位时间线 ↗'}</Link>
                            : <a href={evidenceUrl} target="_blank" rel="noopener noreferrer" data-testid={`citation-timeline-link-${citationId}`} className="rounded-md border border-blue-200 px-1.5 py-0.5 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-blue-800 dark:hover:bg-blue-900/40">{isAndroid ? '查看冻结工件 ↗' : '定位时间线 ↗'}</a>)}
                    </span>
                </span>
            )}
        </span>
    );
}

const NarrativeReportView = ({
    taskId,
    reportId,
    fetchNarrative,
    focusCitationId = null,
    fetchSnapshot = getInvestigationSnapshot,
    TracebackPanel = CitationTracebackPanel,
}) => {
    // identity 绑定 {taskId, reportId}：切换版本/任务后旧响应不写入。
    const identity = taskId && reportId ? `${taskId}|${reportId}` : null;
    const [report, setReport] = useState(null);
    const [error, setError] = useState(null);
    const [openCitationId, setOpenCitationId] = useState(null);
    const [citationPreviews, setCitationPreviews] = useState({});
    const identityRef = useRef(null);
    const pendingPreviewsRef = useRef(new Set());
    const tracebackRef = useRef(null);
    const focusedCitationRef = useRef(null);

    useEffect(() => {
        identityRef.current = identity;
        setReport(null);
        setError(null);
        setOpenCitationId(null);
        setCitationPreviews({});
        pendingPreviewsRef.current.clear();
        if (!identity) return undefined;
        let cancelled = false;

        fetchNarrative(taskId, reportId)
            .then((body) => {
                if (cancelled || identityRef.current !== identity) return;
                setReport(body);
            })
            .catch((nextError) => {
                if (cancelled || identityRef.current !== identity) return;
                setError(nextError);
            });

        return () => { cancelled = true; };
    }, [identity, taskId, reportId, fetchNarrative]);

    const citationsById = useMemo(() => new Map((report?.citations || []).map((entry) => [entry.citation_id, entry])), [report]);
    const classificationsByKey = useMemo(() => new Map((report?.evidence_classifications?.items || []).map(entry => [entry.evidence_key, entry])), [report]);
    const stageMaterialsByKey = useMemo(() => new Map((report?.stage_analysis?.materials || []).map(entry => [entry.evidence_key, entry])), [report]);
    const openEntry = openCitationId ? citationsById.get(openCitationId) || null : null;

    useEffect(() => {
        if (!report || !focusCitationId || !citationsById.has(focusCitationId)) return undefined;
        const focusKey = `${identity}|${focusCitationId}`;
        if (focusedCitationRef.current === focusKey) return undefined;
        focusedCitationRef.current = focusKey;
        const frame = requestAnimationFrame(() => {
            const marker = document.getElementById(`report-citation-${focusCitationId}`);
            const collapsed = marker?.closest('details');
            if (collapsed) collapsed.open = true;
            marker?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
        });
        return () => cancelAnimationFrame(frame);
    }, [report, focusCitationId, identity, citationsById]);

    const openCitation = (citationId) => setOpenCitationId(
        (previous) => (previous === citationId ? null : citationId),
    );
    const loadPreview = (citationId) => {
        const citation = citationsById.get(citationId);
        if (!citation || citationPreviews[citationId] || pendingPreviewsRef.current.has(citationId)) return;
        if (report?.stage_analysis) {
            const material = stageMaterialsByKey.get(citation.evidence_key);
            setCitationPreviews(previous => ({ ...previous, [citationId]: {
                title: citation.evidence_key,
                summary: previewText(material?.text, 130) || '本轮材料不可读，未回退使用历史 AI 摘要。',
                description: material?.kind === 'machine_visual' ? '本轮机器视觉观察，非原文或OCR。' : '本轮冻结材料片段，点击查看来源与读取范围。',
            } }));
            return;
        }
        pendingPreviewsRef.current.add(citationId);
        setCitationPreviews((previous) => ({ ...previous, [citationId]: { loading: true } }));
        const requestedIdentity = identity;
        fetchSnapshot(taskId, citation.evidence_key)
            .then((snapshot) => {
                if (identityRef.current !== requestedIdentity) return;
                const payload = snapshot?.payload || snapshot?.snapshot?.payload || {};
                if (snapshot?.evidence_type === 'windows_artifact' || payload.evidence_type === 'windows_artifact') {
                    setCitationPreviews(previous => ({ ...previous, [citationId]: {
                        title: `Windows 来源记录 #${payload.record_id ?? '—'}`,
                        summary: payload.record_fields?.observation || '冻结来源记录',
                        description: '活动含义、时间与回收状态以冻结原始字段为准。',
                    }}));
                    return;
                }
                if (snapshot?.evidence_type === 'android_artifact' || payload.evidence_type === 'android_artifact') {
                    const fields = payload.record_fields || {};
                    const kind = payload.artifact_kind || 'unknown';
                    const brief = kind === 'sms' ? fields.body : kind === 'contacts' ? fields.display_name
                        : kind === 'apps' ? fields.package_name : kind === 'wifi' ? fields.ssid : null;
                    setCitationPreviews((previous) => ({ ...previous, [citationId]: {
                        title: `Android 工件 ${kind} #${payload.record_id ?? '—'}`,
                        summary: previewText(brief, 130) || '冻结派生解析记录',
                        description: `来源精度：${payload.provenance?.input_file || 'unknown'}；原库主键/WAL 未逐条核实。`,
                    } }));
                    return;
                }
                const fullSummary = String(payload.initial_summary || payload.initial_description || '').replace(/\s+/g, ' ').trim();
                const fullDescription = String(payload.initial_description || '').replace(/\s+/g, ' ').trim();
                const moreDescription = fullDescription === fullSummary
                    ? fullDescription.slice(130).trim()
                    : fullDescription;
                setCitationPreviews((previous) => ({ ...previous, [citationId]: {
                    title: payload.name || (stripFileKeyPrefix(citation.evidence_key) || '').split(/[\\/]/).pop(),
                    summary: previewText(fullSummary, 130),
                    description: previewText(moreDescription, 190),
                } }));
            })
            .catch(() => {
                if (identityRef.current === requestedIdentity) {
                    setCitationPreviews((previous) => ({ ...previous, [citationId]: { error: true } }));
                }
            })
            .finally(() => pendingPreviewsRef.current.delete(citationId));
    };

    useEffect(() => {
        if (!openEntry) return undefined;
        const returnFocus = document.activeElement;
        const frame = requestAnimationFrame(() => tracebackRef.current?.focus());
        const onDialogKeyDown = (event) => {
            if (event.key === 'Escape') setOpenCitationId(null);
            if (event.key !== 'Tab') return;
            const dialog = tracebackRef.current;
            const focusable = [...(dialog?.querySelectorAll(
                'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
            ) || [])].filter(element => element.getClientRects().length > 0);
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            const active = document.activeElement;
            if (!first) {
                event.preventDefault();
                dialog?.focus();
            } else if (!dialog.contains(active) || active === dialog
                || (event.shiftKey ? active === first : active === last)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            }
        };
        window.addEventListener('keydown', onDialogKeyDown);
        return () => {
            cancelAnimationFrame(frame);
            window.removeEventListener('keydown', onDialogKeyDown);
            if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
        };
    }, [openEntry]);

    const openMaterial = materialId => {
        const material=report?.stage_analysis?.materials.find(m => m.material_id===materialId);
        const citation=report?.citations.find(c => c.evidence_key===material?.evidence_key);
        if (citation) setOpenCitationId(citation.citation_id);
    };
    const explicitProse = (section,prefix) => explicitNarrativeParts(section.content,section.citation_ids,citationsById).map((part,index) => part.citationId
        ? <CitationMarker key={`${prefix}-${index}`} taskId={taskId} reportId={reportId} citationId={part.citationId}
            citation={citationsById.get(part.citationId)} classification={classificationsByKey.get(citationsById.get(part.citationId)?.evidence_key)}
            inline focused={focusCitationId===part.citationId} preview={citationPreviews[part.citationId]} onOpen={openCitation} onPreview={loadPreview} />
        : part.text);

    return (
        <div className="space-y-4 [overflow-wrap:anywhere]" data-testid="narrative-report-view">
            {error && (
                <div role="alert" className="rounded-2xl border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-900/20 p-4 text-sm text-rose-600 dark:text-rose-400" data-testid="narrative-report-error">
                    叙事报告暂时不可读取（HTTP {error?.status || '错误'}）：
                    {forensicError(error, '报告记录暂不可用，请核对版本与完整性。')}
                </div>
            )}
            {!report && !error && (
                <p className="text-sm text-slate-400" data-testid="narrative-report-loading">正在读取叙事报告…</p>
            )}
            {report && (
                <>
                    <header className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-white via-white to-indigo-50/50 p-5 shadow-sm dark:border-indigo-900/50 dark:from-slate-800 dark:via-slate-800 dark:to-indigo-950/20 md:p-6">
                        <div className="flex items-start gap-3">
                            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-100 text-indigo-600 dark:bg-indigo-900/50 dark:text-indigo-300"><FileText size={20} aria-hidden /></span>
                            <div className="min-w-0 space-y-1.5">
                                <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-indigo-600 dark:text-indigo-300">{report.stage_analysis
                                    ? report.stage_analysis.analysis_mode === 'evidence_only' ? '首次研判 · 材料自主' : '二次研判 · 案情对照'
                                    : '最终报告 · 证据叙事'}</p>
                                <h2 className="text-xl font-bold leading-snug text-slate-900 dark:text-white md:text-2xl">{report.title}</h2>
                                <p className="text-xs text-slate-500 dark:text-slate-400">版本 v{report.version} · 生成时间 {report.created_at} · {report.sections?.length || 0} 个章节</p>
                            </div>
                        </div>
                        {/* 审计字段按需展开，正文仍只使用冻结的报告版本。 */}
                        <details className="group mt-4 border-t border-indigo-100 pt-3 dark:border-slate-700">
                            <summary className="flex w-fit cursor-pointer items-center gap-1 text-xs font-medium text-slate-500 hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-300">查看版本审计信息 <ChevronDown size={13} className="transition-transform group-open:rotate-180" aria-hidden /></summary>
                            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-slate-400" data-testid="narrative-audit-metadata">
                                <span>生成记录 {report.generation_id}</span>
                                <span>提示版本 {report.prompt_version}</span>
                                <span>模型 {report.model}</span>
                                <span>输入摘要 {report.input_hash?.slice(0, 16)}…</span>
                            </div>
                        </details>
                    </header>

                    <DeliveryQualityPanel quality={report.quality} />
                    <ReportOrganizationPanel organization={report.organization} onOpenMaterial={openMaterial} />
                    <EvidenceClassification key={reportId} classification={report.evidence_classifications}
                        citations={report.citations} taskId={taskId} reportId={reportId} onOpenCitation={openCitation} />
                    {!report.organization && <>
                    <StageAnalysisPanel stage={report.stage_analysis} taskId={taskId} classifications={report.evidence_classifications}
                        onOpenMaterial={materialId => {
                            const material = report.stage_analysis?.materials.find(m => m.material_id === materialId);
                            const citation = report.citations.find(c => c.evidence_key === material?.evidence_key);
                            if (citation) setOpenCitationId(citation.citation_id);
                        }} />
                    </>}

                    <article className="space-y-5" data-testid="narrative-sections">
                        {(report.sections || []).map((section, index) => {
                            const { placements, unresolved } = report.organization ? { placements: [], unresolved: [] } : placeNarrativeCitations(section.content, section.citation_ids, citationsById);
                            const prose = [];
                            let cursor = 0;
                            placements.forEach(({ end, citationId }) => {
                                prose.push(section.content.slice(cursor, end));
                                prose.push(<CitationMarker key={citationId} taskId={taskId} reportId={reportId} citationId={citationId} citation={citationsById.get(citationId)} classification={classificationsByKey.get(citationsById.get(citationId)?.evidence_key)} inline focused={focusCitationId === citationId} preview={citationPreviews[citationId]} onOpen={openCitation} onPreview={loadPreview} />);
                                cursor = end;
                            });
                            prose.push(section.content.slice(cursor));
                            if (report.organization) { prose.length=0; prose.push(...explicitProse(section,`body-${index}`)); }
                            return (
                                <section key={`${section.heading}-${index}`} className="rounded-2xl border border-slate-200 bg-white px-5 py-6 shadow-sm dark:border-slate-700 dark:bg-slate-800 md:px-7 md:py-7" data-testid="narrative-section">
                                    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4 dark:border-slate-700">
                                        <div className="flex min-w-0 items-center gap-3">
                                            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 font-mono text-xs font-bold text-indigo-600 dark:bg-indigo-900/40 dark:text-indigo-300">{String(index + 1).padStart(2, '0')}</span>
                                            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{section.heading}</h3>
                                        </div>
                                        <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"><FileSearch size={12} aria-hidden />{section.citation_ids?.length || 0} 条证据引用</span>
                                    </div>
                                    <p className="whitespace-pre-wrap break-words text-[15px] leading-8 text-slate-700 dark:text-slate-300">{prose}</p>
                                    {unresolved.length > 0 && (
                                        <details className="group mt-6 border-t border-dashed border-slate-200 pt-4 dark:border-slate-700">
                                            <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-blue-700 dark:text-slate-400 dark:hover:text-blue-300"><ChevronDown size={14} className="transition-transform group-open:rotate-180" aria-hidden />另有 {unresolved.length} 条章节级引用（未推测具体句子）</summary>
                                            <div className="mt-3 flex flex-wrap gap-1.5">
                                                {unresolved.map((citationId) => <CitationMarker key={citationId} taskId={taskId} reportId={reportId} citationId={citationId} citation={citationsById.get(citationId)} classification={classificationsByKey.get(citationsById.get(citationId)?.evidence_key)} focused={focusCitationId === citationId} preview={citationPreviews[citationId]} onOpen={openCitation} onPreview={loadPreview} />)}
                                            </div>
                                        </details>
                                    )}
                                </section>
                            );
                        })}
                    </article>

                    {report.organization && <details className="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800" data-testid="narrative-appendices">
                        <summary className="cursor-pointer font-semibold">报告附录 · 材料覆盖、未决事项与来源审计</summary>
                        {(report.appendices || []).map((section,index) => <section key={index} className="mt-4">
                            <h3 className="font-semibold">{section.heading}</h3>
                            <p className="mt-2 whitespace-pre-wrap text-sm leading-7">{explicitProse(section,`appendix-${index}`)}</p>
                        </section>)}
                        <StageAnalysisPanel stage={report.stage_analysis} taskId={taskId} classifications={report.evidence_classifications} onOpenMaterial={openMaterial} />
                    </details>}

                    {openCitationId && !openEntry && (
                        <p className="text-xs text-amber-600 dark:text-amber-400" data-testid="citation-unknown-warning">
                            未知引用 ID：{openCitationId}。manifest 中不存在该引用，不做任何推测。
                        </p>
                    )}
                    {openEntry && (
                        <div className="fixed inset-0 z-[70] !m-0 flex justify-end" data-testid="citation-overlay">
                            <button type="button" className="absolute inset-0 bg-slate-950/35 backdrop-blur-[2px]" aria-label="关闭证据溯源" onClick={() => setOpenCitationId(null)} />
                            <div ref={tracebackRef} id={`citation-evidence-${openCitationId}`} role="dialog" aria-modal="true" aria-label={`引用 ${openCitationId} 的证据溯源`} tabIndex={-1} className="relative z-10 h-full w-full max-w-[540px] overflow-y-auto border-l border-blue-100 bg-slate-50 p-4 shadow-[-18px_0_45px_rgba(15,23,42,0.2)] outline-none dark:border-slate-700 dark:bg-slate-900 md:p-6" data-testid="citation-evidence-target">
                                {report.stage_analysis
                                    ? <StageSourcePanel material={stageMaterialsByKey.get(openEntry.evidence_key)} citationId={openCitationId}
                                        taskId={taskId} reportId={reportId} sourceSpans={(report.organization?.spans || []).filter(s => s.evidence_key===openEntry.evidence_key)} onClose={() => setOpenCitationId(null)} />
                                    : <TracebackPanel taskId={taskId} reportId={reportId} citation={openEntry} onClose={() => setOpenCitationId(null)} />}
                                <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800" aria-label="引用证据分类">
                                    <h4 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">报告生成时的证据分类</h4>
                                    <ClassificationDetails classification={classificationsByKey.get(openEntry.evidence_key)} questions={report.evidence_classifications?.questions} />
                                </section>
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

export default NarrativeReportView;
