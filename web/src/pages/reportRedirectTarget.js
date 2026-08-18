export function getReportTarget(searchParams) {
  const caseId = searchParams.get('case_id');
  if (caseId) return `/case-intelligence?case_id=${encodeURIComponent(caseId)}&tab=forensic`;

  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  if (taskId) return `/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic`;

  return '/tasks';
}
