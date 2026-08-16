// Investigation.jsx
// Investigation Workbench 三栏 Shell：
//   左栏 Evidence Workspace | 中栏 Timeline | Graph | 右栏 Analysis Workspace
//
// 单一 primary selection（{type, id}，claim 附 analysisId 上下文）由本页持有，
// 不引入 Redux Investigation store；task 来自全局 TaskSelector（searchParam）。
// C9b：Evidence Analysis 动作面——显式提交 Secondary Analysis、按 exact
// analysis_id 轮询、review_pending 后的显式 Analyst Review。
// C9c：Investigation Event 动作面——显式创建 Event、append-only Evidence
// link、显式 refresh admission + 按 exact refresh_id 轮询 history。一切
// read-side 变化通过重新读取服务端状态获得（C7b needs_refresh / C7c
// completion-time staleness / C8b selection），本页从不前端 patch 业务结论。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import EvidenceListPanel from '../components/investigation/workbench/EvidenceListPanel';
import EventTimelinePanel from '../components/investigation/workbench/EventTimelinePanel';
import GraphTabPanel from '../components/investigation/workbench/GraphTabPanel';
import DetailPanel from '../components/investigation/workbench/DetailPanel';
import CaptureEvidenceForm from '../components/investigation/workbench/CaptureEvidenceForm';
import { useStaleResource } from '../hooks/useStaleResource';
import { useSecondaryAnalysisPolling } from '../hooks/useSecondaryAnalysisPolling';
import { useEventRefreshPolling } from '../hooks/useEventRefreshPolling';
import { useTranslation } from '../hooks/useTranslation';
import { getLargestFiles } from '../services/forensicsService';
import {
    captureInvestigationSnapshot,
    createInvestigationEvent,
    createSecondaryAnalysis,
    getInvestigationAnalysis,
    getInvestigationEvent,
    getInvestigationSnapshot,
    linkInvestigationEventEvidence,
    listInvestigationAnalyses,
    listInvestigationAnalysisClaims,
    listInvestigationEventEvidence,
    listInvestigationEventRefreshes,
    listInvestigationEventVersions,
    listInvestigationEvents,
    listInvestigationEvidence,
    listReportEvidence,
    addReportEvidence,
    updateReportEvidence,
    reviewSecondaryAnalysis,
    startInvestigationEventRefresh,
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
    // 渲染期同步的 refs：mutation 晚返回时用它们判定"用户是否仍在原地"，
    // 绝不让晚到的成功劫持当前 selection（§20）。
    const selectionRef = useRef(null);
    selectionRef.current = selection;
    const taskIdRef = useRef(taskId);
    taskIdRef.current = taskId;
    const [middleTab, setMiddleTab] = useState('timeline');
    useEffect(() => {
        setSelection(null);
        setSubmission(null); // 旧 task 的轮询/提交上下文一并丢弃（§4 stale-safe）
        setRefreshSubmission(null);
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

    // ── C9c：Event refresh 提交 + exact refresh_id 轮询 ──────────────────────
    // refreshSubmission 是轮询身份三元组 {taskId, eventId, refreshId}；
    // admission 不等待 LLM，hook 轮询 refresh history 并按 exact
    // refresh_id 过滤（后端无 exact GET，绝不轮询 latest）。
    const [refreshSubmission, setRefreshSubmission] = useState(null);
    const refreshSubmissionRef = useRef(null);
    refreshSubmissionRef.current = refreshSubmission;

    const refreshPolling = useEventRefreshPolling(taskId ? refreshSubmission : null);

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
    // C10 §20：capture 候选来自任务真实文件列表（与 Files 页同一 API），
    // 不做自由文本输入；resolve/capture 的完整性边界在后端。
    const fileList = useStaleResource(
        () => getLargestFiles(taskId, 100),
        taskId || null,
    );
    const eventList = useStaleResource(
        () => listInvestigationEvents(taskId),
        taskId || null,
    );
    const reportEvidenceList = useStaleResource(
        () => listReportEvidence(taskId),
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

    // ── C9c mutation 面：createEvent / linkEventEvidence / startEventRefresh
    //    三类 mutation 分开持有 identity/loading/error/invalidation（§19）。──

    // C10 §20：capture 成功 → 重读 Evidence 列表 + Graph。capture 不改变
    // selection（用户链第一步；晚返回同样不劫持当前工作区）。
    const handleCaptureEvidence = useCallback(async (evidenceKey) => {
        const captured = await captureInvestigationSnapshot(taskId, evidenceKey);
        evidenceList.refresh();
        setGraphRefreshSignal((signal) => signal + 1);
        return captured;
    }, [taskId, evidenceList]);

    const handleAddReportEvidence = useCallback(async ({ evidenceKey, reportStatus, analysisId, addedBy }) => {
        const added = await addReportEvidence(taskId, evidenceKey, {
            reportStatus,
            analysisId,
            addedBy,
        });
        reportEvidenceList.refresh();
        return added;
    }, [taskId, reportEvidenceList]);

    const handleUpdateReportEvidence = useCallback(async ({ evidenceKey, reportStatus, analysisId, updatedBy }) => {
        const updated = await updateReportEvidence(taskId, evidenceKey, {
            reportStatus,
            analysisId,
            updatedBy,
        });
        reportEvidenceList.refresh();
        return updated;
    }, [taskId, reportEvidenceList]);

    // §1：创建成功 → 重新读取 Event list（不插入临时 row），且仅在用户
    // 仍停留在同一 task 时按 exact event_id 选中新建事件（§20 晚返回不劫持）。
    const handleCreateEvent = useCallback(async (payload) => {
        const created = await createInvestigationEvent(taskId, {
            title: payload.title,
            summary: payload.summary,
            createdBy: payload.created_by,
        });
        if (!created?.event_id) {
            throw new Error('admission response missing event_id');
        }
        const createdEventId = created.event_id;
        eventList.refresh();
        setGraphRefreshSignal((signal) => signal + 1);
        if (taskIdRef.current === taskId) {
            selectEvent(createdEventId);
        }
        return created;
    }, [taskId, eventList, selectEvent]);

    // §6：link 成功 → 重读 event detail/links、Event list、Graph。C7b 的
    // needs_refresh 传播完全由 link transaction 决定，前端只重新 GET。
    const handleLinkEvidence = useCallback(async (eventId, evidenceKey, { linked_by: linkedBy }) => {
        const linked = await linkInvestigationEventEvidence(taskId, eventId, evidenceKey, {
            linkedBy,
        });
        // §20：用户已切走时只失效全局数据，绝不把 selection 切回该 event。
        if (selectionRef.current?.type === 'event' && selectionRef.current.id === eventId) {
            eventBundle.refresh();
        }
        eventList.refresh();
        setGraphRefreshSignal((signal) => signal + 1);
        return linked;
    }, [taskId, eventBundle, eventList]);

    // §9/§10：admission 只发送 task_id/requested_by，立即拿到 queued
    // refresh row；exact refresh_id 进入轮询身份，不等待 LLM。
    const handleStartRefresh = useCallback(async (eventId, { requested_by: requestedBy }) => {
        const admitted = await startInvestigationEventRefresh(taskId, eventId, { requestedBy });
        if (!admitted?.refresh_id) {
            throw new Error('admission response missing refresh_id');
        }
        setRefreshSubmission({
            taskId,
            eventId,
            refreshId: admitted.refresh_id,
        });
        return admitted;
    }, [taskId]);

    // refresh 轮询离开 queued/running（completed/failed）时：重读 event
    // detail/versions/refresh history（同一个 bundle）、Event list、Graph。
    // §13：绝不能因 completed 就本地清 needs_refresh——dirty 与否由服务器
    // 在 completion transaction 里决定（C7c-2 允许 completed 后仍 dirty）。
    // §14：primary selection 保持 Event，不切到任何 Refresh 对象。
    const refreshHandledRef = useRef(null);
    const refreshEventBundle = eventBundle.refresh;
    const refreshEventList = eventList.refresh;
    useEffect(() => {
        const refreshRow = refreshPolling.refresh;
        const current = refreshSubmissionRef.current;
        if (!refreshRow || !current) return;
        if (refreshRow.status === 'queued' || refreshRow.status === 'running') return;
        if (refreshHandledRef.current === refreshRow.refresh_id) return;
        refreshHandledRef.current = refreshRow.refresh_id;
        if (taskIdRef.current !== current.taskId) return; // 跨 task 晚返回：只忽略

        refreshEventBundle();
        refreshEventList();
        setGraphRefreshSignal((signal) => signal + 1);
    }, [refreshPolling.refresh, refreshEventBundle, refreshEventList]);

    // 本页发起的 refresh 仍在 queued/running 期间：该 event 的 refresh
    // admission 按钮保持 disabled（§10/§17；后端 409 in-progress 之外的前端防抖）。
    const refreshBusyEventId = refreshSubmission && refreshSubmission.taskId === taskId && refreshPolling.active
        ? refreshSubmission.eventId
        : null;

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

    // capture 候选 = 任务文件列表（file:<path> canonical 形态）去重；
    // 已捕获项由表单按 capturedKeys 排除。
    const captureFileOptions = useMemo(() => {
        const files = fileList.data?.files || [];
        const keys = files
            .map((file) => file?.path || file?.file_path)
            .filter(Boolean)
            .map((path) => `file:${path}`);
        return [...new Set(keys)];
    }, [fileList.data]);

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
                    <aside className="w-full lg:w-80 shrink-0 glass rounded-2xl overflow-hidden min-h-[220px] lg:min-h-0 flex flex-col">
                        <CaptureEvidenceForm
                            capturedKeys={(evidenceList.data || []).map((row) => row.evidence_key)}
                            fileOptions={captureFileOptions}
                            onCapture={handleCaptureEvidence}
                        />
                        <div className="flex-1 min-h-0 flex flex-col">
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
                        </div>
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
                                    onCreateEvent={handleCreateEvent}
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
                            reportEvidence={(reportEvidenceList.data || []).find(
                                (item) => item.evidence_key === selectedEvidenceKey,
                            ) || null}
                            submitBusy={submitBusyEvidenceKey !== null && submitBusyEvidenceKey === selectedEvidenceKey}
                            onSubmitAnalysis={handleSubmitAnalysis}
                            onAddReportEvidence={handleAddReportEvidence}
                            onUpdateReportEvidence={handleUpdateReportEvidence}
                            onSubmitReview={handleReviewAnalysis}
                            onLinkEvidence={handleLinkEvidence}
                            refreshBusy={refreshBusyEventId !== null && refreshBusyEventId === selectedEventId}
                            onStartRefresh={handleStartRefresh}
                        />
                    </aside>
                </div>
            )}
        </div>
    );
};

export default Investigation;
