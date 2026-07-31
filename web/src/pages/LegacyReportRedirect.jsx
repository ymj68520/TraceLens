import { Navigate, useSearchParams } from 'react-router-dom';

export function getReportTarget(searchParams) {
  const caseId = searchParams.get('case_id');
  if (caseId) return `/reports/case/${encodeURIComponent(caseId)}`;

  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  if (taskId) return `/reports/task/${encodeURIComponent(taskId)}`;

  return '/tasks';
}

export default function LegacyReportRedirect() {
  const [searchParams] = useSearchParams();
  return <Navigate to={getReportTarget(searchParams)} replace />;
}
