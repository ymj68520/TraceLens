import { useParams } from 'react-router-dom';

export default function ForensicReportPage({ scopeType }) {
  const params = useParams();
  const scopeId = scopeType === 'case' ? params.caseId : params.taskId;

  return (
    <section aria-label="Forensic report">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">取证报告</h1>
      <p className="text-sm text-slate-500">{scopeType}: {scopeId}</p>
    </section>
  );
}
