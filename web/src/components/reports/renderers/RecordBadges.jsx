const stateLabels = {
  existing: '现存',
  deleted: '已删除',
  recovered: '已恢复',
  unknown: '未知',
};

const severityLabels = {
  info: '信息',
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '严重',
};

const badgeClassName = 'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium';

export default function RecordBadges({ record }) {
  const references = Array.isArray(record?.analysis_references) ? record.analysis_references : [];

  return (
    <div className="flex flex-wrap gap-1.5" aria-label="记录取证标记">
      <span className={`${badgeClassName} bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200`}>
        {stateLabels[record?.data_state] || stateLabels.unknown}
      </span>
      <span className={`${badgeClassName} bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200`}>
        {severityLabels[record?.severity] || severityLabels.info}
      </span>
      {record?.is_relevant && (
        <span className={`${badgeClassName} bg-primary-100 text-primary-800 dark:bg-primary-950/60 dark:text-primary-200`}>
          重点证据
        </span>
      )}
      {references.map((reference, index) => (
        <span
          key={`${reference?.chapter || 'reference'}-${reference?.token || index}`}
          className={`${badgeClassName} bg-violet-100 text-violet-800 dark:bg-violet-950/60 dark:text-violet-200`}
        >
          被 {reference?.chapter || '分析章节'} 引用
        </span>
      ))}
    </div>
  );
}
