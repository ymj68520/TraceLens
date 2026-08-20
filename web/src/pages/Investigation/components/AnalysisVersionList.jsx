import Badge from '../../../components/common/Badge';
import { ANALYSIS_STATUS } from '../utils/investigationConstants';

export default function AnalysisVersionList({ versions = [], selectedId, onSelect }) {
  if (!versions.length) return <p className="text-sm text-slate-500">暂无二次分析历史。</p>;
  return (
    <div className="space-y-2">
      {versions.map((version) => {
        const status = ANALYSIS_STATUS[version.status] || ANALYSIS_STATUS.review_pending;
        return (
          <button type="button" key={version.id} onClick={() => onSelect?.(version.id)} className={`w-full rounded-xl border p-3 text-left ${selectedId === version.id ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-950/25' : 'border-slate-200/60 dark:border-slate-700/60'}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-sm">Secondary Analysis v{version.version}</span>
              <Badge size="sm" variant={status.variant}>{status.label}</Badge>
            </div>
            <div className="mt-1 text-[11px] text-slate-500">{version.model || 'model unknown'} · input {version.input_hash?.slice(0, 8) || '—'}</div>
          </button>
        );
      })}
    </div>
  );
}
