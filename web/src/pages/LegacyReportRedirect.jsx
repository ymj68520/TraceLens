import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import { getReportTarget } from './reportRedirectTarget';

export default function LegacyReportRedirect() {
  const [searchParams] = useSearchParams();
  return <Navigate to={getReportTarget(searchParams)} replace />;
}

/** /reports/task/:taskId → /case-intelligence?task_id=:taskId */
export function TaskReportRedirect() {
  const { taskId } = useParams();
  return <Navigate to={`/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic`} replace />;
}

/** /reports/case/:caseId → /case-intelligence?case_id=:caseId */
export function CaseReportRedirect() {
  const { caseId } = useParams();
  return <Navigate to={`/case-intelligence?case_id=${encodeURIComponent(caseId)}&tab=forensic`} replace />;
}

