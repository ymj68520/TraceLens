import { Navigate, useParams, useSearchParams } from 'react-router-dom';

/**
 * 报告路由已整合进证据研判页面（/case-intelligence）。
 * 统一以 query 参数（case_id / task_id）携带上下文。
 */
export function getReportTarget(searchParams) {
  const caseId = searchParams.get('case_id');
  if (caseId) return `/case-intelligence?case_id=${encodeURIComponent(caseId)}&tab=forensic`;

  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  if (taskId) return `/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic`;

  return '/tasks';
}

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

