import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ReportStatusPanel from '../components/reports/ReportStatusPanel';
import ReportToolbar from '../components/reports/ReportToolbar';
import ReportWorkspace from '../components/reports/ReportWorkspace';
import VersionHistory from '../components/reports/VersionHistory';
import { useReportSearch } from '../hooks/useReportSearch';
import { useReportVersion } from '../hooks/useReportVersion';
import { reportDataSource } from '../services/reportService';

export default function ForensicReportPage({ scopeType, dataSource = reportDataSource }) {
  const params = useParams();
  const scopeId = scopeType === 'case' ? params.caseId : params.taskId;
  const state = useReportVersion({ scopeType, scopeId, dataSource });
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
        onCreateVersion={() => { void state.createVersion().catch(() => {}); }}
      />
      {state.error && <div role="alert">{state.error.message || String(state.error)}</div>}
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
