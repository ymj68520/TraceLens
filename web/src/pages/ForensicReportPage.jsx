import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import GenerateReportPanel from '../components/reports/GenerateReportPanel';
import NarrativeReportView from '../components/reports/NarrativeReportView';
import ReportStatusPanel from '../components/reports/ReportStatusPanel';
import PipelineReportProgress from '../components/reports/PipelineReportProgress';
import ReportToolbar from '../components/reports/ReportToolbar';
import ReportWorkspace from '../components/reports/ReportWorkspace';
import VersionHistory from '../components/reports/VersionHistory';
import { useReportSearch } from '../hooks/useReportSearch';
import { useReportVersion } from '../hooks/useReportVersion';
import { getNarrativeReport } from '../services/reportGenerationService';
import { reportDataSource } from '../services/reportService';
import { fetchTaskById } from '../services/taskService';
import AndroidCoverageCard from '../components/AndroidCoverageCard';
import { getFinalReportHtml, getFinalReportOffline } from '../services/investigationService';
import { pythonApi } from '../services/api';
import { forensicError } from '../utils/forensicLabels';

function reportErrorMessage(error) {
  return forensicError(error, '报告操作失败，请核对服务与版本。');
}

export default function ForensicReportPage({
  scopeType,
  scopeId,
  dataSource = reportDataSource,
  narrativeLoader = getNarrativeReport,
  generationPollIntervalMs,
  requestedReportId = null,
  focusCitationId = null,
  onVersionChange,
}) {
  const params = useParams();
  // Prefer an explicit prop (used when embedded outside of /reports/.../:id routes);
  // fall back to the route param otherwise.
  const resolvedScopeId = scopeId ?? (scopeType === 'case' ? params.caseId : params.taskId);
  const state = useReportVersion({ scopeType, scopeId: resolvedScopeId, dataSource });
  const selectedReportId = state.selectedVersion?.report_id;
  const selectByReportId = state.selectByReportId;
  const requestedSelectionRef = useRef(null);
  const reportId = state.selectedVersion?.report_id || null;
  const searchState = useReportSearch({ dataSource, reportId });
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedPage, setSelectedPage] = useState(1);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [imageTask, setImageTask] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);
  const historyRef = useRef(null);
  const currentManifest = state.manifest?.report_id === reportId ? state.manifest : null;
  const defaultCategoryId = currentManifest?.categories?.[0]?.category_id || null;
  const incompatible = Boolean(currentManifest && currentManifest.schema_version !== '1.0');
  // R2d: a published narrative version renders the Narrative view; it never
  // enters the deterministic category/page workspace.
  const selectedIsNarrative = state.selectedVersion?.report_kind === 'llm_generation';
  const requestedVersionFound = !requestedReportId || state.versions.some((version) => version.report_id === requestedReportId);
  const requestedVersionMissing = Boolean(requestedReportId && !state.loading && !requestedVersionFound);
  const awaitingRequestedVersion = Boolean(requestedReportId && requestedVersionFound && reportId !== requestedReportId);

  // 渲染期同步 refs：generation 晚完成时用它们判定"用户是否仍在原地"，
  // 绝不让晚到的 completed 劫持当前 selection（§7/§30）。
  const selectionRef = useRef(null);
  selectionRef.current = state.selectedVersion;
  const scopeRef = useRef(null);
  const navigationRevisionRef = useRef(0);
  const generationIntentRef = useRef(null);

  const handleGenerationSubmitStart = useCallback(() => ({
    scopeKey: scopeRef.current,
    reportId: selectionRef.current?.report_id ?? null,
    navigationRevision: navigationRevisionRef.current,
  }), []);

  const handleGenerationAdmitted = useCallback((intent) => {
    generationIntentRef.current = intent;
  }, []);

  const handleGenerationComplete = useCallback((generation) => {
    if (!generation?.report_id || !generation?.produced_version) return;
    const scopeKey = `${scopeType}:${resolvedScopeId}`;
    if (scopeRef.current !== scopeKey) return;
    const intent = generationIntentRef.current;
    const selectionStillAtSubmission = intent?.scopeKey === scopeKey
      && navigationRevisionRef.current === intent.navigationRevision
      && (selectionRef.current?.report_id ?? null) === intent.reportId;
    void state.refresh().then(() => {
      if (scopeRef.current !== scopeKey) return;
      // 用户已主动查看历史版本：只刷新列表，绝不劫持 Viewer。
      if (!selectionStillAtSubmission || generationIntentRef.current !== intent
          || navigationRevisionRef.current !== intent.navigationRevision) return;
      // §8：只使用 completed 返回的 exact identity（绝不 GET latest）。
      void state.selectByReportId(generation.report_id).then((selected) => {
        if (selected && scopeRef.current === scopeKey && generationIntentRef.current === intent
            && navigationRevisionRef.current === intent.navigationRevision) {
          onVersionChange?.(generation.report_id);
        }
      });
    });
  }, [onVersionChange, resolvedScopeId, scopeType, state]);

  useEffect(() => {
    scopeRef.current = `${scopeType}:${resolvedScopeId}`;
    navigationRevisionRef.current += 1;
    generationIntentRef.current = null;
    requestedSelectionRef.current = null;
  }, [scopeType, resolvedScopeId]);

  useEffect(() => {
    let active = true;
    setImageTask(false);
    if (scopeType !== 'task' || !resolvedScopeId) return () => { active = false; };
    fetchTaskById(resolvedScopeId).then((task) => {
      if (active) setImageTask(['filesystem-image', 'android-container'].includes(task?.android_source));
    }).catch(() => {});
    return () => { active = false; };
  }, [scopeType, resolvedScopeId]);

  useEffect(() => {
    if (!requestedReportId || selectedReportId === requestedReportId) return;
    if (!state.versions.some((version) => version.report_id === requestedReportId)) return;
    const requestKey = `${scopeType}:${resolvedScopeId}:${requestedReportId}`;
    if (requestedSelectionRef.current === requestKey) return;
    requestedSelectionRef.current = requestKey;
    navigationRevisionRef.current += 1;
    void selectByReportId(requestedReportId);
  }, [requestedReportId, resolvedScopeId, scopeType, selectedReportId, selectByReportId, state.versions]);

  useEffect(() => {
    setSelectedCategory(defaultCategoryId);
    setSelectedPage(1);
    setDirectoryOpen(false);
  }, [defaultCategoryId, reportId]);

  const selectCategory = useCallback((categoryId, page = 1) => {
    const nextPage = Number.isInteger(Number(page)) && Number(page) > 0 ? Number(page) : 1;
    setSelectedCategory(categoryId);
    setSelectedPage(nextPage);
  }, []);

  const exportSelected = async (format) => {
    const selected = state.selectedVersion;
    if (!selected || exporting) return;
    setExporting(true); setExportError(null);
    const task = resolvedScopeId, identity = selected.report_id;
    try {
      const narrative = selected.report_kind === 'llm_generation';
      const payload = narrative
        ? await (format === 'html' ? getFinalReportHtml(task, identity) : getFinalReportOffline(task, identity))
        : await pythonApi.get(dataSource.getOfflineBundleUrl(identity), { responseType: 'blob' });
      // A response for a previous selection must not download as the current report.
      if (selectionRef.current?.report_id !== identity || scopeRef.current !== `${scopeType}:${task}`) return;
      const blob = payload instanceof Blob ? payload : new Blob([payload], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url; anchor.download = `report-${identity.replace(/[^a-zA-Z0-9_-]/g, '')}.${format === 'html' ? 'html' : 'zip'}`;
      anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setExportError(forensicError(error, '导出失败；请检查报告完整性与当前任务范围。')); }
    finally { setExporting(false); }
  };

  return (
    <section aria-label="取证报告" className="space-y-5">
      <ReportToolbar
        manifest={state.manifest}
        version={state.selectedVersion}
        generating={state.generating}
        scopeType={scopeType}
        onCreateVersion={() => { void state.createVersion(); }}
        onRefresh={() => { void state.refresh(); }}
        onExportHtml={selectedIsNarrative && scopeType === 'task' && state.selectedVersion?.status === 'ready' ? () => exportSelected('html') : undefined}
        onExportBundle={state.selectedVersion?.status === 'ready' && (selectedIsNarrative || dataSource.getOfflineBundleUrl?.(reportId)) ? () => exportSelected('zip') : undefined}
        onHistory={state.versions.length ? () => { historyRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); historyRef.current?.focus(); } : undefined}
        exporting={exporting}
      />
      {exportError && <p role="alert">{exportError}</p>}
      {state.error && <div role="alert">{reportErrorMessage(state.error)}</div>}
      {scopeType === 'task' && resolvedScopeId && <PipelineReportProgress
        taskId={resolvedScopeId}
        onReportAvailable={() => { void state.refresh(); }}
        onOpenReport={(identity) => { void state.selectByReportId(identity); }}
      />}
      {scopeType === 'task' && resolvedScopeId && (
        <GenerateReportPanel
          taskId={resolvedScopeId}
          pollIntervalMs={generationPollIntervalMs}
          onSubmitStart={handleGenerationSubmitStart}
          onAdmitted={handleGenerationAdmitted}
          onComplete={handleGenerationComplete}
          selectedReportId={selectedIsNarrative ? reportId : null}
          narrativeLoader={narrativeLoader}
        />
      )}
      <ReportStatusPanel
        versions={state.versions}
        version={state.selectedVersion}
        incompatible={incompatible}
      />
      {imageTask && resolvedScopeId && <div data-testid="android-report-coverage-reference" className="space-y-2">
        <p className="text-sm text-amber-700">本报告须连同下列 Android 来源覆盖清单阅读；已解析记录不代表全部加密或缺失数据可用。</p>
        <AndroidCoverageCard taskId={resolvedScopeId} />
      </div>}
      {requestedVersionMissing && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/20 dark:text-amber-200">指定的最终报告版本不属于当前任务或尚未就绪；不会自动改为其他版本。</div>}
      {awaitingRequestedVersion && <div className="flex justify-center rounded-xl border border-slate-200 p-6 dark:border-slate-700"><span className="text-sm text-slate-500">正在定位指定报告版本…</span></div>}
      {state.versions.length > 0 && (
        <div ref={historyRef} tabIndex={-1} aria-label="报告版本列表"><VersionHistory
          versions={state.versions}
          selectedVersion={state.selectedVersion}
          onSelect={(version) => {
            navigationRevisionRef.current += 1;
            onVersionChange?.(version.report_id);
            void state.selectVersion(version);
          }}
        /></div>
      )}
      {!requestedVersionMissing && !awaitingRequestedVersion && selectedIsNarrative && resolvedScopeId ? (
        <NarrativeReportView
          taskId={resolvedScopeId}
          reportId={reportId}
          fetchNarrative={narrativeLoader}
          focusCitationId={focusCitationId}
        />
      ) : (
        !requestedVersionMissing && !awaitingRequestedVersion && currentManifest && !incompatible && reportId && (
          <ReportWorkspace
            manifest={currentManifest}
            dataSource={dataSource}
            reportId={reportId}
            selectedCategory={selectedCategory}
            selectedPage={selectedPage}
            onSelectCategory={selectCategory}
            onSelectPage={setSelectedPage}
            searchState={searchState}
            directoryOpen={directoryOpen}
            onDirectoryOpenChange={setDirectoryOpen}
          />
        )
      )}
    </section>
  );
}
