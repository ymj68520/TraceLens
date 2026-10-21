import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import GenerateReportPanel from '../components/reports/GenerateReportPanel';
import NarrativeReportView from '../components/reports/NarrativeReportView';
import ReportStatusPanel from '../components/reports/ReportStatusPanel';
import ReportToolbar from '../components/reports/ReportToolbar';
import ReportWorkspace from '../components/reports/ReportWorkspace';
import VersionHistory from '../components/reports/VersionHistory';
import { useReportSearch } from '../hooks/useReportSearch';
import { useReportVersion } from '../hooks/useReportVersion';
import { getNarrativeReport, generateCaseReport, generateReport } from '../services/reportGenerationService';
import { reportDataSource } from '../services/reportService';
import { fetchTaskById } from '../services/taskService';
import AndroidCoverageCard from '../components/AndroidCoverageCard';

function reportErrorMessage(error) {
  const detail = error?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ');
  }
  return error?.message || String(error || '报告操作失败');
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
  const selectionWhenAdmittedRef = useRef(undefined);

  const handleGenerationAdmitted = useCallback(() => {
    // 记录 admission 时刻的 selection；completed 时只有"selection 未被
    // 用户改变"才允许自动打开 exact 产物版本。
    selectionWhenAdmittedRef.current = selectionRef.current?.report_id ?? null;
  }, []);

  const handleGenerationComplete = useCallback((generation) => {
    if (!generation?.report_id || !generation?.produced_version) return;
    const scopeKey = `${scopeType}:${resolvedScopeId}`;
    if (scopeRef.current !== scopeKey) return;
    const selectionStillAtAdmission = selectionRef.current?.report_id
      === selectionWhenAdmittedRef.current;
    void state.refresh().then(() => {
      if (scopeRef.current !== scopeKey) return;
      // 用户已主动查看历史版本：只刷新列表，绝不劫持 Viewer。
      if (!selectionStillAtAdmission) return;
      // §8：只使用 completed 返回的 exact identity（绝不 GET latest）。
      void state.selectByReportId(generation.report_id);
    });
  }, [resolvedScopeId, scopeType, state]);

  useEffect(() => {
    scopeRef.current = `${scopeType}:${resolvedScopeId}`;
    selectionWhenAdmittedRef.current = undefined;
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

  return (
    <section aria-label="Forensic report" className="space-y-5">
      <ReportToolbar
        manifest={state.manifest}
        version={state.selectedVersion}
        generating={state.generating}
        scopeType={scopeType}
        onCreateVersion={() => { void state.createVersion(); }}
        onRefresh={() => { void state.refresh(); }}
      />
      {state.error && <div role="alert">{reportErrorMessage(state.error)}</div>}
      {resolvedScopeId && (
        <GenerateReportPanel
          taskId={resolvedScopeId}
          scopeType={scopeType}
          scopeId={resolvedScopeId}
          generate={scopeType === 'case' ? generateCaseReport : generateReport}
          pollIntervalMs={generationPollIntervalMs}
          onAdmitted={handleGenerationAdmitted}
          onComplete={handleGenerationComplete}
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
        <VersionHistory
          versions={state.versions}
          selectedVersion={state.selectedVersion}
          onSelect={(version) => { onVersionChange?.(version.report_id); void state.selectVersion(version); }}
        />
      )}
      {!requestedVersionMissing && !awaitingRequestedVersion && selectedIsNarrative && resolvedScopeId ? (
        <NarrativeReportView
          taskId={resolvedScopeId}
          scopeType={scopeType}
          scopeId={resolvedScopeId}
          reportId={reportId}
          fetchNarrative={(id, rId) => narrativeLoader(id, rId, { scopeType })}
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
