import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ReportStatusPanel from '../components/reports/ReportStatusPanel';
import ReportToolbar from '../components/reports/ReportToolbar';
import ReportWorkspace from '../components/reports/ReportWorkspace';
import VersionHistory from '../components/reports/VersionHistory';
import { useReportSearch } from '../hooks/useReportSearch';
import { useReportVersion } from '../hooks/useReportVersion';
import { reportDataSource } from '../services/reportService';

function reportErrorMessage(error) {
  const detail = error?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ');
  }
  return error?.message || String(error || '报告操作失败');
}

export default function ForensicReportPage({ scopeType, scopeId, dataSource = reportDataSource }) {
  const params = useParams();
  // Prefer an explicit prop (used when embedded outside of /reports/.../:id routes);
  // fall back to the route param otherwise.
  const resolvedScopeId = scopeId ?? (scopeType === 'case' ? params.caseId : params.taskId);
  const state = useReportVersion({ scopeType, scopeId: resolvedScopeId, dataSource });
  const reportId = state.selectedVersion?.report_id || null;
  const searchState = useReportSearch({ dataSource, reportId });
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedPage, setSelectedPage] = useState(1);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const currentManifest = state.manifest?.report_id === reportId ? state.manifest : null;
  const defaultCategoryId = currentManifest?.categories?.[0]?.category_id || null;
  const incompatible = Boolean(currentManifest && currentManifest.schema_version !== '1.0');

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
      <ReportStatusPanel
        versions={state.versions}
        version={state.selectedVersion}
        incompatible={incompatible}
      />
      {state.versions.length > 0 && (
        <VersionHistory
          versions={state.versions}
          selectedVersion={state.selectedVersion}
          onSelect={(version) => { void state.selectVersion(version); }}
        />
      )}
      {currentManifest && !incompatible && reportId && (
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
      )}
    </section>
  );
}
