import { useEffect, useState } from 'react';
import ForensicReportPage from '../../pages/ForensicReportPage';
import { getCaseReportByCase } from '../../services/caseGroupService';
import { ChevronDown, ChevronRight, FileText } from 'lucide-react';

export default function CrossImageReport({
  caseId,
  requestedReportId = null,
  focusCitationId = null,
  onVersionChange,
  loadReport = getCaseReportByCase,
}) {
  const [legacyResult, setLegacyResult] = useState({ loading: true, report: null, error: null });
  const [showLegacy, setShowLegacy] = useState(false);

  useEffect(() => {
    let active = true;
    setLegacyResult({ loading: true, report: null, error: null });
    loadReport(caseId)
      .then((data) => {
        if (active) setLegacyResult({ loading: false, report: data, error: null });
      })
      .catch((error) => {
        if (active) setLegacyResult({ loading: false, report: null, error });
      });
    return () => { active = false; };
  }, [caseId, loadReport]);

  return (
    <div className="space-y-6" data-testid="cross-image-report-container">
      {/* 现代版本化跨镜像综合研判报告体系 */}
      <ForensicReportPage
        scopeType="case"
        scopeId={caseId}
        requestedReportId={requestedReportId}
        focusCitationId={focusCitationId}
        onVersionChange={onVersionChange}
      />

      {/* 历史格式纯文本折叠区（如果存在） */}
      {legacyResult.report?.report?.trim() && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 shadow-sm">
          <button
            type="button"
            onClick={() => setShowLegacy(!showLegacy)}
            className="w-full flex items-center justify-between text-left text-sm font-semibold text-slate-700 dark:text-slate-300 hover:text-slate-900"
          >
            <span className="flex items-center gap-2">
              <FileText size={16} className="text-slate-400" />
              <span>📜 历史纯文本分析记录（参考归档）</span>
              <span className="text-xs font-normal text-slate-400">
                生成时间: {legacyResult.report.generated_at || '早期'}
              </span>
            </span>
            {showLegacy ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
          {showLegacy && (
            <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
              {legacyResult.report.case_description && (
                <p className="text-xs text-slate-500 mb-2">案情描述：{legacyResult.report.case_description}</p>
              )}
              <pre className="whitespace-pre-wrap break-words font-sans text-xs leading-6 text-slate-700 dark:text-slate-300 p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
                {legacyResult.report.report}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
