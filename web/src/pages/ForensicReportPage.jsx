import { useParams } from 'react-router-dom';
import ReportStatusPanel from '../components/reports/ReportStatusPanel';
import ReportToolbar from '../components/reports/ReportToolbar';
import VersionHistory from '../components/reports/VersionHistory';
import { useReportVersion } from '../hooks/useReportVersion';
import { reportDataSource } from '../services/reportService';

export default function ForensicReportPage({ scopeType, dataSource = reportDataSource }) {
  const params = useParams();
  const scopeId = scopeType === 'case' ? params.caseId : params.taskId;
  const state = useReportVersion({ scopeType, scopeId, dataSource });
  const incompatible = Boolean(state.manifest && state.manifest.schema_version !== '1.0');

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
      {state.manifest && !incompatible && (
        <div aria-label="Report manifest">{state.manifest.title}</div>
      )}
    </section>
  );
}
