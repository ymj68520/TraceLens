import { useEffect, useState } from 'react';
import { getCaseReportByCase } from '../../services/caseGroupService';

export default function CrossImageReport({ caseId, loadReport = getCaseReportByCase }) {
  const [result, setResult] = useState({ loading: true, report: null, error: null });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setResult({ loading: true, report: null, error: null });
    const load = async () => {
      try {
        const data = await loadReport(caseId);
        if (active) setResult({ loading: false, report: data, error: null });
      } catch (error) {
        if (active) setResult({ loading: false, report: null, error });
      }
    };
    void load();
    return () => { active = false; };
  }, [caseId, loadReport, retry]);

  if (result.loading) return <div className="p-8 text-sm text-slate-500">正在读取跨镜像报告…</div>;

  const missing = result.error?.status === 404 || (!result.error && !result.report?.report?.trim());
  if (missing) {
    return (
      <div role="alert" className="rounded-2xl border border-amber-300 bg-amber-50 p-6 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/20 dark:text-amber-200">
        <h2 className="text-lg font-semibold">跨镜像报告缺失</h2>
        <p className="mt-2">案件状态为“完成”不代表历史报告已成功保存。现有案件数据不会自动重生成；如需补报，请先确认可写副本与 LLM 调用。</p>
        <button type="button" className="mt-4 rounded-lg border border-amber-500 px-3 py-1.5 font-medium" onClick={() => setRetry((value) => value + 1)}>重试读取</button>
      </div>
    );
  }
  if (result.error) {
    return <div role="alert" className="rounded-2xl border border-rose-300 bg-rose-50 p-6 text-sm text-rose-800">读取跨镜像报告失败：{result.error?.data?.detail || result.error.message || String(result.error)}</div>;
  }

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
      <h2 className="text-xl font-bold text-slate-900 dark:text-white">跨镜像研判报告</h2>
      <p className="mt-1 text-xs text-slate-500">历史格式 · 案件 {caseId} · 生成时间 {result.report.generated_at || '未知'}</p>
      {result.report.case_description && <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">案情：{result.report.case_description}</p>}
      <pre className="mt-6 whitespace-pre-wrap break-words font-sans text-sm leading-7 text-slate-800 dark:text-slate-200">{result.report.report}</pre>
    </article>
  );
}
