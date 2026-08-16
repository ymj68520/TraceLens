// Investigation.jsx
// Investigation Workbench 三栏 Shell：
//   左栏 Evidence Workspace | 中栏 Timeline | Graph | 右栏 Analysis Workspace
//
// 单一 primary selection（{type, id}，claim 附 analysisId 上下文）由本页持有，
// 不引入 Redux Investigation store；task 来自全局 TaskSelector（searchParam）。
// C9b：Evidence Analysis 动作面——显式提交 Secondary Analysis、按 exact
// analysis_id 轮询、review_pending 后的显式 Analyst Review；一切 read-side
// 变化通过重新读取服务端状态获得（C7b needs_refresh / C8b selection），
// 本页从不前端 patch 业务结论。Event 创建/链接/refresh 属于 C9c。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import EvidenceListPanel from '../components/investigation/workbench/EvidenceListPanel';
import EventTimelinePanel from '../components/investigation/workbench/EventTimelinePanel';
import GraphTabPanel from '../components/investigation/workbench/GraphTabPanel';
import DetailPanel from '../components/investigation/workbench/DetailPanel';
import { useStaleResource } from '../hooks/useStaleResource';
import { useSecondaryAnalysisPolling } from '../hooks/useSecondaryAnalysisPolling';
import { useTranslation } from '../hooks/useTranslation';
import {
    createSecondaryAnalysis,
    getInvestigationAnalysis,
    getInvestigationEvent,
    getInvestigationSnapshot,
    listInvestigationAnalyses,
    listInvestigationAnalysisClaims,
    listInvestigationEventEvidence,
    listInvestigationEventRefreshes,
    listInvestigationEventVersions,
    listInvestigationEvents,
    listInvestigationEvidence,
    reviewSecondaryAnalysis,
} from '../services/investigationService';

const STATUS_BADGES = {
    accepted: { text: 'accepted', variant: 'green' },
    review_pending: { text: 'review_pending', variant: 'yellow' },
};

const graphNodeIdForSelection = (selection) => {
    if (!selection) return null;
    switch (selection.type) {
        case 'event': return `event:${selection.id}`;
        case 'evidence': return `evidence:${selection.id}`;
        case 'analysis': return `analysis:${selection.id}`;
        case 'claim': return `claim:${selection.id}`;
        default: return null;
    }
};

const Investigation = () => {
    const { t } = useTranslation();
    const [searchParams] = useSearchParams();
    const taskId = searchParams.get('taskId') || searchParams.get('task_id');

    // 单一 primary selection；task 切换时清空（含 Graph 节点选择）。
    const [selection, setSelection] = useState(null);
    const [middleTab, setMiddleTab] = useState('timeline');
    useEffect(() => {
        setSelection(null);
        setSubmission(null); // 旧 task 的轮询/提交上下文一并丢弃（§4 stale-safe）
    }, [taskId]);

    const selectedEvidenceKey = selection?.type === 'evidence' ? selection.id : null;
    const selectedEventId = selection?.type === 'event' ? selection.id : null;
    const selectedClaimId = selection?.type === 'claim' ? selection.id : null;
    // claim 选中时以其所属 analysis 为上下文加载 bundle。
    const activeAnalysisId = selection?.type === 'analysis'
        ? selection.id
        : (selection?.type === 'claim' ? selection.analysisId : null);

    const selectEvidence = useCallback((evidenceKey) => setSelection({ type: 'evidence', id: evidenceKey }), []);
    const selectEvent = useCallback((eventId) => setSelection({ type: 'event', id: eventId }), []);
    const selectAnalysis = useCallback((analysisId) => setSelection({ type: 'analysis', id: analysisId }), []);
    const selectClaim = useCallback((claimId, analysisId) => setSelection({ type: 'claim', id: claimId, analysisId }), []);

    // ── C9b：Secondary Analysis 提交 + exact-id 轮询 ──────────────────────────
    // submission 是轮询身份三元组 {taskId, evidenceKey, analysisId}；POST
    // admission 返回的 exact analysis_id 是唯一轮询对象，绝不回退 latest。
    const [submission, setSubmission] = useState(null);
    const submissionRef = useRef(null);
    submissionRef.current = submission;
    const [graphRefreshSignal, setGraphRefreshSignal] = useState(0);

    const polling = useSecondaryAnalysisPolling(taskId ? submission : null);

    // Graph 节点点击 → 统一 Workbench selection（§8：四类 overlay 命名空间）。
    const handleGraphNodeClick = useCallback((node) => {
        if (!node || node.source !== 'investigation') return;
        const id = String(node.id ?? '');
        if (id.startsWith('event:')) selectEvent(id.slice('event:'.length));
        else if (id.startsWith('evidence:')) selectEvidence(id.slice('evidence:'.length));
        else if (id.startsWith('analysis:')) selectAnalysis(id.slice('analysis:'.length));
        else if (id.startsWith('claim:')) {
            selectClaim(id.slice('claim:'.length), node.provenance?.analysis_id);
        }
    }, [selectEvent, selectEvidence, selectAnalysis, selectClaim]);

    // ── 列表（左栏 / 中栏 Timeline） ───────────────────────────────────────────
    const evidenceList = useStaleResource(
        () => listInvestigationEvidence(taskId),
        taskId || null,
    );
    const eventList = useStaleResource(
        () => listInvestigationEvents(taskId),
        taskId || null,
    );

    // ── Event bundle：当前 narrative + 版本 + authoritative evidence + refresh ──
    const eventBundleKey = taskId && selectedEventId ? `${taskId}|${selectedEventId}` : null;
    const eventBundle = useStaleResource(async () => {
        const [event, versions, links, refreshes] = await Promise.all([
            getInvestigationEvent(taskId, selectedEventId),
            listInvestigationEventVersions(taskId, selectedEventId),
            listInvestigationEventEvidence(taskId, selectedEventId),
            listInvestigationEventRefreshes(taskId, selectedEventId),
        ]);
        return { event, versions, links, refreshes };
    }, eventBundleKey);

    // ── Evidence bundle：Snapshot（Initial Analysis 唯一来源）+ 全部版本 ────────
    const evidenceBundleKey = taskId && selectedEvidenceKey ? `${taskId}|${selectedEvidenceKey}` : null;
    const evidenceBundle = useStaleResource(async () => {
        const [snapshot, analyses] = await Promise.all([
            getInvestigationSnapshot(taskId, selectedEvidenceKey)
                .catch((snapshotError) => {
                    if (snapshotError?.status === 404) return null; // 未捕获 ≠ 错误
                    throw snapshotError;
                }),
            listInvestigationAnalyses(taskId, selectedEvidenceKey),
        ]);
        return { snapshot, analyses };
    }, evidenceBundleKey);

    // ── Analysis bundle：exact analysis + exact 持久化 claims ──────────────────
    const analysisBundleKey = taskId && activeAnalysisId ? `${taskId}|${activeAnalysisId}` : null;
    const analysisBundle = useStaleResource(async () => {
        const [analysis, claimsResponse] = await Promise.all([
            getInvestigationAnalysis(taskId, activeAnalysisId),
            listInvestigationAnalysisClaims(taskId, activeAnalysisId),
        ]);
        return { analysis, claims: claimsResponse?.claims ?? [] };
    }, analysisBundleKey);

    const selectedClaim = useMemo(
        () => (analysisBundle.data?.claims || []).find((claim) => claim.claim_id === selectedClaimId) || null,
        [analysisBundle.data, selectedClaimId],
    );

    // ── C9b mutation 面 ────────────────────────────────────────────────────────

    const handleSubmitAnalysis = useCallback(async (payload) => {
        const created = await createSecondaryAnalysis(taskId, payload.evidence_key, {
            analystNote: payload.analyst_note,
            caseContext: payload.case_context,
            relatedEvidence: payload.related_evidence,
        });
        if (!created?.analysis_id) {
            throw new Error('admission response missing analysis_id');
        }
        const next = {
            taskId,
            evidenceKey: payload.evidence_key,
            analysisId: created.analysis_id,
        };
        setSubmission(next);
        return created;
    }, [taskId]);

    const handleReviewAnalysis = useCallback(async (analysisId, decision, { reviewer, reason }) => {
        const updated = await reviewSecondaryAnalysis(taskId, analysisId, {
            decision,
            reviewer,
            reason,
        });
        // §9/§10：决策后统一失效重读——exact Analysis、Evidence 版本列表、
        // accepted-first 选择徽章、Event needs_refresh（C7b 服务端传播）、
        // Graph overlay confirmed（C8b 服务端 selection）全部以服务端为准，
        // 前端不做任何本地业务状态 patch。
        analysisBundle.refresh();
        evidenceBundle.refresh();
        evidenceList.refresh();
        eventList.refresh();
        setGraphRefreshSignal((signal) => signal + 1);
        return updated;
    }, [taskId, analysisBundle, evidenceBundle, evidenceList, eventList]);

    // 轮询离开 queued/running（review_pending 或 terminal）时：重读相关
    // read-side，且仅在用户仍停留在同一 Evidence 时自动选中这次新 Analysis
    // （§15）。用户已切走则不打扰当前工作区——晚到的完成不切换右栏（§4）。
    const autoSelectedRef = useRef(null);
    const selectionRef = useRef(null);
    selectionRef.current = selection;
    const refreshEvidenceList = evidenceList.refresh;
    const refreshEvidenceBundle = evidenceBundle.refresh;
    useEffect(() => {
        const analysis = polling.analysis;
        const current = submissionRef.current;
        if (!analysis || !current) return;
        if (analysis.status === 'queued' || analysis.status === 'running') return;
        if (autoSelectedRef.current === analysis.analysis_id) return;
        autoSelectedRef.current = analysis.analysis_id;

        refreshEvidenceList();
        refreshEvidenceBundle();
        setGraphRefreshSignal((signal) => signal + 1);

        const stillOnEvidence = selectionRef.current?.type === 'evidence'
            && selectionRef.current.id === current.evidenceKey;
        if (stillOnEvidence) {
            selectAnalysis(analysis.analysis_id);
        }
    }, [polling.analysis, refreshEvidenceList, refreshEvidenceBundle, selectAnalysis]);

    // 该 Evidence 上有本页发起的 submission 仍在排队/执行时，提交按钮保持
    // disabled（§13 防误双击；后端 versioning 契约不被前端改写）。
    const submitBusyEvidenceKey = submission && submission.taskId === taskId && polling.active
        ? submission.evidenceKey
        : null;
    const evidenceOptions = useMemo(
        () => (evidenceList.data || []).map((row) => row.evidence_key),
        [evidenceList.data],
    );

    // 左栏：选中 Event 时显示其 authoritative evidence；否则显示任务全量 evidence。
    const statusByEvidenceKey = useMemo(() => {
        const map = {};
        for (const row of evidenceList.data || []) {
            const badge = STATUS_BADGES[row.selected_analysis?.review_state];
            if (badge) map[row.evidence_key] = badge;
        }
        return map;
    }, [evidenceList.data]);

    const evidenceItems = useMemo(() => {
        if (selectedEventId && eventBundle.data) {
            return (eventBundle.data.links || []).map((link) => {
                const badge = statusByEvidenceKey[link.evidence_key];
                return {
                    key: link.evidence_key,
                    sublabel: `${t('investigation_workbench.linked_by')}: ${link.linked_by || '-'} · ${link.linked_at || ''}`,
                    badgeText: badge?.text,
                    badgeVariant: badge?.variant,
                };
            });
        }
        return (evidenceList.data || []).map((row) => {
            const badge = statusByEvidenceKey[row.evidence_key];
            return {
                key: row.evidence_key,
                sublabel: row.evidence_type,
                badgeText: badge?.text,
                badgeVariant: badge?.variant,
            };
        });
    }, [selectedEventId, eventBundle.data, evidenceList.data, statusByEvidenceKey, t]);

    // 右栏数据按 selection 类型路由。
    const detail = selection?.type === 'event' ? eventBundle
        : selection?.type === 'evidence' ? evidenceBundle
            : analysisBundle;

    const needsRefreshCount = useMemo(
        () => (eventList.data || []).filter((event) => event.needs_refresh).length,
        [eventList.data],
    );

    const tabs = [
        { id: 'timeline', label: t('investigation_workbench.tab_timeline') },
        { id: 'graph', label: t('investigation_workbench.tab_graph') },
    ];

    return (
        <div className="flex flex-col gap-3" style={{ height: 'calc(100vh - 120px)', minHeight: 560 }}>
            {/* header */}
            <div className="flex flex-wrap items-center justify-between gap-2 shrink-0">
                <div>
                    <h1 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight">
                        {t('investigation_workbench.title')}
                    </h1>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                        {t('investigation_workbench.subtitle')}
                    </p>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                    <span data-testid="evidence-count">
                        {t('investigation_workbench.evidence_count')}: {(evidenceList.data || []).length}
                    </span>
                    <span data-testid="event-count">
                        {t('investigation_workbench.event_count')}: {(eventList.data || []).length}
                    </span>
                    {needsRefreshCount > 0 && (
                        <span data-testid="needs-refresh-count" className="px-2 py-0.5 rounded-lg bg-amber-100/70 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300">
                            {t('investigation_workbench.needs_refresh')}: {needsRefreshCount}
                        </span>
                    )}
                </div>
            </div>

            {!taskId && (
                <div className="flex items-center justify-center py-6 rounded-2xl glass text-sm text-slate-400 dark:text-slate-500" data-testid="no-task">
                    {t('investigation_graph.no_task')}
                </div>
            )}

            {/* three columns */}
            {taskId && (
                <div className="flex flex-col lg:flex-row gap-3 flex-1 min-h-0">
                    {/* 左栏：Evidence Workspace */}
                    <aside className="w-full lg:w-80 shrink-0 glass rounded-2xl overflow-hidden min-h-[220px] lg:min-h-0">
                        <EvidenceListPanel
                            title={selectedEventId
                                ? t('investigation_workbench.event_evidence_title')
                                : t('investigation_workbench.evidence_title')}
                            items={selectedEventId && !eventBundle.data && eventBundle.loading ? [] : evidenceItems}
                            selectedKey={selectedEvidenceKey}
                            onSelect={selectEvidence}
                            loading={selectedEventId ? eventBundle.loading : evidenceList.loading}
                            error={selectedEventId ? eventBundle.error : evidenceList.error}
                            onRetry={selectedEventId ? eventBundle.refresh : evidenceList.refresh}
                        />
                    </aside>

                    {/* 中栏：Timeline | Graph */}
                    <section className="flex-1 min-w-0 glass rounded-2xl overflow-hidden flex flex-col">
                        <div className="flex items-center gap-1 px-2 pt-2 shrink-0" role="tablist">
                            {tabs.map((tab) => (
                                <button
                                    key={tab.id}
                                    type="button"
                                    role="tab"
                                    aria-selected={middleTab === tab.id}
                                    data-testid={`tab-${tab.id}`}
                                    onClick={() => setMiddleTab(tab.id)}
                                    className={`px-3 py-1.5 text-xs font-medium rounded-t-lg transition-colors ${
                                        middleTab === tab.id
                                            ? 'bg-slate-100/80 dark:bg-slate-800/80 text-slate-900 dark:text-slate-100'
                                            : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
                                    }`}
                                >
                                    {tab.label}
                                </button>
                            ))}
                        </div>
                        <div className="flex-1 min-h-0">
                            {middleTab === 'timeline' ? (
                                <EventTimelinePanel
                                    events={eventList.data || []}
                                    selectedEventId={selectedEventId}
                                    onSelectEvent={selectEvent}
                                    loading={eventList.loading}
                                    error={eventList.error}
                                    onRetry={eventList.refresh}
                                />
                            ) : (
                                <GraphTabPanel
                                    taskId={taskId}
                                    selectedNodeId={graphNodeIdForSelection(selection)}
                                    onNodeClick={handleGraphNodeClick}
                                    refreshSignal={graphRefreshSignal}
                                />
                            )}
                        </div>
                    </section>

                    {/* 右栏：Analysis Workspace */}
                    <aside className="w-full lg:w-96 shrink-0 glass rounded-2xl overflow-hidden min-h-[260px] lg:min-h-0">
                        <DetailPanel
                            selection={selection}
                            loading={detail?.loading && !detail?.data}
                            error={detail?.error}
                            eventBundle={eventBundle.data}
                            evidenceBundle={evidenceBundle.data}
                            analysisBundle={analysisBundle.data}
                            claim={selectedClaim}
                            onSelectEvidence={selectEvidence}
                            onSelectAnalysis={selectAnalysis}
                            onSelectClaim={selectClaim}
                            selectedAnalysisId={activeAnalysisId}
                            selectedClaimId={selectedClaimId}
                            evidenceOptions={evidenceOptions}
                            submitBusy={submitBusyEvidenceKey !== null && submitBusyEvidenceKey === selectedEvidenceKey}
                            onSubmitAnalysis={handleSubmitAnalysis}
                            onSubmitReview={handleReviewAnalysis}
                        />
                    </aside>
                </div>
            )}
        </div>
    );
};

export default Investigation;
